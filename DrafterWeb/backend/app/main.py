"""FastAPI entry point.

P0 scope: prove the whole path works end to end -- rankings load, the board
builds, and both are reachable over the tunnel. Draft sessions arrive in P1.
"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .api import sessions
from .core.models import DraftConfig, RankingsError
from .core.order import build_board, picks_for_slot
from .core import adp, roster
from .core.rankings import PlayerPool, build_pool
from .store import SessionStore

logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Rankings are read once at startup. They only change when build_rankings.py
# runs, so re-reading per request would be waste; /rankings/reload picks up a
# regenerated file without a restart.
_pool: PlayerPool | None = None
_load_error: str | None = None
_store: SessionStore | None = None


def _load() -> None:
    global _pool, _load_error
    try:
        _pool = build_pool(
            year=config.SEASON,
            teams=config.ADP_TEAMS,
            scoring=config.ADP_SCORING,
            cache_dir=config.ADP_CACHE_DIR,
            ttl_seconds=config.ADP_TTL_SECONDS,
            csv_dir=config.RANKINGS_DIR,
            allow_network=config.ADP_ALLOW_NETWORK,
        )
        _load_error = None
    except RankingsError as exc:
        # Startup must not die here: an unreachable feed with no cache should
        # render as a readable message in the UI, not an unreachable container.
        _pool = None
        _load_error = str(exc)
        logger.error("rankings unavailable: %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    _load()
    yield


app = FastAPI(title="NGFL Drafter", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_pool() -> PlayerPool:
    if _pool is None:
        raise HTTPException(status_code=503, detail=_public_error() or "rankings not loaded")
    return _pool


# Public names the routers depend on.
def require_pool() -> PlayerPool:
    return _require_pool()


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore(config.DATA_DIR / "sessions.db")
    return _store


@app.get("/api/health")
def health() -> dict:
    """Public: reachable by anyone who knows the domain.

    Deliberately reports the rankings directory by name rather than by absolute
    path, and summarizes a load failure instead of echoing it, so a server-side
    path never reaches an unauthenticated caller. The full path and the full
    error are both in the logs.
    """
    body = {
        "status": "ok" if _pool else "degraded",
        "season": config.SEASON,
        "players_loaded": len(_pool) if _pool else 0,
        "error": _public_error(),
    }
    if _pool is not None:
        provenance = _pool.provenance
        body["adp"] = provenance.as_dict()
        body["adp"]["age"] = adp.humanize_age(provenance.age_seconds)
    return body


def _public_error() -> str | None:
    if _load_error is None:
        return None
    if "missing required column" in _load_error:
        return "rankings file does not match the expected schema"
    if "unreachable" in _load_error or "could not reach" in _load_error:
        return "the ADP feed is unreachable and nothing is cached yet"
    return "rankings could not be loaded"


@app.post("/api/rankings/reload")
def reload_rankings(x_admin_token: str = Header(default="")) -> dict:
    """Admin only. The site is public, so this fails closed.

    With no ADMIN_TOKEN configured the route 404s rather than 403s, so a public
    scan cannot confirm an admin endpoint exists here.
    """
    if not config.ADMIN_TOKEN:
        raise HTTPException(status_code=404, detail="Not Found")
    if not secrets.compare_digest(x_admin_token, config.ADMIN_TOKEN):
        logger.warning("rejected rankings reload with a bad admin token")
        raise HTTPException(status_code=403, detail="forbidden")

    _load()
    return health()


@app.get("/api/players")
def list_players(
    position: str | None = Query(None, description="QB, RB, WR, TE, K, or DST"),
    search: str | None = Query(None, description="partial player name"),
    limit: int = Query(500, ge=1, le=2000),
) -> dict:
    pool = _require_pool()

    if search:
        players = pool.search(search, limit=limit)
    elif position:
        players = pool.by_position(position)[:limit]
    else:
        players = pool.players[:limit]

    return {"count": len(players), "players": players}


@app.get("/api/board")
def board(
    teams: int = Query(12, ge=2, le=32),
    rounds: int = Query(15, ge=1, le=40),
    your_slot: int = Query(6, ge=1),
) -> dict:
    """The empty draft board for a config. Keepers are not wired up until P1."""
    draft = DraftConfig(
        year=config.SEASON, teams=teams, rounds=rounds, your_slot=your_slot
    )
    try:
        cells = build_board(draft)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "teams": teams,
        "rounds": rounds,
        "your_slot": your_slot,
        "your_picks": picks_for_slot(draft, your_slot),
        "board": cells,
    }


@app.get("/api/roster-capacity")
def roster_capacity(teams: int = Query(12, ge=2, le=32)) -> dict:
    """How deep a draft this league size can actually run.

    The setup screen uses it to cap the rounds control, so an impossible
    combination is unreachable rather than an error after pressing start.
    """
    pool = _require_pool()
    capacity = roster.pool_capacity(pool, teams)
    max_rounds = sum(capacity.values())

    return {
        "teams": teams,
        "max_rounds": max_rounds,
        "per_position": capacity,
        "suggested": roster.auto_limits(pool, teams, min(15, max_rounds)),
    }


app.include_router(sessions.router)


# Mounted last so it never shadows /api.
_STATIC = Path(__file__).parent / "static"
if _STATIC.is_dir():
    app.mount("/", StaticFiles(directory=_STATIC, html=True), name="static")
