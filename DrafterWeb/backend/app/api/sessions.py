"""Mock draft sessions.

The route layer stays thin on purpose: it loads a log, calls the engine, and
saves the log back. All the draft rules live in core/.
"""

from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import config as app_config
from ..core import bots
from ..core.engine import DraftError, DraftState, LoggedPick, append_pick, replay, undo
from ..core.models import ConfigError, DraftConfig, Keeper
from ..core.order import picks_until_next
from ..core.rankings import PlayerPool
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
    rounds: int = Field(default=15, ge=1, le=40)
    your_slot: int = Field(default=6, ge=1)
    randomness: float = Field(default=1.0, ge=0.0, le=3.0)
    seed: int | None = None
    position_limits: dict[str, int] | None = None
    keepers: list[KeeperIn] = Field(default_factory=list)


class PickIn(BaseModel):
    player_key: str


# ------------------------------------------------------------- dependencies

def get_pool() -> PlayerPool:
    from ..main import require_pool

    return require_pool()


def get_store() -> SessionStore:
    from ..main import get_session_store

    return get_session_store()


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
        "config": {
            "teams": state.config.teams,
            "rounds": state.config.rounds,
            "your_slot": your_slot,
            "position_limits": state.config.position_limits,
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


def _load_or_404(store: SessionStore, session_id: str) -> dict:
    session = store.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="no such session")
    return session


# ------------------------------------------------------------------- routes

@router.post("")
def create_session(
    body: SessionIn,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
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
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    seed = body.seed if body.seed is not None else random.randrange(1, 2**31)
    session_id = store.create(
        draft, seed=seed, name=body.name, mode="mock", randomness=body.randomness
    )
    session = _load_or_404(store, session_id)

    # Run the bots picking ahead of the user's first pick.
    log = _run_bots(session, pool, [])
    store.save_log(session_id, log)

    return _serialize(session, replay(draft, pool, log), pool)


@router.get("")
def list_sessions(store: SessionStore = Depends(get_store)) -> dict:
    return {"sessions": store.list()}


@router.get("/{session_id}")
def get_session(
    session_id: str,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
) -> dict:
    session = _load_or_404(store, session_id)
    state = replay(session["config"], pool, session["log"])
    return _serialize(session, state, pool)


@router.get("/{session_id}/available")
def available_players(
    session_id: str,
    position: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
) -> dict:
    session = _load_or_404(store, session_id)
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
) -> dict:
    session = _load_or_404(store, session_id)

    try:
        log = append_pick(session["config"], pool, session["log"], body.player_key, "user")
        log = _run_bots(session, pool, log)
    except DraftError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    store.save_log(session_id, log)
    return _serialize(session, replay(session["config"], pool, log), pool)


@router.post("/{session_id}/undo")
def undo_pick(
    session_id: str,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
) -> dict:
    session = _load_or_404(store, session_id)
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
    store.save_log(session_id, log)
    return _serialize(session, replay(session["config"], pool, log), pool)


@router.post("/{session_id}/autopick")
def autopick(
    session_id: str,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
) -> dict:
    """Let the bot logic take this pick for the user."""
    session = _load_or_404(store, session_id)
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
    store.save_log(session_id, log)
    return _serialize(session, replay(session["config"], pool, log), pool)


@router.post("/{session_id}/simulate")
def simulate_to_end(
    session_id: str,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
) -> dict:
    """Autopick the user's remaining picks and run the draft out."""
    session = _load_or_404(store, session_id)
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

    store.save_log(session_id, log)
    return _serialize(session, state, pool)


@router.delete("/{session_id}")
def delete_session(session_id: str, store: SessionStore = Depends(get_store)) -> dict:
    if not store.delete(session_id):
        raise HTTPException(status_code=404, detail="no such session")
    return {"deleted": session_id}
