"""Mock draft sessions.

The route layer stays thin on purpose: it loads a log, calls the engine, and
saves the log back. All the draft rules live in core/.
"""

from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from .. import config as app_config
from ..core import bots
from ..core.engine import DraftError, DraftState, LoggedPick, append_pick, replay, undo
from ..core.models import ConfigError, DraftConfig, Keeper
from ..core.order import picks_until_next
from ..core.rankings import PlayerPool
from ..owner import resolve as resolve_owner
from ..store import SessionStore

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ------------------------------------------------------------------ schemas

class KeeperIn(BaseModel):
    team_slot: int = Field(ge=1)
    round: int = Field(ge=1)
    player_name: str


class SessionIn(BaseModel):
    name: str = ""
    teams: int = Field(default=12, ge=2, le=32)
    # The league drafts 15 rounds, and the default roster limits sum to 15.
    rounds: int = Field(default=15, ge=1, le=15)
    your_slot: int = Field(default=6, ge=1)
    randomness: float = Field(default=1.0, ge=0.0, le=3.0)
    seed: int | None = None
    # 0 disables the clock. Capped at 10 minutes; longer is not a draft.
    pick_seconds: int = Field(default=0, ge=0, le=600)
    position_limits: dict[str, int] | None = None
    keepers: list[KeeperIn] = Field(default_factory=list)


class PickIn(BaseModel):
    player_key: str


class SessionPatch(BaseModel):
    """Settings that can change after a draft has started."""

    name: str | None = Field(default=None, max_length=80)
    pick_seconds: int | None = Field(default=None, ge=0, le=600)


# ------------------------------------------------------------- dependencies

def get_pool() -> PlayerPool:
    from ..main import require_pool

    return require_pool()


def get_store() -> SessionStore:
    from ..main import get_session_store

    return get_session_store()


def get_owner(request: Request, response: Response) -> str:
    return resolve_owner(request, response)


# ---------------------------------------------------------------- rendering

def _serialize(session: dict, state: DraftState, pool: PlayerPool) -> dict:
    cell = state.current
    your_slot = state.config.your_slot
    you = state.team(your_slot)

    next_pick = None
    if cell is not None:
        next_pick = picks_until_next(state.config, your_slot, cell.overall - 1)

    return {
        "id": session["id"],
        "name": session["name"],
        "mode": session["mode"],
        "seed": session["seed"],
        "pick_seconds": session.get("pick_seconds", 0),
        "randomness": session.get("randomness", 1.0),
        "config": {
            "teams": state.config.teams,
            "rounds": state.config.rounds,
            "your_slot": your_slot,
            "position_limits": state.config.position_limits,
            # The configured keepers, not the placed ones: a keeper in a later
            # round has no pick yet, and copying settings needs all of them.
            "keepers": [
                {
                    "team_slot": k.team_slot,
                    "round": k.round,
                    "player_name": k.player_name,
                }
                for k in state.config.keepers
            ],
        },
        "complete": state.complete,
        "your_turn": state.your_turn,
        "on_the_clock": None if cell is None else {
            "overall": cell.overall,
            "round": cell.round,
            "pick_in_round": cell.pick_in_round,
            "team_slot": cell.team_slot,
        },
        "picks_until_your_next": next_pick,
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
        "unresolved_keepers": state.unresolved_keepers,
    }


def _run_bots(session: dict, pool: PlayerPool, log: list[LoggedPick]) -> list[LoggedPick]:
    """Advance the draft until the user is on the clock again, or it ends."""
    state = replay(session["config"], pool, log)
    randomness = float(session.get("randomness", 1.0))

    guard = 0
    while not state.complete and not state.your_turn:
        guard += 1
        if guard > state.config.teams * state.config.rounds + 5:
            raise DraftError("bot loop failed to terminate")

        cell = state.current
        rng = bots.rng_for(session["seed"], cell.overall)
        choice = bots.choose(state, pool, cell.team_slot, rng, randomness)
        if choice is None:
            raise DraftError(
                f"no eligible player for slot {cell.team_slot} at pick {cell.overall}; "
                "the player pool is too small for these position limits"
            )
        log = log + [LoggedPick(player_key=choice.key, source="bot")]
        state = replay(session["config"], pool, log)

    return log


def _check_pool_depth(pool: PlayerPool, draft: DraftConfig) -> None:
    """Reject a league the player pool cannot actually fill.

    Without this the draft simply runs dry -- 14 teams needs 28 tight ends and
    the pool holds 27, so the board stops two picks short and reports itself
    incomplete, which reads like success. A wrong answer that looks right is
    worse than an error.
    """
    from collections import Counter

    have = Counter(p.position for p in pool.players)
    for position, limit in draft.position_limits.items():
        needed = limit * draft.teams
        if needed > have.get(position, 0):
            raise ConfigError(
                f"a {draft.teams}-team draft needs {needed} {position}s but the "
                f"player pool only has {have.get(position, 0)}. Use fewer teams."
            )


def _load_or_404(store: SessionStore, session_id: str, owner: str) -> dict:
    """404, not 403, for a session you do not own.

    Distinguishing "not yours" from "does not exist" would let anyone probe for
    other people's draft ids, and buys nothing: either way you cannot open it.
    """
    session = store.load(session_id, owner)
    if session is None or session["mode"] != "mock":
        raise HTTPException(status_code=404, detail="no such session")
    return session


# ------------------------------------------------------------------- routes

@router.post("")
def create_session(
    body: SessionIn,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    limits = body.position_limits or dict(DraftConfig(year=app_config.SEASON).position_limits)
    draft = DraftConfig(
        year=app_config.SEASON,
        teams=body.teams,
        rounds=body.rounds,
        your_slot=body.your_slot,
        position_limits=limits,
        keepers=tuple(Keeper(**k.model_dump()) for k in body.keepers),
    )

    try:
        from ..core.order import validate_config

        validate_config(draft)
        _check_pool_depth(pool, draft)
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    seed = body.seed if body.seed is not None else random.randrange(1, 2**31)
    session_id = store.create(
        draft, seed=seed, name=body.name, mode="mock",
        randomness=body.randomness, pick_seconds=body.pick_seconds,
        owner_id=owner,
    )
    session = _load_or_404(store, session_id, owner)

    # Run the bots picking ahead of the user's first pick. A pool too thin for
    # this league size runs dry here, and must read as a rejected config rather
    # than a server error.
    try:
        log = _run_bots(session, pool, [])
    except DraftError as exc:
        store.delete(session_id, owner)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.save_log(session_id, log, owner)

    return _serialize(session, replay(draft, pool, log), pool)


@router.get("")
def list_sessions(
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    # Mock drafts only; the assistant keeps its own list.
    return {"sessions": store.list(owner, mode="mock")}


@router.get("/{session_id}")
def get_session(
    session_id: str,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    session = _load_or_404(store, session_id, owner)
    state = replay(session["config"], pool, session["log"])
    return _serialize(session, state, pool)


@router.patch("/{session_id}")
def update_session(
    session_id: str,
    body: SessionPatch,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    """Rename a session, or change its pick clock, mid-draft.

    Deliberately narrow: teams, rounds, slot and keepers all change what the
    board means, so altering them after picks exist would invalidate the log.
    Those stay fixed at creation.
    """
    _load_or_404(store, session_id, owner)

    if body.name is not None:
        store.rename(session_id, body.name.strip(), owner)
    if body.pick_seconds is not None:
        store.set_pick_seconds(session_id, body.pick_seconds, owner)

    session = _load_or_404(store, session_id, owner)
    return _serialize(session, replay(session["config"], pool, session["log"]), pool)


@router.get("/{session_id}/available")
def available_players(
    session_id: str,
    position: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    session = _load_or_404(store, session_id, owner)
    state = replay(session["config"], pool, session["log"])

    slot = state.config.your_slot
    players = state.eligible(pool, slot)

    if position:
        wanted = position.upper()
        players = [p for p in players if p.position == wanted]
    if search:
        matches = {p.key for p in pool.search(search, limit=limit * 3)}
        players = [p for p in players if p.key in matches]

    return {
        "count": len(players),
        "players": [
            {
                "key": p.key, "name": p.name, "position": p.position, "team": p.team,
                "bye_week": p.bye_week, "adp": p.adp, "pos_rank": p.pos_rank,
                "stdev": p.stdev,
            }
            for p in players[:limit]
        ],
    }


@router.post("/{session_id}/pick")
def make_pick(
    session_id: str,
    body: PickIn,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    session = _load_or_404(store, session_id, owner)

    try:
        log = append_pick(session["config"], pool, session["log"], body.player_key, "user")
        log = _run_bots(session, pool, log)
    except DraftError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    store.save_log(session_id, log, owner)
    return _serialize(session, replay(session["config"], pool, log), pool)


@router.post("/{session_id}/undo")
def undo_pick(
    session_id: str,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    session = _load_or_404(store, session_id, owner)
    log = session["log"]

    if not log:
        raise HTTPException(status_code=409, detail="nothing to undo")

    # Walk back past the bot picks to the user's own last pick, so one undo
    # returns the user to their own decision rather than to a bot's.
    while log and log[-1].source != "user":
        log = undo(log)
    if log:
        log = undo(log)

    log = _run_bots(session, pool, log)
    store.save_log(session_id, log, owner)
    return _serialize(session, replay(session["config"], pool, log), pool)


@router.post("/{session_id}/autopick")
def autopick(
    session_id: str,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    """Let the bot logic take this pick for the user."""
    session = _load_or_404(store, session_id, owner)
    state = replay(session["config"], pool, session["log"])

    if state.complete:
        raise HTTPException(status_code=409, detail="the draft is already complete")

    cell = state.current
    rng = bots.rng_for(session["seed"], cell.overall)
    choice = bots.choose(state, pool, cell.team_slot, rng, 1.0)
    if choice is None:
        raise HTTPException(status_code=409, detail="no eligible player available")

    log = session["log"] + [LoggedPick(player_key=choice.key, source="user")]
    log = _run_bots(session, pool, log)
    store.save_log(session_id, log, owner)
    return _serialize(session, replay(session["config"], pool, log), pool)


@router.post("/{session_id}/simulate")
def simulate_to_end(
    session_id: str,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    """Autopick the user's remaining picks and run the draft out."""
    session = _load_or_404(store, session_id, owner)
    log = session["log"]

    state = replay(session["config"], pool, log)
    while not state.complete:
        cell = state.current
        rng = bots.rng_for(session["seed"], cell.overall)
        choice = bots.choose(state, pool, cell.team_slot, rng, 1.0)
        if choice is None:
            break
        source = "user" if cell.team_slot == state.config.your_slot else "bot"
        log = log + [LoggedPick(player_key=choice.key, source=source)]
        state = replay(session["config"], pool, log)

    store.save_log(session_id, log, owner)
    return _serialize(session, state, pool)


@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    if not store.delete(session_id, owner):
        raise HTTPException(status_code=404, detail="no such session")
    return {"deleted": session_id}
