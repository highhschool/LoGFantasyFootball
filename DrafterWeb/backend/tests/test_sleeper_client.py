"""The Sleeper client.

Driven entirely by the cached 2025 fixture, so the suite stays offline and
deterministic. The fallback behaviour matters most: a draft is happening in
real time, and Sleeper being briefly unreachable must not empty the board.
"""

from __future__ import annotations

import json

import pytest

from app.integrations.sleeper import (
    SleeperClient,
    SleeperError,
    draft_id_from_url,
    parse_draft,
    parse_picks,
)


@pytest.fixture
def draft_payload(sleeper_2025):
    return sleeper_2025["draft"]


@pytest.fixture
def picks_payload(sleeper_2025):
    return sleeper_2025["picks"]


@pytest.fixture
def client(tmp_path):
    return SleeperClient(cache_dir=tmp_path)


class TestParsingTheDraft:
    def test_it_reads_the_league_shape(self, draft_payload):
        draft = parse_draft(draft_payload)
        assert draft.is_snake
        assert draft.teams == 12
        assert draft.rounds == 15
        assert draft.draft_id

    def test_a_missing_settings_block_does_not_explode(self):
        draft = parse_draft({"draft_id": "1", "type": "snake"})
        assert draft.teams == 0 and draft.rounds == 0

    def test_slot_to_roster_keys_become_integers(self, draft_payload):
        draft = parse_draft(draft_payload)
        if draft.slot_to_roster:
            assert all(isinstance(k, int) for k in draft.slot_to_roster)


class TestParsingPicks:
    def test_the_whole_board_parses(self, picks_payload):
        picks = parse_picks(picks_payload)
        assert len(picks) == 180
        assert [p.pick_no for p in picks] == list(range(1, 181))

    def test_picks_are_ordered_even_if_the_feed_is_not(self, picks_payload):
        shuffled = list(reversed(picks_payload))
        assert [p.pick_no for p in parse_picks(shuffled)] == list(range(1, 181))

    def test_names_are_joined(self, picks_payload):
        first = parse_picks(picks_payload)[0]
        assert " " in first.name
        assert first.position and first.team

    def test_keeper_flag_is_a_real_boolean(self, picks_payload):
        # Sleeper sends null rather than false when unset.
        assert all(isinstance(p.is_keeper, bool) for p in parse_picks(picks_payload))

    def test_an_empty_board_is_valid(self):
        assert parse_picks([]) == []


class TestFetchingAndCaching:
    def test_a_successful_read_is_cached(self, client, monkeypatch, picks_payload):
        monkeypatch.setattr(
            "app.integrations.sleeper._get", lambda *a, **k: picks_payload
        )
        assert len(client.picks("123")) == 180
        assert client._cache_path("draft-123-picks").is_file()

    def test_an_outage_falls_back_to_the_cache(self, client, monkeypatch, picks_payload):
        monkeypatch.setattr(
            "app.integrations.sleeper._get", lambda *a, **k: picks_payload
        )
        client.picks("123")

        def down(*_a, **_k):
            raise SleeperError("simulated outage")

        monkeypatch.setattr("app.integrations.sleeper._get", down)
        # The board must survive Sleeper going away mid-draft.
        assert len(client.picks("123")) == 180

    def test_an_outage_with_no_cache_raises(self, client, monkeypatch):
        def down(*_a, **_k):
            raise SleeperError("simulated outage")

        monkeypatch.setattr("app.integrations.sleeper._get", down)
        with pytest.raises(SleeperError):
            client.picks("never-fetched")

    def test_a_corrupt_cache_is_ignored(self, client, monkeypatch, picks_payload):
        path = client._cache_path("draft-123-picks")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")

        monkeypatch.setattr(
            "app.integrations.sleeper._get", lambda *a, **k: picks_payload
        )
        assert len(client.picks("123")) == 180

    def test_caches_do_not_collide_between_drafts(self, client):
        assert client._cache_path("draft-1-picks") != client._cache_path("draft-2-picks")


class TestDraftDiscovery:
    def test_the_latest_season_wins(self, client, monkeypatch, draft_payload):
        older = dict(draft_payload, draft_id="old", season="2024")
        newer = dict(draft_payload, draft_id="new", season="2025")
        monkeypatch.setattr(
            "app.integrations.sleeper._get", lambda *a, **k: [older, newer]
        )
        # Each season is a new league and draft id; discovery beats hardcoding.
        assert client.latest_draft("league").draft_id == "new"

    def test_a_league_with_no_drafts_is_an_error(self, client, monkeypatch):
        monkeypatch.setattr("app.integrations.sleeper._get", lambda *a, **k: [])
        with pytest.raises(SleeperError, match="no drafts"):
            client.latest_draft("league")


class TestDraftIdFromUrl:
    @pytest.mark.parametrize(
        "value",
        [
            "1261437960088195073",
            "https://sleeper.com/draft/nfl/1261437960088195073",
            "https://sleeper.com/draft/nfl/1261437960088195073/",
            "  1261437960088195073  ",
        ],
    )
    def test_it_accepts_what_people_actually_paste(self, value):
        assert draft_id_from_url(value) == "1261437960088195073"

    @pytest.mark.parametrize("value", ["", "   ", "https://sleeper.com/leagues"])
    def test_it_rejects_what_it_cannot_read(self, value):
        with pytest.raises(SleeperError):
            draft_id_from_url(value)


class TestAgainstTheRealFixture:
    def test_every_pick_resolves_against_the_adp_pool(self, picks_payload, pool_2025):
        """The name join, re-checked through the client's own parsing."""
        unresolved = [
            p for p in parse_picks(picks_payload)[:120]
            if pool_2025.find(p.name, p.position, p.team) is None
        ]
        assert not unresolved, [p.name for p in unresolved]

    def test_the_fixture_is_still_a_snake_draft(self, draft_payload, picks_payload):
        assert parse_draft(draft_payload).is_snake
        picks = parse_picks(picks_payload)
        assert [p.draft_slot for p in picks[:12]] == list(range(1, 13))
        assert [p.draft_slot for p in picks[12:24]] == list(range(12, 0, -1))
