"""Roster shape: how many of each position a team may hold.

The defaults sum to exactly 15, which matches the league's 15 rounds. Any
deeper draft needs more roster spots, and they cannot be handed out blindly:
the player pool is only so deep at each position, and a limit the pool cannot
fill leaves bots with nothing legal to draft in the final rounds.

So limits grow toward the round count, capped by what the pool can actually
support for every team.
"""

from __future__ import annotations

from collections import Counter

from .models import DEFAULT_POSITION_LIMITS, POSITIONS, ConfigError
from .rankings import PlayerPool

# Where extra roster spots go first. Bench depth is overwhelmingly at the
# skill positions -- nobody carries a third kicker.
GROWTH_ORDER = ("WR", "RB", "TE", "QB", "K", "DST")


def pool_capacity(pool: PlayerPool, teams: int) -> dict[str, int]:
    """The largest per-team limit each position can support.

    Integer division on purpose: if 93 wide receivers are shared by 12 teams,
    a limit of 8 (96 needed) would strand the last teams with none available.
    """
    if teams < 1:
        raise ConfigError(f"teams must be at least 1, got {teams}")

    counts = Counter(p.position for p in pool.players)
    return {pos: counts.get(pos, 0) // teams for pos in POSITIONS}


def auto_limits(
    pool: PlayerPool,
    teams: int,
    rounds: int,
    base: dict[str, int] | None = None,
) -> dict[str, int]:
    """Position limits that can actually fill `rounds` rounds for every team."""
    capacity = pool_capacity(pool, teams)
    start = dict(base or DEFAULT_POSITION_LIMITS)

    # Never start above what the pool can support, even if the caller asked.
    limits = {pos: min(start.get(pos, 0), capacity.get(pos, 0)) for pos in POSITIONS}

    while sum(limits.values()) < rounds:
        grew = False
        for position in GROWTH_ORDER:
            if sum(limits.values()) >= rounds:
                break
            if limits[position] < capacity.get(position, 0):
                limits[position] += 1
                grew = True

        if not grew:
            total = sum(capacity.values())
            raise ConfigError(
                f"a {teams}-team draft cannot run {rounds} rounds: the player pool "
                f"supports at most {total} roster spots per team "
                f"({_describe(capacity)}). Reduce the rounds or the team count."
            )

    return limits


def describe_limits(limits: dict[str, int]) -> str:
    return _describe(limits)


def _describe(limits: dict[str, int]) -> str:
    return ", ".join(f"{pos} {limits.get(pos, 0)}" for pos in POSITIONS if limits.get(pos, 0))
