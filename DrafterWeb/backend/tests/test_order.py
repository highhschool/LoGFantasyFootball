from __future__ import annotations

import pytest

from app.core.models import ConfigError, DraftConfig, Keeper
from app.core.order import (
    build_board,
    next_pick_for_slot,
    picks_for_slot,
    picks_until_next,
    snake_order,
)


class TestSnakeOrder:
    def test_odd_rounds_ascend_and_even_rounds_descend(self):
        order = snake_order(teams=4, rounds=4)
        assert order[0] == [1, 2, 3, 4]
        assert order[1] == [4, 3, 2, 1]
        assert order[2] == [1, 2, 3, 4]
        assert order[3] == [4, 3, 2, 1]

    def test_rounds_are_independent_objects(self):
        # A shared list object between rounds would let one round's mutation
        # silently rewrite another's.
        order = snake_order(teams=3, rounds=3)
        order[0][0] = 99
        assert order[2][0] == 1

    def test_every_slot_picks_once_per_round(self):
        for round_slots in snake_order(teams=12, rounds=15):
            assert sorted(round_slots) == list(range(1, 13))

    @pytest.mark.parametrize("teams,rounds", [(0, 5), (12, 0), (-1, 3)])
    def test_rejects_nonsense_dimensions(self, teams, rounds):
        with pytest.raises(ConfigError):
            snake_order(teams, rounds)


class TestBoard:
    def test_ngfl_board_is_180_picks(self):
        board = build_board(DraftConfig(year=2026))
        assert len(board) == 180
        assert board[0].overall == 1
        assert board[-1].overall == 180

    def test_turn_at_the_snake(self):
        board = build_board(DraftConfig(year=2026, teams=12, rounds=15))
        # Pick 12 ends round 1 and pick 13 opens round 2, both for slot 12.
        assert (board[11].team_slot, board[11].round) == (12, 1)
        assert (board[12].team_slot, board[12].round) == (12, 2)

    def test_overall_numbering_is_dense_and_ordered(self):
        board = build_board(DraftConfig(year=2026, teams=8, rounds=6))
        assert [cell.overall for cell in board] == list(range(1, 49))

    def test_pick_in_round_resets_each_round(self):
        board = build_board(DraftConfig(year=2026, teams=4, rounds=3, your_slot=1))
        assert [c.pick_in_round for c in board] == [1, 2, 3, 4] * 3

    def test_no_keepers_means_no_keeper_cells(self):
        board = build_board(DraftConfig(year=2026))
        assert all(cell.keeper is None for cell in board)
        assert not any(cell.is_keeper for cell in board)


class TestPickWindows:
    def test_slot_gets_one_pick_per_round(self):
        config = DraftConfig(year=2026, teams=12, rounds=15, your_slot=6)
        assert len(picks_for_slot(config, 6)) == 15

    def test_turn_gives_back_to_back_picks(self):
        config = DraftConfig(year=2026, teams=12, rounds=15)
        assert picks_for_slot(config, 12)[:2] == [12, 13]

    def test_wait_is_longest_at_the_turn(self):
        config = DraftConfig(year=2026, teams=12, rounds=15)
        # Slot 1 picks at 1, then last in round 2 at 24: 23 picks of exposure,
        # which is the gap the advisor scores survival probability against.
        assert picks_until_next(config, 1, after=1) == 23
        # Slot 12 turns the corner and picks back to back.
        assert picks_until_next(config, 12, after=12) == 1

    def test_next_pick_is_none_after_the_last_one(self):
        config = DraftConfig(year=2026, teams=12, rounds=15)
        assert next_pick_for_slot(config, 6, after=180) is None


class TestKeepersAreOptional:
    def test_default_config_has_none(self):
        assert DraftConfig(year=2026).keepers == ()

    def test_keeper_fills_the_right_cell(self):
        config = DraftConfig(
            year=2026,
            keepers=(Keeper(team_slot=3, round=4, player_name="Ja'Marr Chase"),),
        )
        board = build_board(config)
        kept = [cell for cell in board if cell.is_keeper]
        assert len(kept) == 1
        assert (kept[0].team_slot, kept[0].round) == (3, 4)
        assert kept[0].keeper == "Ja'Marr Chase"

    def test_keepers_do_not_change_board_shape(self):
        plain = build_board(DraftConfig(year=2026))
        kept = build_board(
            DraftConfig(year=2026, keepers=(Keeper(2, 5, "Bijan Robinson"),))
        )
        assert len(plain) == len(kept)
        assert [c.overall for c in plain] == [c.overall for c in kept]
        assert [c.team_slot for c in plain] == [c.team_slot for c in kept]

    def test_two_keepers_in_one_cell_is_rejected(self):
        config = DraftConfig(
            year=2026,
            keepers=(Keeper(3, 4, "Player A"), Keeper(3, 4, "Player B")),
        )
        with pytest.raises(ConfigError, match="slot 3 in round 4"):
            build_board(config)

    def test_same_player_kept_twice_is_rejected(self):
        config = DraftConfig(
            year=2026,
            keepers=(Keeper(3, 4, "Ja'Marr Chase"), Keeper(7, 2, "Ja'Marr Chase")),
        )
        with pytest.raises(ConfigError, match="more than one team"):
            build_board(config)

    @pytest.mark.parametrize(
        "keeper", [Keeper(0, 1, "X"), Keeper(13, 1, "X"), Keeper(1, 0, "X"), Keeper(1, 16, "X")]
    )
    def test_out_of_range_keeper_is_rejected(self, keeper):
        with pytest.raises(ConfigError):
            build_board(DraftConfig(year=2026, keepers=(keeper,)))

    def test_unknown_keeper_name_is_not_a_config_error(self):
        # Names are resolved against the pool separately and warn rather than
        # raise, so a typo cannot take down a session.
        board = build_board(
            DraftConfig(year=2026, keepers=(Keeper(1, 1, "Definitely Not A Player"),))
        )
        assert board[0].keeper == "Definitely Not A Player"


class TestConfigValidation:
    def test_slot_outside_the_league_is_rejected(self):
        with pytest.raises(ConfigError, match="your_slot"):
            build_board(DraftConfig(year=2026, teams=12, your_slot=13))

    def test_position_limits_must_cover_the_rounds(self):
        # 15 rounds against limits summing to 15 is exactly enough; 16 is not.
        with pytest.raises(ConfigError, match="could never be filled"):
            build_board(DraftConfig(year=2026, rounds=16))
