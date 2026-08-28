"""When slates open and when their markets stop taking money.

The close is the one with money on it: a market still trading after kickoff is
a market selling contracts on a game already being played. Most of these are
about the boundary being exact, and about the clocks that shift under it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core.slates import (
    LEAGUE_TZ,
    Slate,
    SlateError,
    draft_slate,
    kickoff,
    next_open,
    weekly_slate,
)


def ct(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=LEAGUE_TZ)


class TestTheTuesdayCadence:
    def test_it_finds_the_coming_tuesday(self):
        assert next_open(ct(2026, 8, 28, 12)) == ct(2026, 9, 1, 9)  # a Friday

    def test_nine_on_the_day_is_already_open(self):
        assert next_open(ct(2026, 9, 1, 9)) == ct(2026, 9, 1, 9)

    def test_just_before_nine_still_opens_that_morning(self):
        assert next_open(ct(2026, 9, 1, 8, 59)) == ct(2026, 9, 1, 9)

    def test_after_nine_waits_a_week(self):
        assert next_open(ct(2026, 9, 1, 9, 1)) == ct(2026, 9, 8, 9)

    def test_every_answer_is_a_tuesday_at_nine(self):
        start = ct(2026, 9, 1)
        for offset in range(0, 140, 3):
            when = next_open(start + timedelta(days=offset))
            assert when.weekday() == 1, when
            assert (when.hour, when.minute) == (9, 0)

    def test_it_holds_nine_local_across_the_clock_change(self):
        """Central drops to UTC-6 on 1 November; a fixed offset would slip.

        Written as -05:00 all season, every slate from November would open and
        close an hour late -- and an hour late on a close is a market still
        taking money after kickoff.
        """
        autumn = next_open(ct(2026, 10, 20, 10))    # -> Tue 27 Oct, still CDT
        winter = next_open(ct(2026, 11, 10, 10))    # -> Tue 17 Nov, now CST
        assert autumn.hour == winter.hour == 9
        assert autumn.utcoffset() != winter.utcoffset(), "the offset really does move"


class TestKickoffs:
    OPENS = ct(2026, 9, 1, 9)   # a Tuesday

    def test_thursday_night_is_two_days_on(self):
        when = kickoff(self.OPENS, "thursday")
        assert when.weekday() == 3
        assert (when.hour, when.minute) == (19, 15)

    def test_sunday_windows_run_in_order(self):
        early = kickoff(self.OPENS, "sunday")
        late = kickoff(self.OPENS, "sunday_late")
        night = kickoff(self.OPENS, "sunday_night")
        assert early < late < night
        assert {w.weekday() for w in (early, late, night)} == {6}

    def test_monday_night_closes_the_week(self):
        when = kickoff(self.OPENS, "monday")
        assert when.weekday() == 0
        assert when > kickoff(self.OPENS, "sunday_night")

    def test_every_kickoff_is_after_the_slate_opens(self):
        for game in ("thursday", "sunday", "sunday_late", "sunday_night", "monday"):
            assert kickoff(self.OPENS, game) > self.OPENS, game

    def test_an_unknown_game_day_is_refused(self):
        with pytest.raises(SlateError, match="unknown game day"):
            kickoff(self.OPENS, "wednesday")

    def test_kickoffs_hold_local_time_in_winter(self):
        december = ct(2026, 12, 8, 9)
        assert kickoff(december, "sunday").hour == 12


class TestTheDraftSlate:
    DRAFT = ct(2026, 9, 1, 18, 30)

    def test_it_opens_on_the_cadence_the_morning_of(self):
        slate = draft_slate("s1", "Draft night", self.DRAFT)
        assert slate.opens_at == ct(2026, 9, 1, 9)

    def test_it_closes_at_the_first_pick(self):
        slate = draft_slate("s1", "Draft night", self.DRAFT)
        assert slate.closes_at == self.DRAFT

    def test_every_market_shares_that_close(self):
        """One event answers all of them, so one deadline covers all of them."""
        slate = draft_slate("s1", "Draft night", self.DRAFT)
        assert slate.close_for(None) == self.DRAFT

    def test_the_window_is_a_working_day(self):
        slate = draft_slate("s1", "Draft night", self.DRAFT)
        assert timedelta(hours=9) < slate.closes_at - slate.opens_at < timedelta(hours=10)

    def test_a_draft_needs_a_timezone(self):
        with pytest.raises(SlateError, match="explicit timezone"):
            draft_slate("s1", "d", datetime(2026, 9, 1, 18, 30))

    def test_a_draft_before_nine_hangs_off_the_previous_tuesday(self):
        """Nine o'clock that morning has not happened yet."""
        slate = draft_slate("s1", "d", ct(2026, 9, 1, 8))
        assert slate.opens_at == ct(2026, 8, 25, 9)

    def test_a_midweek_draft_still_opens_on_the_tuesday(self):
        slate = draft_slate("s1", "d", ct(2026, 9, 3, 19))   # a Thursday
        assert slate.opens_at == ct(2026, 9, 1, 9)


class TestWeeklySlates:
    OPENS = ct(2026, 9, 8, 9)

    def test_each_market_closes_on_its_own_game(self):
        slate = weekly_slate("w2", "Week 2", self.OPENS)
        assert slate.close_for("thursday") < slate.close_for("sunday")
        assert slate.close_for("sunday") < slate.close_for("monday")

    def test_a_market_naming_no_game_is_refused(self):
        """Without a default close there is nothing to fall back to."""
        slate = weekly_slate("w2", "Week 2", self.OPENS)
        with pytest.raises(SlateError, match="must .* name a game day"):
            slate.close_for(None)

    def test_a_thursday_market_trades_for_two_days(self):
        slate = weekly_slate("w2", "Week 2", self.OPENS)
        window = slate.close_for("thursday") - slate.opens_at
        assert timedelta(days=2) < window < timedelta(days=3)

    def test_a_monday_market_trades_almost_the_whole_week(self):
        slate = weekly_slate("w2", "Week 2", self.OPENS)
        window = slate.close_for("monday") - slate.opens_at
        assert timedelta(days=6) < window < timedelta(days=7)

    def test_a_slate_cannot_close_before_it_opens(self):
        with pytest.raises(SlateError, match="close before it opens"):
            Slate("x", "x", opens_at=self.OPENS, closes_at=self.OPENS - timedelta(hours=1))

    def test_a_naive_open_is_refused(self):
        with pytest.raises(SlateError, match="explicit timezone"):
            Slate("x", "x", opens_at=datetime(2026, 9, 8, 9))

    def test_it_serializes_with_offsets_intact(self):
        slate = weekly_slate("w2", "Week 2", self.OPENS)
        assert slate.as_dict()["opens_at"].endswith("-05:00")
        assert slate.as_dict()["closes_at"] is None
