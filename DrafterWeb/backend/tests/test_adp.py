"""ADP fetching, caching, and the offline fallback.

The fallback is the point of this module: a third party being down must never
be able to take the site out on draft night. These tests never touch the
network -- the fetch is stubbed, so they also prove the cache path works
without one.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core import adp
from app.core.models import RankingsError
from app.core.rankings import build_pool


@pytest.fixture
def payload(ffc_2025):
    return ffc_2025


@pytest.fixture
def no_network(monkeypatch):
    """Make every fetch fail, as if FFC were down."""
    def boom(*_args, **_kwargs):
        raise RankingsError("could not reach the ADP feed: simulated outage")

    monkeypatch.setattr(adp, "fetch", boom)


@pytest.fixture
def good_network(monkeypatch, payload):
    calls = {"n": 0}

    def ok(*_args, **_kwargs):
        calls["n"] += 1
        return payload

    monkeypatch.setattr(adp, "fetch", ok)
    return calls


class TestNormalization:
    def test_players_come_back_adp_ordered(self, payload):
        players = adp.to_players(payload)
        adps = [p.adp for p in players]
        assert adps == sorted(adps)

    def test_the_whole_feed_is_kept(self, payload):
        # Nothing should be silently truncated; only unknown positions drop out.
        players = adp.to_players(payload)
        recognized = [
            p for p in payload["players"]
            if adp.POSITION_ALIASES.get(p["position"], p["position"]) in adp.POSITIONS
        ]
        assert len(players) == len(recognized)

    def test_positions_are_normalized(self, payload):
        positions = {p.position for p in adp.to_players(payload)}
        assert positions <= set(adp.POSITIONS)
        assert "DEF" not in positions and "PK" not in positions

    def test_positional_ranks_are_dense(self, payload):
        players = adp.to_players(payload)
        for position in ("QB", "RB", "WR", "TE"):
            ranks = sorted(p.pos_rank for p in players if p.position == position)
            assert ranks == list(range(1, len(ranks) + 1))

    def test_overall_rank_matches_adp_order(self, payload):
        players = adp.to_players(payload)
        assert [p.rank for p in players] == list(range(1, len(players) + 1))

    def test_stdev_survives(self, payload):
        # Without STDEV the bots cannot vary and the advisor cannot score.
        players = adp.to_players(payload)
        assert any(p.stdev > 0 for p in players)

    def test_matches_the_csv_pipeline(self, payload, pool_2025):
        """The API path and build_rankings.py must rank identically."""
        from_api = adp.to_players(payload)
        assert len(from_api) == len(pool_2025.players)
        assert [p.name for p in from_api[:25]] == [p.name for p in pool_2025.players[:25]]

    def test_empty_feed_is_rejected(self):
        with pytest.raises(RankingsError, match="no players"):
            adp.to_players({"players": []})


class TestCaching:
    def test_a_fetch_writes_a_cache(self, tmp_path, good_network):
        adp.load(2025, 12, "ppr", tmp_path, ttl_seconds=3600)
        assert adp.cache_file(tmp_path, 2025, 12, "ppr").is_file()

    def test_a_fresh_cache_avoids_the_network(self, tmp_path, good_network):
        adp.load(2025, 12, "ppr", tmp_path, ttl_seconds=3600)
        assert good_network["n"] == 1

        _, provenance = adp.load(2025, 12, "ppr", tmp_path, ttl_seconds=3600)
        assert good_network["n"] == 1, "a fresh cache should not re-fetch"
        assert provenance.source == "cache"
        assert provenance.stale is False

    def test_an_expired_cache_refetches(self, tmp_path, good_network):
        adp.load(2025, 12, "ppr", tmp_path, ttl_seconds=3600)
        _, provenance = adp.load(2025, 12, "ppr", tmp_path, ttl_seconds=0)
        assert good_network["n"] == 2
        assert provenance.source == "api"

    def test_caches_are_keyed_by_parameters(self, tmp_path):
        a = adp.cache_file(tmp_path, 2025, 12, "ppr")
        assert a != adp.cache_file(tmp_path, 2026, 12, "ppr")
        assert a != adp.cache_file(tmp_path, 2025, 10, "ppr")
        assert a != adp.cache_file(tmp_path, 2025, 12, "standard")

    def test_a_corrupt_cache_is_ignored_not_fatal(self, tmp_path, good_network):
        path = adp.cache_file(tmp_path, 2025, 12, "ppr")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not json", encoding="utf-8")

        players, provenance = adp.load(2025, 12, "ppr", tmp_path)
        assert players and provenance.source == "api"


class TestOfflineFallback:
    """The reason this module exists."""

    def test_an_outage_serves_the_cache(self, tmp_path, payload, monkeypatch):
        monkeypatch.setattr(adp, "fetch", lambda *a, **k: payload)
        adp.load(2025, 12, "ppr", tmp_path, ttl_seconds=3600)

        # Now the feed goes down and the cache is past its TTL.
        def boom(*_a, **_k):
            raise RankingsError("simulated outage")

        monkeypatch.setattr(adp, "fetch", boom)
        players, provenance = adp.load(2025, 12, "ppr", tmp_path, ttl_seconds=0)

        assert len(players) > 200, "the draft must still work"
        assert provenance.source == "cache"
        assert provenance.stale is True, "a stale fallback must be visible, not silent"

    def test_an_outage_with_no_cache_fails_loudly(self, tmp_path, no_network):
        with pytest.raises(RankingsError):
            adp.load(2025, 12, "ppr", tmp_path, ttl_seconds=0)

    def test_network_can_be_disabled_entirely(self, tmp_path, payload, monkeypatch):
        monkeypatch.setattr(adp, "fetch", lambda *a, **k: payload)
        adp.load(2025, 12, "ppr", tmp_path, ttl_seconds=3600)

        def never(*_a, **_k):
            raise AssertionError("network was used despite allow_network=False")

        monkeypatch.setattr(adp, "fetch", never)
        players, provenance = adp.load(
            2025, 12, "ppr", tmp_path, ttl_seconds=0, allow_network=False
        )
        assert players and provenance.source == "cache"


class TestProvenance:
    def test_metadata_survives_the_round_trip(self, tmp_path, good_network, payload):
        _, provenance = adp.load(2025, 12, "ppr", tmp_path, ttl_seconds=3600)
        meta = payload["meta"]
        assert provenance.total_drafts == meta["total_drafts"]
        assert provenance.start_date == meta["start_date"]
        assert provenance.end_date == meta["end_date"]

    def test_age_is_reported(self, tmp_path, good_network):
        _, provenance = adp.load(2025, 12, "ppr", tmp_path, ttl_seconds=3600)
        assert provenance.age_seconds is not None
        assert provenance.age_seconds < 60

    def test_serializes_without_datetimes(self, tmp_path, good_network):
        _, provenance = adp.load(2025, 12, "ppr", tmp_path, ttl_seconds=3600)
        json.dumps(provenance.as_dict())  # must not raise

    @pytest.mark.parametrize(
        "seconds,expected",
        [(None, "unknown age"), (10, "just now"), (600, "10 minutes ago"),
         (7200, "2 hours ago"), (60 * 60 * 72, "3 days ago")],
    )
    def test_humanized_age(self, seconds, expected):
        assert adp.humanize_age(seconds) == expected


class TestSourceSelection:
    def test_api_is_the_default(self, tmp_path, good_network):
        pool = build_pool(2025, 12, "ppr", cache_dir=tmp_path)
        assert pool.provenance.source == "api"
        assert len(pool) > 200

    def test_a_csv_directory_overrides_the_api(self, tmp_path, rankings_dir_2025, monkeypatch):
        def never(*_a, **_k):
            raise AssertionError("the API was called despite a CSV override")

        monkeypatch.setattr(adp, "fetch", never)
        pool = build_pool(2025, 12, "ppr", cache_dir=tmp_path, csv_dir=rankings_dir_2025)
        assert pool.provenance.source == "csv"
        assert len(pool) > 200


class TestFetchGuards:
    def test_bad_scoring_is_rejected_before_any_request(self):
        with pytest.raises(RankingsError, match="scoring must be"):
            adp.fetch(2026, 12, "superflex-ppr")


def test_cache_survives_a_clock_without_timezone(tmp_path, payload):
    """A cache written by an older build may carry a naive timestamp."""
    path = adp.cache_file(tmp_path, 2025, 12, "ppr")
    path.parent.mkdir(parents=True, exist_ok=True)
    naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=30)
    path.write_text(
        json.dumps({"fetched_at": naive.isoformat(), "payload": payload}),
        encoding="utf-8",
    )
    players, provenance = adp.load(2025, 12, "ppr", tmp_path, ttl_seconds=3600)
    assert players and provenance.source == "cache"
