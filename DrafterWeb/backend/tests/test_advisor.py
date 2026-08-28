"""The advisor.

The question it answers is not "who is best on the board" but "what do I lose
by waiting", so most of these pin down that the cost of waiting is measured
honestly and that the list is a decision rather than five names from two
positions.
"""

from __future__ import annotations

import pytest

from app.core.advisor import _article, outlook, recommend, survival_probability, tier_size
from app.core.engine import LoggedPick, replay
from app.core.models import DraftConfig


@pytest.fixture
def mock_client(tmp_path, monkeypatch, rankings_dir_2025):
    from fastapi.testclient import TestClient

    from app import config as app_config
    from app import main
    from app.store import SessionStore

    monkeypatch.setattr(app_config, "RANKINGS_DIR", rankings_dir_2025)
    monkeypatch.setattr(app_config, "SEASON", 2025)
    monkeypatch.setattr(main, "_store", SessionStore(tmp_path / "adv.db"))
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def config():
    return DraftConfig(year=2025, teams=12, rounds=15, your_slot=1)


@pytest.fixture
def state(config, pool_2025):
    return replay(config, pool_2025, [])


def at_position(pool, position):
    return sorted(
        (p for p in pool.players if p.position == position), key=lambda p: p.adp
    )


class TestSurvivalProbability:
    def test_a_player_far_from_the_window_is_near_certain(self, pool_2025):
        mid = next(p for p in pool_2025.players if p.adp > 50)
        assert survival_probability(mid, now=1, until=3) > 0.95

    def test_a_player_at_the_boundary_is_genuinely_uncertain(self, pool_2025):
        top = pool_2025.players[0]
        assert 0.05 < survival_probability(top, now=1, until=2) < 0.95

    def test_a_long_wait_erodes_it(self, pool_2025):
        top = pool_2025.players[0]
        assert survival_probability(top, now=1, until=25) < survival_probability(
            top, now=1, until=3
        )

    def test_the_last_pick_of_the_draft_needs_nothing_to_survive(self, pool_2025):
        assert survival_probability(pool_2025.players[0], now=180, until=None) == 1.0

    def test_it_is_always_a_probability(self, pool_2025):
        for player in pool_2025.players[::20]:
            for now, until in ((1, 12), (50, 62), (100, 130), (170, 180)):
                assert 0.0 <= survival_probability(player, now, until) <= 1.0

    def test_a_zero_spread_does_not_divide_by_zero(self, pool_2025):
        from dataclasses import replace

        rigid = replace(pool_2025.players[10], stdev=0.0)
        assert 0.0 <= survival_probability(rigid, now=5, until=20) <= 1.0

    def test_conditioning_matters(self, pool_2025):
        """Surviving to pick 30 is likelier once he has already reached 25."""
        player = pool_2025.players[15]
        assert survival_probability(player, now=25, until=30) > survival_probability(
            player, now=1, until=30
        )


class TestTierSize:
    def test_it_measures_the_tier_not_a_place_within_it(self, pool_2025):
        """Counting from each player onward made being *last* in a tier score
        highest, which recommended the worst member over the best."""
        assert tier_size(at_position(pool_2025, "RB"), teams=12) >= 1

    def test_drafting_the_leader_shrinks_it(self, config, pool_2025):
        rbs = at_position(pool_2025, "RB")
        before = tier_size(rbs, teams=12)
        if before < 2:
            pytest.skip("top RB tier holds only one player")
        assert tier_size(rbs[1:], teams=12) == before - 1

    def test_an_empty_position_is_zero(self):
        assert tier_size([], teams=12) == 0


class TestOutlook:
    def test_it_names_who_you_would_be_choosing_from_instead(self, pool_2025):
        wrs = at_position(pool_2025, "WR")
        view = outlook(wrs, now=6, until=19, teams=12)
        assert view is not None
        assert view.best_now is wrs[0]
        assert view.likely_later.adp >= view.best_now.adp

    def test_a_longer_wait_costs_more(self, pool_2025):
        wrs = at_position(pool_2025, "WR")
        soon = outlook(wrs, now=6, until=8, teams=12)
        later = outlook(wrs, now=6, until=40, teams=12)
        assert later.dropoff >= soon.dropoff

    def test_with_no_next_pick_nothing_is_lost(self, pool_2025):
        view = outlook(at_position(pool_2025, "WR"), now=180, until=None, teams=12)
        assert view.dropoff == 0.0
        assert view.likely_later is view.best_now

    def test_dropoff_is_never_negative(self, pool_2025):
        for position in ("QB", "RB", "WR", "TE", "K", "DST"):
            view = outlook(at_position(pool_2025, position), now=1, until=25, teams=12)
            assert view is None or view.dropoff >= 0

    def test_an_empty_position_has_no_outlook(self):
        assert outlook([], now=1, until=13, teams=12) is None


class TestRecommendations:
    def test_it_offers_one_player_per_position(self, state, pool_2025):
        """Five names from two positions is two decisions dressed as five."""
        positions = [a.player.position for a in recommend(state, pool_2025, limit=8)]
        assert len(positions) == len(set(positions))

    def test_each_is_the_best_available_at_its_position(self, state, pool_2025):
        for a in recommend(state, pool_2025, limit=8):
            assert a.player.key == at_position(pool_2025, a.player.position)[0].key

    def test_it_is_ranked_by_urgency(self, state, pool_2025):
        scores = [a.score for a in recommend(state, pool_2025, limit=8)]
        assert scores == sorted(scores, reverse=True)

    def test_the_opening_pick_leads_with_a_premium_position(self, state, pool_2025):
        top = recommend(state, pool_2025, limit=3)[0]
        assert top.player.position in {"RB", "WR"}
        assert top.player.adp < 20

    def test_it_never_suggests_a_drafted_player(self, config, pool_2025):
        taken = pool_2025.players[0]
        state = replay(config, pool_2025, [LoggedPick(taken.key)])
        assert all(a.player.key != taken.key for a in recommend(state, pool_2025))

    def test_it_never_suggests_a_position_you_cannot_roster(self, pool_2025):
        config = DraftConfig(
            year=2025, teams=2, rounds=2, your_slot=1,
            position_limits={"QB": 2, "RB": 0, "WR": 0, "TE": 0, "K": 0, "DST": 0},
        )
        state = replay(config, pool_2025, [])
        assert {a.player.position for a in recommend(state, pool_2025)} == {"QB"}

    def test_a_completed_draft_has_nothing_to_advise(self, pool_2025):
        config = DraftConfig(
            year=2025, teams=1, rounds=1, your_slot=1,
            position_limits={"QB": 1, "RB": 1, "WR": 1, "TE": 1, "K": 1, "DST": 1},
        )
        state = replay(config, pool_2025, [LoggedPick(pool_2025.players[0].key)])
        assert recommend(state, pool_2025) == []

    def test_every_recommendation_explains_itself(self, state, pool_2025):
        assert all(a.reasons for a in recommend(state, pool_2025, limit=8))

    def test_it_explains_itself_mid_draft_too(self, config, pool_2025):
        log = [LoggedPick(p.key) for p in pool_2025.players[:40]]
        state = replay(config, pool_2025, log)
        assert all(a.reasons for a in recommend(state, pool_2025, limit=8))

    def test_it_serializes(self, state, pool_2025):
        import json

        json.dumps([a.as_dict() for a in recommend(state, pool_2025, limit=3)])


class TestQuietPositionsAreNotOffered:
    def test_a_kicker_is_not_urged_at_the_top_of_the_draft(self, state, pool_2025):
        """Best kicker left is not a reason to draft a kicker at 1.01."""
        advice = recommend(state, pool_2025, limit=8)
        assert "K" not in {a.player.position for a in advice[:2]}

    def test_at_least_three_options_are_always_offered(self, state, pool_2025):
        assert len(recommend(state, pool_2025, limit=8)) >= 3

    def test_advice_still_comes_late_in_the_draft(self, config, pool_2025):
        log = [LoggedPick(p.key) for p in pool_2025.players[:150]]
        state = replay(config, pool_2025, log)
        assert recommend(state, pool_2025, limit=8)


class TestReasoning:
    def test_a_steep_drop_names_the_alternative(self, config, pool_2025):
        log = [LoggedPick(p.key) for p in pool_2025.players[:28]]
        state = replay(config, pool_2025, log)

        steep = [a for a in recommend(state, pool_2025, limit=8) if a.dropoff >= 3]
        assert steep, "expected at least one position under pressure"
        for a in steep:
            assert a.alternative
            assert any(r.startswith("Next probable pick:") for r in a.reasons)

    def test_a_quiet_position_says_so(self, state, pool_2025):
        for a in recommend(state, pool_2025, limit=8):
            if a.dropoff < 3:
                assert any("keeps" in r for r in a.reasons)

    def test_it_never_names_a_player_as_his_own_alternative(self, state, pool_2025):
        for a in recommend(state, pool_2025, limit=8):
            if a.alternative == a.player.name:
                assert not any(r.startswith("Next probable pick:") for r in a.reasons)

    def test_a_last_roster_spot_is_called_out(self, pool_2025):
        # One of each: every position is your last spot at that position.
        # Rounds must match the roster or the config is rejected outright.
        config = DraftConfig(
            year=2025, teams=12, rounds=6, your_slot=1,
            position_limits={"QB": 1, "RB": 1, "WR": 1, "TE": 1, "K": 1, "DST": 1},
        )
        state = replay(config, pool_2025, [])
        advice = recommend(state, pool_2025, limit=8)
        assert any("last" in r for a in advice for r in a.reasons)

    @pytest.mark.parametrize(
        "picks,expected", [(8, "an"), (11, "an"), (18, "an"), (14, "a"), (3, "a")]
    )
    def test_the_article_agrees_with_the_number(self, picks, expected):
        assert _article(picks) == expected


class TestAdviceEndpoints:
    def test_the_mock_tool_advises(self, mock_client):
        session = mock_client.post("/api/sessions", json={"your_slot": 1, "seed": 3}).json()
        advice = mock_client.get(f"/api/sessions/{session['id']}/advice").json()["advice"]
        assert advice
        assert {
            "name", "score", "survival", "dropoff", "alternative", "reasons"
        } <= advice[0].keys()

    def test_it_refuses_a_session_that_is_not_yours(self, mock_client):
        assert mock_client.get("/api/sessions/deadbeef/advice").status_code == 404

    def test_a_finished_draft_has_nothing_to_advise(self, mock_client):
        session = mock_client.post("/api/sessions", json={"your_slot": 1, "seed": 3}).json()
        before = mock_client.get(f"/api/sessions/{session['id']}/advice").json()["advice"]

        mock_client.post(f"/api/sessions/{session['id']}/simulate")
        after = mock_client.get(f"/api/sessions/{session['id']}/advice").json()["advice"]

        assert before and after == []
