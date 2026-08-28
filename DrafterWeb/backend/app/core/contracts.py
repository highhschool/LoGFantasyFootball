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
from datetime import datetime, timezone

from .lmsr import DOLLAR, NO, SIDES, YES, apply, cost, price_cents, quote

# Sized against a season rather than a night. Twenty-five is the largest
# position at which a manager who maxes every market with a poor read still
# cannot be knocked out of a $1,000 season: simulated over eighteen slates they
# bottom out near $500 and never miss a market, where fifty leaves them at $10
# and seventy-five has them broke by November. `b` tracks the cap at twice it,
# which keeps one maximum buy worth about twelve points of price.
DEFAULT_B = 50.0
DEFAULT_SPREAD = 1      # cents per contract, each way
DEFAULT_CAP = 25        # contracts per manager per market
OPENING_FLOOR, OPENING_CEILING = 5, 95

# Where a market is in its life. Trading happens in exactly one of these.
PENDING = "pending"     # priced, not yet open
OPEN = "open"
CLOSED = "closed"       # the draft is under way; positions are locked
SETTLED = "settled"


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
    opens_at: datetime | None = None
    closes_at: datetime | None = None

    def __post_init__(self) -> None:
        if not OPENING_FLOOR <= self.opening <= OPENING_CEILING:
            raise MarketError(
                f"opening price must be between {OPENING_FLOOR}c and "
                f"{OPENING_CEILING}c, got {self.opening}c"
            )
        if self.b <= 0:
            raise MarketError(f"b must be positive, got {self.b}")
        if self.position_cap < 1:
            raise MarketError("the cap must allow at least one contract")
        if self.opens_at and self.closes_at and self.closes_at <= self.opens_at:
            raise MarketError("a market cannot close before it opens")

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


def phase(config: MarketConfig, now: datetime | None = None, settled: bool = False) -> str:
    """Where a market is in its life.

    Trading closes when the draft starts rather than market by market. A per
    market close would have to be driven by observed picks, and a stalled feed
    would then leave something tradeable after its answer was on screen -- with
    real money, the difference between a bug and an argument. One hard close
    before the first pick means nothing is ever tradeable once any answer is
    knowable.
    """
    if settled:
        return SETTLED
    at = now or datetime.now(timezone.utc)
    if config.opens_at and at < config.opens_at:
        return PENDING
    if config.closes_at and at >= config.closes_at:
        return CLOSED
    return OPEN


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
        """A rough mark, at the current line. See `MarketState.liquidation`."""
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

    def liquidation(self, user_id: str) -> int:
        """What closing this position right now would actually return.

        Not the position marked at the current price, which is the obvious
        thing and is wrong twice. Selling walks back down the curve, so a large
        holding fetches less per contract than the last one cost -- and the
        spread is paid on the way out as well as the way in.

        The difference is not rounding. Marking at the line credits a buyer
        with the move their own purchase caused: twenty-five contracts pushes
        the price twelve points and instantly shows a profit for having done
        so. Across a slate that is a few dollars of invention, and on a
        leaderboard it is a strategy.
        """
        held = self.position(user_id)
        if not held.held:
            return 0

        qy, qn = self.book_yes, self.book_no
        out = 0
        for side, count in ((YES, held.yes), (NO, held.no)):
            if not count:
                continue
            back = quote(qy, qn, self.config.b, side, -count, self.config.spread)
            out -= back.cash
            qy, qn = apply(qy, qn, side, -count)
        return max(0, out)

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


def _money(cents: int) -> str:
    return f"${cents / DOLLAR:,.2f}"


def plan(
    state: MarketState,
    user_id: str,
    side: str,
    shares: int,
    now: datetime | None = None,
    settled: bool = False,
    balance: int | None = None,
) -> Plan:
    """Price a request to hold `shares` more of `side`.

    A negative count sells that side back. Buying the side you are not on sells
    your existing holding down first, so nobody ends up paying the spread to
    hold a pair that is worth exactly a dollar whichever way it lands.

    Refused outside the trading window -- including selling. Once the draft is
    running there is no exit, which is the cost of closing before the first
    pick rather than market by market.

    A `balance` refuses anything it cannot cover. Passed only for play-money
    markets: a real-money slate settles up afterwards and has no wallet to
    check against. Selling is never refused for want of funds, since it returns
    money rather than costing it.
    """
    at = phase(state.config, now, settled)
    if at != OPEN:
        raise MarketError(
            {
                PENDING: "this market has not opened yet",
                CLOSED: "trading closed when the draft started",
                SETTLED: "this market has already settled",
            }[at]
        )

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

    if balance is not None and total > balance:
        raise MarketError(
            f"that costs {_money(total)} and you have {_money(balance)}"
        )

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
