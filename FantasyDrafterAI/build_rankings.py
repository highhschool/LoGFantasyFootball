"""Build the DrafterAI ranking CSVs from Fantasy Football Calculator's public ADP API.

Replaces the old manual FantasyPros CSV downloads. Writes one overall file plus
one file per position into <YEAR>_Rankings/, ordered by ADP.

    python build_rankings.py
"""

import logging
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ====== CONFIG ======
YEAR = 2026
TEAMS = 12
SCORING = "ppr"  # ppr | half-ppr | standard
OUT_DIR = Path(__file__).parent / f"{YEAR}_Rankings"

API_URL = "https://fantasyfootballcalculator.com/api/v1/adp/{scoring}"

# FFC labels these differently than the league does
POSITION_ALIASES = {"DEF": "DST", "PK": "K"}

# Position files DrafterAI expects, keyed by the POS value used in the CSVs
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]

COLUMNS = [
    "RK", "PLAYER NAME", "POS", "POS RANK", "TEAM", "BYE WEEK",
    "ADP", "ADP ROUND", "TIMES DRAFTED", "HIGH", "LOW", "STDEV",
]


def fetch_adp(year: int, teams: int, scoring: str) -> list[dict]:
    """Pull the raw ADP feed. No API key required."""
    url = API_URL.format(scoring=scoring)
    params = {"teams": teams, "year": year, "position": "all"}
    logging.info(f"fetching {scoring.upper()} ADP for {year} ({teams}-team)...")

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    players = payload.get("players", [])
    if not players:
        raise ValueError(f"No players returned for {year}. Season data may not be published yet.")

    meta = payload.get("meta", {})
    logging.info(
        f"got {len(players)} players from {meta.get('total_drafts', '?')} drafts "
        f"({meta.get('start_date', '?')} to {meta.get('end_date', '?')})"
    )
    return players


def build_frame(players: list[dict]) -> pd.DataFrame:
    """Normalize the feed into the wide table the drafter reads."""
    df = pd.DataFrame(players)
    df["POS"] = df["position"].replace(POSITION_ALIASES)

    unknown = set(df["POS"]) - set(POSITIONS)
    if unknown:
        logging.warning(f"dropping players with unrecognized positions: {sorted(unknown)}")
        df = df[df["POS"].isin(POSITIONS)]

    # ADP order is draft order; every rank below derives from it
    df = df.sort_values("adp").reset_index(drop=True)
    df["RK"] = df.index + 1
    df["POS RANK"] = df.groupby("POS").cumcount() + 1

    df = df.rename(columns={
        "name": "PLAYER NAME",
        "team": "TEAM",
        "bye": "BYE WEEK",
        "adp": "ADP",
        "adp_formatted": "ADP ROUND",
        "times_drafted": "TIMES DRAFTED",
        "high": "HIGH",
        "low": "LOW",
        "stdev": "STDEV",
    })
    return df[COLUMNS]


def write_csvs(df: pd.DataFrame, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    df.to_csv(out_dir / "OVR_Rankings.csv", index=False)
    logging.info(f"wrote OVR_Rankings.csv ({len(df)} players)")

    for pos in POSITIONS:
        pos_df = df[df["POS"] == pos].copy()
        # RK is positional rank within these files
        pos_df["RK"] = pos_df["POS RANK"]
        pos_df.to_csv(out_dir / f"{pos}_Rankings.csv", index=False)
        logging.info(f"wrote {pos}_Rankings.csv ({len(pos_df)} players)")


def report_roster_capacity(df: pd.DataFrame, teams: int) -> None:
    """Warn early if the pool can't fill every roster at some position."""
    from DrafterAI import TheGeneralManager as GM

    for pos, limit in GM.POSITION_LIMITS.items():
        needed = limit * teams
        available = int((df["POS"] == pos).sum())
        if available < needed:
            logging.warning(f"{pos}: only {available} available, draft needs up to {needed}")


def main() -> None:
    logging.info(" -- STARTING -- ")
    players = fetch_adp(YEAR, TEAMS, SCORING)
    df = build_frame(players)
    write_csvs(df, OUT_DIR)

    try:
        report_roster_capacity(df, TEAMS)
    except ImportError:
        pass

    logging.info(f"rankings ready in {OUT_DIR}")
    logging.info(" -- FINISHED -- ")


if __name__ == "__main__":
    main()
