"""Keeper selection.

One keeper per manager, and keeping a player costs the round his ADP falls in:
in a twelve-team league, ADP 1 to 12 is a first-round keeper, 13 to 24 a
second, and so on. So the cost is not fixed -- it moves as the board does, and
a player sitting near a round boundary can change price without anyone
touching him.

That is worth surfacing rather than hiding. Every selection records the ADP and
round it was made under, so a manager can see whether the thing they agreed to
has since moved, and by how much.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Player
from .names import player_key
from .rankings import PlayerPool

# How close to the next round a player has to sit before it is worth warning
# about. Roughly a sixth of a round.
BOUNDARY_MARGIN = 2.0


@dataclass(frozen=True, slots=True)
class KeeperOption:
    """One player on a manager's roster, priced."""

    player: Player | None
    sleeper_id: str
    name: str
    position: str
    team: str
    adp: float | None
    round: int | None
    near_boundary: bool

    key: str = ""

    @property
    def ranked(self) -> bool:
        """Whether this year's ADP feed prices him at all."""
        return self.player is not None

    @property
    def keepable(self) -> bool:
        """Every player on your roster can be kept.

        Refusing the unranked had it backwards. Keeping costs the round a
        player's ADP falls in, and a player with no ADP is by definition one
        nobody drafts -- so he is the cheapest keeper available, not an
        ineligible one. Colby Parkinson at a fifteenth-round price was not a
        choice you could make, while his teammate at round fourteen was.
        """
        return True

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            # So a row can open a profile. Zero for anyone this year's board
            # does not rank, who has no profile to open.
            "ffc_id": self.player.ffc_id if self.player else 0,
            "ranked": self.ranked,
            "sleeper_id": self.sleeper_id,
            "name": self.name,
            "position": self.position,
            "team": self.team,
            "bye_week": self.player.bye_week if self.player else None,
            "adp": None if self.adp is None else round(self.adp, 1),
            "round": self.round,
            "near_boundary": self.near_boundary,
            "keepable": self.keepable,
        }


def keeper_round(adp: float, teams: int) -> int:
    """The round a player's ADP falls in, which is what keeping him costs.

    ADP is one-based, so pick 12 in a twelve-team league is still the first
    round and pick 13 opens the second.
    """
    if teams < 1:
        raise ValueError(f"teams must be at least 1, got {teams}")
    return max(1, math.ceil(adp / teams))


def rounds_apart(adp: float, teams: int) -> float:
    """How far the next round boundary is, in picks."""
    return keeper_round(adp, teams) * teams - adp


def price(player: Player, teams: int) -> tuple[int, bool]:
    """His keeper round, and whether he is close enough to move."""
    this_round = keeper_round(player.adp, teams)
    return this_round, rounds_apart(player.adp, teams) <= BOUNDARY_MARGIN


def roster_options(
    roster: list[str],
    directory: dict[str, dict],
    pool: PlayerPool,
    teams: int,
    rounds: int,
) -> list[KeeperOption]:
    """Price every player on one manager's roster, cheapest round first.

    A roster is last season's, so some of it will have fallen off this year's
    ADP entirely -- eighteen of the league's hundred and eighty-five did in
    2026. Those cost the last round, the cheapest price there is, and sort to
    the bottom where the expensive picks are.
    """
    options: list[KeeperOption] = []

    for sleeper_id in roster:
        meta = directory.get(sleeper_id) or {}
        first = (meta.get("first_name") or "").strip()
        last = (meta.get("last_name") or "").strip()
        name = f"{first} {last}".strip() or sleeper_id
        position = (meta.get("position") or "").strip().upper()
        team = (meta.get("team") or "").strip().upper()

        found = pool.find(name, position, team)
        if found is None:
            # Keyed the same way the draft board keys anyone, so an unranked
            # keeper is still one identity across the tools.
            options.append(
                KeeperOption(
                    player=None, sleeper_id=sleeper_id, name=name,
                    position=position, team=team, adp=None,
                    round=max(1, rounds), near_boundary=False,
                    key=player_key(name, position, team),
                )
            )
            continue

        this_round, near = price(found, teams)
        options.append(
            KeeperOption(
                player=found, sleeper_id=sleeper_id, name=found.name,
                position=found.position, team=found.team, adp=found.adp,
                round=this_round, near_boundary=near, key=found.key,
            )
        )

    # Cheapest first. The unranked sort last: they cost the final round, which
    # is the most a keeper can cost.
    options.sort(key=lambda o: (o.round, o.adp is None, o.adp or 0.0))
    return options
