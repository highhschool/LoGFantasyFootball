"""Trading.

A fourth tool, separate from the three before it in the same way they are
separate from each other. It borrows two things and owns everything else:
identity comes from the keeper codes, so nobody signs up twice, and resolution
comes from the Sleeper picks feed, so nobody has to rule on anything.

The important line here is `POST /trade`. A quote is indicative -- it is priced
against whatever the book looked like when the screen last loaded -- and the
price actually charged is computed inside the write transaction, after everyone
who got there first. With a position cap and real money, pricing against a
stale log is the difference between five contracts and ten.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import config as app_config
from ..core.contracts import (
    OPEN,
    MarketConfig,
    MarketError,
    Trade,
    phase,
    plan,
    replay,
    settle_all,
)
from ..core.lmsr import NO, YES
from ..core.rankings import PlayerPool
from ..owner import resolve as resolve_owner
from ..store import SessionStore

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


class TradeIn(BaseModel):
    market_id: str
    side: str = Field(pattern="^(yes|no)$")
    shares: int = Field(ge=-50, le=50)


# ------------------------------------------------------------- dependencies

def get_pool() -> PlayerPool:
    from ..main import require_pool

    return require_pool()


def get_store() -> SessionStore:
    from ..main import get_session_store

    return get_session_store()


def get_owner(request: Request, response: Response) -> str:
    return resolve_owner(request, response)


def require_manager(store: SessionStore, owner: str) -> dict:
    """Trading is for the twelve, identified by their keeper code."""
    manager = store.claimed_manager(owner)
    if manager is None:
        raise HTTPException(
            status_code=403,
            detail="sign in with your manager code first",
        )
    return manager


# ------------------------------------------------------------------ helpers

def market_config(row: dict) -> MarketConfig:
    """A stored market as the engine wants it."""
    slate_opens = row.get("opens_at")
    return MarketConfig(
        market_id=row["market_id"],
        question=row["question"],
        opening=row["opening"],
        b=row["b"],
        spread=row["spread"],
        position_cap=row["position_cap"],
        opens_at=datetime.fromisoformat(slate_opens) if slate_opens else None,
        closes_at=datetime.fromisoformat(row["closes_at"]) if row["closes_at"] else None,
    )


def logged(rows: list[dict]) -> list[Trade]:
    return [
        Trade(user_id=r["user_id"], side=r["side"], shares=r["shares"],
              cash=r["cash"], at=r["at"])
        for r in rows
    ]


def with_slate(store: SessionStore, row: dict) -> dict:
    """Markets carry their own close; the open comes from their slate."""
    slate = store.slate(row["slate_id"]) or {}
    return {**row, "opens_at": slate.get("opens_at")}


def market_view(store: SessionStore, row: dict, user_id: str | None,
                now: datetime | None = None) -> dict:
    row = with_slate(store, row)
    config = market_config(row)
    state = replay(config, logged(store.trades(row["market_id"])))
    settled = row["resolved"] is not None

    view = {
        **state.as_dict(),
        "kind": row["kind"],
        "slate_id": row["slate_id"],
        "game": row["game"],
        "closes_at": row["closes_at"],
        "phase": phase(config, now, settled),
        "resolved": None if not settled else bool(row["resolved"]),
        "cap": config.position_cap,
    }
    if user_id:
        held = state.position(user_id)
        view["you"] = held.as_dict(state.price_yes)
        view["headroom"] = config.position_cap - max(held.yes, held.no)
    return view


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------- routes

@router.get("")
def overview(
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    """The slates, and whether you are able to trade at all."""
    manager = store.claimed_manager(owner)
    slates = store.slates()

    out = []
    for slate in slates:
        rows = store.markets(slate["slate_id"])
        out.append({
            **slate,
            "markets": len(rows),
            "settled": sum(1 for r in rows if r["resolved"] is not None),
        })

    return {
        "you": manager,
        "cap": app_config.CONTRACTS_CAP,
        "slates": out,
    }


@router.get("/slates/{slate_id}")
def one_slate(
    slate_id: str,
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    slate = store.slate(slate_id)
    if slate is None:
        raise HTTPException(status_code=404, detail="no such slate")

    manager = store.claimed_manager(owner)
    who = manager["user_id"] if manager else None
    now = _now()

    return {
        "slate": slate,
        "you": manager,
        "markets": [
            market_view(store, row, who, now) for row in store.markets(slate_id)
        ],
    }


@router.post("/quote")
def quote_trade(
    body: TradeIn,
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    """What a trade would cost, indicatively.

    Priced against the book as it stands now. The trade route prices again
    inside its transaction, so this can move underneath you -- which is the
    honest behaviour for a market, and why the number is shown as an estimate.
    """
    manager = require_manager(store, owner)
    row = store.market(body.market_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such market")

    row = with_slate(store, row)
    config = market_config(row)
    state = replay(config, logged(store.trades(body.market_id)))

    try:
        done = plan(
            state, manager["user_id"], body.side, body.shares,
            now=_now(), settled=row["resolved"] is not None,
        )
    except MarketError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"indicative": True, **done.as_dict()}


@router.post("/trade")
def make_trade(
    body: TradeIn,
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    """Buy or sell, priced against the committed book."""
    manager = require_manager(store, owner)
    who = manager["user_id"]
    now = _now()

    def price_trade(row: dict, log: list[dict], _when) -> dict:
        row = with_slate(store, row)
        state = replay(market_config(row), logged(log))
        done = plan(
            state, who, body.side, body.shares,
            now=now, settled=row["resolved"] is not None,
        )
        return done.as_dict()

    try:
        done = store.execute_trade(body.market_id, who, body.side, body.shares,
                                   price_trade, now)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such market") from None
    except MarketError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    row = store.market(body.market_id)
    return {"traded": done, "market": market_view(store, row, who, now)}


@router.get("/me")
def my_book(
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    """Every position, open and settled, and what it all comes to."""
    manager = require_manager(store, owner)
    who = manager["user_id"]
    now = _now()

    open_rows, settled_rows, realised, unrealised = [], [], 0, 0

    for row in store.markets():
        state = replay(
            market_config(with_slate(store, row)), logged(store.trades(row["market_id"]))
        )
        held = state.position(who)
        if not held.held and not held.cash:
            continue

        entry = {
            "market_id": row["market_id"],
            "question": row["question"],
            "slate_id": row["slate_id"],
            **held.as_dict(state.price_yes),
            "price_yes": state.price_yes,
        }

        if row["resolved"] is None:
            unrealised += entry["open_pnl"]
            open_rows.append(entry)
        else:
            entry["result"] = settle_all(state, bool(row["resolved"]))[who]
            realised += entry["result"]
            settled_rows.append(entry)

    return {
        "you": manager,
        "open": open_rows,
        "settled": settled_rows,
        "realised": realised,
        "unrealised": unrealised,
        "as_of": now.isoformat(),
    }
