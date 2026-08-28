"""SQLite-backed session storage.

A session is its config plus its event log, which is all the state there is --
so a row is small, and saving is just overwriting two JSON blobs. That is the
payoff of deriving everything else at read time.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .core.engine import LoggedPick
from .core.models import DraftConfig, Keeper

# Codes people read off a phone and type in, so the ambiguous glyphs are gone:
# no O or 0, no I, 1 or L. Six characters of this alphabet is about thirty
# bits, far beyond guessing for a twelve-person league.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    mode        TEXT NOT NULL DEFAULT 'mock',
    seed        INTEGER NOT NULL,
    owner_id    TEXT NOT NULL DEFAULT '',
    source_id   TEXT NOT NULL DEFAULT '',
    randomness  REAL NOT NULL DEFAULT 1.0,
    pick_seconds INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL,
    log_json    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS keeper_managers (
    user_id      TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    team_name    TEXT NOT NULL DEFAULT '',
    code         TEXT NOT NULL,
    claimed_by   TEXT NOT NULL DEFAULT '',
    claimed_at   TEXT
);

CREATE TABLE IF NOT EXISTS keeper_picks (
    user_id      TEXT PRIMARY KEY,
    player_key   TEXT NOT NULL,
    player_name  TEXT NOT NULL,
    position     TEXT NOT NULL,
    nfl_team     TEXT NOT NULL,
    adp          REAL,
    round        INTEGER NOT NULL,
    submitted_at TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
"""


def _new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _owner_digest(owner_id: str) -> str:
    """A short, stable label for an owner that is not the owner's own key."""
    if not owner_id:
        return "unclaimed"
    if owner_id.startswith("email:"):
        return owner_id.split(":", 1)[1]
    return hashlib.sha256(owner_id.encode()).hexdigest()[:8]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def config_to_json(config: DraftConfig) -> str:
    payload = asdict(config)
    payload["keepers"] = [asdict(k) for k in config.keepers]
    return json.dumps(payload)


def config_from_json(raw: str) -> DraftConfig:
    payload = json.loads(raw)
    keepers = tuple(Keeper(**k) for k in payload.pop("keepers", []))
    # JSON has no tuples, so both of these come back as lists.
    slots = tuple((str(k), int(v)) for k, v in payload.pop("lineup_slots", []))
    return DraftConfig(keepers=keepers, lineup_slots=slots, **payload)


def log_to_json(log: list[LoggedPick]) -> str:
    return json.dumps([asdict(entry) for entry in log])


def log_from_json(raw: str) -> list[LoggedPick]:
    return [LoggedPick(**entry) for entry in json.loads(raw)]


# CREATE TABLE IF NOT EXISTS does nothing to a table that already exists, so
# columns added after a database was first created need adding explicitly.
# Existing sessions keep working rather than erroring on a missing column.
ADDED_COLUMNS = {
    "owner_id": "TEXT NOT NULL DEFAULT ''",
    "source_id": "TEXT NOT NULL DEFAULT ''",
    "randomness": "REAL NOT NULL DEFAULT 1.0",
    "pick_seconds": "INTEGER NOT NULL DEFAULT 0",
}


def _migrate(conn: sqlite3.Connection) -> None:
    have = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    for column, spec in ADDED_COLUMNS.items():
        if column not in have:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {column} {spec}")

    _allow_keepers_without_adp(conn)


def _allow_keepers_without_adp(conn: sqlite3.Connection) -> None:
    """Drop the NOT NULL on keeper_picks.adp.

    Keeping an unranked player costs the last round, and he has no ADP to
    record. SQLite cannot relax a constraint in place, so the table is rebuilt
    -- once, on databases that predate the rule.
    """
    adp = next(
        (r for r in conn.execute("PRAGMA table_info(keeper_picks)") if r["name"] == "adp"),
        None,
    )
    if adp is None or not adp["notnull"]:
        return

    conn.executescript(
        """
        CREATE TABLE keeper_picks_new (
            user_id      TEXT PRIMARY KEY,
            player_key   TEXT NOT NULL,
            player_name  TEXT NOT NULL,
            position     TEXT NOT NULL,
            nfl_team     TEXT NOT NULL,
            adp          REAL,
            round        INTEGER NOT NULL,
            submitted_at TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        INSERT INTO keeper_picks_new SELECT * FROM keeper_picks;
        DROP TABLE keeper_picks;
        ALTER TABLE keeper_picks_new RENAME TO keeper_picks;
        """
    )


class SessionStore:
    def __init__(self, db_path: Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connect().close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
        return conn

    def create(
        self,
        config: DraftConfig,
        seed: int,
        name: str = "",
        mode: str = "mock",
        randomness: float = 1.0,
        pick_seconds: int = 0,
        owner_id: str = "",
        source_id: str = "",
    ) -> str:
        session_id = uuid.uuid4().hex[:12]
        stamp = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, name, mode, seed, owner_id, source_id,"
                " randomness, pick_seconds, config_json, log_json, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (session_id, name, mode, seed, owner_id, source_id, randomness,
                 pick_seconds, config_to_json(config), "[]", stamp, stamp),
            )
        return session_id

    def load(self, session_id: str, owner_id: str) -> dict | None:
        """Scoped to the owner: someone else's session reads as absent."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ? AND owner_id = ?",
                (session_id, owner_id),
            ).fetchone()
        return None if row is None else self._row_to_session(row)

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "mode": row["mode"],
            "seed": row["seed"],
            "owner_id": row["owner_id"],
            "source_id": row["source_id"],
            "randomness": row["randomness"],
            "pick_seconds": row["pick_seconds"],
            "config": config_from_json(row["config_json"]),
            "log": log_from_json(row["log_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def save_log(self, session_id: str, log: list[LoggedPick], owner_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET log_json = ?, updated_at = ?"
                " WHERE id = ? AND owner_id = ?",
                (log_to_json(log), _now(), session_id, owner_id),
            )

    def rename(self, session_id: str, name: str, owner_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE sessions SET name = ?, updated_at = ?"
                " WHERE id = ? AND owner_id = ?",
                (name, _now(), session_id, owner_id),
            )
            return cur.rowcount > 0

    def set_pick_seconds(self, session_id: str, seconds: int, owner_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE sessions SET pick_seconds = ?, updated_at = ?"
                " WHERE id = ? AND owner_id = ?",
                (seconds, _now(), session_id, owner_id),
            )
            return cur.rowcount > 0

    def list(self, owner_id: str, mode: str | None = None, limit: int = 25) -> list[dict]:
        """Your own drafts for one tool.

        The mock simulator and the live assistant keep separate lists; a mode
        is always passed in practice so neither shows the other's sessions.
        """
        sql = (
            "SELECT id, name, mode, created_at, updated_at, log_json"
            " FROM sessions WHERE owner_id = ?"
        )
        params: list[object] = [owner_id]
        if mode is not None:
            sql += " AND mode = ?"
            params.append(mode)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "mode": r["mode"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "picks_made": len(json.loads(r["log_json"])),
            }
            for r in rows
        ]

    # ------------------------------------------------------------- keepers

    def sync_managers(self, managers: list[tuple[str, str, str]]) -> dict:
        """Reconcile the stored members with the league's.

        Existing codes are left alone -- re-syncing must never invalidate one
        somebody has already been sent -- but managers who have left the league
        are removed along with their selection. Only ever adding leaves a
        departed manager holding a working code and a row on the board, and a
        twelve-team league offering fourteen names to choose from.
        """
        incoming = {user_id for user_id, _, _ in managers}
        added = 0

        with self._connect() as conn:
            for user_id, display_name, team_name in managers:
                existing = conn.execute(
                    "SELECT code FROM keeper_managers WHERE user_id = ?", (user_id,)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE keeper_managers SET display_name = ?, team_name = ?"
                        " WHERE user_id = ?",
                        (display_name, team_name, user_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO keeper_managers (user_id, display_name,"
                        " team_name, code) VALUES (?,?,?,?)",
                        (user_id, display_name, team_name, _new_code()),
                    )
                    added += 1

            stored = {
                r["user_id"]
                for r in conn.execute("SELECT user_id FROM keeper_managers")
            }
            departed = stored - incoming
            for user_id in departed:
                conn.execute("DELETE FROM keeper_picks WHERE user_id = ?", (user_id,))
                conn.execute("DELETE FROM keeper_managers WHERE user_id = ?", (user_id,))

        return {"added": added, "removed": len(departed), "total": len(incoming)}

    def managers(self, with_codes: bool = False) -> list[dict]:
        """The league's members. Codes are admin-only."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM keeper_managers ORDER BY"
                " CASE WHEN display_name = '' THEN team_name ELSE display_name END"
            ).fetchall()

        out = []
        for r in rows:
            entry = {
                "user_id": r["user_id"],
                "display_name": r["display_name"],
                "team_name": r["team_name"],
                "claimed": bool(r["claimed_by"]),
            }
            if with_codes:
                entry["code"] = r["code"]
                entry["claimed_at"] = r["claimed_at"]
            out.append(entry)
        return out

    def claim_manager(self, user_id: str, code: str, owner_id: str) -> bool:
        """Tie a browser to a manager, if the code matches.

        A different browser may take a claim over, because people switch
        phones and there is nobody here to appeal to.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT code FROM keeper_managers WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row is None or not secrets.compare_digest(
                row["code"].upper(), code.strip().upper()
            ):
                return False

            conn.execute(
                "UPDATE keeper_managers SET claimed_by = ?, claimed_at = ?"
                " WHERE user_id = ?",
                (owner_id, _now(), user_id),
            )
        return True

    def claimed_manager(self, owner_id: str) -> dict | None:
        """Which manager this browser has claimed, if any."""
        if not owner_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM keeper_managers WHERE claimed_by = ?", (owner_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "user_id": row["user_id"],
            "display_name": row["display_name"],
            "team_name": row["team_name"],
        }

    def set_keeper(self, user_id: str, pick: dict) -> None:
        """Record or replace a manager's selection."""
        stamp = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO keeper_picks (user_id, player_key, player_name,"
                " position, nfl_team, adp, round, submitted_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                " player_key=excluded.player_key, player_name=excluded.player_name,"
                " position=excluded.position, nfl_team=excluded.nfl_team,"
                " adp=excluded.adp, round=excluded.round,"
                " updated_at=excluded.updated_at",
                (user_id, pick["player_key"], pick["player_name"], pick["position"],
                 pick["nfl_team"], pick["adp"], pick["round"], stamp, stamp),
            )

    def clear_keeper(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM keeper_picks WHERE user_id = ?", (user_id,))

    def keeper(self, user_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM keeper_picks WHERE user_id = ?", (user_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def all_keepers(self) -> list[dict]:
        """Every manager and their selection, cheapest round first.

        Managers who have not chosen are included with nulls, because who has
        not answered yet is the thing you actually want to know before a
        deadline.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT m.user_id, m.display_name, m.team_name,"
                " k.player_name, k.position, k.nfl_team, k.adp, k.round,"
                " k.submitted_at, k.updated_at"
                " FROM keeper_managers m LEFT JOIN keeper_picks k"
                " ON m.user_id = k.user_id"
                " ORDER BY k.round IS NULL, k.round, k.adp"
            ).fetchall()
        return [dict(r) for r in rows]

    def list_all(self, mode: str | None = None, limit: int = 200) -> list[dict]:
        """Every session, whoever made it. Admin only.

        Owners are reported as a short digest rather than the raw id: it is
        enough to tell two people apart in the listing, and the raw value is a
        bearer token for their sessions.
        """
        sql = (
            "SELECT id, name, mode, owner_id, source_id, created_at, updated_at,"
            " log_json, config_json FROM sessions"
        )
        params: list[object] = []
        if mode is not None:
            sql += " WHERE mode = ?"
            params.append(mode)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        out = []
        for r in rows:
            config = config_from_json(r["config_json"])
            out.append({
                "id": r["id"],
                "name": r["name"],
                "mode": r["mode"],
                "owner": _owner_digest(r["owner_id"]),
                "teams": config.teams,
                "rounds": config.rounds,
                "your_slot": config.your_slot,
                "keepers": len(config.keepers),
                "picks_made": len(json.loads(r["log_json"])),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            })
        return out

    def load_any(self, session_id: str) -> dict | None:
        """Load regardless of owner. Admin only."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return None if row is None else self._row_to_session(row)

    def delete(self, session_id: str, owner_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM sessions WHERE id = ? AND owner_id = ?",
                (session_id, owner_id),
            )
            return cur.rowcount > 0
