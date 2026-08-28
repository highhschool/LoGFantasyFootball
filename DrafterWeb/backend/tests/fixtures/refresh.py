"""Refresh the cached test fixtures. Run only when you want new data.

    python -m tests.fixtures.refresh

Pulls two things and caches them as JSON so the suite runs offline:

  ffc_adp_2025.json      Fantasy Football Calculator PPR ADP for 2025. The
                         league's real draft ran 25 Aug 2025, and this feed
                         covers drafts from 25 Aug to 1 Sep 2025, so it is the
                         ADP landscape that actually existed on the night.

  sleeper_draft_2025.json  The league's completed 180-pick board.

Together they make an end-to-end regression test: replay the real draft through
the engine and assert the resulting board matches what happened.

Note this deliberately does not use FantasyDrafterAI/2025_Rankings/, which
predates build_rankings.py and carries an incompatible schema.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent

FFC_URL = "https://fantasyfootballcalculator.com/api/v1/adp/ppr?teams=12&year=2025&position=all"
LEAGUE_ID = "1261437958930563072"
SLEEPER = "https://api.sleeper.app/v1"


# FFC returns 403 to urllib's default agent. build_rankings.py never hits this
# because requests sends a browser-shaped one.
USER_AGENT = "NGFL-Drafter/0.1 (+https://github.com/ngfl; fixture refresh)"


def fetch(url: str) -> object:
    print(f"  GET {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def write(name: str, payload: object) -> None:
    path = HERE / name
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"  wrote {path.name}")


def main() -> None:
    print("fantasy football calculator, 2025 PPR ADP:")
    adp = fetch(FFC_URL)
    meta = adp.get("meta", {})
    print(f"  {len(adp.get('players', []))} players from {meta.get('total_drafts')} drafts")
    write("ffc_adp_2025.json", adp)

    print("sleeper, 2025 league draft:")
    drafts = fetch(f"{SLEEPER}/league/{LEAGUE_ID}/drafts")
    draft_id = drafts[0]["draft_id"]
    picks = fetch(f"{SLEEPER}/draft/{draft_id}/picks")
    print(f"  {len(picks)} picks from draft {draft_id}")
    write("sleeper_draft_2025.json", {"draft": drafts[0], "picks": picks})


if __name__ == "__main__":
    main()
