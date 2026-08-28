"""Read a live draft from Sleeper.

Sleeper's API is public and needs no key: a league id is enough to read its
drafts, and a draft id is enough to read every pick. That is what makes the
assistant possible without asking anyone to log in.

The same discipline as core.adp applies, for the same reason. A draft is
happening in real time; if Sleeper hiccups for thirty seconds the board must
keep showing what it already knows rather than emptying itself. Every
successful fetch is cached, and a failed one falls back to that cache.

Nothing here returns the league id to a caller. The site is public, and the
league id is the one piece that turns "public in principle" into "trivially
findable" -- see the privacy note in README.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..core.names import normalize_position

logger = logging.getLogger(__name__)

DEFAULT_API = "https://api.sleeper.app/v1"
USER_AGENT = "NGFL-Drafter/1.0 (self-hosted league tool)"


class SleeperError(RuntimeError):
    """Sleeper could not be reached, or returned something unusable."""


@dataclass(frozen=True, slots=True)
class DraftInfo:
    """The shape of a draft, as Sleeper describes it."""

    draft_id: str
    status: str            # pre_draft | drafting | complete | paused
    draft_type: str        # snake | linear | auction
    season: str
    teams: int
    rounds: int
    slot_to_roster: dict[int, int]
    # Raw slot counts, so the lineup can be read rather than assumed.
    slots: dict[str, int]
    # Which manager picks where, by Sleeper user id. Empty until the
    # commissioner sets an order, which is a normal pre-draft state.
    draft_order: dict[str, int] = field(default_factory=dict)

    @property
    def is_snake(self) -> bool:
        return self.draft_type == "snake"


@dataclass(frozen=True, slots=True)
class Manager:
    """One member of the league, as Sleeper knows them."""

    user_id: str
    display_name: str
    team_name: str
    avatar: str | None = None

    @property
    def label(self) -> str:
        """The manager, not the team.

        Team names are jokes that change between seasons, and two of the
        league have not set one at all; a Sleeper account always has a
        display name.
        """
        return self.display_name or self.team_name


@dataclass(frozen=True, slots=True)
class SleeperPick:
    """One pick from the live board."""

    pick_no: int
    round: int
    draft_slot: int
    player_id: str
    name: str
    position: str
    team: str
    is_keeper: bool


def _get(url: str, timeout: float) -> object:
    try:
        response = httpx.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise SleeperError(f"could not reach Sleeper: {exc}") from exc
    except ValueError as exc:
        raise SleeperError(f"Sleeper returned invalid JSON: {exc}") from exc


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def parse_draft(payload: dict) -> DraftInfo:
    settings = payload.get("settings") or {}
    raw_slots = payload.get("slot_to_roster_id") or {}

    return DraftInfo(
        draft_id=str(payload.get("draft_id", "")),
        status=str(payload.get("status", "")),
        draft_type=str(payload.get("type", "")),
        season=str(payload.get("season", "")),
        teams=_as_int(settings.get("teams")),
        rounds=_as_int(settings.get("rounds")),
        slot_to_roster={_as_int(k): _as_int(v) for k, v in raw_slots.items()},
        slots={k: v for k, v in settings.items() if k.startswith("slots_")},
        draft_order={
            str(k): _as_int(v) for k, v in (payload.get("draft_order") or {}).items()
        },
    )


def parse_picks(payload: list[dict]) -> list[SleeperPick]:
    """Normalize the picks feed, in pick order.

    Sorted by pick_no rather than trusting the response order, because the
    board's meaning depends entirely on that sequence.
    """
    picks: list[SleeperPick] = []

    for entry in payload:
        meta = entry.get("metadata") or {}
        first = (meta.get("first_name") or "").strip()
        last = (meta.get("last_name") or "").strip()

        picks.append(
            SleeperPick(
                pick_no=_as_int(entry.get("pick_no")),
                round=_as_int(entry.get("round")),
                draft_slot=_as_int(entry.get("draft_slot")),
                player_id=str(entry.get("player_id", "")),
                name=f"{first} {last}".strip(),
                # Sleeper says DEF and PK where the rankings say DST and K.
                # Translating at the boundary keeps that dialect out of the app.
                position=normalize_position(meta.get("position") or ""),
                team=(meta.get("team") or "").strip().upper(),
                # Sleeper sends null rather than false when unset.
                is_keeper=bool(entry.get("is_keeper")),
            )
        )

    picks.sort(key=lambda p: p.pick_no)
    return picks


class SleeperClient:
    def __init__(
        self,
        cache_dir: Path,
        api: str = DEFAULT_API,
        timeout: float = 10.0,
    ) -> None:
        self.api = api.rstrip("/")
        self.timeout = timeout
        self.cache_dir = Path(cache_dir)

    # ------------------------------------------------------------- caching

    def _cache_path(self, name: str) -> Path:
        safe = "".join(c for c in name if c.isalnum() or c in "-_")
        return self.cache_dir / f"sleeper-{safe}.json"

    def _write_cache(self, name: str, payload: object) -> None:
        path = self._cache_path(name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"at": datetime.now(timezone.utc).isoformat(), "payload": payload}),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError as exc:
            logger.warning("could not cache %s: %s", name, exc)

    def _read_cache(self, name: str) -> object | None:
        path = self._cache_path(name)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))["payload"]
        except (OSError, ValueError, KeyError):
            return None

    def _fetch(self, path: str, cache_key: str) -> object:
        """Fetch, caching on success and falling back to the cache on failure."""
        try:
            payload = _get(f"{self.api}{path}", self.timeout)
            self._write_cache(cache_key, payload)
            return payload
        except SleeperError as exc:
            cached = self._read_cache(cache_key)
            if cached is None:
                raise
            logger.warning("Sleeper unreachable (%s); using the cached %s", exc, cache_key)
            return cached

    # --------------------------------------------------------------- reads

    def drafts_for_league(self, league_id: str) -> list[DraftInfo]:
        payload = self._fetch(f"/league/{league_id}/drafts", f"league-{league_id}-drafts")
        if not isinstance(payload, list):
            raise SleeperError(f"no drafts found for league {league_id}")
        return [parse_draft(d) for d in payload]

    def latest_draft(self, league_id: str) -> DraftInfo:
        """The most recent draft for a league.

        Discovered rather than configured: each season is a new league id with
        a new draft id, so hardcoding one guarantees a stale board next year.
        """
        drafts = self.drafts_for_league(league_id)
        if not drafts:
            raise SleeperError(f"league {league_id} has no drafts")
        return sorted(drafts, key=lambda d: d.season, reverse=True)[0]

    def draft(self, draft_id: str) -> DraftInfo:
        payload = self._fetch(f"/draft/{draft_id}", f"draft-{draft_id}")
        if not isinstance(payload, dict) or not payload.get("draft_id"):
            raise SleeperError(f"draft {draft_id} not found")
        return parse_draft(payload)

    def league_managers(self, league_id: str) -> list[Manager]:
        """The league's members. This is the user list for the keeper tool:
        a closed set of known people, so nobody has to be signed up."""
        payload = self._fetch(f"/league/{league_id}/users", f"league-{league_id}-users")
        if not isinstance(payload, list):
            raise SleeperError(f"could not read members of league {league_id}")
        return parse_managers(payload)

    def league_rosters(self, league_id: str) -> dict[str, list[str]]:
        """Each manager's roster, as Sleeper player ids, keyed by user id."""
        payload = self._fetch(f"/league/{league_id}/rosters", f"league-{league_id}-rosters")
        if not isinstance(payload, list):
            raise SleeperError(f"could not read rosters of league {league_id}")
        return {
            str(r.get("owner_id") or ""): [str(p) for p in (r.get("players") or [])]
            for r in payload
            if r.get("owner_id")
        }

    def player_directory(self) -> dict[str, dict]:
        """Sleeper's whole player dictionary, keyed by player id.

        Twelve thousand entries and several megabytes, which Sleeper asks not
        to be fetched more than once a day, so this one leans hard on the
        cache: a stale name is harmless, a hammered endpoint is not.
        """
        cached = self._read_cache("players-nfl")
        if isinstance(cached, dict) and cached:
            return cached

        payload = self._fetch("/players/nfl", "players-nfl")
        if not isinstance(payload, dict):
            raise SleeperError("could not read the player directory")
        return payload

    def picks(self, draft_id: str) -> list[SleeperPick]:
        payload = self._fetch(f"/draft/{draft_id}/picks", f"draft-{draft_id}-picks")
        if not isinstance(payload, list):
            raise SleeperError(f"could not read picks for draft {draft_id}")
        return parse_picks(payload)


def parse_managers(users: list[dict]) -> list[Manager]:
    managers = []
    for u in users:
        meta = u.get("metadata") or {}
        managers.append(
            Manager(
                user_id=str(u.get("user_id", "")),
                display_name=(u.get("display_name") or "").strip(),
                team_name=(meta.get("team_name") or "").strip(),
                avatar=u.get("avatar"),
            )
        )
    managers.sort(key=lambda m: m.label.lower())
    return managers


def _extend_client() -> None:  # pragma: no cover - documentation anchor
    """League reads live on SleeperClient below; see league_managers."""


def draft_id_from_url(value: str) -> str:
    """Pull a draft id out of whatever someone pastes.

    Sleeper draft URLs look like https://sleeper.com/draft/nfl/<id>, and people
    paste the URL far more often than the bare id.
    """
    text = value.strip().rstrip("/")
    if not text:
        raise SleeperError("no draft id or URL given")

    if text.isdigit():
        return text

    tail = text.split("/")[-1]
    if tail.isdigit():
        return tail

    raise SleeperError(f"could not find a draft id in {value!r}")
