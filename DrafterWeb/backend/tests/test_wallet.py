"""Balances and standings.

A wallet is the trade log read a different way, so these are mostly about the
two numbers not being the same one: what you can spend, and what you are worth.
Confusing them makes buying anything look like a loss until it settles, which
would put whoever sat out at the top of the table.
"""

from __future__ import annotations

import pytest

from app.core.contracts import MarketConfig, plan, replay
from app.core.lmsr import NO, YES
from app.core.wallet import START, Standing, leaderboard, standings

# The shipped sizing, since a wallet is only meaningful against it.
EVEN = MarketConfig(market_id="m1", question="q?", opening=50)


class Book:
    """A market you can trade against, keeping its own log."""

    def __init__(self, config=EVEN):
        self.config = config
        self.log = []

    @property
    def state(self):
        return replay(self.config, self.log)

    def buy(self, user, side, shares, balance=None):
        done = plan(self.state, user, side, shares, balance=balance)
        self.log.extend(done.legs)
        return done


def book(trades, outcome=None, config=EVEN):
    b = Book(config)
    for user, side, shares in trades:
        b.buy(user, side, shares)
    return (b.state, outcome)


class TestAnUntouchedSeason:
    def test_everybody_starts_level(self):
        table = standings([], everyone=["u1", "u2"])
        assert {s.balance for s in table.values()} == {START}
        assert {s.equity for s in table.values()} == {START}
        assert {s.profit for s in table.values()} == {0}

    def test_somebody_who_never_traded_is_still_on_the_table(self):
        """A leaderboard showing eight of twelve looks broken."""
        table = standings([book([("u1", YES, 5)])], everyone=["u1", "u2", "u3"])
        assert set(table) == {"u1", "u2", "u3"}
        assert table["u2"].markets == 0


class TestSpendingAndWorth:
    def test_buying_moves_money_out_of_the_balance(self):
        table = standings([book([("u1", YES, 4)])])
        assert table["u1"].balance < START
        assert table["u1"].staked > 0

    def test_but_not_out_of_your_equity(self):
        """Otherwise buying anything reads as a loss until it settles."""
        table = standings([book([("u1", YES, 4)])])
        assert table["u1"].equity == pytest.approx(START, abs=200)

    def test_the_spread_is_the_only_immediate_cost(self):
        table = standings([book([("u1", YES, 4)])])
        assert table["u1"].open_pnl < 0
        assert table["u1"].open_pnl > -100, "a cent a contract, not more"

    def test_a_market_moving_your_way_shows_as_open_profit(self):
        b = Book()
        b.buy("u1", YES, 4)
        b.buy("u2", YES, 5)          # pushes the line up under u1
        table = standings([(b.state, None)])
        assert table["u1"].open_pnl > 0
        assert table["u1"].balance < table["u1"].equity


class TestSettlement:
    def test_winning_pays_a_dollar_a_contract(self):
        table = standings([book([("u1", YES, 4)], outcome=True)])
        assert table["u1"].balance > START
        assert table["u1"].settled_pnl > 0
        assert table["u1"].staked == 0, "nothing is tied up any more"

    def test_losing_costs_what_it_cost(self):
        table = standings([book([("u1", YES, 4)], outcome=False)])
        assert table["u1"].balance < START
        assert table["u1"].settled_pnl == table["u1"].profit

    def test_a_settled_market_stops_being_marked(self):
        table = standings([book([("u1", YES, 4)], outcome=True)])
        assert table["u1"].open_pnl == 0
        assert table["u1"].balance == table["u1"].equity

    def test_the_two_sides_are_a_zero_sum_against_the_house(self):
        b = Book()
        b.buy("u1", YES, 4)
        b.buy("u2", NO, 4)
        state = b.state
        table = standings([(state, True)])
        league = sum(s.profit for s in table.values())
        assert league + state.house_pnl(True) == 0


class TestAcrossMarkets:
    def test_positions_add_up(self):
        books = [
            book([("u1", YES, 5)], outcome=True),
            book([("u1", NO, 5)], outcome=True),      # wrong side
            book([("u1", YES, 5)]),                    # still open
        ]
        table = standings(books)
        assert table["u1"].markets == 3
        assert table["u1"].staked > 0, "the open one is still tied up"

    def test_equity_is_balance_plus_what_is_still_riding(self):
        books = [book([("u1", YES, 3)], outcome=True), book([("u1", YES, 3)])]
        s = standings(books)["u1"]
        assert s.equity > s.balance

    def test_a_market_nobody_touched_changes_nothing(self):
        alone = standings([book([("u1", YES, 5)])])["u1"]
        with_extra = standings([book([("u1", YES, 5)]), book([])])["u1"]
        assert alone == with_extra


class TestTheLeaderboard:
    def test_it_ranks_on_equity(self):
        table = leaderboard([
            book([("winner", YES, 5)], outcome=True),
            book([("loser", YES, 5)], outcome=False),
        ], everyone=["winner", "loser", "quiet"])

        assert [s.user_id for s in table] == ["winner", "quiet", "loser"]

    def test_sitting_out_does_not_win(self):
        """Somebody up on paper outranks somebody who never played."""
        b = Book()
        b.buy("bold", YES, 4)
        b.buy("other", YES, 5)      # moves the line in bold's favour
        table = leaderboard([(b.state, None)], everyone=["bold", "quiet", "other"])
        assert table[0].user_id == "bold"

    def test_a_settled_win_outranks_the_same_on_paper(self):
        """Ties break towards what has actually been decided."""
        done = Standing("done", balance=START + 500, equity=START + 500,
                        staked=0, settled_pnl=500, open_pnl=0, markets=1)
        riding = Standing("riding", balance=START, equity=START + 500,
                          staked=1000, settled_pnl=0, open_pnl=500, markets=1)
        order = sorted([riding, done],
                       key=lambda s: (s.equity, s.settled_pnl, s.user_id),
                       reverse=True)
        assert [s.user_id for s in order] == ["done", "riding"]


class TestTheBalanceIsEnforced:
    def test_you_cannot_spend_what_you_do_not_have(self):
        b = Book()
        with pytest.raises(Exception, match="you have"):
            b.buy("u1", YES, 5, balance=50)

    def test_what_you_can_afford_goes_through(self):
        b = Book()
        b.buy("u1", YES, 5, balance=START)
        assert b.state.position("u1").yes == 5

    def test_selling_is_never_refused_for_want_of_money(self):
        """It returns money rather than costing it."""
        b = Book()
        b.buy("u1", YES, 5)
        out = b.buy("u1", YES, -5, balance=0)
        assert out.cash < 0

    def test_no_balance_means_no_check(self):
        """A real-money slate settles up afterwards and has no wallet."""
        b = Book()
        b.buy("u1", YES, 5, balance=None)
        assert b.state.position("u1").yes == 5


class TestASeasonHolds:
    def test_a_full_slate_is_a_dent_not_a_wipeout(self):
        """Why the cap is twenty-five: eight maxed markets, one bad week."""
        books = []
        for i in range(8):
            books.append(book([("u1", YES, 5)], outcome=False,
                              config=MarketConfig(f"m{i}", "q?", opening=50)))
        left = standings(books)["u1"].balance
        assert left > START * 0.85, "a wholly wrong week costs under 15%"


class TestYouCannotMarkYourOwnPosition:
    """Valuing at the screen price pays you for the move you caused.

    Twenty-five contracts pushes the line twelve points, so marking there
    shows a profit for having bought. Across a slate that is a few invented
    dollars, and on a leaderboard it is a strategy.
    """

    def test_a_fresh_buy_is_never_instantly_up(self):
        for size in (1, 2, 3, 5):
            table = standings([book([("u1", YES, size)])])
            assert table["u1"].open_pnl <= 0, size

    def test_it_is_down_by_about_the_spread(self):
        table = standings([book([("u1", YES, 4)])])
        assert -300 < table["u1"].open_pnl < 0

    def test_marking_at_the_line_would_have_shown_a_profit(self):
        """The bug this guards, stated so the guard cannot be quietly removed."""
        state, _ = book([("u1", YES, 5)])
        naive = state.position("u1").value(state.price_yes)
        honest = state.liquidation("u1")
        assert naive > state.position("u1").cash, "the tempting number invents money"
        assert honest < naive

    def test_a_bigger_position_gives_back_less_of_what_it_cost(self):
        """The gap is the spread, paid on the way in and again on the way out.

        Per contract a large position marks *higher*, not lower -- it sits on
        a price it pushed up, and selling recovers part of that move. What
        cannot happen is getting back more than was paid.
        """
        for size in (1, 2, 3, 5):
            state, _ = book([("u1", YES, size)])
            paid = state.position("u1").cash
            back = state.liquidation("u1")
            assert back < paid, size
            assert paid - back >= 2 * size, "a cent each way, at least"

    def test_someone_elses_buying_is_a_real_gain(self):
        """What the mark should reward: being right before the room."""
        b = Book()
        b.buy("u1", YES, 4)
        before = standings([(b.state, None)])["u1"].open_pnl
        b.buy("u2", YES, 5)
        assert standings([(b.state, None)])["u1"].open_pnl > before

    def test_holding_nothing_liquidates_to_nothing(self):
        state, _ = book([("u1", YES, 5), ("u1", YES, -5)])
        assert state.liquidation("u1") == 0
        assert state.liquidation("never-traded") == 0
