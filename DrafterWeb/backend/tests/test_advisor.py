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
    def test_only_the_leading_position_offers_two_names(self, state, pool_2025):
        """Five names from two positions is two decisions dressed as five.

        The position that actually matters gets a runner-up; everything below
        it offers one, so the list stays a choice between positions.
        """
        positions = [a.player.position for a in recommend(state, pool_2025, limit=8)]
        counts = {p: positions.count(p) for p in set(positions)}

        assert counts[positions[0]] == 2, "the leading position offers an alternative"
        assert all(n == 1 for p, n in counts.items() if p != positions[0])
        assert positions[:2] == [positions[0], positions[0]], "its two sit together"

    def test_each_position_leads_with_its_best_available(self, state, pool_2025):
        advice = recommend(state, pool_2025, limit=8)
        seen: set[str] = set()
        for a in advice:
            position = a.player.position
            if position in seen:
                continue  # the runner-up at the leading position
            seen.add(position)
            assert a.player.key == at_position(pool_2025, position)[0].key

    def test_the_runner_up_is_the_second_best_at_his_position(self, state, pool_2025):
        advice = recommend(state, pool_2025, limit=8)
        leader, runner_up = advice[0], advice[1]
        assert runner_up.player.position == leader.player.position
        assert runner_up.player.key == at_position(pool_2025, leader.player.position)[1].key

    def test_the_runner_up_does_not_repeat_the_leader_reasoning(self, state, pool_2025):
        """"only 1 TE left at this level" cannot be true of the second one."""
        runner_up = recommend(state, pool_2025, limit=8)[1]
        assert any("the next" in r for r in runner_up.reasons)
        assert not any("at this level" in r for r in runner_up.reasons)
        assert not any(r.startswith("Next probable pick:") for r in runner_up.reasons)

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

    def test_a_filled_position_is_still_offered(self, pool_2025):
        """Limits guide the advice rather than censoring the board.

        A chalk board is used rather than a hand-built one: draining a single
        position to fill it leaves every other position artificially flat, and
        the advice then reflects the fixture rather than the rule under test.
        """
        # One receiver slot, so slot 1's opening pick fills it outright.
        config = DraftConfig(
            year=2025, teams=12, rounds=15, your_slot=1,
            position_limits={"WR": 1, "RB": 5, "QB": 3, "TE": 3, "K": 1, "DST": 2},
        )
        assert pool_2025.players[0].position == "WR", "fixture no longer opens with a WR"

        chalk = [LoggedPick(p.key) for p in pool_2025.players[:23]]
        state = replay(config, pool_2025, chalk)

        assert state.team(1).needs(config.position_limits)["WR"] == 0
        assert state.current.team_slot == 1, "should be back on slot 1's clock"

        positions = [a.player.position for a in recommend(state, pool_2025, limit=8)]
        assert "WR" in positions, "a filled position must still be offered"
        assert positions[0] != "WR", "but it should not lead over a position you need"

    def test_an_overfilled_position_says_so(self, pool_2025):
        config = DraftConfig(
            year=2025, teams=2, rounds=2, your_slot=1,
            position_limits={"QB": 0, "RB": 2, "WR": 0, "TE": 0, "K": 0, "DST": 0},
        )
        state = replay(config, pool_2025, [])
        qb = next(
            (a for a in recommend(state, pool_2025, limit=8) if a.player.position == "QB"),
            None,
        )
        assert qb is not None
        assert any("already filled" in r for r in qb.reasons)

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

        advice = recommend(state, pool_2025, limit=8)
        # Skip the runner-up, which describes itself rather than its position.
        leaders, seen = [], set()
        for a in advice:
            if a.player.position not in seen:
                seen.add(a.player.position)
                leaders.append(a)

        steep = [a for a in leaders if a.dropoff >= 3]
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


class TestOverfilledPositions:
    """Going past your plan should sink a position further each time."""

    @staticmethod
    def _with_quarterbacks(pool, config, count):
        qbs = [p for p in pool.players if p.position == "QB"][:count]
        others = iter(p for p in pool.players if p.position != "QB")
        mine = {1, 24, 25, 48, 49, 72, 73}
        log, taken = [], 0
        for overall in range(1, 74):
            if overall in mine and taken < count:
                log.append(LoggedPick(qbs[taken].key))
                taken += 1
            else:
                log.append(LoggedPick(next(others).key))
        return replay(config, pool, log)

    def test_a_fourth_quarterback_ranks_below_a_third(self, config, pool_2025):
        def qb_rank(count):
            state = self._with_quarterbacks(pool_2025, config, count)
            advice = recommend(state, pool_2025, limit=8)
            return next(
                (i for i, a in enumerate(advice) if a.player.position == "QB"), 99
            )

        assert qb_rank(4) >= qb_rank(2), "going further over must not help"

    def test_it_says_how_far_over_you_are(self, config, pool_2025):
        state = self._with_quarterbacks(pool_2025, config, 4)
        assert state.team(1).needs(config.position_limits)["QB"] == -2

        qb = next(
            (a for a in recommend(state, pool_2025, limit=8) if a.player.position == "QB"),
            None,
        )
        assert qb is not None, "still offered -- the limits are a suggestion"
        assert qb.need == -2, "the real figure, not clamped to zero"
        assert any("2 over your plan" in r for r in qb.reasons)

    def test_positions_you_need_still_lead(self, config, pool_2025):
        state = self._with_quarterbacks(pool_2025, config, 4)
        advice = recommend(state, pool_2025, limit=8)
        assert advice[0].player.position != "QB"
        assert advice[0].need > 0


class TestStartersBeatBench:
    """The change that mattered most: a first back and a fifth are not alike."""

    @staticmethod
    def _roster(pool, config, positions):
        """Give slot 1 exactly these positions, and stop there.

        Running past slot 1's nth pick fills its later cells too, which is how
        an earlier version of this helper handed it nine players while claiming
        three.
        """
        from app.core.order import picks_for_slot

        mine = picks_for_slot(config, 1)[: len(positions)]
        available = {p: [q for q in pool.players if q.position == p] for p in set(positions)}

        chosen, taken = [], 0
        for position in positions:
            chosen.append(available[position].pop(0))
        spare = iter(p for p in pool.players if p not in chosen)

        log = []
        for overall in range(1, mine[-1] + 1):
            if overall in mine:
                log.append(LoggedPick(chosen[taken].key))
                taken += 1
            else:
                log.append(LoggedPick(next(spare).key))
        return replay(config, pool, log)

    def test_an_empty_starting_slot_is_named(self, config, pool_2025):
        state = replay(config, pool_2025, [])
        advice = recommend(state, pool_2025, limit=8)
        assert all(a.slot == "starter" for a in advice), "nothing is filled yet"
        assert any("empty starting" in r for a in advice for r in a.reasons)

    def test_starting_slots_count_down(self, config, pool_2025):
        state = replay(config, pool_2025, [])
        assert recommend(state, pool_2025, limit=1)[0].starters_left == 10

        after = self._roster(pool_2025, config, ["QB", "RB", "WR"])
        assert recommend(after, pool_2025, limit=1)[0].starters_left == 7

    def test_a_backup_quarterback_is_bench_not_a_starter(self, config, pool_2025):
        state = self._roster(pool_2025, config, ["QB", "RB", "WR"])
        qb = next(
            (a for a in recommend(state, pool_2025, limit=8) if a.player.position == "QB"),
            None,
        )
        if qb is None:
            pytest.skip("QB not offered at this board state")
        assert qb.slot == "bench"
        assert any("bench depth" in r for r in qb.reasons)

    def test_a_third_back_takes_the_flex(self, config, pool_2025):
        state = self._roster(pool_2025, config, ["RB", "RB"])
        rb = next(
            (a for a in recommend(state, pool_2025, limit=8) if a.player.position == "RB"),
            None,
        )
        if rb is None:
            pytest.skip("RB not offered at this board state")
        assert rb.slot == "flex"
        assert any("flex" in r for r in rb.reasons)

    def test_a_starter_outranks_bench_depth_at_a_steeper_position(self, config, pool_2025):
        """The whole point: filling the lineup beats hoarding one position."""
        state = self._roster(pool_2025, config, ["QB", "QB", "QB"])
        advice = recommend(state, pool_2025, limit=8)

        assert advice[0].slot in {"starter", "flex"}
        assert advice[0].player.position != "QB"

    def test_the_lineup_comes_from_the_config(self, pool_2025):
        # A league starting two quarterbacks values the second one.
        two_qb = DraftConfig(
            year=2025, teams=12, rounds=15, your_slot=1,
            lineup_slots=(
                ("slots_qb", 2), ("slots_rb", 2), ("slots_wr", 2), ("slots_te", 1),
                ("slots_flex", 1), ("slots_k", 1), ("slots_def", 1), ("slots_bn", 5),
            ),
        )
        assert two_qb.lineup.starters["QB"] == 2
        assert two_qb.lineup.starting_spots == 10
