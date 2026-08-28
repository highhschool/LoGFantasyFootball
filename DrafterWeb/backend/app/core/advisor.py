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
WEIGHT_VALUE = 1.0      # has fallen past his ADP
# Beyond this, being early or late stops telling you anything new. Without it,
# at pick 1 every deep player scores as hundreds of picks of "value", and a
# round-15 receiver outranks the first name on the board.
VALUE_CAP = 25.0
WEIGHT_URGENCY = 2.5    # unlikely to survive, and you still need the position
WEIGHT_TIER = 1.5       # last of his tier
BYE_PENALTY = 2.0       # would put a third starter on one bye week

_NORMAL = NormalDist()


@dataclass(frozen=True, slots=True)
class Advice:
    player: Player
    score: float
    survival: float          # chance he is still there at your next pick
    value: float             # picks he has fallen past his ADP; negative is a reach
    tier: int                # 1 is the best remaining tier at his position
    tier_remaining: int      # players left in his tier
    need: int                # roster spots you still have at his position
    bye_clash: bool
    gone_by_next: bool       # will not survive to your next pick
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
            "tier": self.tier,
            "tier_remaining": self.tier_remaining,
            "need": self.need,
            "bye_clash": self.bye_clash,
            "gone_by_next": self.gone_by_next,
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


def tiers(players: list[Player], teams: int) -> dict[str, tuple[int, int]]:
    """Tier number and players remaining in that tier, per player key.

    A tier ends where the ADP gap to the next player at the same position is
    wide enough that waiting means a real drop rather than a near-equal
    alternative.
    """
    threshold = max(MIN_TIER_GAP, TIER_GAP_FRACTION * teams)
    result: dict[str, tuple[int, int]] = {}

    by_position: dict[str, list[Player]] = {}
    for player in players:
        by_position.setdefault(player.position, []).append(player)

    for group in by_position.values():
        ordered = sorted(group, key=lambda p: p.adp)

        # Split into runs wherever the gap is wide.
        runs: list[list[Player]] = [[]]
        for i, player in enumerate(ordered):
            runs[-1].append(player)
            if i + 1 < len(ordered) and ordered[i + 1].adp - player.adp >= threshold:
                runs.append([])

        for tier_number, run in enumerate(runs, start=1):
            for index, player in enumerate(run):
                result[player.key] = (tier_number, len(run) - index)

    return result


def _reasons(
    player: Player,
    survival: float,
    value: float,
    tier: int,
    tier_remaining: int,
    need: int,
    bye_clash: bool,
) -> list[str]:
    """Plain statements of what drove the score, strongest first."""
    said: list[str] = []

    # Survival is only worth stating when it would change the decision. The
    # reported ADP spread is tight -- two to five picks through the early
    # rounds -- so nearly everyone at the top of the board is gone before your
    # next turn, and saying so on every row explains nothing. The actionable
    # half is the opposite: who you can afford to wait on.
    if survival >= 0.4:
        said.append(f"should still be there next turn ({survival:.0%}) — you can wait")

    if value >= 6:
        said.append(f"available {value:.0f} picks past his ADP")

    if tier_remaining == 1:
        said.append(f"last {player.position} in tier {tier}")
    elif tier_remaining <= 3:
        said.append(f"{tier_remaining} left in tier {tier}")

    if need == 1:
        said.append(f"your last {player.position} spot")

    if bye_clash and player.bye_week is not None:
        said.append(f"would be a third starter on the week {player.bye_week} bye")

    # Early on, nothing above fires: tiers are still full, nobody has fallen,
    # and everyone is gone by your next pick. A score with no stated reason is
    # the black box this module exists to avoid, so say where he actually sits.
    if not said:
        if value >= 3:
            said.append(f"{value:.0f} picks past his ADP of {player.adp:.0f}")
        elif value <= -3:
            said.append(f"a {abs(value):.0f}-pick reach on his ADP of {player.adp:.0f}")
        else:
            said.append(f"the consensus pick here (ADP {player.adp:.0f})")

    return said


def recommend(
    state: DraftState,
    pool: PlayerPool,
    slot: int | None = None,
    limit: int = 10,
) -> list[Advice]:
    """Rank the players worth taking at this pick, best first."""
    cell = state.current
    if cell is None:
        return []

    slot = slot if slot is not None else state.config.your_slot
    now = cell.overall
    until = next_pick_for_slot(state.config, slot, now)

    eligible = state.eligible(pool, slot)
    if not eligible:
        return []

    tier_of = tiers(eligible, state.config.teams)
    needs = state.team(slot).needs(state.config.position_limits)
    spots_left = max(1, sum(max(0, n) for n in needs.values()))
    byes = state.team(slot).bye_weeks

    advice: list[Advice] = []
    for player in eligible:
        need = max(0, needs.get(player.position, 0))
        if need == 0:
            continue

        survival = survival_probability(player, now, until)
        # Positive when the board has moved past his ADP: he has fallen, and
        # is a bargain here. Negative means taking him now is a reach.
        value = now - player.adp
        tier, tier_remaining = tier_of.get(player.key, (1, 1))

        # Third starter sharing a bye is the point it starts to hurt.
        bye_clash = (
            player.bye_week is not None
            and byes.count(player.bye_week) >= 2
        )

        # Scarcity only matters for a position you can still use, so need
        # scales urgency rather than adding to it separately.
        need_share = need / spots_left
        urgency = (1.0 - survival) * need_share
        tier_pressure = (1.0 / tier_remaining) * need_share

        score = (
            WEIGHT_VALUE * (max(-VALUE_CAP, min(VALUE_CAP, value)) / 10.0)
            + WEIGHT_URGENCY * urgency
            + WEIGHT_TIER * tier_pressure
            - (BYE_PENALTY if bye_clash else 0.0)
        )

        advice.append(
            Advice(
                player=player,
                score=score,
                survival=survival,
                value=value,
                tier=tier,
                tier_remaining=tier_remaining,
                need=need,
                bye_clash=bye_clash,
                gone_by_next=survival < 0.25,
                reasons=_reasons(
                    player, survival, value, tier, tier_remaining, need, bye_clash
                ),
            )
        )

    # ADP breaks ties, so equal scores fall back to consensus order.
    advice.sort(key=lambda a: (-a.score, a.player.adp))
    return advice[:limit]
