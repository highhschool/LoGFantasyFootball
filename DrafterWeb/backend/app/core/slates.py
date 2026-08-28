"""When a slate opens, and when its markets stop taking money.

A slate is a week's worth of markets that open together. They open Tuesday
morning, which puts them up after the previous week has settled and leaves the
league the run-up to the games to argue about them.

Closing is the part with money on it, and the rule is one line: **a market
stops trading before anything that could answer it happens.** For the draft
that is the first pick. In season it is kickoff -- and which kickoff depends on
the market, because the week is not one event. Thursday night, three windows on
Sunday, then Monday night.

Times are computed from `America/Chicago` rather than a fixed offset. Central
is UTC-5 in September and UTC-6 from the first of November, so a slate written
as `-05:00` would open and close an hour late for most of the season -- and an
hour late on a close is a market still taking money after kickoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

LEAGUE_TZ = ZoneInfo("America/Chicago")

# Tuesday, 9am. Monday is 0.
OPEN_WEEKDAY = 1
OPEN_TIME = time(9, 0)

# Typical kickoffs, Central, as offsets from the Tuesday a slate opens on.
# Defaults only -- flex scheduling moves games, so a market may carry its own.
KICKOFFS: dict[str, tuple[int, time]] = {
    "thursday":     (2, time(19, 15)),
    "sunday":       (5, time(12, 0)),    # the early window, and the week's first Sunday ball
    "sunday_late":  (5, time(15, 25)),
    "sunday_night": (5, time(19, 20)),
    "monday":       (6, time(19, 15)),
}


class SlateError(ValueError):
    """A slate that cannot be scheduled."""


def _at(day: datetime, clock: time) -> datetime:
    """A wall-clock time on a given day in the league's zone."""
    return datetime.combine(day.date(), clock, tzinfo=LEAGUE_TZ)


def next_open(after: datetime) -> datetime:
    """The next Tuesday 9am on or after `after`.

    Ties go to opening: asked at exactly 9am on a Tuesday, the answer is now.
    """
    local = after.astimezone(LEAGUE_TZ)
    ahead = (OPEN_WEEKDAY - local.weekday()) % 7
    candidate = _at(local + timedelta(days=ahead), OPEN_TIME)
    return candidate if candidate >= local else candidate + timedelta(days=7)


def last_open_before(when: datetime) -> datetime:
    """The most recent Tuesday 9am strictly before `when`.

    Which Tuesday a one-off slate hangs off. A draft at 6:30pm on a Tuesday
    opens that morning; one at 8am opens the Tuesday before, because nine
    o'clock has not happened yet.
    """
    local = when.astimezone(LEAGUE_TZ)
    back = (local.weekday() - OPEN_WEEKDAY) % 7
    candidate = _at(local - timedelta(days=back), OPEN_TIME)
    return candidate if candidate < local else candidate - timedelta(days=7)


def kickoff(opens_at: datetime, game: str) -> datetime:
    """When a market on a given game day has to stop trading."""
    if game not in KICKOFFS:
        raise SlateError(f"unknown game day {game!r}; known are {sorted(KICKOFFS)}")
    days, clock = KICKOFFS[game]
    local = opens_at.astimezone(LEAGUE_TZ)
    return _at(local + timedelta(days=days), clock)


@dataclass(frozen=True, slots=True)
class Slate:
    """A week's markets, opening together and closing on their own games."""

    slate_id: str
    name: str
    opens_at: datetime
    closes_at: datetime | None = None   # the default for markets that name no game

    def __post_init__(self) -> None:
        if self.opens_at.tzinfo is None:
            raise SlateError("a slate needs an explicit timezone, not a naive time")
        if self.closes_at and self.closes_at <= self.opens_at:
            raise SlateError("a slate cannot close before it opens")

    def close_for(self, game: str | None) -> datetime:
        """When a market in this slate closes.

        Naming no game falls back to the slate's own close -- which is how the
        draft slate works, where every market shares one deadline because the
        whole thing is answered by a single event starting.
        """
        if game is None:
            if self.closes_at is None:
                raise SlateError(
                    f"{self.name!r} has no default close, so its markets must "
                    f"each name a game day"
                )
            return self.closes_at
        return kickoff(self.opens_at, game)

    def as_dict(self) -> dict:
        return {
            "slate_id": self.slate_id,
            "name": self.name,
            "opens_at": self.opens_at.isoformat(),
            "closes_at": self.closes_at.isoformat() if self.closes_at else None,
        }


def draft_slate(slate_id: str, name: str, draft_start: datetime) -> Slate:
    """The one-off slate for draft night.

    Opens on the Tuesday cadence like any other, and closes at the first pick
    rather than at a kickoff, because the draft is the only event in it.
    """
    if draft_start.tzinfo is None:
        raise SlateError("the draft start needs an explicit timezone")
    return Slate(
        slate_id=slate_id,
        name=name,
        opens_at=last_open_before(draft_start),
        closes_at=draft_start,
    )


def weekly_slate(slate_id: str, name: str, opens_at: datetime) -> Slate:
    """An in-season slate. Its markets each close on their own game."""
    return Slate(slate_id=slate_id, name=name, opens_at=opens_at, closes_at=None)
