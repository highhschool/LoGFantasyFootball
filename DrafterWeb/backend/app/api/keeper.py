"""Keeper selection.

A third tool, separate from the two draft tools in the same way they are
separate from each other: its own routes, its own screens, its own storage.

Sleeper cannot authenticate anyone -- it has no OAuth, and its API answers
anyone who asks -- so nobody signs in. The league is a closed set of twelve
known people, and each proves which one they are with a code sent to them
privately. That ties every selection to a real Sleeper user id, which is what
makes the result usable on draft night.

Nobody sees anyone else's pick before the deadline. Keeping is a decision made
against the board, not against each other.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import config as app_config
from ..core.keepers import roster_options
from ..core.rankings import PlayerPool
from ..integrations.sleeper import SleeperClient, SleeperError
from ..owner import resolve as resolve_owner
from ..store import SessionStore

router = APIRouter(prefix="/api/keeper", tags=["keeper"])


class ClaimIn(BaseModel):
    user_id: str
    code: str = Field(min_length=1, max_length=32)


class PickIn(BaseModel):
    player_key: str


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


# -------------------------------------------------------------------- state

def deadline() -> datetime | None:
    return app_config.KEEPER_DEADLINE


def is_open() -> bool:
    """Selections are open until the deadline passes.

    With no deadline configured the tool stays open, because a keeper board
    that silently refuses everyone is worse than one with no cutoff.
    """
    when = deadline()
    return when is None or datetime.now(timezone.utc) < when


def require_open() -> None:
    if not is_open():
        raise HTTPException(
            status_code=409,
            detail="the keeper deadline has passed; selections are locked",
        )


def require_claim(store: SessionStore, owner: str) -> dict:
    """The same wording everywhere: identity is no longer this tool's alone."""
    manager = store.claimed_manager(owner)
    if manager is None:
        raise HTTPException(
            status_code=403, detail="sign in with your manager code first"
        )
    return manager


def _league_id() -> str:
    league = app_config.SLEEPER_LEAGUE_ID
    if not league:
        raise HTTPException(
            status_code=503,
            detail="no league configured; set SLEEPER_LEAGUE_ID",
        )
    return league


# ------------------------------------------------------------------- routes

@router.get("")
def status(
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    """Where things stand for whoever is asking."""
    when = deadline()
    manager = store.claimed_manager(owner)
    pick = store.keeper(manager["user_id"]) if manager else None

    return {
        "open": is_open(),
        "deadline": when.isoformat() if when else None,
        "you": manager,
        # The key as well as the name, so the roster can mark which row is
        # already yours without matching on a display string.
        "pick_key": pick["player_key"] if pick else None,
        "pick": None if pick is None else {
            "player_name": pick["player_name"],
            "position": pick["position"],
            "team": pick["nfl_team"],
            "adp": pick["adp"],
            "round": pick["round"],
            "submitted_at": pick["submitted_at"],
            "updated_at": pick["updated_at"],
        },
    }


@router.get("/managers")
def managers(store: SessionStore = Depends(get_store)) -> dict:
    """The teams to choose from. Codes are never included here."""
    return {"managers": store.managers(with_codes=False)}


@router.post("/claim")
def claim(
    body: ClaimIn,
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    if not store.claim_manager(body.user_id, body.code, owner):
        raise HTTPException(status_code=403, detail="that code does not match that team")

    manager = store.claimed_manager(owner)
    return {"you": manager}


@router.get("/roster")
def roster(
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    client: SleeperClient = Depends(get_client),
    owner: str = Depends(get_owner),
) -> dict:
    """Your roster from last season, priced by keeper round."""
    manager = require_claim(store, owner)

    try:
        rosters = client.league_rosters(_league_id())
        directory = client.player_directory()
    except SleeperError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    mine = rosters.get(manager["user_id"], [])
    options = roster_options(
        mine, directory, pool, app_config.ADP_TEAMS, app_config.DRAFT_ROUNDS
    )
    current = store.keeper(manager["user_id"])

    return {
        "you": manager,
        "open": is_open(),
        "teams": app_config.ADP_TEAMS,
        "season": app_config.SEASON,
        "rounds": app_config.DRAFT_ROUNDS,
        "selected": current["player_key"] if current else None,
        "options": [o.as_dict() for o in options],
    }


@router.post("/pick")
def pick(
    body: PickIn,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
    client: SleeperClient = Depends(get_client),
    owner: str = Depends(get_owner),
) -> dict:
    """Choose, or change, your keeper."""
    require_open()
    manager = require_claim(store, owner)

    # Validated against your own roster, which is the only list that matters:
    # keeping someone else's player is not a thing, and a player this year's
    # ADP has never heard of is still yours to keep.
    try:
        rosters = client.league_rosters(_league_id())
        directory = client.player_directory()
    except SleeperError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    mine = roster_options(
        rosters.get(manager["user_id"], []), directory, pool,
        app_config.ADP_TEAMS, app_config.DRAFT_ROUNDS,
    )
    chosen = next((o for o in mine if o.key == body.player_key), None)
    if chosen is None:
        raise HTTPException(
            status_code=422, detail="that player was not on your roster last season"
        )

    store.set_keeper(manager["user_id"], {
        "player_key": chosen.key,
        "player_name": chosen.name,
        "position": chosen.position,
        "nfl_team": chosen.team,
        "adp": chosen.adp,
        "round": chosen.round,
    })

    return {
        "you": manager,
        "pick": {
            "player_name": chosen.name,
            "position": chosen.position,
            "team": chosen.team,
            "adp": chosen.adp,
            "round": chosen.round,
            "ranked": chosen.ranked,
            "near_boundary": chosen.near_boundary,
        },
    }


@router.delete("/pick")
def unpick(
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    require_open()
    manager = require_claim(store, owner)
    store.clear_keeper(manager["user_id"])
    return {"cleared": True}


@router.get("/import")
def draft_import(
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    """The league's keepers as a mock draft's keeper list.

    A mock draft needs a team slot and a round, which the keeper board only
    half knows: it has the round, and the draft order supplies the slot. Both
    have to be there for a row to be importable, so a manager with no slot is
    reported rather than dropped -- an import that silently lands eleven of
    twelve keepers is worse than one that says why.

    Signing in is the gate, not the deadline. Those are different questions
    and the earlier version confused them: a league member should be able to
    mock against the real keepers whenever they like -- the selections are in
    Sleeper anyway, so a time lock bought no privacy -- but this site is public,
    and a stranger who has never heard of the league had no business pulling
    twelve people's keepers out of it.

    That also puts the league where it belongs. A mock draft has no inherent
    knowledge of the NGFL; it asks whoever is running it, and the answer comes
    from their account. Today one account means one league, which is why the
    league id is still configuration -- but the seam is here rather than baked
    into the mock draft tool.

    Selections stay provisional until the lock, which the caller is told with
    `open` rather than by being refused.
    """
    manager = require_claim(store, owner)
    rows = store.all_keepers()

    keepers, waiting, unordered = [], [], []
    for row in rows:
        who = row["display_name"] or row["team_name"] or row["user_id"]
        if not row["player_name"]:
            waiting.append(who)
        elif row["draft_slot"] is None:
            unordered.append(who)
        else:
            keepers.append({
                "team_slot": row["draft_slot"],
                "round": row["round"],
                "player_name": row["player_name"],
                "manager": who,
                "position": row["position"],
                "adp": row["adp"],
            })

    keepers.sort(key=lambda k: (k["team_slot"], k["round"]))
    return {
        # True while selections can still change, which is the caveat on
        # anything imported from here.
        "open": is_open(),
        # Whose league this is. One account, one league, for now.
        "league": manager["display_name"] or manager["team_name"],
        "managers": len(rows),
        "waiting": waiting,
        "unordered": unordered,
        "keepers": keepers,
    }


@router.get("/board")
def board(store: SessionStore = Depends(get_store)) -> dict:
    """Everyone's selections -- but only once the deadline has passed.

    Publishing them live would turn a decision about the board into a decision
    about each other.
    """
    if is_open():
        chosen = sum(1 for k in store.all_keepers() if k["player_name"])
        total = len(store.managers())
        return {
            "open": True,
            "chosen": chosen,
            "total": total,
            "keepers": [],
        }

    return {"open": False, "keepers": store.all_keepers()}
