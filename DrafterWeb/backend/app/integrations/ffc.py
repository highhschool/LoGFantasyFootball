"""Fantasy Football Calculator's per-player record.

The ADP feed is one call for the whole board and is fetched on a schedule. This
is one call *per player* -- a headshot, a dated analysis piece, a rookie flag --
so it is fetched only for players somebody actually opens, and cached to disk
for a day afterwards.

That laziness is the point. Hydrating all 265 on boot would be 265 requests to
a free service that asks nothing of us, for a panel most of them will never
appear in.

Everything here is decoration. A profile without it loses a face and a headline
and keeps its statistics, its ADP and its survival curve, so a failure is
returned as absence rather than raised.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

API = "https://fantasyfootballcalculator.com/api/v1"
USER_AGENT = "ngfl-drafter/1.0"

# News moves in days, not minutes. A day of staleness on an analysis piece
# costs nothing; a burst of requests to somebody else's free API costs them.
TTL = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class Note:
    """One dated piece of analysis."""

    title: str
    body: str
    updated: str
    priority: int

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "body": self.body,
            "updated": self.updated,
            "priority": self.priority,
        }


@dataclass(frozen=True, slots=True)
class PlayerNote:
    """What FFC knows about a player beyond where he is drafted."""

    ffc_id: int
    full_name: str = ""
    team_full: str = ""
    rookie: bool = False
    headshot: str | None = None
    notes: tuple[Note, ...] = ()

    def as_dict(self) -> dict:
        return {
            "ffc_id": self.ffc_id,
            "full_name": self.full_name,
            "team_full": self.team_full,
            "rookie": self.rookie,
            "headshot": self.headshot,
            "notes": [n.as_dict() for n in self.notes],
        }


def parse(payload: object, ffc_id: int) -> PlayerNote:
    """Their endpoint answers with a list of one."""
    row = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(row, dict):
        return PlayerNote(ffc_id=ffc_id)

    notes = []
    headshot = None
    for item in (row.get("news") or []):
        if not headshot and item.get("player_image"):
            headshot = item["player_image"]
        notes.append(Note(
            title=(item.get("title") or "").strip(),
            body=(item.get("analysis") or item.get("content") or "").strip(),
            updated=(item.get("updated_at") or "").strip(),
            priority=int(item.get("priority") or 0),
        ))

    # Loudest first, since a profile shows one or two of them.
    notes.sort(key=lambda n: -n.priority)

    return PlayerNote(
        ffc_id=ffc_id,
        full_name=(row.get("full_name") or "").strip(),
        team_full=(row.get("team_full") or "").strip(),
        rookie=bool(row.get("rookie")),
        headshot=headshot,
        notes=tuple(notes),
    )


class FfcClient:
    def __init__(self, cache_dir: Path, timeout: float = 8.0, api: str = API) -> None:
        self.cache_dir = Path(cache_dir)
        self.timeout = timeout
        self.api = api

    def _cache_path(self, ffc_id: int) -> Path:
        return self.cache_dir / f"ffc-{ffc_id}.json"

    def _read_cache(self, ffc_id: int, ignore_age: bool = False) -> dict | None:
        path = self._cache_path(ffc_id)
        if not path.exists():
            return None
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(body["fetched_at"])
        except (OSError, ValueError, KeyError):
            return None

        if not ignore_age and datetime.now(timezone.utc) - fetched > TTL:
            return None
        return body["payload"]

    def _write_cache(self, ffc_id: int, payload: object) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._cache_path(ffc_id)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "payload": payload,
                }),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError as exc:
            logger.warning("could not cache FFC player %s: %s", ffc_id, exc)

    def player(self, ffc_id: int) -> PlayerNote | None:
        """One player's record, or None if it cannot be had.

        Never raises. This is the decorative half of a profile, and a headshot
        being unavailable is not a reason for the statistics beside it to fail.
        """
        if not ffc_id:
            return None

        cached = self._read_cache(ffc_id)
        if cached is not None:
            return parse(cached, ffc_id)

        try:
            response = httpx.get(
                f"{self.api}/players/{ffc_id}",
                timeout=self.timeout,
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("FFC player %s unavailable (%s); using any cache", ffc_id, exc)
            stale = self._read_cache(ffc_id, ignore_age=True)
            return parse(stale, ffc_id) if stale is not None else None

        self._write_cache(ffc_id, payload)
        return parse(payload, ffc_id)
