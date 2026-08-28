"""Running the markets: opening them, settling them, and seeing the damage.

Under `/api/admin`, so the same Cloudflare Access rule that guards the rest of
the admin surface guards this -- which matters more here than anywhere else in
the app, since these routes create real financial obligations.

Settlement takes no argument. A market is resolved by the picks feed or it is
not resolved at all; there is deliberately no route to declare an outcome by
hand, because with real money a commissioner who *can* overrule the feed will
be asked to.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import config as app_config
from ..admin import require_admin
from ..core.contracts import MarketConfig, replay, settle_all
from ..core.draft_markets import Board, TemplateError, build, template
from ..core.rankings import PlayerPool
from ..core.slates import Slate, SlateError, draft_slate, next_open, weekly_slate
from ..integrations.sleeper import SleeperClient, SleeperError
from ..store import SessionStore
from .contracts import logged, market_config, with_slate

router = APIRouter(prefix="/api/admin/contracts", tags=["admin"])


class SlateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(default="weekly", pattern="^(draft|weekly)$")
    draft_start: str | None = None      # required for a draft slate
    opens_at: str | None = None         # defaults to the next Tuesday


class MarketIn(BaseModel):
    slate_id: str
    kind: str
    params: dict
    game: str | None = None
    opening: int | None = None          # for markets the model cannot price


def get_pool() -> PlayerPool:
    from ..main import require_pool

    return require_pool()


def get_store() -> SessionStore:
    from ..main import get_session_store

    return get_session_store()


def get_client() -> SleeperClient:
    from ..main import get_sleeper_client

    return get_sleeper_client()


def _league() -> str:
    league = app_config.SLEEPER_LEAGUE_ID
    if not league:
        raise HTTPException(status_code=503, detail="no league configured")
    return league


def _board(client: SleeperClient) -> Board:
    """The draft as Sleeper has it, which is what settles everything."""
    try:
        draft = client.latest_draft(_league())
        return Board(picks=client.picks(draft.draft_id), teams=draft.teams,
                     rounds=draft.rounds)
    except SleeperError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _as_slate(row: dict) -> Slate:
    return Slate(
        slate_id=row["slate_id"],
        name=row["name"],
        opens_at=datetime.fromisoformat(row["opens_at"]),
        closes_at=datetime.fromisoformat(row["closes_at"]) if row["closes_at"] else None,
    )


def _state(store: SessionStore, row: dict):
    return replay(market_config(with_slate(store, row)), logged(store.trades(row["market_id"])))


@router.get("")
def overview(
    request: Request,
    store: SessionStore = Depends(get_store),
) -> dict:
    """Every market, and which way the house is leaning on each."""
    require_admin(request)

    rows, budgeted, if_yes, if_no = [], 0, 0, 0
    for row in store.markets():
        config = market_config(with_slate(store, row))
        state = _state(store, row)
        budgeted += config.exposure
        if_yes += state.house_pnl(True)
        if_no += state.house_pnl(False)
        rows.append({
            **state.as_dict(),
            "slate_id": row["slate_id"],
            "game": row["game"],
            "closes_at": row["closes_at"],
            "resolved": None if row["resolved"] is None else bool(row["resolved"]),
            "traders": len(state.positions),
        })

    return {
        "slates": store.slates(),
        "markets": rows,
        # What is actually on the line now, against what was budgeted at open.
        "house_if_all_yes": if_yes,
        "house_if_all_no": if_no,
        "budgeted_exposure": budgeted,
    }


@router.post("/slates")
def create_slate(
    body: SlateIn,
    request: Request,
    store: SessionStore = Depends(get_store),
) -> dict:
    require_admin(request)

    try:
        if body.kind == "draft":
            if not body.draft_start:
                raise HTTPException(
                    status_code=422,
                    detail="a draft slate needs the draft's start time",
                )
            built = draft_slate("", body.name, datetime.fromisoformat(body.draft_start))
        else:
            opens = (
                datetime.fromisoformat(body.opens_at) if body.opens_at
                else next_open(datetime.now(timezone.utc))
            )
            built = weekly_slate("", body.name, opens)
    except (SlateError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    slate_id = store.create_slate(body.name, body.kind, built.opens_at, built.closes_at)
    return {"slate": store.slate(slate_id)}


@router.post("/markets")
def create_market(
    body: MarketIn,
    request: Request,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    client: SleeperClient = Depends(get_client),
) -> dict:
    """Open a market from a template, priced off ADP.

    Refuses anything the board has already answered, which needs the live feed
    rather than an empty board: keepers are on it before the draft starts, so
    a market about a kept player is settled before anyone could trade it.
    """
    require_admin(request)

    slate = store.slate(body.slate_id)
    if slate is None:
        raise HTTPException(status_code=404, detail="no such slate")

    board = _board(client)

    try:
        made = build(body.kind, body.params, pool, board)
        closes = _as_slate(slate).close_for(body.game)
    except (TemplateError, SlateError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    opening = body.opening if body.opening is not None else made["opening"]

    try:
        config = MarketConfig(
            market_id="", question=made["question"], opening=opening,
            b=app_config.CONTRACTS_B, spread=app_config.CONTRACTS_SPREAD,
            position_cap=app_config.CONTRACTS_CAP,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    market_id = store.create_market(
        slate_id=body.slate_id, kind=body.kind, params=body.params,
        question=made["question"], opening=opening, closes_at=closes,
        b=config.b, spread=config.spread, position_cap=config.position_cap,
        game=body.game,
    )
    return {"market": store.market(market_id), "exposure": config.exposure}


@router.delete("/markets/{market_id}")
def remove_market(
    market_id: str,
    request: Request,
    store: SessionStore = Depends(get_store),
) -> dict:
    """Drop a market nobody has traded.

    The only destructive route here, and deliberately the narrowest one it can
    be: once a single contract has changed hands the market is somebody's
    position, and removing it would take real money off the board with nothing
    recording why. A mistyped market that nobody touched is just a typo.
    """
    require_admin(request)

    row = store.market(market_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such market")
    if not store.delete_market(market_id):
        raise HTTPException(
            status_code=409,
            detail="that market has been traded or settled, so it stays on the board",
        )
    return {"deleted": market_id, "question": row["question"]}


@router.post("/markets/{market_id}/resolve")
def resolve(
    market_id: str,
    request: Request,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    client: SleeperClient = Depends(get_client),
) -> dict:
    """Settle from the picks feed. No judgment, or no settlement."""
    require_admin(request)

    row = store.market(market_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such market")
    if row["resolved"] is not None:
        raise HTTPException(status_code=409, detail="that market has already settled")

    board = _board(client)
    try:
        outcome = template(row["kind"]).resolve(json.loads(row["params_json"]), board, pool)
    except TemplateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if outcome is None:
        raise HTTPException(status_code=409, detail="the draft has not answered this yet")

    state = _state(store, row)
    if not store.resolve_market(market_id, outcome):
        raise HTTPException(status_code=409, detail="that market has already settled")

    return {
        "market_id": market_id,
        "question": row["question"],
        "outcome": "yes" if outcome else "no",
        "house": state.house_pnl(outcome),
        "managers": settle_all(state, outcome),
    }


@router.post("/resolve")
def resolve_everything(
    request: Request,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    client: SleeperClient = Depends(get_client),
) -> dict:
    """Settle everything the board can answer, in one pass.

    The draft answers markets in bursts, so calling these one at a time on the
    night would be its own job. Anything still undecided is left alone and
    named.
    """
    require_admin(request)
    board = _board(client)

    settled, waiting, house = [], [], 0
    for row in store.markets():
        if row["resolved"] is not None:
            continue
        try:
            outcome = template(row["kind"]).resolve(
                json.loads(row["params_json"]), board, pool
            )
        except TemplateError:
            waiting.append({"market_id": row["market_id"], "question": row["question"]})
            continue

        if outcome is None:
            waiting.append({"market_id": row["market_id"], "question": row["question"]})
            continue

        state = _state(store, row)
        if store.resolve_market(row["market_id"], outcome):
            house += state.house_pnl(outcome)
            settled.append({
                "market_id": row["market_id"],
                "question": row["question"],
                "outcome": "yes" if outcome else "no",
                "house": state.house_pnl(outcome),
            })

    return {"settled": settled, "waiting": waiting, "house": house}


@router.get("/ledger")
def ledger(
    request: Request,
    store: SessionStore = Depends(get_store),
) -> dict:
    """Who owes whom, once markets have settled.

    Everyone settles with the house, so this is twelve bilateral numbers rather
    than a web of them -- and one of the twelve is the house's own.
    """
    require_admin(request)

    owed: dict[str, int] = {}
    house, counted = 0, 0

    for row in store.markets():
        if row["resolved"] is None:
            continue
        counted += 1
        state = _state(store, row)
        outcome = bool(row["resolved"])
        house += state.house_pnl(outcome)
        for user, amount in settle_all(state, outcome).items():
            owed[user] = owed.get(user, 0) + amount

    names = {m["user_id"]: m["display_name"] or m["team_name"] for m in store.managers()}
    return {
        "settled_markets": counted,
        "house": house,
        "managers": sorted(
            ({"user_id": u, "manager": names.get(u, u), "net": n}
             for u, n in owed.items()),
            key=lambda r: r["net"],
            reverse=True,
        ),
    }
