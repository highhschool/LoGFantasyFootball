"""The live draft assistant.

A separate tool from the mock simulator, deliberately: its own routes, its own
sessions, its own list. They share the engine underneath -- the board, the
roster maths, name resolution -- but nothing either tool does can change how
the other behaves.

The difference in kind: a mock draft invents its picks, so it can always
produce the next one. The assistant only reports picks that really happened,
which means it can be behind, and can be blocked by a name it cannot place.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from .. import config as app_config
from ..core import advisor
from ..core.engine import DraftState, LoggedPick, replay
from ..core.models import ConfigError, DraftConfig
from ..core.order import picks_until_next, validate_config
from ..core.names import player_key
from ..core.rankings import PlayerPool
from ..integrations.sleeper import (
    SleeperClient,
    SleeperError,
    SleeperPick,
    draft_id_from_url,
)
from ..owner import resolve as resolve_owner
from ..store import SessionStore

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class ConnectIn(BaseModel):
    """Start following a live draft."""

    draft: str = Field(description="Sleeper draft id, or the URL of the draft")
    your_slot: int = Field(ge=1, le=32)
    name: str = ""


# ------------------------------------------------------------- dependencies

def get_pool() -> PlayerPool:
    from ..main import require_pool

    return require_pool()


def get_store() -> SessionStore:
    from ..main import get_session_store

    return get_session_store()


def get_client() -> SleeperClient:
    from ..main import get_sleeper_client

    return get_sleeper_client()


def get_owner(request: Request, response: Response) -> str:
    return resolve_owner(request, response)


# ------------------------------------------------------------------- syncing

def resolve_pick(pool: PlayerPool, pick: SleeperPick):
    """Find the ranked player behind a Sleeper pick, or None."""
    return pool.find(pick.name, pick.position, pick.team)


def sync_log(
    pool: PlayerPool,
    log: list[LoggedPick],
    picks: list[SleeperPick],
) -> tuple[list[LoggedPick], list[SleeperPick]]:
    """Extend the log with picks made since we last looked.

    The log is positional -- entry N is pick N -- so a pick can never be
    skipped: every later one would land in the wrong team's seat. A player the
    rankings do not cover is therefore logged with his own details rather than
    dropped, which is the ordinary case late in a real draft. The 2025 board
    took a round-15 back who is not in the ADP feed at all; stalling there
    would have stopped the assistant at pick 173 of 180.

    Returns the extended log and the picks that could not be matched to a
    ranked player, so the board can say so.

    Idempotent by pick number: polling the same board twice adds nothing.
    """
    extended = list(log)
    unranked: list[SleeperPick] = []

    for pick in picks:
        if pick.pick_no <= len(extended):
            continue
        if pick.pick_no != len(extended) + 1:
            # A hole in the feed. Continuing would shift every later seat, so
            # stop and let the next sync pick it up once the feed is whole.
            break

        player = resolve_pick(pool, pick)
        if player is not None:
            extended.append(
                LoggedPick(
                    player_key=player.key,
                    source="keeper" if pick.is_keeper else "sleeper",
                )
            )
            continue

        unranked.append(pick)
        extended.append(
            LoggedPick(
                player_key=player_key(pick.name, pick.position, pick.team),
                source="keeper" if pick.is_keeper else "sleeper",
                name=pick.name,
                position=pick.position,
                team=pick.team,
            )
        )

    return extended, unranked


def _serialize(
    session: dict,
    state: DraftState,
    unranked: list[SleeperPick] | None = None,
) -> dict:
    cell = state.current
    your_slot = state.config.your_slot
    you = state.team(your_slot)

    return {
        "id": session["id"],
        "name": session["name"],
        "mode": session["mode"],
        "your_slot": your_slot,
        "config": {
            "teams": state.config.teams,
            "rounds": state.config.rounds,
            "your_slot": your_slot,
            "position_limits": state.config.position_limits,
            "lineup": state.config.lineup.as_dict(),
        },
        "complete": state.complete,
        "your_turn": state.your_turn,
        "on_the_clock": None if cell is None else {
            "overall": cell.overall,
            "round": cell.round,
            "pick_in_round": cell.pick_in_round,
            "team_slot": cell.team_slot,
        },
        "picks_until_your_next": None if cell is None else picks_until_next(
            state.config, your_slot, cell.overall - 1
        ),
        "picks": [
            {
                "overall": p.overall, "round": p.round, "team_slot": p.team_slot,
                "player_name": p.player_name, "position": p.position, "team": p.team,
                "bye_week": p.bye_week, "adp": p.adp, "source": p.source,
            }
            for p in state.picks
        ],
        "your_roster": [
            {
                "player_name": p.player_name, "position": p.position, "team": p.team,
                "bye_week": p.bye_week, "round": p.round, "adp": p.adp,
            }
            for p in you.picks
        ],
        "your_needs": you.needs(state.config.position_limits),
        "bye_clashes": you.bye_clashes(),
        # Picks whose player is not in the rankings. They still hold their
        # seat on the board; they simply have no ADP behind them.
        "unranked": [
            {
                "pick_no": p.pick_no,
                "round": p.round,
                "team_slot": p.draft_slot,
                "name": p.name,
                "position": p.position,
                "team": p.team,
            }
            for p in (unranked or [])
        ],
    }


def _load_or_404(store: SessionStore, session_id: str, owner: str) -> dict:
    session = store.load(session_id, owner)
    if session is None or session["mode"] != "assistant":
        raise HTTPException(status_code=404, detail="no such draft")
    return session


# -------------------------------------------------------------------- routes

@router.post("")
def connect(
    body: ConnectIn,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    client: SleeperClient = Depends(get_client),
    owner: str = Depends(get_owner),
) -> dict:
    """Follow a Sleeper draft, reading its shape from Sleeper itself."""
    try:
        draft_id = draft_id_from_url(body.draft)
        info = client.draft(draft_id)
    except SleeperError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not info.is_snake:
        raise HTTPException(
            status_code=422,
            detail=f"this draft is {info.draft_type or 'an unknown type'}; "
                   "the assistant only understands snake drafts",
        )
    if info.teams < 2 or info.rounds < 1:
        raise HTTPException(status_code=422, detail="Sleeper reported an unusable draft shape")

    # Rankings are loaded for one season. Following a draft from another one
    # leaves most of its picks unmatched -- connecting the 2025 board against
    # 2026 rankings left 27 picks unranked, Tyreek Hill and Joe Mixon among
    # them -- which looks like a broken assistant rather than a mismatch.
    if info.season and info.season != str(app_config.SEASON):
        raise HTTPException(
            status_code=422,
            detail=f"this is a {info.season} draft, but the rankings loaded are "
                   f"for {app_config.SEASON}. The assistant needs both to be the "
                   f"same season to match players.",
        )
    if body.your_slot > info.teams:
        raise HTTPException(
            status_code=422,
            detail=f"this draft has {info.teams} slots, so slot {body.your_slot} does not exist",
        )

    draft = DraftConfig(
        year=app_config.SEASON,
        teams=info.teams,
        rounds=info.rounds,
        your_slot=body.your_slot,
        # Sleeper knows the real starting lineup, so it is read rather than
        # assumed: a first back fills a starting slot, a fifth does not.
        lineup_slots=tuple(sorted(info.slots.items())),
    )
    try:
        validate_config(draft)
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session_id = store.create(
        draft,
        seed=0,
        name=body.name.strip() or f"Live draft · slot {body.your_slot}",
        mode="assistant",
        owner_id=owner,
        source_id=draft_id,
    )

    return _sync(store, pool, client, _load_or_404(store, session_id, owner))


@router.get("")
def list_drafts(
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    return {"sessions": store.list(owner, mode="assistant")}


@router.get("/{session_id}")
def get_draft(
    session_id: str,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    session = _load_or_404(store, session_id, owner)
    state = replay(session["config"], pool, session["log"])
    return _serialize(session, state, None)


@router.get("/{session_id}/advice")
def advice(
    session_id: str,
    limit: int = Query(8, ge=1, le=50),
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    """Who to take at this pick, and why."""
    session = _load_or_404(store, session_id, owner)
    state = replay(session["config"], pool, session["log"])
    return {
        "advice": [a.as_dict() for a in advisor.recommend(state, pool, limit=limit)]
    }


@router.post("/{session_id}/sync")
def sync(
    session_id: str,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    client: SleeperClient = Depends(get_client),
    owner: str = Depends(get_owner),
) -> dict:
    """Pull any picks made since the last look. Safe to call repeatedly."""
    return _sync(store, pool, client, _load_or_404(store, session_id, owner))


def _sync(
    store: SessionStore,
    pool: PlayerPool,
    client: SleeperClient,
    session: dict,
) -> dict:
    try:
        picks = client.picks(session["source_id"])
    except SleeperError as exc:
        # Unreachable with nothing cached: show the board we have and say why,
        # rather than failing the request mid-draft.
        state = replay(session["config"], pool, session["log"])
        payload = _serialize(session, state, None)
        payload["sync_error"] = str(exc)
        return payload

    log, unranked = sync_log(pool, session["log"], picks)
    if len(log) != len(session["log"]):
        store.save_log(session["id"], log, session["owner_id"])

    state = replay(session["config"], pool, log)
    return _serialize(session, state, unranked)


@router.delete("/{session_id}")
def delete_draft(
    session_id: str,
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    _load_or_404(store, session_id, owner)
    store.delete(session_id, owner)
    return {"deleted": session_id}
