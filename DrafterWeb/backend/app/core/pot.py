"""The season pot.

The only real money in the tool, and the reason it is safe: the pot is exactly
the sum of what people put in, so it cannot pay out more than it holds and
nobody can be down more than their ante. The commissioner is not a counterparty
to any of it -- unlike a real-money market, where the house wears the losses.

Splitting a pot into percentages does not divide evenly, and the remainder has
to go somewhere explicit. It goes to first place, because a winner being a
penny up is the kind of arbitrary nobody argues with, and because the
alternative -- dropping it -- means the pot does not add up.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Payout:
    rank: int
    user_id: str
    manager: str
    amount: int

    def as_dict(self) -> dict:
        return {
            "rank": self.rank,
            "user_id": self.user_id,
            "manager": self.manager,
            "amount": self.amount,
        }


def split(pot: int, shares: list[int]) -> list[int]:
    """Divide a pot by percentage, losing nothing.

    Every part is floored and the remainder handed to first place, so the
    parts always sum to the pot exactly. A pot of nothing pays nothing rather
    than paying a rounding error to whoever is winning.
    """
    if pot <= 0 or not shares:
        return [0] * len(shares)

    parts = [pot * share // 100 for share in shares]
    parts[0] += pot - sum(parts)
    return parts


def payouts(
    pot: int,
    shares: list[int],
    standings: list[dict],
) -> list[Payout]:
    """Who gets what, given the table as it stands.

    Fewer paid-in managers than places is a real state early in a season, so
    the split covers only the places there are people for -- the rest of the
    pot would otherwise be paid to nobody.
    """
    places = min(len(shares), len(standings))
    if not places:
        return []

    amounts = split(pot, shares[:places])
    return [
        Payout(
            rank=row.get("rank", i + 1),
            user_id=row["user_id"],
            manager=row.get("manager", row["user_id"]),
            amount=amount,
        )
        for i, (row, amount) in enumerate(zip(standings, amounts))
    ]
