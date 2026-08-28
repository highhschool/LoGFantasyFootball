"""Core domain types for the draft.

These are plain dataclasses with no framework dependency, so the engine and its
tests stay fast and importable on their own. Pydantic lives at the API boundary.

Slot and round numbering is 1-based everywhere in this package: draft slot 1 is
the first pick of round 1, round 1 is the first round. The CLI tool mixes 0- and
1-based indexing (``DRAFT_POSITION - 1`` in the keeper dict); we do not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Position = Literal["QB", "RB", "WR", "TE", "K", "DST"]

POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DST")

# Mirrors TheGeneralManager.POSITION_LIMITS. Overridable per session.
DEFAULT_POSITION_LIMITS: dict[str, int] = {
    "WR": 5, "RB": 4, "QB": 2, "TE": 2, "K": 1, "DST": 1,
}

PickSource = Literal["user", "bot", "keeper", "sleeper", "manual", "remote"]


@dataclass(frozen=True, slots=True)
class Player:
    """One row of a rankings CSV."""

    key: str          # normalized identity, see core.names.player_key
    name: str
    position: str
    team: str
    rank: int         # overall rank by ADP
    pos_rank: int
    bye_week: int | None
    adp: float
    adp_round: str
    times_drafted: int
    high: int
    low: int
    stdev: float


@dataclass(frozen=True, slots=True)
class Keeper:
    """A roster spot pre-filled before the draft runs.

    Optional. A config with no keepers is a plain snake draft, which is the
    default and a fully supported state.
    """

    team_slot: int
    round: int
    player_name: str


@dataclass(frozen=True, slots=True)
class DraftConfig:
    year: int
    teams: int = 12
    rounds: int = 15
    your_slot: int = 6
    position_limits: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_POSITION_LIMITS))
    keepers: tuple[Keeper, ...] = ()
    # The starting slots this roster fills, read from Sleeper for a live draft.
    # Position limits say how many of a position you plan to carry; this says
    # how many of them actually start, which is what makes a first back worth
    # more than a fifth. Stored as the raw Sleeper slot counts so the config
    # serializes as plain data.
    lineup_slots: tuple[tuple[str, int], ...] = ()

    @property
    def lineup(self):
        from .lineup import default_lineup, from_sleeper_settings

        if not self.lineup_slots:
            return default_lineup()
        return from_sleeper_settings(dict(self.lineup_slots))

    @property
    def total_picks(self) -> int:
        return self.teams * self.rounds


@dataclass(frozen=True, slots=True)
class PickSlot:
    """A cell on the draft board, before anyone has picked into it."""

    overall: int         # 1..teams*rounds
    round: int           # 1..rounds
    pick_in_round: int   # 1..teams
    team_slot: int       # 1..teams
    keeper: str | None = None

    @property
    def is_keeper(self) -> bool:
        return self.keeper is not None


class ConfigError(ValueError):
    """The draft configuration is not internally consistent."""


class RankingsError(RuntimeError):
    """A rankings file is missing, empty, or does not match the expected schema."""
