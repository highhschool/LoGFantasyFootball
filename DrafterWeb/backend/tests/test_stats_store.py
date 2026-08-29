"""The statistics cache.

A separate database from the league's, because this is refetchable and that is
not. These are mostly about the two rules that make it cheap to keep: a
finished season is never asked for twice, and players who did not play are not
stored at all.
"""

from __future__ import annotations

import pytest

from app.stats_store import SEASONS_BACK, StatsStore, wanted_seasons


def season(**players) -> dict:
    """A season payload, in Sleeper's shape."""
    return {pid: stats for pid, stats in players.items()}


@pytest.fixture
def store(tmp_path):
    return StatsStore(tmp_path / "stats.db")


class TestWhichSeasons:
    def test_it_counts_back_from_the_current_one(self):
        assert wanted_seasons(2026, 3) == [2026, 2025, 2024]

    def test_the_default_is_ten(self):
        assert len(wanted_seasons(2026)) == SEASONS_BACK == 10

    def test_it_rolls_forward_on_its_own(self):
        """Not a written-down year -- there are enough of those to update."""
        assert wanted_seasons(2027, 3)[0] == 2027
        assert 2016 not in wanted_seasons(2027)


class TestStoringASeason:
    def test_it_keeps_who_played(self, store):
        n = store.ingest(2025, season(
            a={"gp": 17, "rush_yd": 1223},
            b={"gp": 3, "rec": 4},
        ), final=True)
        assert n == 2

    def test_it_drops_who_did_not(self, store):
        """Three quarters of the feed never took the field."""
        n = store.ingest(2025, season(
            played={"gp": 17, "rush_yd": 1223},
            benched={"gp": 0},
            empty={},
            missing=None,
        ), final=True)
        assert n == 1
        assert [r["season"] for r in store.career("benched")] == []

    def test_re_ingesting_replaces_rather_than_doubles(self, store):
        store.ingest(2025, season(a={"gp": 17, "rush_yd": 1000}), final=False)
        store.ingest(2025, season(a={"gp": 17, "rush_yd": 1223}), final=True)
        career = store.career("a")
        assert len(career) == 1
        assert career[0]["rush_yd"] == 1223

    def test_every_stat_key_survives(self, store):
        """Wide now so trimming later is a SELECT, not a refetch."""
        wide = {f"stat_{i}": i for i in range(245)}
        wide["gp"] = 17
        store.ingest(2025, season(a=wide), final=True)
        assert len(store.career("a")[0]) == 247, "245 stats, plus gp and season"

    def test_an_empty_season_is_fine(self, store):
        """The current one, before a game is played."""
        assert store.ingest(2026, {}, final=False) == 0
        assert store.seasons()[0]["players"] == 0


class TestReadingACareer:
    @pytest.fixture
    def filled(self, store):
        for year, yards in ((2023, 945), (2024, 1412), (2025, 1223)):
            store.ingest(year, season(gibbs={"gp": 17, "rush_yd": yards},
                                      other={"gp": 17, "rush_yd": 1}),
                         final=True)
        return store

    def test_it_comes_back_newest_first(self, filled):
        assert [r["season"] for r in filled.career("gibbs")] == [2025, 2024, 2023]

    def test_each_row_carries_its_season(self, filled):
        assert filled.career("gibbs")[0]["season"] == 2025
        assert filled.career("gibbs")[0]["rush_yd"] == 1223

    def test_it_can_be_capped(self, filled):
        assert len(filled.career("gibbs", limit=2)) == 2

    def test_somebody_with_no_seasons_is_empty_not_an_error(self, filled):
        assert filled.career("nobody") == []

    def test_it_does_not_leak_another_player(self, filled):
        assert all(r["rush_yd"] == 1 for r in filled.career("other"))


class TestNotFetchingTwice:
    def test_a_final_season_is_never_wanted_again(self, store):
        store.ingest(2025, season(a={"gp": 17}), final=True)
        assert 2025 not in store.missing(2026, back=3)

    def test_an_unfinished_one_still_is(self, store):
        """The current season changes every week it is played."""
        store.ingest(2026, season(a={"gp": 1}), final=False)
        assert 2026 in store.missing(2026, back=3)

    def test_what_was_never_fetched_is_wanted(self, store):
        assert store.missing(2026, back=3) == [2026, 2025, 2024]

    def test_a_full_cache_wants_nothing_but_the_current_year(self, store):
        for year in (2024, 2025):
            store.ingest(year, season(a={"gp": 17}), final=True)
        store.ingest(2026, {}, final=False)
        assert store.missing(2026, back=3) == [2026]


class TestTrimmingItBack:
    def test_a_season_can_be_dropped(self, store):
        store.ingest(2016, season(a={"gp": 16}), final=True)
        store.ingest(2025, season(a={"gp": 17}), final=True)
        store.forget(2016)
        assert [r["season"] for r in store.career("a")] == [2025]
        assert [r["season"] for r in store.seasons()] == [2025]

    def test_dropping_one_that_is_not_there_is_harmless(self, store):
        assert store.forget(1999) == 0

    def test_it_reports_what_it_is_holding(self, store):
        store.ingest(2025, season(a={"gp": 17}, b={"gp": 12}), final=True)
        held = store.size()
        assert held["rows"] == 2
        assert held["seasons"] == 1
        assert held["bytes"] > 0


class TestItStaysOutOfTheLeagueDatabase:
    def test_it_is_its_own_file(self, tmp_path):
        """A league backup should not carry eleven megabytes of statistics."""
        from app.store import SessionStore

        league = SessionStore(tmp_path / "sessions.db")
        stats = StatsStore(tmp_path / "stats.db")
        stats.ingest(2025, season(a={"gp": 17}), final=True)

        assert stats.path != league.path
        tables = {r[0] for r in league._connect().execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "player_stats" not in tables

    def test_deleting_it_loses_nothing_that_cannot_be_refetched(self, tmp_path):
        path = tmp_path / "stats.db"
        StatsStore(path).ingest(2025, season(a={"gp": 17}), final=True)
        path.unlink()
        assert StatsStore(path).career("a") == []
        assert StatsStore(path).missing(2026, back=1) == [2026]
