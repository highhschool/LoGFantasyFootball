"""The owner's view across every session.

Almost entirely read-only. Seeing what the league has been drafting is one
thing; deleting somebody's draft from a browser is a much larger blast radius
for the same gate, so exactly two routes here change anything -- the keeper
sync and the session purge -- and both are named in a test that fails if a
third appears.

The purge exists because the alternative was worse. A user's delete used to
drop the row, which meant anybody could quietly erase a draft from the one
view meant to see all of them. Now their delete hides and this one removes.

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
from ..core.keeper_verify import compare, summarize
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
        "total": store.count_all(mode=mode),
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


@router.delete("/sessions/{session_id}")
def purge_session(
    session_id: str,
    request: Request,
    store: SessionStore = Depends(get_store),
) -> dict:
    """Remove a session for good.

    The only route in this app that truly destroys anything, and it exists
    because the alternative was worse: a hard delete on the owner's side, so
    anybody could quietly erase a draft from the one view meant to see all of
    them. Their delete hides; this one removes, and it is reachable from one
    screen behind one gate.

    There is no undo. A session is its config and its log, so what goes is a
    board somebody drafted -- which is why the button asks first.
    """
    require_admin(request)

    session = store.load_any(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="no such session")
    if not store.purge(session_id):
        raise HTTPException(status_code=404, detail="no such session")

    return {"purged": session_id, "name": session["name"]}


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


@router.get("/keepers/verify")
def keeper_verify(
    request: Request,
    store: SessionStore = Depends(get_store),
    client: SleeperClient = Depends(get_client),
) -> dict:
    """Diff this league's chosen keepers against the Sleeper draft board.

    Sleeper cannot be written to, so the keepers get typed into its
    commissioner UI by hand -- and it publishes them before the draft starts,
    which makes the mistakes findable while there is still time to fix them.
    """
    require_admin(request)

    league = app_config.SLEEPER_LEAGUE_ID
    if not league:
        raise HTTPException(status_code=503, detail="no league configured")

    try:
        draft = client.latest_draft(league)
        picks = client.picks(draft.draft_id)
    except SleeperError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    rows = compare(store.all_keepers(), picks)
    return {
        "draft_id": draft.draft_id,
        "draft_status": draft.status,
        "rows": [r.as_dict() for r in rows],
        **summarize(rows),
    }


@router.post("/keepers/sync")
def keeper_sync(
    request: Request,
    store: SessionStore = Depends(get_store),
    client: SleeperClient = Depends(get_client),
) -> dict:
    """Pull the league's members and draft order, minting codes for anyone new."""
    require_admin(request)

    league = app_config.SLEEPER_LEAGUE_ID
    if not league:
        raise HTTPException(status_code=503, detail="no league configured")

    try:
        managers = client.league_managers(league)
    except SleeperError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # The order is discovered from whichever draft is current, and is missing
    # until the commissioner sets one. That is a normal pre-draft state, so a
    # league without an order still syncs -- it just lists by name.
    try:
        order = client.latest_draft(league).draft_order
    except SleeperError:
        order = {}

    result = store.sync_managers(
        [(m.user_id, m.display_name, m.team_name) for m in managers],
        order,
        {m.user_id: m.avatar for m in managers if m.avatar},
    )
    return {"managers": len(managers), **result}
