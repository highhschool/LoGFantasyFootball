from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.core.rankings import REQUIRED_COLUMNS, load_pool

FIXTURES = Path(__file__).parent / "fixtures"

POSITION_ALIASES = {"DEF": "DST", "PK": "K"}


def _ffc_to_csv(payload: dict, out_dir: Path) -> Path:
    """Write an FFC ADP payload out in build_rankings.py's exact CSV format.

    Mirrors that script's transform so the fixture exercises the real loader
    rather than a convenient shortcut.
    """
    players = sorted(payload["players"], key=lambda p: p["adp"])

    rows, pos_counts = [], {}
    for index, player in enumerate(players, start=1):
        position = POSITION_ALIASES.get(player["position"], player["position"])
        if position not in {"QB", "RB", "WR", "TE", "K", "DST"}:
            continue
        pos_counts[position] = pos_counts.get(position, 0) + 1
        rows.append({
            "RK": index,
            "PLAYER NAME": player["name"],
            "POS": position,
            "POS RANK": pos_counts[position],
            "TEAM": player["team"],
            "BYE WEEK": player.get("bye", ""),
            "ADP": player["adp"],
            "ADP ROUND": player.get("adp_formatted", ""),
            "TIMES DRAFTED": player.get("times_drafted", 0),
            "HIGH": player.get("high", 0),
            "LOW": player.get("low", 0),
            "STDEV": player.get("stdev", 0),
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "OVR_Rankings.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REQUIRED_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture(scope="session")
def ffc_2025() -> dict:
    return json.loads((FIXTURES / "ffc_adp_2025.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def sleeper_2025() -> dict:
    return json.loads((FIXTURES / "sleeper_draft_2025.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def rankings_dir_2025(ffc_2025, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("rankings_2025")
    _ffc_to_csv(ffc_2025, out)
    return out


@pytest.fixture(scope="session")
def pool_2025(rankings_dir_2025):
    return load_pool(rankings_dir_2025, 2025)
