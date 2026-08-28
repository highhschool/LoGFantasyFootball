"""Starting slots.

The point of the module: a first running back fills a starting slot and a
fifth does not, and the advisor has to be able to tell them apart.
"""

from __future__ import annotations

import pytest

from app.core.lineup import (
    BENCH,
    FLEX,
    STARTER,
    Lineup,
    default_lineup,
    flex_gaps,
    from_sleeper_settings,
    slot_for,
    starters_remaining,
    starting_gaps,
)

# What Sleeper reported for the league's own draft.
LEAGUE_SETTINGS = {
    "slots_qb": 1, "slots_rb": 2, "slots_wr": 2, "slots_te": 1,
    "slots_flex": 2, "slots_k": 1, "slots_def": 1, "slots_bn": 5,
}


class TestReadingSleeper:
    def test_it_matches_the_league(self):
        lineup = from_sleeper_settings(LEAGUE_SETTINGS)
        assert lineup.starters == {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DST": 1}
        assert lineup.flex == 2
        assert lineup.bench == 5

    def test_the_shape_adds_up_to_the_roster(self):
        lineup = from_sleeper_settings(LEAGUE_SETTINGS)
        assert lineup.starting_spots == 10
        assert lineup.size == 15, "ten starters and five bench is the 15-round draft"

    def test_the_default_matches_what_sleeper_reports(self):
        assert default_lineup() == from_sleeper_settings(LEAGUE_SETTINGS)

    def test_missing_settings_do_not_explode(self):
        lineup = from_sleeper_settings({})
        assert lineup.starting_spots == 0
        assert lineup.size == 0

    def test_rubbish_values_are_ignored(self):
        lineup = from_sleeper_settings({"slots_qb": "two", "slots_rb": None, "slots_wr": -3})
        assert lineup.starters["QB"] == 0
        assert lineup.starters["RB"] == 0
        assert lineup.starters["WR"] == 0

    def test_a_receiver_flex_counts_as_flex(self):
        lineup = from_sleeper_settings({**LEAGUE_SETTINGS, "slots_rec_flex": 1})
        assert lineup.flex == 3

    def test_superflex_is_read_separately(self):
        lineup = from_sleeper_settings({**LEAGUE_SETTINGS, "slots_super_flex": 1})
        assert lineup.superflex == 1
        assert lineup.starting_spots == 11


class TestWhereAPickGoes:
    @pytest.fixture
    def lineup(self):
        return default_lineup()

    def test_an_empty_roster_starts_everyone(self, lineup):
        for position in ("QB", "RB", "WR", "TE", "K", "DST"):
            assert slot_for(lineup, {}, position) == STARTER

    def test_a_dedicated_slot_fills_first(self, lineup):
        assert slot_for(lineup, {"RB": 1}, "RB") == STARTER
        assert slot_for(lineup, {"RB": 2}, "RB") != STARTER

    def test_the_third_back_takes_a_flex(self, lineup):
        assert slot_for(lineup, {"RB": 2}, "RB") == FLEX

    def test_flex_is_shared_between_positions(self, lineup):
        # Two backs and two receivers fill the dedicated slots; the next of
        # either takes a flex, and the one after that takes the second flex.
        counts = {"RB": 2, "WR": 2}
        assert slot_for(lineup, counts, "RB") == FLEX
        assert slot_for(lineup, {**counts, "RB": 3}, "WR") == FLEX
        # Both flexes now used, and the dedicated tight end already filled,
        # so the next of any flex-eligible position sits.
        full_flex = {"RB": 3, "WR": 3, "TE": 1}
        assert slot_for(lineup, full_flex, "TE") == BENCH
        assert slot_for(lineup, full_flex, "RB") == BENCH

    def test_a_second_quarterback_is_bench(self, lineup):
        """One starting quarterback, and he is not flex-eligible here."""
        assert slot_for(lineup, {"QB": 1}, "QB") == BENCH

    def test_a_second_kicker_is_bench(self, lineup):
        assert slot_for(lineup, {"K": 1}, "K") == BENCH

    def test_the_fifth_back_is_bench(self, lineup):
        assert slot_for(lineup, {"RB": 4, "WR": 2}, "RB") == BENCH

    def test_superflex_takes_a_quarterback(self):
        lineup = Lineup(
            starters={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DST": 1},
            flex=1, superflex=1, bench=4,
        )
        # Dedicated QB filled, flex filled by a spare back: the superflex is
        # still open, and a second quarterback may take it.
        assert slot_for(lineup, {"QB": 1, "RB": 3, "WR": 2, "TE": 1}, "QB") == FLEX


class TestGaps:
    def test_an_empty_roster_needs_every_starter(self):
        lineup = default_lineup()
        assert starters_remaining(lineup, {}) == 10
        assert starting_gaps(lineup, {}) == {
            "QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DST": 1
        }

    def test_drafting_closes_the_gap(self):
        lineup = default_lineup()
        assert starting_gaps(lineup, {"RB": 1})["RB"] == 1
        assert starting_gaps(lineup, {"RB": 2})["RB"] == 0
        assert starting_gaps(lineup, {"RB": 5})["RB"] == 0, "never negative"

    def test_spare_players_consume_the_flex(self):
        lineup = default_lineup()
        assert flex_gaps(lineup, {}) == 2
        assert flex_gaps(lineup, {"RB": 3}) == 1
        assert flex_gaps(lineup, {"RB": 3, "WR": 3}) == 0
        assert flex_gaps(lineup, {"RB": 6}) == 0, "never negative"

    def test_a_full_starting_lineup_needs_nothing(self):
        lineup = default_lineup()
        full = {"QB": 1, "RB": 3, "WR": 3, "TE": 1, "K": 1, "DST": 1}
        assert starters_remaining(lineup, full) == 0

    def test_bench_players_do_not_count_as_starters(self):
        lineup = default_lineup()
        # Four quarterbacks: one starts, three sit, and none of them fills
        # anything that was still open.
        assert starters_remaining(lineup, {"QB": 4}) == 9
