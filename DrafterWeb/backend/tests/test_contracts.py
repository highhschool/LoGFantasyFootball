"""The market as a state machine.

Real money settles off the ledger these produce, so the tests worth having are
about the accounting closing: that the house's books balance against what it
owes, that the cap cannot be walked around, and that a market opened away from
a coin flip reports the risk it actually carries.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.contracts import (
    CLOSED,
    OPEN,
    PENDING,
    SETTLED,
    MarketConfig,
    MarketError,
    Trade,
    phase,
    plan,
    replay,
    settle_all,
)

CENTRAL = timezone(timedelta(hours=-5))
from app.core.lmsr import NO, YES

# Pinned rather than inherited. These test the machine, not the sizing, and
# the sizing is a product decision that has already moved once -- a cap chosen
# for a season should not be able to break arithmetic tests when it changes
# again. TestTheShippedSizing below is where the real numbers are asserted.
B, CAP = 10.0, 5

EVEN = MarketConfig(market_id="m1", question="Chase in the first three?",
                    opening=50, b=B, position_cap=CAP)


def market(**kw) -> MarketConfig:
    kw.setdefault("b", B)
    kw.setdefault("position_cap", CAP)
    return MarketConfig(market_id="m", question="q", **kw)


class Book:
    """A market you can trade against, keeping its own log."""

    def __init__(self, config=EVEN):
        self.config = config
        self.log: list[Trade] = []

    @property
    def state(self):
        return replay(self.config, self.log)

    def buy(self, user, side, shares):
        done = plan(self.state, user, side, shares)
        self.log.extend(done.legs)
        return done


class TestAnUntouchedMarket:
    def test_it_opens_where_it_was_priced(self):
        assert replay(EVEN, []).price_yes == 50
        assert replay(market(opening=71), []).price_yes == 71

    def test_the_sides_sum_to_a_dollar(self):
        state = replay(market(opening=71), [])
        assert state.price_yes + state.price_no == 100

    def test_nobody_holds_anything(self):
        assert replay(EVEN, []).positions == {}
        assert replay(EVEN, []).position("nobody").held == 0

    @pytest.mark.parametrize("bad", [0, 4, 96, 100, -1])
    def test_an_impossible_opening_is_refused(self, bad):
        with pytest.raises(MarketError):
            market(opening=bad)


class TestTrading:
    def test_buying_gives_you_the_contracts(self):
        book = Book()
        book.buy("u1", YES, 5)
        assert book.state.position("u1").yes == 5

    def test_buying_moves_the_line(self):
        book = Book()
        book.buy("u1", YES, 5)
        assert book.state.price_yes == 62

    def test_buying_no_moves_it_the_other_way(self):
        book = Book()
        book.buy("u1", NO, 5)
        assert book.state.price_yes == 38

    def test_the_second_buyer_pays_more(self):
        book = Book()
        first = book.buy("u1", YES, 5)
        second = book.buy("u2", YES, 5)
        assert second.cash > first.cash

    def test_selling_back_returns_money_and_the_contracts(self):
        book = Book()
        book.buy("u1", YES, 5)
        out = book.buy("u1", YES, -5)
        assert out.cash < 0
        assert book.state.position("u1").yes == 0

    def test_a_round_trip_costs_the_spread(self):
        book = Book()
        book.buy("u1", YES, 5)
        book.buy("u1", YES, -5)
        assert book.state.position("u1").cash > 0, "you paid to go and come back"

    def test_you_cannot_sell_what_you_do_not_hold(self):
        book = Book()
        book.buy("u1", YES, 2)
        with pytest.raises(MarketError, match="nothing more to sell"):
            book.buy("u1", YES, -3)

    def test_a_trade_must_move_something(self):
        with pytest.raises(MarketError):
            plan(replay(EVEN, []), "u1", YES, 0)

    def test_an_unknown_side_is_refused(self):
        with pytest.raises(MarketError):
            plan(replay(EVEN, []), "u1", "maybe", 1)


class TestTheCap:
    def test_five_is_the_limit(self):
        book = Book()
        book.buy("u1", YES, 5)
        with pytest.raises(MarketError, match="limit"):
            book.buy("u1", YES, 1)

    def test_it_cannot_be_walked_up_to_in_steps(self):
        book = Book()
        for _ in range(5):
            book.buy("u1", YES, 1)
        with pytest.raises(MarketError):
            book.buy("u1", YES, 1)

    def test_selling_frees_it_up_again(self):
        """The cap is on the position, not on lifetime volume."""
        book = Book()
        book.buy("u1", YES, 5)
        book.buy("u1", YES, -3)
        book.buy("u1", YES, 3)
        assert book.state.position("u1").yes == 5

    def test_it_is_per_manager_not_per_market(self):
        book = Book()
        for who in ("u1", "u2", "u3"):
            book.buy(who, YES, 5)
        assert book.state.traded_yes == 15

    def test_each_side_has_its_own_headroom(self):
        book = Book()
        book.buy("u1", YES, 5)
        book.buy("u2", NO, 5)
        assert book.state.position("u2").no == 5


class TestNettingOutTheOtherSide:
    """A YES and a NO cost a dollar and pay a dollar. Nobody should hold both."""

    def test_buying_against_yourself_sells_down_first(self):
        book = Book()
        book.buy("u1", YES, 4)
        book.buy("u1", NO, 3)
        held = book.state.position("u1")
        assert (held.yes, held.no) == (1, 0)

    def test_it_can_cross_all_the_way_over(self):
        book = Book()
        book.buy("u1", YES, 2)
        book.buy("u1", NO, 5)
        held = book.state.position("u1")
        assert (held.yes, held.no) == (0, 3)

    def test_crossing_over_still_respects_the_cap(self):
        book = Book()
        book.buy("u1", YES, 1)
        with pytest.raises(MarketError):
            book.buy("u1", NO, 7)

    def test_nobody_can_end_up_holding_a_pair(self):
        book = Book()
        book.buy("u1", YES, 5)
        book.buy("u1", NO, 5)
        held = book.state.position("u1")
        assert held.yes == 0 or held.no == 0


class TestTheHouseBooksBalance:
    def test_it_reports_both_outcomes(self):
        """Which way the house is leaning is the number to watch on the night."""
        book = Book()
        book.buy("u1", YES, 5)
        state = book.state
        assert state.house_pnl(True) < state.house_pnl(False)

    def test_what_it_keeps_equals_what_the_league_loses(self):
        """The ledger has to close: this is somebody's actual money."""
        book = Book()
        book.buy("u1", YES, 5)
        book.buy("u2", NO, 3)
        book.buy("u3", YES, 2)
        state = book.state

        for yes_won in (True, False):
            league = sum(settle_all(state, yes_won).values())
            assert league + state.house_pnl(yes_won) == 0

    def test_an_untraded_market_costs_nothing(self):
        state = replay(market(opening=71), [])
        assert state.house_pnl(True) == state.house_pnl(False) == 0

    def test_the_seed_is_not_owed_to_anyone(self):
        """It is an accounting offset, not a holding somebody can redeem."""
        book = Book(market(opening=90))
        book.buy("u1", YES, 5)
        state = book.state
        assert state.traded_yes == 5
        assert state.house_pnl(True) == state.collected - 500

    def test_a_full_league_on_the_winning_side_stays_within_the_cap(self):
        book = Book()
        for i in range(12):
            book.buy(f"u{i}", YES, 5)
        state = book.state
        assert -state.house_pnl(True) <= state.config.exposure


class TestExposure:
    """`b * ln 2` is the textbook number and only true at 50c."""

    def test_an_even_market_matches_the_textbook(self):
        assert market(opening=50).exposure == 694  # b*ln2 = $6.93, rounded up

    def test_an_opinionated_opening_risks_more(self):
        assert market(opening=71).exposure > market(opening=50).exposure

    def test_it_grows_the_further_out_the_opening_sits(self):
        run = [market(opening=p).exposure for p in (50, 60, 71, 80, 90)]
        assert run == sorted(run)

    def test_the_two_directions_are_mirror_images(self):
        assert market(opening=20).exposure == market(opening=80).exposure

    def test_a_realistic_slate_costs_well_over_the_textbook_figure(self):
        """The gap a commissioner would otherwise budget straight past.

        Ten markets priced off ADP land where ADP puts them, not at 50c. Using
        `b * ln 2` for all ten says $69.40; the real worst case is $116.50.
        """
        slate = [50, 62, 71, 71, 80, 45, 35, 71, 60, 85]
        total = sum(market(opening=p).exposure for p in slate)
        assert total == 11_650
        assert total > 10 * market(opening=50).exposure * 1.6


class TestSettlement:
    def test_a_winner_is_paid_a_dollar_a_contract(self):
        book = Book()
        book.buy("u1", YES, 5)
        paid = book.state.position("u1").cash
        assert settle_all(book.state, yes_won=True)["u1"] == 500 - paid

    def test_a_loser_is_out_what_they_paid(self):
        book = Book()
        book.buy("u1", YES, 5)
        paid = book.state.position("u1").cash
        assert settle_all(book.state, yes_won=False)["u1"] == -paid

    def test_nobody_can_lose_more_than_five_dollars(self):
        """What the cap is for."""
        book = Book(market(opening=95))
        book.buy("u1", YES, 5)
        for yes_won in (True, False):
            assert settle_all(book.state, yes_won)["u1"] >= -500

    def test_someone_who_traded_out_is_still_on_the_ledger(self):
        book = Book()
        book.buy("u1", YES, 5)
        book.buy("u2", YES, 5)
        book.buy("u1", YES, -5)
        result = settle_all(book.state, yes_won=True)
        assert result["u1"] > 0, "sold into u2's buying, so came out ahead"


class TestReplayIsTheWholeTruth:
    def test_the_same_log_gives_the_same_state(self):
        book = Book()
        book.buy("u1", YES, 5)
        book.buy("u2", NO, 2)
        again = replay(book.config, book.log)
        assert again.as_dict() == book.state.as_dict()

    def test_dropping_the_last_trade_undoes_it(self):
        book = Book()
        book.buy("u1", YES, 5)
        before = book.state.as_dict()
        book.buy("u2", NO, 3)
        assert replay(book.config, book.log[:-1]).as_dict() == before

    def test_an_empty_log_is_the_opening_line(self):
        assert replay(market(opening=71), []).price_yes == 71


class TestTheTradingWindow:
    """Trading runs from the Monday to the first pick, then stops.

    A per-market close driven by observed picks would leave something tradeable
    after its answer was on screen whenever the feed stalled. One hard close
    before the draft means nothing is ever tradeable once any answer is
    knowable -- and it costs the early exit, which is the trade.
    """

    OPENS = datetime(2026, 8, 31, 9, 0, tzinfo=CENTRAL)
    CLOSES = datetime(2026, 9, 1, 18, 30, tzinfo=CENTRAL)

    def slate(self, **kw):
        return market(opens_at=self.OPENS, closes_at=self.CLOSES, **kw)

    def at(self, *args):
        return datetime(*args, tzinfo=CENTRAL)

    def test_it_is_pending_before_monday(self):
        assert phase(self.slate(), self.at(2026, 8, 30, 12)) == PENDING

    def test_it_is_open_through_monday_and_tuesday_afternoon(self):
        for when in [self.at(2026, 8, 31, 9), self.at(2026, 8, 31, 23),
                     self.at(2026, 9, 1, 18, 29)]:
            assert phase(self.slate(), when) == OPEN, when

    def test_it_closes_the_moment_the_draft_starts(self):
        assert phase(self.slate(), self.at(2026, 9, 1, 18, 30)) == CLOSED
        assert phase(self.slate(), self.at(2026, 9, 1, 18, 31)) == CLOSED

    def test_settled_beats_the_clock(self):
        assert phase(self.slate(), self.at(2026, 8, 31, 12), settled=True) == SETTLED

    def test_nobody_can_buy_before_it_opens(self):
        state = replay(self.slate(), [])
        with pytest.raises(MarketError, match="not opened yet"):
            plan(state, "u1", YES, 1, now=self.at(2026, 8, 30, 12))

    def test_nobody_can_buy_once_the_draft_starts(self):
        state = replay(self.slate(), [])
        with pytest.raises(MarketError, match="trading closed"):
            plan(state, "u1", YES, 1, now=self.at(2026, 9, 1, 18, 30))

    def test_nobody_can_sell_out_during_the_draft_either(self):
        """The cost of one hard close: no exit once it is running."""
        config = self.slate()
        monday = self.at(2026, 8, 31, 12)
        done = plan(replay(config, []), "u1", YES, 5, now=monday)
        state = replay(config, done.legs)

        with pytest.raises(MarketError, match="trading closed"):
            plan(state, "u1", YES, -5, now=self.at(2026, 9, 1, 19, 0))

    def test_selling_works_right_up_to_the_close(self):
        config = self.slate()
        done = plan(replay(config, []), "u1", YES, 5, now=self.at(2026, 8, 31, 12))
        state = replay(config, done.legs)
        out = plan(state, "u1", YES, -5, now=self.at(2026, 9, 1, 18, 29))
        assert out.cash < 0

    def test_a_settled_market_takes_no_more_trades(self):
        state = replay(self.slate(), [])
        with pytest.raises(MarketError, match="already settled"):
            plan(state, "u1", YES, 1, now=self.at(2026, 8, 31, 12), settled=True)

    def test_a_market_with_no_window_is_always_open(self):
        """Which is what every other test in this file relies on."""
        assert phase(market()) == OPEN

    def test_closing_before_opening_is_refused(self):
        with pytest.raises(MarketError, match="close before it opens"):
            market(opens_at=self.CLOSES, closes_at=self.OPENS)


class TestTheShippedSizing:
    """The numbers the league actually plays at.

    Chosen against a season rather than a night: twenty-five is the largest
    position at which a manager who maxes every market with a poor read still
    cannot be knocked out of a $1,000 season. Simulated over eighteen slates
    they bottom out near $500 and never miss a market; at fifty they reach $10,
    and at seventy-five they are broke by November and miss seventy-four.
    """

    def test_the_defaults_are_the_chosen_ones(self):
        from app.core.contracts import DEFAULT_B, DEFAULT_CAP, DEFAULT_SPREAD

        assert (DEFAULT_CAP, DEFAULT_B, DEFAULT_SPREAD) == (25, 50.0, 1)

    def test_liquidity_tracks_the_cap(self):
        """b at twice the cap keeps one maximum buy worth about twelve points."""
        from app.core.contracts import DEFAULT_B, DEFAULT_CAP

        assert DEFAULT_B == 2 * DEFAULT_CAP

    def test_a_maximum_buy_moves_the_line_twelve_points(self):
        from app.core.contracts import DEFAULT_B, DEFAULT_CAP

        done = plan(replay(market(b=DEFAULT_B, position_cap=DEFAULT_CAP), []),
                    "u1", YES, DEFAULT_CAP)
        assert (done.price_before, done.price_after) == (50, 62)

    def test_a_maximum_buy_costs_about_fourteen_dollars(self):
        from app.core.contracts import DEFAULT_B, DEFAULT_CAP

        done = plan(replay(market(b=DEFAULT_B, position_cap=DEFAULT_CAP), []),
                    "u1", YES, DEFAULT_CAP)
        assert 1_350 <= done.cash <= 1_500

    def test_the_whole_league_maxed_still_leaves_room(self):
        from app.core.contracts import DEFAULT_B, DEFAULT_CAP
        from app.core.lmsr import price_cents

        assert price_cents(12 * DEFAULT_CAP, 0, DEFAULT_B) == 99
