"""The owner's view across every session.

Read-only, deliberately. Seeing what the league has been drafting is one
thing; being able to delete somebody's draft from a browser is a much larger
blast radius for the same gate.

Guarded by Cloudflare Access -- see app/admin.py, and note that the Access
application has to cover `/api/admin` as well as `/admin`, or the page is
locked while the data behind it is not.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..admin import require_admin
from .. import config as app_config
from ..integrations.sleeper import SleeperClient, SleeperError
from ..core.engine import replay
from ..core.rankings import PlayerPool
from ..store import SessionStore

router = APIRouter(prefix="/api/admin", tags=["admin"])


def get_pool() -> PlayerPool:
    from ..main import require_pool

    return require_pool()


def get_store() -> SessionStore:
    from ..main import get_session_store

    return get_session_store()


def get_client() -> SleeperClient:
    from ..main import get_sleeper_client

    return get_sleeper_client()


@router.get("/whoami")
def whoami(request: Request) -> dict:
    """Confirms the gate is working and says which identity got through."""
    return {"admin": require_admin(request)}


@router.get("/sessions")
def all_sessions(
    request: Request,
    mode: str | None = Query(None, description="mock or assistant; both if unset"),
    limit: int = Query(200, ge=1, le=1000),
    store: SessionStore = Depends(get_store),
) -> dict:
    require_admin(request)
    sessions = store.list_all(mode=mode, limit=limit)

    owners = {s["owner"] for s in sessions}
    return {
        "count": len(sessions),
        "owners": len(owners),
        "sessions": sessions,
    }


@router.get("/sessions/{session_id}")
def one_session(
    session_id: str,
    request: Request,
    pool: PlayerPool = Depends(get_pool),
    store: SessionStore = Depends(get_store),
) -> dict:
    """The full board of any session, whoever made it."""
    require_admin(request)

    session = store.load_any(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="no such session")

    state = replay(session["config"], pool, session["log"])
    config = session["config"]

    return {
        "id": session["id"],
        "name": session["name"],
        "mode": session["mode"],
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "config": {
            "teams": config.teams,
            "rounds": config.rounds,
            "your_slot": config.your_slot,
            "position_limits": config.position_limits,
            "keepers": [
                {"team_slot": k.team_slot, "round": k.round, "player_name": k.player_name}
                for k in config.keepers
            ],
        },
        "complete": state.complete,
        "on_the_clock": None if state.current is None else {
            "overall": state.current.overall,
            "round": state.current.round,
            "team_slot": state.current.team_slot,
        },
        "picks": [
            {
                "overall": p.overall, "round": p.round, "team_slot": p.team_slot,
                "player_name": p.player_name, "position": p.position, "team": p.team,
                "bye_week": p.bye_week, "adp": p.adp, "source": p.source,
            }
            for p in state.picks
        ],
        "rosters": {
            str(slot): [
                {"player_name": p.player_name, "position": p.position, "round": p.round}
                for p in team.picks
            ]
            for slot, team in state.teams.items()
        },
    }


@router.get("/keepers")
def keeper_board(
    request: Request,
    store: SessionStore = Depends(get_store),
) -> dict:
    """Every selection, and who has not answered yet.

    Visible to the owner before the deadline, unlike the public board: chasing
    the four people who have not picked is the whole reason to look.
    """
    require_admin(request)
    rows = store.all_keepers()
    return {
        "deadline": app_config.KEEPER_DEADLINE.isoformat()
        if app_config.KEEPER_DEADLINE else None,
        "chosen": sum(1 for r in rows if r["player_name"]),
        "total": len(rows),
        "keepers": rows,
    }


@router.get("/keepers/codes")
def keeper_codes(
    request: Request,
    store: SessionStore = Depends(get_store),
) -> dict:
    """The per-manager codes, to send out. Behind Access, like everything here."""
    require_admin(request)
    return {"managers": store.managers(with_codes=True)}


@router.post("/keepers/sync")
def keeper_sync(
    request: Request,
    store: SessionStore = Depends(get_store),
    client: SleeperClient = Depends(get_client),
) -> dict:
    """Pull the league's members from Sleeper, minting codes for anyone new."""
    require_admin(request)

    league = app_config.SLEEPER_LEAGUE_ID
    if not league:
        raise HTTPException(status_code=503, detail="no league configured")

    try:
        managers = client.league_managers(league)
    except SleeperError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    added = store.sync_managers(
        [(m.user_id, m.display_name, m.team_name) for m in managers]
    )
    return {"managers": len(managers), "added": added}
