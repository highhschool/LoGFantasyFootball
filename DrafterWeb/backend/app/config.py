"""Runtime settings, all overridable by environment variable.

RANKINGS_DIR points at a directory containing OVR_Rankings.csv. In Docker it is
a read-only bind mount of FantasyDrafterAI/<YEAR>_Rankings; running locally it
defaults to the sibling checkout.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

# DrafterWeb/backend/app/config.py -> DrafterWeb/
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent

# Docker Compose reads DrafterWeb/.env on its own, but a bare `uvicorn` run does
# not, which would make the same file work in one path and be silently ignored
# in the other. Real environment variables still win over the file.
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:  # optional; the defaults below stand on their own
    pass


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw) if raw else default


SEASON = int(os.getenv("SEASON", "2026"))

# ADP comes from Fantasy Football Calculator by default, so the app needs
# nothing from the CLI tool in order to run.
ADP_TEAMS = int(os.getenv("ADP_TEAMS", "12"))

# The league's draft length, which is also what an unranked keeper costs: a
# player nobody drafts is the cheapest keeper there is, not an ineligible one.
DRAFT_ROUNDS = int(os.getenv("DRAFT_ROUNDS", "15"))
ADP_SCORING = os.getenv("ADP_SCORING", "ppr")  # ppr | half-ppr | standard

# How long a cached feed is served without re-fetching. FFC publishes a rolling
# one-week window, so hourly is plenty fresh and keeps startup instant.
ADP_TTL_SECONDS = int(os.getenv("ADP_TTL_SECONDS", "3600"))

# Set to false for an air-gapped run: serve the cache and never dial out.
ADP_ALLOW_NETWORK = os.getenv("ADP_ALLOW_NETWORK", "true").lower() not in {"0", "false", "no"}

# Optional CSV override. Unset by default -- point it at build_rankings.py
# output (or hand-curated rankings in that format) and it wins over the API.
_csv_override = os.getenv("RANKINGS_DIR", "").strip()
RANKINGS_DIR: Path | None = Path(_csv_override) if _csv_override else None

DATA_DIR = _env_path("DATA_DIR", PROJECT_ROOT / "data")
ADP_CACHE_DIR = DATA_DIR / "adp-cache"

# When keeper selections lock. An explicit offset is required rather than
# assumed, because a deadline an hour out from what people expect is worse
# than no deadline. Unset leaves selections open indefinitely.
def _deadline() -> "datetime | None":
    raw = os.getenv("KEEPER_DEADLINE", "").strip()
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(raw)
    except ValueError:
        return None
    # A naive value would compare against UTC and silently shift.
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


KEEPER_DEADLINE = _deadline()


def _moment(name: str) -> "datetime | None":
    """An instant from the environment, or None. Same rules as the deadline:
    an explicit offset, because an hour's silent shift is worse than nothing."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


# The contracts slate. Trading runs from the Monday until the draft starts,
# and everything settles from the picks feed afterwards -- so nothing is
# tradeable once any answer is knowable, which is the whole reason for a single
# hard close rather than per-market ones.
CONTRACTS_OPEN = _moment("CONTRACTS_OPEN")
CONTRACTS_CLOSE = _moment("CONTRACTS_CLOSE")

SLEEPER_API = os.getenv("SLEEPER_API", "https://api.sleeper.app/v1")
SLEEPER_LEAGUE_ID = os.getenv("SLEEPER_LEAGUE_ID", "")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Gates the admin-only routes. The site is public, so they fail closed: with
# neither of these set, nothing admin is reachable at all.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# Addresses Cloudflare Access may admit to the admin view. Access verifies the
# identity; this decides which verified identity is the site owner.
ADMIN_EMAILS = {
    email.strip().lower()
    for email in os.getenv("ADMIN_EMAILS", "").split(",")
    if email.strip()
}

# Comma-separated. The tunnel terminates TLS and forwards to the API, so in
# production this is the real hostname.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
