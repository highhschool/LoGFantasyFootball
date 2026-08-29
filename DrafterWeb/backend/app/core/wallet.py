"""What a manager is worth.

Derived, not stored. A wallet is the trade log read a different way:

    balance = start - everything paid + everything won back
    equity  = balance + what closing every open position would return

Both terms already exist -- the trades are the log every market replays from,
and settlement is a flag on the market. So there is no balance to keep in step
with anything, nothing to reconcile, and a standing somebody disputes can be
walked back through the same trades that produced it. The same reason the draft
engine derives its board instead of mutating one.

**Balance and equity are different numbers and both matter.** Balance is what
you can spend, and money in an open position is not in it. Equity is what you
are worth if every open market settled at today's price, and that is what the
leaderboard ranks -- otherwise buying anything would look like a loss until it
resolved, and the standings would reward sitting out.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import MarketState
from .lmsr import DOLLAR

# What everyone starts a season with, in cents. Sized against the five
# contract cap -- see core/contracts.py for why the two travel together.
START = 20_000


@dataclass(frozen=True, slots=True)
class Standing:
    """One manager's season."""

    user_id: str
    balance: int         # spendable
    equity: int          # balance plus what closing the open ones would return
    staked: int          # cents currently tied up in open markets
    settled_pnl: int     # from markets that have resolved
    open_pnl: int        # on paper, from those that have not
    markets: int         # how many they have traded

    @property
    def profit(self) -> int:
        return self.equity - START

    def as_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "balance": self.balance,
            "equity": self.equity,
            "staked": self.staked,
            "settled_pnl": self.settled_pnl,
            "open_pnl": self.open_pnl,
            "profit": self.profit,
            "markets": self.markets,
        }


def standings(
    books: list[tuple[MarketState, bool | None]],
    everyone: list[str] | None = None,
    start: int = START,
) -> dict[str, Standing]:
    """Every manager's position across a season's markets.

    `books` pairs each market's replayed state with its outcome -- True, False,
    or None while it is still open. Only play-money markets belong here; a real
    money slate settles to a list of who owes whom, not to a wallet.

    Managers who have never traded are included when `everyone` is given, so a
    leaderboard shows the whole league rather than only the people on it.
    """
    spent: dict[str, int] = {}
    won: dict[str, int] = {}
    value: dict[str, int] = {}
    staked: dict[str, int] = {}
    counted: dict[str, int] = {}

    for state, outcome in books:
        for user, held in state.positions.items():
            if not held.held and not held.cash:
                continue

            spent[user] = spent.get(user, 0) + held.cash
            counted[user] = counted.get(user, 0) + 1

            if outcome is None:
                # What closing would return, not what the screen says it is
                # worth. Not money until it settles either way, which is why
                # it lands in equity rather than balance.
                value[user] = value.get(user, 0) + state.liquidation(user)
                staked[user] = staked.get(user, 0) + held.cash
            else:
                won[user] = won.get(user, 0) + (
                    (held.yes if outcome else held.no) * DOLLAR
                )

    names = set(spent) | set(everyone or [])
    out: dict[str, Standing] = {}

    for user in names:
        paid = spent.get(user, 0)
        back = won.get(user, 0)
        open_value = value.get(user, 0)
        tied = staked.get(user, 0)

        balance = start - paid + back
        out[user] = Standing(
            user_id=user,
            balance=balance,
            equity=balance + open_value,
            staked=tied,
            # What has actually been decided: won back, less what it cost.
            settled_pnl=back - (paid - tied),
            open_pnl=open_value - tied,
            markets=counted.get(user, 0),
        )

    return out


def leaderboard(
    books: list[tuple[MarketState, bool | None]],
    everyone: list[str] | None = None,
    start: int = START,
) -> list[Standing]:
    """Standings, richest first.

    Ties break on settled profit, so somebody holding an open position is not
    ranked above somebody who has already been proved right by the same amount.
    """
    table = standings(books, everyone, start)
    return sorted(
        table.values(),
        key=lambda s: (s.equity, s.settled_pnl, s.user_id),
        reverse=True,
    )
