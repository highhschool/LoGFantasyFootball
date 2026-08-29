"""A player, from every angle the app has one.

Four sources, joined on a click. Where a player is drafted comes from the ADP
feed, what he did comes from ten seasons of Sleeper statistics, who he is comes
from Sleeper's directory, and a face and a headline come from Fantasy Football
Calculator.

Only the first is load-bearing. The other three are separately unavailable and
separately optional: a profile with no headshot, no career and no news still
shows a name, an ADP and the model's view of it, and says which parts are
missing rather than failing. Nothing here settles anything, so best-effort is
the right posture for all of it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import config as app_config
from ..core.advisor import survival_probability
from ..core.models import Player
from ..core.rankings import PlayerPool
from ..integrations.ffc import FfcClient
from ..integrations.sleeper import SleeperClient
from ..stats_store import StatsStore

router = APIRouter(prefix="/api/players", tags=["players"])

# The stats worth showing, by position. Everything is stored -- this is the
# view, so widening it is a change here rather than a refetch.
COLUMNS = {
    "QB": ["gp", "pass_cmp", "pass_att", "pass_yd", "pass_td", "pass_int",
           "rush_att", "rush_yd", "rush_td", "pts_ppr"],
    "RB": ["gp", "rush_att", "rush_yd", "rush_td",
           "rec_tgt", "rec", "rec_yd", "rec_td", "fum_lost", "pts_ppr"],
    "WR": ["gp", "rec_tgt", "rec", "rec_yd", "rec_td",
           "rush_att", "rush_yd", "fum_lost", "pts_ppr"],
    "TE": ["gp", "rec_tgt", "rec", "rec_yd", "rec_td", "fum_lost", "pts_ppr"],
    "K": ["gp", "fgm", "fga", "fgm_50p", "xpm", "xpa", "pts_ppr"],
    "DST": ["gp", "def_st_td", "int", "ff", "fum_rec", "sack", "pts_allow",
            "pts_ppr"],
}
DEFAULT_COLUMNS = ["gp", "pts_ppr"]


def get_pool() -> PlayerPool:
    from ..main import require_pool

    return require_pool()


def get_stats() -> StatsStore:
    from ..main import get_stats_store

    return get_stats_store()


def get_ffc() -> FfcClient:
    from ..main import get_ffc_client

    return get_ffc_client()


def get_sleeper() -> SleeperClient:
    from ..main import get_sleeper_client

    return get_sleeper_client()


def _sleeper_id(client: SleeperClient, player: Player) -> tuple[str | None, dict]:
    """Find this player in Sleeper's directory.

    Two feeds naming the same people differently is the oldest problem in this
    app, so it reuses the matching the draft board already relies on rather
    than inventing a second one.
    """
    from ..core.names import normalize_name, normalize_position

    try:
        directory = client.player_directory()
    except Exception:
        return None, {}

    wanted = normalize_name(player.name)
    position = normalize_position(player.position)

    fallback = None
    for pid, entry in directory.items():
        name = f"{entry.get('first_name') or ''} {entry.get('last_name') or ''}"
        if normalize_name(name) != wanted:
            continue
        if normalize_position(entry.get("position") or "") == position:
            return pid, entry
        fallback = fallback or (pid, entry)

    return fallback if fallback else (None, {})


@router.get("/{ffc_id}/profile")
def profile(
    ffc_id: int,
    seasons: int = Query(5, ge=1, le=10),
    at_pick: int | None = Query(None, ge=1, description="your next pick, for survival"),
    pool: PlayerPool = Depends(get_pool),
    stats: StatsStore = Depends(get_stats),
    ffc: FfcClient = Depends(get_ffc),
    sleeper: SleeperClient = Depends(get_sleeper),
) -> dict:
    """Everything known about one player.

    Keyed on Fantasy Football Calculator's id rather than the app's own
    composite key, which carries colons and spaces and would need escaping in
    a URL.
    """
    player = next((p for p in pool.players if p.ffc_id == ffc_id), None)
    if player is None:
        raise HTTPException(
            status_code=404, detail="no player on this year's board with that id"
        )

    sleeper_id, entry = _sleeper_id(sleeper, player)
    career = stats.career(sleeper_id, limit=seasons) if sleeper_id else []
    note = ffc.player(ffc_id)

    columns = COLUMNS.get(player.position, DEFAULT_COLUMNS)
    rows = [
        {"season": row["season"],
         **{c: row.get(c) for c in columns}}
        for row in career
    ]

    return {
        "player": {
            "ffc_id": player.ffc_id,
            "key": player.key,
            "name": player.name,
            "position": player.position,
            "team": player.team,
            "team_full": note.team_full if note else "",
            "bye_week": player.bye_week,
            "rookie": bool(note and note.rookie),
            "headshot": note.headshot if note else None,
        },
        # Where the room has him, and how sure it is.
        "adp": {
            "adp": player.adp,
            "round": player.adp_round,
            "rank": player.rank,
            "pos_rank": player.pos_rank,
            "high": player.high,
            "low": player.low,
            "stdev": player.stdev,
            "times_drafted": player.times_drafted,
            # Only meaningful with a pick to survive to.
            "survives_to": None if at_pick is None else round(
                survival_probability(player, 0, at_pick) * 100
            ),
            "at_pick": at_pick,
        },
        # Who he is, when Sleeper knows.
        "bio": {
            "age": entry.get("age"),
            "college": entry.get("college"),
            "years_exp": entry.get("years_exp"),
            "number": entry.get("number"),
            "height": entry.get("height"),
            "weight": entry.get("weight"),
            "depth_chart_order": entry.get("depth_chart_order"),
            "injury_status": entry.get("injury_status"),
            "status": entry.get("status"),
        } if entry else None,
        "career": {"columns": columns, "seasons": rows},
        "notes": [n.as_dict() for n in (note.notes if note else ())][:3],
        # Which halves came back, so the page can say so rather than showing
        # an empty box that reads as a bug.
        "have": {
            "career": bool(rows),
            "bio": bool(entry),
            "notes": bool(note and note.notes),
        },
        "season": app_config.SEASON,
    }
