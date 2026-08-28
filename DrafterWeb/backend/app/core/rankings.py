"""Building the player pool, from the ADP API or from CSVs.

The app fetches ADP directly from Fantasy Football Calculator (see core.adp),
the same public endpoint FantasyDrafterAI/build_rankings.py uses. That keeps the
webapp deployable on its own: it does not need the CLI tool to have been run,
and the two projects cannot drift because both derive from the same upstream.

The CSV reader below remains as an explicit override. Point RANKINGS_DIR at a
directory of build_rankings.py output (or hand-curated rankings in that format)
and it wins over the API. Its schema check is not hypothetical:
FantasyDrafterAI/2025_Rankings/ predates build_rankings.py and carries the old
FantasyPros columns under the same naming convention.

Only OVR_Rankings.csv is read. The per-position files are a projection of it.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from . import adp
from .models import Keeper, Player, RankingsError
from .names import normalize_name, normalize_position, player_key

logger = logging.getLogger(__name__)

OVERALL_FILE = "OVR_Rankings.csv"

# Guaranteed by build_rankings.py. Absence of any of these means the file did
# not come from that script.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "RK", "PLAYER NAME", "POS", "POS RANK", "TEAM", "BYE WEEK",
    "ADP", "ADP ROUND", "TIMES DRAFTED", "HIGH", "LOW", "STDEV",
)


class PlayerPool:
    """Every player in a season's rankings, indexed for lookup."""

    def __init__(
        self,
        players: list[Player],
        year: int,
        provenance: "adp.Provenance | None" = None,
    ) -> None:
        self.year = year
        self.players = players
        self.provenance = provenance or adp.Provenance(source="csv", year=year)
        self.by_key = {p.key: p for p in players}

        self._by_name: dict[str, list[Player]] = {}
        for player in players:
            self._by_name.setdefault(normalize_name(player.name), []).append(player)

    def __len__(self) -> int:
        return len(self.players)

    def by_position(self, position: str) -> list[Player]:
        pos = position.upper()
        return [p for p in self.players if p.position == pos]

    def find(self, name: str, position: str = "", team: str = "") -> Player | None:
        """Resolve a name from another source, most confident match first."""
        if position and team:
            exact = self.by_key.get(player_key(name, position, team))
            if exact is not None:
                return exact

        candidates = self._by_name.get(normalize_name(name), [])
        if position:
            pos = normalize_position(position)
            narrowed = [p for p in candidates if p.position == pos]
            if len(narrowed) == 1:
                return narrowed[0]
            candidates = narrowed or candidates

        return candidates[0] if len(candidates) == 1 else None

    def search(self, query: str, limit: int = 10) -> list[Player]:
        """Prefix and substring search, ADP order preserved."""
        needle = normalize_name(query)
        if not needle:
            return []

        starts, contains = [], []
        for player in self.players:
            haystack = normalize_name(player.name)
            if haystack.startswith(needle):
                starts.append(player)
            elif needle in haystack:
                contains.append(player)
            if len(starts) >= limit:
                break

        return (starts + contains)[:limit]


def _require_int(row: dict[str, str], column: str, line: int) -> int:
    raw = (row.get(column) or "").strip()
    try:
        return int(float(raw))
    except ValueError:
        raise RankingsError(
            f"line {line}: {column} is {raw!r}, which is not a number"
        ) from None


def _optional_int(row: dict[str, str], column: str) -> int | None:
    raw = (row.get(column) or "").strip()
    try:
        return int(float(raw))
    except ValueError:
        return None


def _require_float(row: dict[str, str], column: str, line: int) -> float:
    raw = (row.get(column) or "").strip()
    try:
        return float(raw)
    except ValueError:
        raise RankingsError(
            f"line {line}: {column} is {raw!r}, which is not a number"
        ) from None


def load_pool(rankings_dir: Path, year: int) -> PlayerPool:
    """Read <rankings_dir>/OVR_Rankings.csv into a PlayerPool, ADP-ordered."""
    path = Path(rankings_dir) / OVERALL_FILE

    if not path.is_file():
        raise RankingsError(
            f"{path} does not exist. Run build_rankings.py in FantasyDrafterAI "
            f"to generate the {year} rankings."
        )

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []

        missing = [col for col in REQUIRED_COLUMNS if col not in columns]
        if missing:
            raise RankingsError(
                f"{path} is missing required column(s): {missing}.\n"
                f"Found: {columns}\n"
                f"This file did not come from build_rankings.py. Regenerate it, or "
                f"point RANKINGS_DIR at a directory that did."
            )

        players: list[Player] = []
        seen: set[str] = set()

        for line, row in enumerate(reader, start=2):
            name = (row.get("PLAYER NAME") or "").strip()
            if not name:
                continue

            position = normalize_position(row.get("POS", ""))
            team = (row.get("TEAM") or "").strip().upper()
            key = player_key(name, position, team)

            if key in seen:
                logger.warning("duplicate player %r at line %d, keeping the first", name, line)
                continue
            seen.add(key)

            players.append(
                Player(
                    key=key,
                    name=name,
                    position=position,
                    team=team,
                    rank=_require_int(row, "RK", line),
                    pos_rank=_require_int(row, "POS RANK", line),
                    bye_week=_optional_int(row, "BYE WEEK"),
                    adp=_require_float(row, "ADP", line),
                    adp_round=(row.get("ADP ROUND") or "").strip(),
                    times_drafted=_optional_int(row, "TIMES DRAFTED") or 0,
                    high=_optional_int(row, "HIGH") or 0,
                    low=_optional_int(row, "LOW") or 0,
                    stdev=_require_float(row, "STDEV", line),
                )
            )

    if not players:
        raise RankingsError(f"{path} contains a header but no players.")

    players.sort(key=lambda p: p.adp)
    logger.info("loaded %d players for %d from %s", len(players), year, path)
    return PlayerPool(
        players, year, adp.Provenance(source="csv", year=year)
    )


def build_pool(
    year: int,
    teams: int,
    scoring: str,
    cache_dir: Path,
    ttl_seconds: int = 3600,
    csv_dir: Path | None = None,
    allow_network: bool = True,
) -> PlayerPool:
    """The pool the app runs on.

    An explicit csv_dir wins outright -- if someone points RANKINGS_DIR at a
    directory they mean it, and silently preferring the network would ignore
    hand-curated rankings. Otherwise the ADP feed is used, falling back to its
    own disk cache when the feed is unreachable.
    """
    if csv_dir is not None:
        logger.info("rankings source: CSV override at %s", csv_dir)
        return load_pool(csv_dir, year)

    players, provenance = adp.load(
        year=year,
        teams=teams,
        scoring=scoring,
        cache_dir=cache_dir,
        ttl_seconds=ttl_seconds,
        allow_network=allow_network,
    )
    return PlayerPool(players, year, provenance)


def resolve_keepers(
    pool: PlayerPool, keepers: tuple[Keeper, ...]
) -> tuple[dict[str, Player], list[str]]:
    """Match keeper names against the pool.

    Returns the resolved players and the names that could not be matched. An
    unmatched keeper is reported, not raised -- the CLI tool raises ValueError
    here, which in a webapp would take down a whole session over one typo.
    """
    resolved: dict[str, Player] = {}
    unresolved: list[str] = []

    for keeper in keepers:
        player = pool.find(keeper.player_name)
        if player is None:
            unresolved.append(keeper.player_name)
        else:
            resolved[keeper.player_name] = player

    if unresolved:
        logger.warning("unresolved keeper name(s): %s", unresolved)

    return resolved, unresolved
