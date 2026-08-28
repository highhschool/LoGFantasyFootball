"""A market is its trade log.

The same shape as the draft engine: `replay(config, trades)` derives the book,
every position, the ledger and the house's exposure, and nothing derived is
stored. Undo is `trades[:-1]`, the audit trail is free, and a settlement
somebody disputes can be replayed trade by trade.

Two things here that the pricing curve underneath does not know about:

**Opening away from a coin flip costs the house more.** `b * ln 2` is the
famous LMSR bound, and it only holds for a market opened at 50c. Seeding the
book so a market opens at 71c -- which is the point of pricing off ADP -- means
the underdog side now risks `b * ln(1 + e^(seed/b))`, which at b=10 is $12.38
rather than $6.93. Every market therefore reports its own worst case, because
a commissioner budgeting ten markets at $6.93 would be wrong by about double.

**Nobody should hold both sides.** A YES and a NO together cost a dollar and
pay a dollar, so they are dead weight that only lose the spread. Buying against
your own position sells it down first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .lmsr import DOLLAR, NO, SIDES, YES, apply, cost, price_cents, quote

DEFAULT_B = 10.0
DEFAULT_SPREAD = 1      # cents per contract, each way
DEFAULT_CAP = 5         # contracts per manager per market
OPENING_FLOOR, OPENING_CEILING = 5, 95


class MarketError(ValueError):
    """A trade the market will not take."""


@dataclass(frozen=True, slots=True)
class MarketConfig:
    market_id: str
    question: str
    opening: int = 50               # cents, YES
    b: float = DEFAULT_B
    spread: int = DEFAULT_SPREAD
    position_cap: int = DEFAULT_CAP

    def __post_init__(self) -> None:
        if not OPENING_FLOOR <= self.opening <= OPENING_CEILING:
            raise MarketError(
                f"opening price must be between {OPENING_FLOOR}c and "
                f"{OPENING_CEILING}c, got {self.opening}c"
            )
        if self.b <= 0:
            raise MarketError(f"b must be positive, got {self.b}")
        if self.position_cap < 1:
            raise MarketError(f"the cap must allow at least one contract")

    @property
    def seed(self) -> float:
        """The book offset that makes the market open at its opening price."""
        p = self.opening / DOLLAR
        return self.b * math.log(p / (1 - p))

    @property
    def exposure(self) -> int:
        """Worst case for the house on this market, in cents.

        `b * ln 2` at 50c, and more the further from a coin flip it opens --
        the underdog side is cheap, so a lot of it can be sold before the price
        moves. This is the number to budget against, not the textbook one.
        """
        return math.ceil(self.b * math.log1p(math.exp(abs(self.seed) / self.b)) * DOLLAR)


@dataclass(frozen=True, slots=True)
class Trade:
    user_id: str
    side: str
    shares: int          # positive buys, negative sells back
    cash: int            # cents charged at the time, as quoted
    at: str = ""


@dataclass(slots=True)
class Position:
    yes: int = 0
    no: int = 0
    cash: int = 0        # net cents paid in; negative means taken out

    @property
    def held(self) -> int:
        return self.yes + self.no

    @property
    def side(self) -> str | None:
        return YES if self.yes else (NO if self.no else None)

    def value(self, yes_price: int) -> int:
        """What the holding would fetch at the current line, ignoring spread."""
        return self.yes * yes_price + self.no * (DOLLAR - yes_price)

    def as_dict(self, yes_price: int) -> dict:
        return {
            "yes": self.yes, "no": self.no, "cash": self.cash,
            "value": self.value(yes_price),
            "open_pnl": self.value(yes_price) - self.cash,
        }


@dataclass(slots=True)
class MarketState:
    config: MarketConfig
    book_yes: float = 0.0
    book_no: float = 0.0
    traded_yes: int = 0
    traded_no: int = 0
    collected: int = 0                                  # cents taken by the house
    positions: dict[str, Position] = field(default_factory=dict)

    @property
    def price_yes(self) -> int:
        return price_cents(self.book_yes, self.book_no, self.config.b, YES)

    @property
    def price_no(self) -> int:
        return DOLLAR - self.price_yes

    def price_of(self, side: str) -> int:
        return self.price_yes if side == YES else self.price_no

    def position(self, user_id: str) -> Position:
        return self.positions.get(user_id) or Position()

    def house_pnl(self, yes_won: bool) -> int:
        """What the house keeps if it lands that way, in cents.

        Only traded shares are owed. The seed is an accounting offset, not a
        holding anybody can redeem.
        """
        owed = (self.traded_yes if yes_won else self.traded_no) * DOLLAR
        return self.collected - owed

    def as_dict(self) -> dict:
        return {
            "market_id": self.config.market_id,
            "question": self.config.question,
            "price_yes": self.price_yes,
            "price_no": self.price_no,
            "traded": self.traded_yes + self.traded_no,
            "collected": self.collected,
            "house_if_yes": self.house_pnl(True),
            "house_if_no": self.house_pnl(False),
            "exposure": self.config.exposure,
        }


def replay(config: MarketConfig, trades: list[Trade]) -> MarketState:
    """Derive everything from the log."""
    state = MarketState(config=config, book_yes=config.seed, book_no=0.0)

    for trade in trades:
        state.book_yes, state.book_no = apply(
            state.book_yes, state.book_no, trade.side, trade.shares
        )
        if trade.side == YES:
            state.traded_yes += trade.shares
        else:
            state.traded_no += trade.shares

        state.collected += trade.cash

        held = state.positions.setdefault(trade.user_id, Position())
        if trade.side == YES:
            held.yes += trade.shares
        else:
            held.no += trade.shares
        held.cash += trade.cash

    return state


@dataclass(frozen=True, slots=True)
class Plan:
    """What a request actually does, once netted against what is held."""

    legs: list[Trade]
    cash: int
    price_before: int
    price_after: int

    def as_dict(self) -> dict:
        return {
            "cash": self.cash,
            "shares": sum(abs(leg.shares) for leg in self.legs),
            "price_before": self.price_before,
            "price_after": self.price_after,
            "legs": [
                {"side": leg.side, "shares": leg.shares, "cash": leg.cash}
                for leg in self.legs
            ],
        }


def plan(state: MarketState, user_id: str, side: str, shares: int) -> Plan:
    """Price a request to hold `shares` more of `side`.

    A negative count sells that side back. Buying the side you are not on sells
    your existing holding down first, so nobody ends up paying the spread to
    hold a pair that is worth exactly a dollar whichever way it lands.
    """
    if side not in SIDES:
        raise MarketError(f"side must be {YES!r} or {NO!r}, got {side!r}")
    if shares == 0:
        raise MarketError("a trade must move the position")

    config = state.config
    held = state.position(user_id)
    other = NO if side == YES else YES
    opposite = held.no if side == YES else held.yes
    same = held.yes if side == YES else held.no

    if shares < 0 and -shares > same:
        raise MarketError(
            f"you hold {same} {side.upper()}, so there is nothing more to sell"
        )

    wants = shares
    legs: list[Trade] = []
    qy, qn = state.book_yes, state.book_no
    before = state.price_of(side)
    total = 0

    # Net against the other side before adding to this one.
    if shares > 0 and opposite:
        unwind = min(opposite, shares)
        leg = quote(qy, qn, config.b, other, -unwind, config.spread)
        legs.append(Trade(user_id, other, -unwind, leg.cash))
        qy, qn = apply(qy, qn, other, -unwind)
        total += leg.cash
        wants -= unwind

    if wants:
        ending = same + wants
        if ending > config.position_cap:
            raise MarketError(
                f"{config.position_cap} contracts a market is the limit; "
                f"you would hold {ending}"
            )
        leg = quote(qy, qn, config.b, side, wants, config.spread)
        legs.append(Trade(user_id, side, wants, leg.cash))
        qy, qn = apply(qy, qn, side, wants)
        total += leg.cash

    return Plan(
        legs=legs,
        cash=total,
        price_before=before,
        price_after=price_cents(qy, qn, config.b, side),
    )


def settle_all(state: MarketState, yes_won: bool) -> dict[str, int]:
    """Each manager's profit or loss in cents, once the market resolves."""
    return {
        user: (held.yes if yes_won else held.no) * DOLLAR - held.cash
        for user, held in state.positions.items()
    }
