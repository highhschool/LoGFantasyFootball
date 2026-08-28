"""Fetch ADP straight from Fantasy Football Calculator.

This is the same public endpoint FantasyDrafterAI/build_rankings.py calls. The
webapp fetches for itself rather than reading that script's CSV output, so it
has no dependency on the CLI tool having been run, and can be deployed on its
own. Both projects derive from the same upstream, so they cannot drift apart.

The feed is cached to disk on every successful fetch. If FFC is unreachable the
last good cache is served and flagged as stale -- a third party being down must
never be able to take the site out on draft night.

The endpoint needs no API key. It does reject urllib's default user agent with
a 403, so one is always sent.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .models import Player, RankingsError
from .names import normalize_position, player_key

logger = logging.getLogger(__name__)

FFC_URL = "https://fantasyfootballcalculator.com/api/v1/adp/{scoring}"
USER_AGENT = "NGFL-Drafter/1.0 (self-hosted league tool)"

VALID_SCORING = ("ppr", "half-ppr", "standard")
POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")

# FFC labels two positions differently than the league does.
POSITION_ALIASES = {"DEF": "DST", "PK": "K"}


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where this player pool came from, and how current it is.

    build_rankings.py logs the draft count and date range and then discards
    them when it writes CSVs, so a file four months old looks identical to a
    fresh one. Keeping them means the UI can always show how current the board
    actually is.
    """

    source: str                       # "api" | "cache" | "csv"
    year: int
    scoring: str = ""
    teams: int = 0
    fetched_at: datetime | None = None
    total_drafts: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    stale: bool = False               # served from cache after a failed fetch

    @property
    def age_seconds(self) -> float | None:
        if self.fetched_at is None:
            return None
        return (datetime.now(timezone.utc) - self.fetched_at).total_seconds()

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "year": self.year,
            "scoring": self.scoring or None,
            "teams": self.teams or None,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "age_seconds": None if self.age_seconds is None else int(self.age_seconds),
            "total_drafts": self.total_drafts,
            "sampled_from": self.start_date,
            "sampled_to": self.end_date,
            "stale": self.stale,
        }


def fetch(year: int, teams: int, scoring: str, timeout: float = 20.0) -> dict:
    """Pull the raw ADP payload. Raises RankingsError on any failure."""
    if scoring not in VALID_SCORING:
        raise RankingsError(f"scoring must be one of {VALID_SCORING}, got {scoring!r}")

    url = FFC_URL.format(scoring=scoring)
    params = {"teams": teams, "year": year, "position": "all"}

    try:
        response = httpx.get(
            url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT}
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise RankingsError(f"could not reach the ADP feed: {exc}") from exc
    except ValueError as exc:
        raise RankingsError(f"the ADP feed returned invalid JSON: {exc}") from exc

    if not payload.get("players"):
        raise RankingsError(
            f"the ADP feed returned no players for {year}; "
            "that season may not be published yet"
        )

    return payload


def to_players(payload: dict) -> list[Player]:
    """Normalize the feed into our Player type, ADP-ordered.

    Mirrors build_rankings.py's transform so both projects rank identically.
    """
    raw = payload.get("players", [])
    rows = []

    for entry in raw:
        position = POSITION_ALIASES.get(entry.get("position", ""), entry.get("position", ""))
        position = normalize_position(position)
        if position not in POSITIONS:
            continue
        rows.append((entry, position))

    if not rows:
        raise RankingsError("no players with a recognized position in the ADP feed")

    # ADP order is draft order; every rank below derives from it.
    rows.sort(key=lambda pair: float(pair[0].get("adp", 9999)))

    players: list[Player] = []
    pos_counts: dict[str, int] = {}
    seen: set[str] = set()

    for index, (entry, position) in enumerate(rows, start=1):
        name = (entry.get("name") or "").strip()
        team = (entry.get("team") or "").strip().upper()
        if not name:
            continue

        key = player_key(name, position, team)
        if key in seen:
            logger.warning("duplicate player in ADP feed: %r", name)
            continue
        seen.add(key)

        pos_counts[position] = pos_counts.get(position, 0) + 1

        players.append(
            Player(
                key=key,
                name=name,
                position=position,
                team=team,
                rank=index,
                pos_rank=pos_counts[position],
                bye_week=_opt_int(entry.get("bye")),
                adp=float(entry.get("adp", 0) or 0),
                adp_round=str(entry.get("adp_formatted", "") or ""),
                times_drafted=_opt_int(entry.get("times_drafted")) or 0,
                high=_opt_int(entry.get("high")) or 0,
                low=_opt_int(entry.get("low")) or 0,
                stdev=float(entry.get("stdev", 0) or 0),
            )
        )

    return players


def _opt_int(value: object) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _meta_of(payload: dict) -> dict:
    meta = payload.get("meta") or {}
    return {
        "total_drafts": _opt_int(meta.get("total_drafts")),
        "start_date": meta.get("start_date"),
        "end_date": meta.get("end_date"),
    }


def cache_file(cache_dir: Path, year: int, teams: int, scoring: str) -> Path:
    return Path(cache_dir) / f"adp-{year}-{teams}team-{scoring}.json"


def _write_cache(path: Path, payload: dict, fetched_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"fetched_at": fetched_at.isoformat(), "payload": payload}
    try:
        # Write then replace, so an interrupted write cannot corrupt the cache
        # that a later outage may depend on.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(body), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning("could not write ADP cache to %s: %s", path, exc)


def _read_cache(path: Path) -> tuple[dict, datetime] | None:
    if not path.is_file():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(body["fetched_at"])
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        return body["payload"], fetched_at
    except (OSError, ValueError, KeyError) as exc:
        logger.warning("ignoring unreadable ADP cache %s: %s", path, exc)
        return None


def load(
    year: int,
    teams: int,
    scoring: str,
    cache_dir: Path,
    ttl_seconds: int = 3600,
    allow_network: bool = True,
) -> tuple[list[Player], Provenance]:
    """Players plus provenance, preferring a fresh cache, then the network.

    Order matters for draft night: a cache inside its TTL is served without a
    request at all, and a failed request falls back to whatever cache exists
    rather than failing outright.
    """
    path = cache_file(cache_dir, year, teams, scoring)
    cached = _read_cache(path)

    if cached is not None:
        payload, fetched_at = cached
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age < ttl_seconds:
            logger.info("using cached ADP (%.0fs old)", age)
            return to_players(payload), Provenance(
                source="cache", year=year, scoring=scoring, teams=teams,
                fetched_at=fetched_at, **_meta_of(payload)
            )

    if allow_network:
        try:
            payload = fetch(year, teams, scoring)
            now = datetime.now(timezone.utc)
            _write_cache(path, payload, now)
            meta = _meta_of(payload)
            logger.info(
                "fetched ADP for %d: %d players from %s drafts (%s to %s)",
                year, len(payload.get("players", [])), meta["total_drafts"],
                meta["start_date"], meta["end_date"],
            )
            return to_players(payload), Provenance(
                source="api", year=year, scoring=scoring, teams=teams,
                fetched_at=now, **meta
            )
        except RankingsError as exc:
            if cached is None:
                raise
            logger.warning("ADP fetch failed (%s); serving the cached feed", exc)

    if cached is not None:
        payload, fetched_at = cached
        return to_players(payload), Provenance(
            source="cache", year=year, scoring=scoring, teams=teams,
            fetched_at=fetched_at, stale=True, **_meta_of(payload)
        )

    raise RankingsError(
        f"no ADP available for {year}: the feed is unreachable and nothing is cached"
    )


def humanize_age(seconds: float | None) -> str:
    if seconds is None:
        return "unknown age"
    if seconds < 90:
        return "just now"
    minutes = seconds / 60
    if minutes < 90:
        return f"{int(minutes)} minutes ago"
    hours = minutes / 60
    if hours < 36:
        return f"{int(hours)} hours ago"
    return f"{int(hours / 24)} days ago"


__all__ = [
    "Provenance", "fetch", "to_players", "load", "cache_file",
    "humanize_age", "POSITIONS", "VALID_SCORING",
]
