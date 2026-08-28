"""Draft-night market templates.

Two jobs, and the second is the one with money on it: open at a price the ADP
model can defend, and resolve from the picks feed without anybody ruling on
anything. The tests that matter are about *not* resolving -- a market called
early is a market paid out wrong.
"""

from __future__ import annotations

import pytest

from app.core.draft_markets import (
    CEILING,
    FLOOR,
    Board,
    ManagerFirstPick,
    PlayerByPick,
    PositionInRound,
    TemplateError,
    build,
    template,
)
from app.integrations.sleeper import SleeperPick


def pick(no, name, position="RB", slot=None, is_keeper=False, teams=12):
    return SleeperPick(
        pick_no=no,
        round=(no - 1) // teams + 1,
        draft_slot=slot if slot is not None else (no - 1) % teams + 1,
        player_id=str(no),
        name=name,
        position=position,
        team="DET",
        is_keeper=is_keeper,
    )


def board(picks=(), teams=12, rounds=15):
    return Board(picks=list(picks), teams=teams, rounds=rounds)


@pytest.fixture
def top(pool_2025):
    """The consensus 1.01, whose ADP is about as low as they come."""
    return pool_2025.players[0]


@pytest.fixture
def mid(pool_2025):
    return pool_2025.players[40]


class TestTheBoard:
    def test_an_empty_board_has_reached_nothing(self):
        assert board().made == 0
        assert not board().complete

    def test_it_tracks_the_furthest_pick(self):
        assert board([pick(1, "A"), pick(7, "B")]).made == 7

    def test_a_round_is_done_when_its_last_pick_lands(self):
        assert not board([pick(11, "A")]).round_done(1)
        assert board([pick(12, "A")]).round_done(1)

    def test_keepers_still_occupy_their_slot(self):
        assert board([pick(6, "Gibbs", is_keeper=True)]).made == 6


class TestPlayerByPickPrices:
    def test_the_top_player_is_near_certain_to_go_early(self, pool_2025, top):
        price = PlayerByPick.opening({"player_key": top.key, "pick": 12}, pool_2025)
        assert price >= 80

    def test_nobody_is_certain_to_go_first_overall(self, pool_2025, top):
        price = PlayerByPick.opening({"player_key": top.key, "pick": 1}, pool_2025)
        assert price < 80

    def test_a_later_pick_is_always_likelier(self, pool_2025, mid):
        run = [
            PlayerByPick.opening({"player_key": mid.key, "pick": n}, pool_2025)
            for n in (12, 24, 36, 60, 100)
        ]
        assert run == sorted(run)

    def test_it_never_opens_at_certainty(self, pool_2025, top):
        """A market at 99c has nothing to argue about and costs the most to run."""
        for n in (1, 2, 200):
            price = PlayerByPick.opening({"player_key": top.key, "pick": n}, pool_2025)
            assert FLOOR <= price <= CEILING

    def test_an_unknown_player_is_refused(self, pool_2025):
        with pytest.raises(TemplateError, match="no player"):
            PlayerByPick.opening({"player_key": "RB:XXX:nobody", "pick": 10}, pool_2025)


class TestPlayerByPickResolves:
    def test_undecided_while_the_draft_is_short_of_the_pick(self, pool_2025, top):
        params = {"player_key": top.key, "pick": 10}
        assert PlayerByPick.resolve(params, board([pick(1, "Someone")]), pool_2025) is None

    def test_yes_the_moment_he_is_taken_in_time(self, pool_2025, top):
        params = {"player_key": top.key, "pick": 10}
        assert PlayerByPick.resolve(params, board([pick(3, top.name)]), pool_2025) is True

    def test_no_once_the_pick_passes_without_him(self, pool_2025, top):
        params = {"player_key": top.key, "pick": 5}
        made = [pick(i, f"Player {i}") for i in range(1, 6)]
        assert PlayerByPick.resolve(params, board(made), pool_2025) is False

    def test_taken_later_than_the_pick_is_still_no(self, pool_2025, top):
        params = {"player_key": top.key, "pick": 5}
        made = [pick(i, f"Player {i}") for i in range(1, 8)] + [pick(9, top.name)]
        assert PlayerByPick.resolve(params, board(made), pool_2025) is False

    def test_a_suffix_does_not_hide_a_pick(self, pool_2025):
        """Sleeper and the ADP feed disagree about Jr. constantly."""
        who = next(p for p in pool_2025.players if p.name.endswith(("Jr.", "Sr.", "III")))
        base = who.name.rsplit(" ", 1)[0]
        params = {"player_key": who.key, "pick": 20}
        assert PlayerByPick.resolve(params, board([pick(2, base)]), pool_2025) is True

    def test_a_keeper_counts_as_having_been_taken(self, pool_2025, top):
        params = {"player_key": top.key, "pick": 10}
        made = board([pick(6, top.name, is_keeper=True)])
        assert PlayerByPick.resolve(params, made, pool_2025) is True


class TestPositionInRound:
    def test_a_quarterback_in_round_one_is_uncertain(self, pool_2025):
        price = PositionInRound.opening({"position": "QB", "round": 1}, pool_2025)
        assert FLOOR <= price <= CEILING

    def test_a_kicker_in_round_one_is_unlikely(self, pool_2025):
        kicker = PositionInRound.opening({"position": "K", "round": 1}, pool_2025)
        runner = PositionInRound.opening({"position": "RB", "round": 1}, pool_2025)
        assert kicker < runner

    def test_running_backs_go_in_round_one(self, pool_2025):
        assert PositionInRound.opening({"position": "RB", "round": 1}, pool_2025) >= 80

    def test_yes_as_soon_as_one_lands(self, pool_2025):
        params = {"position": "QB", "round": 1}
        made = board([pick(3, "A QB", position="QB")])
        assert PositionInRound.resolve(params, made, pool_2025) is True

    def test_undecided_until_the_round_is_out(self, pool_2025):
        params = {"position": "QB", "round": 1}
        made = board([pick(i, f"P{i}", position="RB") for i in range(1, 12)])
        assert PositionInRound.resolve(params, made, pool_2025) is None

    def test_no_once_the_round_completes_without_one(self, pool_2025):
        params = {"position": "QB", "round": 1}
        made = board([pick(i, f"P{i}", position="RB") for i in range(1, 13)])
        assert PositionInRound.resolve(params, made, pool_2025) is False

    def test_a_later_round_is_judged_on_its_own_picks(self, pool_2025):
        params = {"position": "QB", "round": 2}
        made = board([pick(3, "A QB", position="QB")] +
                     [pick(i, f"P{i}", position="RB") for i in range(13, 25)])
        assert PositionInRound.resolve(params, made, pool_2025) is False


class TestManagerFirstPick:
    def test_it_opens_where_it_is_put(self, pool_2025):
        params = {"manager": "BigJedd", "slot": 1, "position": "RB", "opening": 65}
        assert ManagerFirstPick.opening(params, pool_2025) == 65

    def test_it_defaults_to_a_coin_flip(self, pool_2025):
        params = {"manager": "BigJedd", "slot": 1, "position": "RB"}
        assert ManagerFirstPick.opening(params, pool_2025) == 50

    def test_it_reads_that_managers_first_pick(self, pool_2025):
        params = {"manager": "BigJedd", "slot": 1, "position": "RB"}
        made = board([pick(1, "A back", position="RB", slot=1)])
        assert ManagerFirstPick.resolve(params, made, pool_2025) is True

    def test_another_managers_pick_does_not_settle_it(self, pool_2025):
        params = {"manager": "BigJedd", "slot": 1, "position": "RB"}
        made = board([pick(2, "A back", position="RB", slot=2)])
        assert ManagerFirstPick.resolve(params, made, pool_2025) is None

    def test_a_keeper_does_not_count_as_their_first_pick(self, pool_2025):
        """It was decided in August, and would settle six markets before they open."""
        params = {"manager": "CommishSchaffer", "slot": 6, "position": "RB"}
        made = board([pick(6, "Jahmyr Gibbs", position="RB", slot=6, is_keeper=True)])
        assert ManagerFirstPick.resolve(params, made, pool_2025) is None

    def test_the_pick_after_a_keeper_is_what_settles_it(self, pool_2025):
        params = {"manager": "CommishSchaffer", "slot": 6, "position": "WR"}
        made = board([
            pick(6, "Jahmyr Gibbs", position="RB", slot=6, is_keeper=True),
            pick(19, "A receiver", position="WR", slot=6),
        ])
        assert ManagerFirstPick.resolve(params, made, pool_2025) is True


class TestBuildingAMarket:
    def test_it_returns_a_question_and_a_price(self, pool_2025, mid):
        made = build("player_by_pick", {"player_key": mid.key, "pick": 30},
                     pool_2025, board())
        assert mid.name in made["question"]
        assert "pick 30" in made["question"]
        assert FLOOR <= made["opening"] <= CEILING

    def test_it_refuses_a_market_the_board_already_answered(self, pool_2025, top):
        """Selling contracts on a coin that has landed."""
        made = board([pick(2, top.name)])
        with pytest.raises(TemplateError, match="already decided"):
            build("player_by_pick", {"player_key": top.key, "pick": 10}, pool_2025, made)

    def test_it_refuses_one_the_board_has_already_ruled_out(self, pool_2025, top):
        made = board([pick(i, f"P{i}") for i in range(1, 13)])
        with pytest.raises(TemplateError, match="already decided"):
            build("player_by_pick", {"player_key": top.key, "pick": 5}, pool_2025, made)

    def test_an_unknown_kind_is_refused(self, pool_2025):
        with pytest.raises(TemplateError, match="unknown market type"):
            template("will_it_rain")

    def test_every_template_is_reachable_by_key(self):
        for kind in (PlayerByPick, PositionInRound, ManagerFirstPick):
            assert template(kind.key) is kind


class TestRoundMarketsAreCalibrated:
    """The per-player curves are over-subscribed late and must be normalized.

    Raw, they expect 26 players to go in round 13 where twelve picks exist,
    because late ADP spreads are wide and nothing ties them to the slots
    available. Every late-round market then opens too high and the house
    carries the difference, so these pin the shape rather than the numbers.
    """

    def test_round_one_is_backs_and_receivers(self, pool_2025):
        for pos in ("RB", "WR"):
            assert PositionInRound.opening({"position": pos, "round": 1}, pool_2025) >= 80
        for pos in ("QB", "TE", "K", "DST"):
            assert PositionInRound.opening({"position": pos, "round": 1}, pool_2025) <= 25

    def test_nobody_drafts_a_kicker_in_the_first_round(self, pool_2025):
        early = PositionInRound.opening({"position": "K", "round": 1}, pool_2025)
        late = PositionInRound.opening({"position": "K", "round": 13}, pool_2025)
        assert early <= 15 < late

    def test_the_kicker_run_arrives_gradually(self, pool_2025):
        run = [
            PositionInRound.opening({"position": "K", "round": r}, pool_2025)
            for r in (9, 10, 11, 12, 13)
        ]
        assert run == sorted(run), "it should climb, not switch on"
        assert run[0] < run[-1]

    def test_quarterbacks_are_a_middle_round_question(self, pool_2025):
        first = PositionInRound.opening({"position": "QB", "round": 1}, pool_2025)
        middle = PositionInRound.opening({"position": "QB", "round": 5}, pool_2025)
        assert first < middle

    def test_a_round_beyond_the_board_is_not_a_certainty(self, pool_2025):
        """Nothing is ranked out there, so the model must not claim to know."""
        assert PositionInRound.opening({"position": "K", "round": 40}, pool_2025) <= CEILING

    def test_the_league_size_changes_the_window(self, pool_2025):
        """Round 5 of an eight-team league is a different set of picks."""
        twelve = PositionInRound.opening({"position": "QB", "round": 5}, pool_2025)
        eight = PositionInRound.opening(
            {"position": "QB", "round": 5, "teams": 8}, pool_2025
        )
        assert twelve != eight
