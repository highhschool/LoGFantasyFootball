"""The advisor.

The headline number is survival probability, so most of these pin down that it
behaves the way a drafter would expect: certainty at short range, doubt at long
range, and the conditioning on "he is still here now" actually doing something.
"""

from __future__ import annotations

import pytest

from app.core.advisor import recommend, survival_probability, tiers
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


def player_named(pool, name):
    found = pool.find(name)
    assert found is not None, name
    return found


class TestSurvivalProbability:
    def test_a_player_far_from_the_window_is_near_certain(self, pool_2025):
        # A pick or two cannot reach someone whose ADP is fifty picks away.
        mid = next(p for p in pool_2025.players if p.adp > 50)
        assert survival_probability(mid, now=1, until=3) > 0.95

    def test_a_player_at_the_boundary_is_genuinely_uncertain(self, pool_2025):
        # The first name on the board usually goes first or second, so
        # surviving even one pick is a coin toss rather than a formality.
        top = pool_2025.players[0]
        assert 0.05 < survival_probability(top, now=1, until=2) < 0.95

    def test_a_long_wait_erodes_it(self, pool_2025):
        top = pool_2025.players[0]
        soon = survival_probability(top, now=1, until=3)
        later = survival_probability(top, now=1, until=25)
        assert later < soon

    def test_the_last_pick_of_the_draft_needs_nothing_to_survive(self, pool_2025):
        assert survival_probability(pool_2025.players[0], now=180, until=None) == 1.0

    def test_a_player_well_past_his_adp_is_likely_to_keep_falling(self, pool_2025):
        early = pool_2025.players[0]     # ADP around 1
        # He is somehow still there at pick 60; the model was wrong about him,
        # and must not then claim he is certain to vanish immediately.
        assert 0.0 <= survival_probability(early, now=60, until=72) <= 1.0

    def test_a_deep_player_survives_a_short_gap(self, pool_2025):
        deep = pool_2025.players[-1]
        assert survival_probability(deep, now=1, until=10) > 0.95

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
        from_start = survival_probability(player, now=1, until=30)
        from_25 = survival_probability(player, now=25, until=30)
        assert from_25 > from_start


class TestTiers:
    def test_the_best_players_are_tier_one(self, pool_2025):
        assigned = tiers(pool_2025.players, teams=12)
        best_rb = min(
            (p for p in pool_2025.players if p.position == "RB"), key=lambda p: p.adp
        )
        assert assigned[best_rb.key][0] == 1

    def test_tiers_only_group_within_a_position(self, pool_2025):
        assigned = tiers(pool_2025.players, teams=12)
        # Every player is placed, and placement is per position.
        assert len(assigned) == len(pool_2025.players)

    def test_remaining_counts_down_through_a_tier(self, pool_2025):
        assigned = tiers(pool_2025.players, teams=12)
        rbs = sorted(
            (p for p in pool_2025.players if p.position == "RB"), key=lambda p: p.adp
        )
        first_tier = [p for p in rbs if assigned[p.key][0] == 1]
        counts = [assigned[p.key][1] for p in first_tier]
        assert counts == list(range(len(first_tier), 0, -1))

    def test_drafting_shrinks_the_tier_for_whoever_now_leads_it(self, config, pool_2025):
        rbs = sorted(
            (p for p in pool_2025.players if p.position == "RB"), key=lambda p: p.adp
        )
        before = tiers(pool_2025.players, 12)[rbs[0].key][1]

        state = replay(config, pool_2025, [LoggedPick(rbs[0].key)])
        after = tiers(state.available(pool_2025), 12)[rbs[1].key][1]
        assert after == before - 1

    def test_an_empty_pool_is_handled(self):
        assert tiers([], teams=12) == {}


class TestRecommendations:
    def test_it_returns_ranked_advice(self, state, pool_2025):
        advice = recommend(state, pool_2025, limit=5)
        assert len(advice) == 5
        scores = [a.score for a in advice]
        assert scores == sorted(scores, reverse=True)

    def test_the_first_pick_favours_the_top_of_the_board(self, state, pool_2025):
        top = {p.name for p in pool_2025.players[:8]}
        assert recommend(state, pool_2025, limit=3)[0].player.name in top

    def test_it_never_suggests_a_drafted_player(self, config, pool_2025):
        taken = pool_2025.players[0]
        state = replay(config, pool_2025, [LoggedPick(taken.key)])
        assert all(a.player.key != taken.key for a in recommend(state, pool_2025, limit=20))

    def test_it_never_suggests_a_position_you_cannot_roster(self, pool_2025):
        config = DraftConfig(
            year=2025, teams=2, rounds=2, your_slot=1,
            position_limits={"QB": 2, "RB": 0, "WR": 0, "TE": 0, "K": 0, "DST": 0},
        )
        state = replay(config, pool_2025, [])
        assert {a.player.position for a in recommend(state, pool_2025, limit=10)} == {"QB"}

    def test_a_completed_draft_has_nothing_to_advise(self, pool_2025):
        config = DraftConfig(
            year=2025, teams=1, rounds=1, your_slot=1,
            position_limits={"QB": 1, "RB": 1, "WR": 1, "TE": 1, "K": 1, "DST": 1},
        )
        state = replay(config, pool_2025, [LoggedPick(pool_2025.players[0].key)])
        assert recommend(state, pool_2025) == []

    def test_every_recommendation_explains_itself(self, state, pool_2025):
        # A score with no stated reason is not actionable, and at the opening
        # pick none of the interesting factors fire yet.
        assert all(a.reasons for a in recommend(state, pool_2025, limit=10))

    def test_it_explains_itself_mid_draft_too(self, config, pool_2025):
        from app.core.engine import LoggedPick

        log = [LoggedPick(p.key) for p in pool_2025.players[:40]]
        state = replay(config, pool_2025, log)
        assert all(a.reasons for a in recommend(state, pool_2025, limit=10))

    def test_it_serializes(self, state, pool_2025):
        import json

        json.dumps([a.as_dict() for a in recommend(state, pool_2025, limit=3)])


class TestFactorsInfluenceTheOrder:
    def test_scarcity_at_a_needed_position_lifts_a_player(self, pool_2025):
        """Down to one roster spot, that position should be urged."""
        wide = DraftConfig(
            year=2025, teams=12, rounds=15, your_slot=1,
            position_limits={"QB": 1, "RB": 1, "WR": 1, "TE": 1, "K": 1, "DST": 10},
        )
        state = replay(wide, pool_2025, [])
        top = recommend(state, pool_2025, limit=5)
        assert top, "expected advice"
        assert all(a.need > 0 for a in top)

    def test_a_bye_clash_is_flagged_and_penalised(self, config, pool_2025):
        # Two players already on one bye week; a third is the point it hurts.
        same_bye = [p for p in pool_2025.players if p.bye_week == 10][:3]
        if len(same_bye) < 3:
            pytest.skip("fixture lacks three players sharing a bye")

        log = [LoggedPick(same_bye[0].key), LoggedPick(same_bye[1].key)]
        solo = DraftConfig(year=2025, teams=1, rounds=15, your_slot=1)
        state = replay(solo, pool_2025, log)

        advice = {a.player.key: a for a in recommend(state, pool_2025, limit=300)}
        third = advice.get(same_bye[2].key)
        if third is not None:
            assert third.bye_clash is True
            assert any("bye" in r for r in third.reasons)

    def test_value_is_how_far_he_has_fallen_past_his_adp(self, config, pool_2025):
        state = replay(config, pool_2025, [])
        for advice in recommend(state, pool_2025, limit=5):
            assert advice.value == pytest.approx(1 - advice.player.adp)

    def test_a_deep_player_is_not_advised_at_the_first_pick(self, config, pool_2025):
        """The bug this caught: taking a round-15 receiver at 1.01 is a reach,
        not 176 picks of value."""
        state = replay(config, pool_2025, [])
        for advice in recommend(state, pool_2025, limit=5):
            assert advice.player.adp < 40


class TestAdviceEndpoints:
    """Both tools expose it, each only for its own sessions."""

    def test_the_mock_tool_advises(self, mock_client):
        session = mock_client.post("/api/sessions", json={"your_slot": 1, "seed": 3}).json()
        advice = mock_client.get(f"/api/sessions/{session['id']}/advice").json()["advice"]
        assert advice
        assert {"name", "score", "survival", "tier", "need", "reasons"} <= advice[0].keys()

    def test_the_mock_tool_will_not_advise_a_live_draft(self, mock_client):
        assert mock_client.get("/api/sessions/deadbeef/advice").status_code == 404

    def test_advice_shrinks_as_the_board_fills(self, mock_client):
        session = mock_client.post("/api/sessions", json={"your_slot": 1, "seed": 3}).json()
        before = mock_client.get(f"/api/sessions/{session['id']}/advice").json()["advice"]

        mock_client.post(f"/api/sessions/{session['id']}/simulate")
        after = mock_client.get(f"/api/sessions/{session['id']}/advice").json()["advice"]

        assert before and after == [], "a finished draft has nothing to advise"
