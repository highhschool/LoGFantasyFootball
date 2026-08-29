"""The market maker's arithmetic.

Real money settles off this, so the properties worth testing are the ones
nobody would notice being wrong: that a round trip cannot profit, that the
house's loss is genuinely capped, and that the two sides stay symmetric.
"""

from __future__ import annotations

import math

import pytest

from app.core.lmsr import (
    DOLLAR,
    NO,
    YES,
    apply,
    cost,
    max_house_loss,
    price,
    price_cents,
    quote,
    settle,
)

B = 10.0  # the league's setting


class TestThePriceReadsAsAProbability:
    def test_an_untouched_market_is_a_coin_flip(self):
        assert price_cents(0, 0, B) == 50

    def test_buying_yes_raises_yes(self):
        assert price_cents(5, 0, B) > 50

    def test_buying_no_lowers_yes(self):
        assert price_cents(0, 5, B) < 50

    def test_the_two_sides_sum_to_a_dollar(self):
        for qy, qn in [(0, 0), (5, 0), (0, 37), (12, 3), (60, 60)]:
            assert price_cents(qy, qn, B, YES) + price_cents(qy, qn, B, NO) == 100

    def test_one_managers_maximum_moves_it_twelve_points(self):
        """The number `b` was chosen for: a liveable line, not a jumpy one."""
        assert price_cents(5, 0, B) == 62

    def test_the_whole_league_one_way_does_not_reach_certainty(self):
        """At b=5 this pins at 100c, where a dollar buys a dollar."""
        assert price_cents(60, 0, B) == 99

    def test_only_the_difference_between_the_sides_matters(self):
        assert price(30, 25, B) == pytest.approx(price(5, 0, B))

    def test_it_never_quotes_zero_or_a_dollar(self):
        assert price_cents(10_000, 0, B) == 99
        assert price_cents(0, 10_000, B) == 1


class TestBuyingIsBuying:
    """The reason both sides are tracked rather than netted into one number."""

    def test_buying_no_costs_money_rather_than_paying_it(self):
        q = quote(0, 0, B, NO, 5)
        assert q.cash > 0, "a NO contract is bought, not shorted"

    def test_the_two_sides_cost_the_same_in_an_even_market(self):
        assert quote(0, 0, B, NO, 5).cash == quote(0, 0, B, YES, 5).cash

    def test_it_costs_more_the_further_you_push(self):
        assert quote(5, 0, B, YES, 5).cash > quote(0, 0, B, YES, 5).cash

    def test_five_contracts_near_an_even_market_cost_about_half_each(self):
        q = quote(0, 0, B, YES, 5)
        assert q.cash == 281
        assert q.average == 56

    def test_selling_back_returns_money(self):
        assert quote(5, 0, B, YES, -5).cash < 0

    def test_the_quote_says_where_the_price_lands(self):
        q = quote(0, 0, B, YES, 5)
        assert (q.price_before, q.price_after) == (50, 62)

    def test_a_no_quote_reports_the_no_price(self):
        q = quote(0, 0, B, NO, 5)
        assert (q.price_before, q.price_after) == (50, 62)

    def test_a_trade_must_move_something(self):
        with pytest.raises(ValueError):
            quote(0, 0, B, YES, 0)

    def test_an_unknown_side_is_refused(self):
        with pytest.raises(ValueError):
            quote(0, 0, B, "maybe", 1)

    def test_the_book_may_go_wherever_the_trade_takes_it(self):
        """It is a point on a curve, not a pile of shares.

        A market seeded to open at 10c starts far below zero, and bounding the
        coordinate made the positions in it unsellable. What a trader may sell
        is bounded by what they hold, which `contracts.plan` enforces.
        """
        assert quote(2, 0, B, YES, -3).cash < 0
        assert quote(-40, 0, B, YES, -5).cash < 0


class TestTheHouseCannotBeMilked:
    def test_a_round_trip_never_profits(self):
        """Without this the line can be shoved to bluff the room, for free."""
        for qy, qn in [(0, 0), (12, 0), (0, 8), (25, 25)]:
            for side in (YES, NO):
                for size in (1, 3, 5):
                    out = quote(qy, qn, B, side, size, spread=1)
                    ay, an = apply(qy, qn, side, size)
                    back = quote(ay, an, B, side, -size, spread=1)
                    assert out.cash + back.cash > 0, (qy, qn, side, size)

    def test_without_a_spread_a_round_trip_is_free_but_for_rounding(self):
        """Which is exactly why the spread is not optional."""
        out = quote(0, 0, B, YES, 5)
        back = quote(5, 0, B, YES, -5)
        assert 0 <= out.cash + back.cash <= 2

    def test_the_spread_is_charged_in_both_directions(self):
        assert quote(0, 0, B, YES, 5, spread=2).cash - quote(0, 0, B, YES, 5).cash == 10
        assert quote(5, 0, B, YES, -5, spread=2).cash - quote(5, 0, B, YES, -5).cash == 10

    def test_rounding_always_favours_the_house(self):
        for qy in range(0, 40):
            exact = (cost(qy + 1, 0, B) - cost(qy, 0, B)) * DOLLAR
            assert quote(qy, 0, B, YES, 1).cash >= exact - 1e-9


class TestTheLossIsCapped:
    @pytest.mark.parametrize("b", [5.0, 10.0, 20.0, 50.0])
    def test_no_volume_can_breach_the_cap(self, b):
        """The property the whole real-money decision rests on."""
        cap = max_house_loss(b)
        for q in (1, 5, 12, 60, 500, 5000):
            collected = cost(q, 0, b) - cost(0, 0, b)
            assert q - collected <= cap + 1e-9, q

    def test_the_league_at_full_tilt_lands_just_under_the_cap(self):
        """Twelve managers, five contracts each, all on the winning side."""
        collected = (cost(60, 0, B) - cost(0, 0, B)) * DOLLAR
        assert round(60 * DOLLAR - collected) == 691
        assert 691 <= round(max_house_loss(B) * DOLLAR)

    def test_the_same_flow_the_other_way_pays_far_more_than_it_costs(self):
        """Downside capped, upside not -- worth pinning as a test."""
        assert round((cost(60, 0, B) - cost(0, 0, B)) * DOLLAR) == 5309

    def test_balanced_flow_is_flat_but_for_rounding(self):
        """Six a side: the house is a bystander.

        Collects a penny over the $30 it will pay out, because each trade
        rounds its cent up. Never under -- that is the direction that matters.
        """
        yes = quote(0, 0, B, YES, 30)
        no = quote(30, 0, B, NO, 30)
        payout = 30 * DOLLAR
        assert payout <= yes.cash + no.cash <= payout + 2


class TestSettlement:
    def test_a_winning_contract_pays_a_dollar(self):
        assert settle(5, 0, yes_won=True) == 500
        assert settle(0, 5, yes_won=False) == 500

    def test_a_losing_contract_pays_nothing(self):
        assert settle(5, 0, yes_won=False) == 0
        assert settle(0, 5, yes_won=True) == 0

    def test_holding_both_sides_pays_a_dollar_either_way(self):
        assert settle(5, 5, yes_won=True) == settle(5, 5, yes_won=False) == 500

    def test_a_pair_costs_a_dollar_and_pays_a_dollar(self):
        """So holding both sides is dead weight, and should be netted away.

        A cent over the dollar, from the two roundings. It can never come to
        less than the dollar it pays out, which is the point.
        """
        pair = quote(0, 0, B, YES, 1).cash + quote(1, 0, B, NO, 1).cash
        assert DOLLAR <= pair <= DOLLAR + 2


class TestGuards:
    @pytest.mark.parametrize("b", [0.0, -1.0])
    def test_a_market_needs_liquidity(self, b):
        with pytest.raises(ValueError):
            price(0, 0, b)
        with pytest.raises(ValueError):
            cost(0, 0, b)

    def test_a_negative_spread_is_refused(self):
        with pytest.raises(ValueError):
            quote(0, 0, B, YES, 1, spread=-1)

    def test_the_curve_survives_absurd_positions(self):
        """Overflow here would be a silent wrong price, not a crash."""
        assert math.isfinite(cost(10**6, 0, B))
        assert math.isfinite(cost(0, 10**6, B))
        assert 0.0 <= price(10**6, 0, B) <= 1.0
