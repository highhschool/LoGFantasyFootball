"""SQLite-backed session storage.

A session is its config plus its event log, which is all the state there is --
so a row is small, and saving is just overwriting two JSON blobs. That is the
payoff of deriving everything else at read time.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .core.engine import LoggedPick
from .core.models import DraftConfig, Keeper

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    mode        TEXT NOT NULL DEFAULT 'mock',
    seed        INTEGER NOT NULL,
    randomness  REAL NOT NULL DEFAULT 1.0,
    config_json TEXT NOT NULL,
    log_json    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def config_to_json(config: DraftConfig) -> str:
    payload = asdict(config)
    payload["keepers"] = [asdict(k) for k in config.keepers]
    return json.dumps(payload)


def config_from_json(raw: str) -> DraftConfig:
    payload = json.loads(raw)
    keepers = tuple(Keeper(**k) for k in payload.pop("keepers", []))
    return DraftConfig(keepers=keepers, **payload)


def log_to_json(log: list[LoggedPick]) -> str:
    return json.dumps([asdict(entry) for entry in log])


def log_from_json(raw: str) -> list[LoggedPick]:
    return [LoggedPick(**entry) for entry in json.loads(raw)]


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
        return conn

    def create(
        self,
        config: DraftConfig,
        seed: int,
        name: str = "",
        mode: str = "mock",
        randomness: float = 1.0,
    ) -> str:
        session_id = uuid.uuid4().hex[:12]
        stamp = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, name, mode, seed, randomness, config_json,"
                " log_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (session_id, name, mode, seed, randomness,
                 config_to_json(config), "[]", stamp, stamp),
            )
        return session_id

    def load(self, session_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "mode": row["mode"],
            "seed": row["seed"],
            "randomness": row["randomness"],
            "config": config_from_json(row["config_json"]),
            "log": log_from_json(row["log_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def save_log(self, session_id: str, log: list[LoggedPick]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET log_json = ?, updated_at = ? WHERE id = ?",
                (log_to_json(log), _now(), session_id),
            )

    def list(self, limit: int = 25) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, mode, created_at, updated_at, log_json"
                " FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
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

    def delete(self, session_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return cur.rowcount > 0
