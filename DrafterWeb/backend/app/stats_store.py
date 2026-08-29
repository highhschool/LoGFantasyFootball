"""Historical player statistics, in a database of their own.

A profile asks for one player across every season, which is a query rather than
a file read. Ten seasons of Sleeper's stats are about eleven megabytes and two
hundred and forty-five stat keys -- too much to hold in memory, and too slow to
find one player in by parsing ten files. So it is SQLite, indexed on the pair
that is always asked for.

**Deliberately not `sessions.db`.** That file holds what cannot be refetched:
trades, keeper selections, antes, drafted sessions. This holds what is a URL
away. Keeping them apart means a league backup stays a couple of hundred
kilobytes, and this one can be deleted and rebuilt whenever the shape of what
is stored needs to change.

Everything is kept -- all two hundred and forty-five keys -- because trimming
later is a change to a SELECT, while widening later is a refetch. Only players
who actually played a game are stored: of eight thousand rows a season, six
thousand are empty.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# How far back to keep, counted from the current season rather than written
# down as a year -- otherwise it becomes one more thing to remember every
# August, and there is already a list of those.
SEASONS_BACK = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS player_stats (
    player_id  TEXT NOT NULL,
    season     INTEGER NOT NULL,
    stats_json TEXT NOT NULL,
    PRIMARY KEY (player_id, season)
);

CREATE INDEX IF NOT EXISTS player_stats_by_player
    ON player_stats (player_id, season DESC);

-- What has been pulled and when. A finished season never changes, so it is
-- fetched once ever; only the current one is worth asking about again.
CREATE TABLE IF NOT EXISTS stats_seasons (
    season      INTEGER PRIMARY KEY,
    players     INTEGER NOT NULL,
    final       INTEGER NOT NULL DEFAULT 0,
    fetched_at  TEXT NOT NULL
);
"""


def wanted_seasons(current: int, back: int = SEASONS_BACK) -> list[int]:
    """The seasons worth holding, newest first.

    The current one is included even before a game is played -- it comes back
    empty, which is the right answer rather than a missing row.
    """
    return list(range(current, current - back, -1))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StatsStore:
    def __init__(self, db_path: Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect():
            pass

    @contextmanager
    def _connect(self):
        """A connection that commits on the way out, and always closes.

        `with sqlite3.connect(...)` commits but does not close -- a detail that
        costs nothing on a short script and leaves handles open in a server
        that runs for days. On Windows it also keeps the file locked, along
        with its -wal and -shm siblings, so a cache that is meant to be
        deletable is not.
        """
        conn = sqlite3.connect(self.path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------- writing

    def ingest(self, season: int, payload: dict, final: bool) -> int:
        """Store one season, replacing whatever was there.

        Rows without a game played are dropped: three quarters of the feed is
        players who did not take the field, and none of them belong in a
        profile.
        """
        rows = [
            (pid, season, json.dumps(stats))
            for pid, stats in (payload or {}).items()
            if stats and stats.get("gp")
        ]

        with self._connect() as conn:
            conn.execute("DELETE FROM player_stats WHERE season = ?", (season,))
            conn.executemany(
                "INSERT INTO player_stats (player_id, season, stats_json)"
                " VALUES (?,?,?)",
                rows,
            )
            conn.execute(
                "INSERT INTO stats_seasons (season, players, final, fetched_at)"
                " VALUES (?,?,?,?) ON CONFLICT(season) DO UPDATE SET"
                " players = excluded.players, final = excluded.final,"
                " fetched_at = excluded.fetched_at",
                (season, len(rows), 1 if final else 0, _now()),
            )
        return len(rows)

    def forget(self, season: int) -> int:
        """Drop a season, for trimming how far back this goes."""
        with self._connect() as conn:
            dropped = conn.execute(
                "DELETE FROM player_stats WHERE season = ?", (season,)
            ).rowcount
            conn.execute("DELETE FROM stats_seasons WHERE season = ?", (season,))
        return dropped

    # ------------------------------------------------------------- reading

    def career(self, player_id: str, limit: int | None = None) -> list[dict]:
        """One player's seasons, newest first. The whole point of the index."""
        sql = ("SELECT season, stats_json FROM player_stats"
               " WHERE player_id = ? ORDER BY season DESC")
        params: list[object] = [str(player_id)]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [{"season": r["season"], **json.loads(r["stats_json"])} for r in rows]

    def seasons(self) -> list[dict]:
        """What is held, and how fresh."""
        with self._connect() as conn:
            return [
                dict(r) for r in conn.execute(
                    "SELECT * FROM stats_seasons ORDER BY season DESC"
                )
            ]

    def is_final(self, season: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT final FROM stats_seasons WHERE season = ?", (season,)
            ).fetchone()
        return bool(row and row["final"])

    def missing(self, current: int, back: int = SEASONS_BACK) -> list[int]:
        """Which wanted seasons still need fetching.

        A season already stored and marked final is never asked for again --
        1,247 rushing yards in 2022 will not be revised.
        """
        held = {r["season"]: r for r in self.seasons()}
        return [
            season for season in wanted_seasons(current, back)
            if season not in held or not held[season]["final"]
        ]

    def size(self) -> dict:
        with self._connect() as conn:
            rows = conn.execute("SELECT COUNT(*) FROM player_stats").fetchone()[0]
        return {
            "rows": rows,
            "seasons": len(self.seasons()),
            "bytes": self.path.stat().st_size if self.path.exists() else 0,
        }
