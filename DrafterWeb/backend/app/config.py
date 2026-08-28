"""Runtime settings, all overridable by environment variable.

RANKINGS_DIR points at a directory containing OVR_Rankings.csv. In Docker it is
a read-only bind mount of FantasyDrafterAI/<YEAR>_Rankings; running locally it
defaults to the sibling checkout.
"""

from __future__ import annotations

import os
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

RANKINGS_DIR = _env_path(
    "RANKINGS_DIR",
    REPO_ROOT / "FantasyDrafterAI" / f"{SEASON}_Rankings",
)

DATA_DIR = _env_path("DATA_DIR", PROJECT_ROOT / "data")

SLEEPER_API = os.getenv("SLEEPER_API", "https://api.sleeper.app/v1")
SLEEPER_LEAGUE_ID = os.getenv("SLEEPER_LEAGUE_ID", "")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Gates the admin-only rankings reload. The site is public, so this endpoint
# fails closed: with no token set it is not reachable at all.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# Comma-separated. The tunnel terminates TLS and forwards to the API, so in
# production this is the real hostname.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
