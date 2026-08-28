"""Starting slots, and whether a pick fills one.

A roster is not a flat count per position. The league starts one quarterback,
two backs, two receivers, a tight end, two flex and a kicker and defence, then
carries five on the bench -- so a first running back and a fifth are worth
wildly different things, and treating them alike is the single biggest thing
the advisor was getting wrong.

Sleeper reports the real slots on the draft itself, so this is read rather than
guessed at wherever a live draft is involved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Who may fill a flex. Sleeper distinguishes several kinds; these are the two
# that appear in ordinary leagues.
FLEX_ELIGIBLE = frozenset({"RB", "WR", "TE"})
SUPERFLEX_ELIGIBLE = frozenset({"QB", "RB", "WR", "TE"})

# Where a pick would go, most valuable first.
STARTER = "starter"
FLEX = "flex"
BENCH = "bench"


@dataclass(frozen=True, slots=True)
class Lineup:
    """The shape of a starting eleven, plus the bench behind it."""

    starters: dict[str, int] = field(
        default_factory=lambda: {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DST": 1}
    )
    flex: int = 2
    superflex: int = 0
    bench: int = 5

    @property
    def starting_spots(self) -> int:
        return sum(self.starters.values()) + self.flex + self.superflex

    @property
    def size(self) -> int:
        return self.starting_spots + self.bench

    def as_dict(self) -> dict:
        return {
            "starters": dict(self.starters),
            "flex": self.flex,
            "superflex": self.superflex,
            "bench": self.bench,
            "starting_spots": self.starting_spots,
            "size": self.size,
        }


def default_lineup() -> Lineup:
    """The league's own shape: QB, 2RB, 2WR, TE, 2FLEX, K, DEF, 5 bench."""
    return Lineup()


def from_sleeper_settings(settings: dict) -> Lineup:
    """Build a lineup from the slot counts Sleeper puts on a draft."""

    def count(name: str) -> int:
        try:
            return max(0, int(settings.get(name, 0) or 0))
        except (TypeError, ValueError):
            return 0

    return Lineup(
        starters={
            "QB": count("slots_qb"),
            "RB": count("slots_rb"),
            "WR": count("slots_wr"),
            "TE": count("slots_te"),
            "K": count("slots_k"),
            "DST": count("slots_def"),
        },
        flex=count("slots_flex") + count("slots_rec_flex"),
        superflex=count("slots_super_flex"),
        bench=count("slots_bn"),
    )


def _spare(counts: dict[str, int], starters: dict[str, int], eligible) -> int:
    """Players at flex-eligible positions beyond their dedicated slots."""
    return sum(
        max(0, counts.get(position, 0) - starters.get(position, 0))
        for position in eligible
    )


def slot_for(lineup: Lineup, counts: dict[str, int], position: str) -> str:
    """Where one more player at this position would go.

    Dedicated slots fill first, then flex from whoever is spare, and everything
    after that is bench. Good enough without solving an assignment problem:
    positions do not compete for dedicated slots, so filling them greedily is
    already optimal, and the flex is the only place a choice exists.
    """
    if counts.get(position, 0) < lineup.starters.get(position, 0):
        return STARTER

    if lineup.flex and position in FLEX_ELIGIBLE:
        if _spare(counts, lineup.starters, FLEX_ELIGIBLE) < lineup.flex:
            return FLEX

    if lineup.superflex and position in SUPERFLEX_ELIGIBLE:
        # Anyone spilling into a flex has already used one of those spots.
        used = min(lineup.flex, _spare(counts, lineup.starters, FLEX_ELIGIBLE))
        if _spare(counts, lineup.starters, SUPERFLEX_ELIGIBLE) - used < lineup.superflex:
            return FLEX

    return BENCH


def starting_gaps(lineup: Lineup, counts: dict[str, int]) -> dict[str, int]:
    """Unfilled dedicated starting slots, per position."""
    return {
        position: max(0, slots - counts.get(position, 0))
        for position, slots in lineup.starters.items()
    }


def flex_gaps(lineup: Lineup, counts: dict[str, int]) -> int:
    """Unfilled flex slots, counting whoever is already spare."""
    total = lineup.flex + lineup.superflex
    if not total:
        return 0
    eligible = SUPERFLEX_ELIGIBLE if lineup.superflex else FLEX_ELIGIBLE
    return max(0, total - _spare(counts, lineup.starters, eligible))


def starters_remaining(lineup: Lineup, counts: dict[str, int]) -> int:
    """How many starting spots the roster has still to fill."""
    return sum(starting_gaps(lineup, counts).values()) + flex_gaps(lineup, counts)
