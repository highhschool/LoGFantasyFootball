"""The market maker.

Kalshi's price is an order book: 30 cents is 30 cents because somebody will
sell at 30 cents. Twelve people cannot fill a book -- you post an order, nobody
takes it, and the market prices nothing. So the app quotes both sides itself,
using a logarithmic market scoring rule.

    C(qy, qn) = b * ln( e^(qy/b) + e^(qn/b) )     # dollars to have moved here
    price_yes = e^(qy/b) / ( e^(qy/b) + e^(qn/b) )

A trade costs the difference between two costs. The house's loss is capped at
`b * ln 2` whatever the volume and however wrong the opening price was, which
is the property that makes a real-money market safe to run for a league: the
worst case is knowable before anything opens.

**Both sides are tracked explicitly**, though the maths does not require it.
Price depends only on `qy - qn`, so a NO share can be stored as a negative YES
share -- but then buying NO comes out as *shorting* YES, where you are handed
$2.19 now and owe $5 later rather than paying $2.81 to win $5. Those are the
same position and settle identically; only one of them can be shown to twelve
friends. Carrying the extra number keeps every cash flow the obvious one.

Money is integer cents throughout. Floats are fine for the curve and wrong for
a ledger somebody settles up over Venmo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DOLLAR = 100  # cents, and what a winning contract pays

YES = "yes"
NO = "no"
SIDES = (YES, NO)


def cost(qy: float, qn: float, b: float) -> float:
    """The market maker's cost function, in dollars.

    Computed through the larger exponent so that a runaway position is a large
    number rather than an overflow -- a silent wrong price would be worse than
    a crash.
    """
    if b <= 0:
        raise ValueError(f"b must be positive, got {b}")
    hi, lo = max(qy, qn) / b, min(qy, qn) / b
    return b * (hi + math.log1p(math.exp(lo - hi)))


def price(qy: float, qn: float, b: float) -> float:
    """Implied probability of YES, from 0 to 1."""
    if b <= 0:
        raise ValueError(f"b must be positive, got {b}")
    d = (qn - qy) / b
    return 1.0 / (1.0 + math.exp(d)) if d < 0 else math.exp(-d) / (1.0 + math.exp(-d))


def price_cents(qy: float, qn: float, b: float, side: str = YES) -> int:
    """The quoted price, 1 to 99.

    Never 0 or 100: a market quoting zero cannot be traded out of, and a
    contract offered at a dollar to pay a dollar is not a market.
    """
    p = price(qy, qn, b) if side == YES else 1.0 - price(qy, qn, b)
    return min(99, max(1, round(p * DOLLAR)))


def max_house_loss(b: float) -> float:
    """`b * ln 2`, in dollars. The whole reason this is safe to run."""
    return b * math.log(2)


@dataclass(frozen=True, slots=True)
class Quote:
    """What a trade would cost, and what it would do to the market."""

    side: str
    shares: int         # positive buys, negative sells back
    cash: int           # cents; positive is paid to the house, negative received
    spread: int         # how much of that is friction rather than price
    price_before: int   # of `side`
    price_after: int

    @property
    def average(self) -> int:
        """Cents per contract, which is the number a trader actually reads."""
        return round(abs(self.cash) / abs(self.shares)) if self.shares else 0

    def as_dict(self) -> dict:
        return {
            "side": self.side,
            "shares": self.shares,
            "cash": self.cash,
            "spread": self.spread,
            "average": self.average,
            "price_before": self.price_before,
            "price_after": self.price_after,
        }


def _checked(side: str, shares: int) -> None:
    if side not in SIDES:
        raise ValueError(f"side must be {YES!r} or {NO!r}, got {side!r}")
    if shares == 0:
        raise ValueError("a trade must move the position")


def quote(qy: int, qn: int, b: float, side: str, shares: int, spread: int = 0) -> Quote:
    """Price `shares` of `side`; a negative count sells that side back.

    Two adjustments both fall the house's way, deliberately. The spread is
    charged per contract in whichever direction you trade, so a round trip
    costs twice it; without it, LMSR lets you shove the line to bluff the room
    and exit for nothing. And the cent is rounded up rather than to nearest, so
    rounding can never be the thing that makes a trade profitable.
    """
    _checked(side, shares)
    if spread < 0:
        raise ValueError(f"spread cannot be negative, got {spread}")

    ay, an = (qy + shares, qn) if side == YES else (qy, qn + shares)
    if ay < 0 or an < 0:
        raise ValueError("cannot sell back more than the market holds")

    swing = (cost(ay, an, b) - cost(qy, qn, b)) * DOLLAR
    friction = spread * abs(shares)

    return Quote(
        side=side,
        shares=shares,
        cash=math.ceil(swing) + friction,
        spread=friction,
        price_before=price_cents(qy, qn, b, side),
        price_after=price_cents(ay, an, b, side),
    )


def apply(qy: int, qn: int, side: str, shares: int) -> tuple[int, int]:
    """The book after a trade."""
    _checked(side, shares)
    return (qy + shares, qn) if side == YES else (qy, qn + shares)


def settle(yes_shares: int, no_shares: int, yes_won: bool) -> int:
    """What a holding pays out, in cents."""
    return (yes_shares if yes_won else no_shares) * DOLLAR
