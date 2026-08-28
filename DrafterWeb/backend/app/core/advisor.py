"""Who to take, and why.

Every factor here comes from data already loaded -- ADP and its standard
deviation, the board, and your roster. No projections, no new feed.

The scoring is a heuristic, so each factor is reported alongside it. A number
you cannot argue with is not much use on draft night; "4% chance he lasts" is
something you can act on, and disagree with.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist

from .engine import DraftState
from .models import Player
from .order import next_pick_for_slot
from .rankings import PlayerPool

# Below this, a player's ADP spread is treated as noise rather than signal.
MIN_STDEV = 0.5

# A gap this large between consecutive players at a position is a tier break.
# Roughly a third of a round: far enough that the next man is a real step down.
TIER_GAP_FRACTION = 0.35
MIN_TIER_GAP = 4.0

# How the factors combine. Deliberately few, and named, because the score is a
# judgement call and these are the places to argue with it.
WEIGHT_DROPOFF = 1.0    # what you lose by waiting a turn at this position
WEIGHT_VALUE = 0.6      # has fallen past his own ADP
BYE_PENALTY = 2.0       # would put a third starter on one bye week

# What a position you have already filled is worth. Low enough that a real
# need outranks a steeper drop elsewhere, high enough that the option is still
# offered -- the limits are a plan, and the board does not always cooperate.
FILLED_POSITION_WEIGHT = 0.25

# Beyond this, being early or late stops telling you anything new. Without it,
# at pick 1 every deep player scores as hundreds of picks of "value", and a
# round-15 receiver outranks the first name on the board.
VALUE_CAP = 25.0

_NORMAL = NormalDist()


@dataclass(frozen=True, slots=True)
class Outlook:
    """What one position looks like now, and what it will look like next turn."""

    position: str
    best_now: Player
    likely_later: Player
    dropoff: float          # ADP picks between the two
    expected_gone: float    # how many at this position go before your next pick
    remaining: int
    tier_remaining: int     # players left in the best remaining tier


@dataclass(frozen=True, slots=True)
class Advice:
    player: Player
    score: float
    survival: float          # chance he is still there at your next pick
    value: float             # picks he has fallen past his ADP; negative is a reach
    need: int                # roster spots you still have at his position
    bye_clash: bool
    gone_by_next: bool
    dropoff: float           # ADP cost of waiting a turn at this position
    alternative: str         # who you would likely be choosing from instead
    alternative_adp: float
    tier_remaining: int      # players left in this tier at his position
    reasons: list[str]

    def as_dict(self) -> dict:
        return {
            "key": self.player.key,
            "name": self.player.name,
            "position": self.player.position,
            "team": self.player.team,
            "bye_week": self.player.bye_week,
            "adp": self.player.adp,
            "score": round(self.score, 2),
            "survival": round(self.survival, 3),
            "value": round(self.value, 1),
            "need": self.need,
            "bye_clash": self.bye_clash,
            "gone_by_next": self.gone_by_next,
            "dropoff": round(self.dropoff, 1),
            "alternative": self.alternative,
            "alternative_adp": round(self.alternative_adp, 1),
            "tier_remaining": self.tier_remaining,
            "reasons": self.reasons,
        }


def survival_probability(player: Player, now: int, until: int | None) -> float:
    """The chance this player is still available at pick `until`.

    A player's draft position behaves roughly normally around his ADP, with the
    spread the feed already reports. What matters is conditional: he is on the
    board *now*, so the question is whether he survives the gap to your next
    pick, not whether he survives from the start of the draft.

        P(taken after `until` | not taken by `now`)

    With no next pick -- your last of the draft -- nothing has to survive.
    """
    if until is None or until <= now:
        return 1.0

    spread = max(player.stdev, MIN_STDEV)
    still_here = 1.0 - _NORMAL.cdf((now - player.adp) / spread)
    lasts = 1.0 - _NORMAL.cdf((until - player.adp) / spread)

    if still_here <= 1e-9:
        # Long past his ADP and still on the board, so the model has already
        # been proven wrong about him. Fall back to the unconditional chance.
        return max(0.0, min(1.0, lasts))

    return max(0.0, min(1.0, lasts / still_here))


def tier_size(ordered: list[Player], teams: int) -> int:
    """How many players sit in the best remaining tier at a position.

    A tier ends where the ADP gap to the next man is wide enough that waiting
    means a real drop rather than a near-equal alternative. Counted from the
    top of what is left, so it measures the tier's scarcity rather than any one
    player's place in it -- being *last* in a tier is not a reason to prefer
    him over the man above him.
    """
    threshold = max(MIN_TIER_GAP, TIER_GAP_FRACTION * teams)

    for i in range(len(ordered) - 1):
        if ordered[i + 1].adp - ordered[i].adp >= threshold:
            return i + 1
    return len(ordered)


def outlook(players: list[Player], now: int, until: int | None, teams: int) -> Outlook | None:
    """What waiting a turn costs at one position.

    The decisive question at any pick is not who is best on the board, but what
    is lost by taking someone else first. Summing each player's chance of being
    gone gives the expected number taken at this position before your next
    turn; the man that far down the list is who you would likely be choosing
    from instead.
    """
    if not players:
        return None

    ordered = sorted(players, key=lambda p: p.adp)
    best_now = ordered[0]

    expected_gone = sum(1.0 - survival_probability(p, now, until) for p in ordered)
    index_later = min(len(ordered) - 1, int(round(expected_gone)))
    likely_later = ordered[index_later]

    return Outlook(
        position=best_now.position,
        best_now=best_now,
        likely_later=likely_later,
        dropoff=max(0.0, likely_later.adp - best_now.adp),
        expected_gone=expected_gone,
        remaining=len(ordered),
        tier_remaining=tier_size(ordered, teams),
    )


def _article(number: float) -> str:
    """"an 8-pick drop", but "a 14-pick drop"."""
    spoken = f"{number:.0f}"
    return "an" if spoken[0] == "8" or spoken in {"11", "18"} else "a"


def _reasons(
    player: Player,
    view: Outlook,
    survival: float,
    value: float,
    need: int,
    bye_clash: bool,
    until: int | None,
) -> list[str]:
    """What actually bears on this pick, most decisive first."""
    said: list[str] = []
    position = player.position
    holds_up = view.dropoff < 3 or view.likely_later.key == player.key

    if until is None:
        said.append(f"your last pick, and the best {position} left")
    elif holds_up:
        # Naming the same player as the alternative reads as a riddle; the
        # point is simply that this position keeps.
        said.append(f"{position} keeps — little changes by next turn")
    else:
        said.append(
            f"Next probable pick: {view.likely_later.name} "
            f"({position}{view.likely_later.pos_rank}) — "
            f"{_article(view.dropoff)} {view.dropoff:.0f}-pick drop"
        )

    # Tier scarcity only reinforces urgency. When nobody is taking this
    # position anyway, "only 1 left before the next tier" contradicts the line
    # above rather than adding to it.
    if not holds_up and view.tier_remaining <= 3 and view.remaining > view.tier_remaining:
        said.append(
            f"only {view.tier_remaining} {position}"
            f"{'' if view.tier_remaining == 1 else 's'} left at this level"
        )

    if value >= 5:
        said.append(f"fallen {value:.0f} picks past his own ADP")

    if need == 1:
        said.append(f"your last {position} spot")
    elif need <= 0:
        said.append(f"you have already filled {position} — this would be extra")

    if survival >= 0.5 and not holds_up:
        said.append(f"he is {survival:.0%} to still be there himself")

    if bye_clash and player.bye_week is not None:
        said.append(f"would be a third starter on the week {player.bye_week} bye")

    return said


def recommend(
    state: DraftState,
    pool: PlayerPool,
    slot: int | None = None,
    limit: int = 8,
) -> list[Advice]:
    """The best player at each position you can still use, ranked by urgency.

    One entry per position on purpose. Five names from two positions is two
    decisions dressed as five, and the near-identical members of a tier crowd
    out the choice that actually matters -- which position to spend this pick
    on. Within a position the best available is always the answer, so that is
    the one offered.
    """
    cell = state.current
    if cell is None:
        return []

    slot = slot if slot is not None else state.config.your_slot
    now = cell.overall
    until = next_pick_for_slot(state.config, slot, now)

    eligible = state.available(pool)
    if not eligible:
        return []

    needs = state.team(slot).needs(state.config.position_limits)
    spots_left = max(1, sum(max(0, n) for n in needs.values()))
    byes = state.team(slot).bye_weeks

    # Every position is considered. A filled one is weighted down rather than
    # dropped, because the limits are a plan and the board does not always
    # cooperate with it.
    by_position: dict[str, list[Player]] = {}
    for player in eligible:
        by_position.setdefault(player.position, []).append(player)

    advice: list[Advice] = []
    for position, players in by_position.items():
        view = outlook(players, now, until, state.config.teams)
        if view is None:
            continue

        player = view.best_now
        need = max(0, needs.get(position, 0))
        survival = survival_probability(player, now, until)
        value = now - player.adp
        bye_clash = player.bye_week is not None and byes.count(player.bye_week) >= 2

        # Urgency is what waiting costs here, weighted by how much of your
        # remaining roster this position still has to fill. A steep drop at a
        # position you have already filled is not your problem.
        need_share = need / spots_left
        weight = 1.0 + need_share if need > 0 else FILLED_POSITION_WEIGHT
        score = (
            WEIGHT_DROPOFF * (view.dropoff / 10.0) * weight
            + WEIGHT_VALUE * (max(-VALUE_CAP, min(VALUE_CAP, value)) / 10.0)
            - (BYE_PENALTY if bye_clash else 0.0)
        )

        advice.append(
            Advice(
                player=player,
                score=score,
                survival=survival,
                value=value,
                need=need,
                bye_clash=bye_clash,
                gone_by_next=survival < 0.25,
                dropoff=view.dropoff,
                alternative=view.likely_later.name,
                alternative_adp=view.likely_later.adp,
                tier_remaining=view.tier_remaining,
                reasons=_reasons(player, view, survival, value, need, bye_clash, until),
            )
        )

    # ADP breaks ties, so equal urgency falls back to consensus order.
    advice.sort(key=lambda a: (-a.score, a.player.adp))

    # A position where waiting costs nothing is not a decision. Suggesting a
    # kicker in round 1 because he is the best kicker left is noise; these
    # surface on their own once the board starts to thin. At least three
    # options are always offered so the panel never collapses to one.
    pressing = [a for a in advice if a.dropoff >= 1.0]
    return (pressing if len(pressing) >= 3 else advice[:3])[:limit]
