"""Suggesting markets, and copying a slate's shape.

Ninety markets get built over a season, six every Tuesday. These are about the
shortlist being usable without checking: nothing already on the board, nothing
already answered, and not ten framings of the same player.
"""

from __future__ import annotations

import pytest

from app.core.draft_markets import ARGUABLE, Board, suggest
from app.integrations.sleeper import SleeperPick


def pick(no, name, position="RB", teams=12):
    return SleeperPick(
        pick_no=no, round=(no - 1) // teams + 1, draft_slot=(no - 1) % teams + 1,
        player_id=str(no), name=name, position=position, team="DET",
        is_keeper=False,
    )


@pytest.fixture
def board():
    return Board(picks=[], teams=12, rounds=15)


class TestTheShortlist:
    def test_it_returns_what_was_asked_for(self, pool_2025, board):
        assert len(suggest(pool_2025, board, limit=10)) == 10
        assert len(suggest(pool_2025, board, limit=3)) == 3

    def test_everything_on_it_is_arguable(self, pool_2025, board):
        """A market at 90c has no argument in it, so it is not a suggestion."""
        for made in suggest(pool_2025, board, limit=20):
            assert abs(made["opening"] - 50) <= ARGUABLE, made["question"]

    def test_the_most_even_comes_first(self, pool_2025, board):
        out = suggest(pool_2025, board, limit=12)
        gaps = [abs(m["opening"] - 50) for m in out]
        assert gaps == sorted(gaps)

    def test_it_is_not_ten_versions_of_one_player(self, pool_2025, board):
        """The same player against ten pick numbers is one argument, not ten."""
        out = suggest(pool_2025, board, limit=12)
        assert len({m["subject"] for m in out}) == len(out)

    def test_every_suggestion_carries_what_it_takes_to_open_it(self, pool_2025, board):
        for made in suggest(pool_2025, board, limit=5):
            assert made["kind"] and made["params"]
            assert made["question"] and made["opening"]

    def test_manager_markets_are_left_out(self, pool_2025, board):
        """No model opinion to rank them by, and choosing is the fun part."""
        kinds = {m["kind"] for m in suggest(pool_2025, board, limit=20)}
        assert "manager_first_pick" not in kinds


class TestItDoesNotOfferWhatIsAlreadyThere:
    def test_an_excluded_subject_is_dropped(self, pool_2025, board):
        first = suggest(pool_2025, board, limit=1)[0]
        again = suggest(pool_2025, board, exclude={first["subject"]}, limit=5)
        assert first["subject"] not in {m["subject"] for m in again}

    def test_excluding_a_player_drops_every_pick_of_him(self, pool_2025, board):
        top = pool_2025.players[0]
        out = suggest(pool_2025, board,
                      exclude={f"player:{top.key}"}, limit=20)
        assert all(top.name not in m["question"] for m in out)

    def test_a_whole_slate_can_be_excluded(self, pool_2025, board):
        slate = suggest(pool_2025, board, limit=6)
        fresh = suggest(pool_2025, board,
                        exclude={m["subject"] for m in slate}, limit=6)
        assert not ({m["subject"] for m in slate} & {m["subject"] for m in fresh})


class TestItSkipsWhatTheDraftAnswered:
    def test_a_drafted_player_is_not_suggested_at_an_earlier_pick(self, pool_2025):
        """The same check that refuses to open one."""
        top = pool_2025.players[0]
        running = Board(picks=[pick(2, top.name)], teams=12, rounds=15)
        out = suggest(pool_2025, running, limit=20)
        assert all(top.name not in m["question"] for m in out)

    def test_a_finished_round_stops_being_offered(self, pool_2025):
        made = [pick(i, f"P{i}", position="RB") for i in range(1, 13)]
        running = Board(picks=made, teams=12, rounds=15)
        out = suggest(pool_2025, running, limit=30)
        assert all("round 1?" not in m["question"] for m in out)


class TestCopyingLastWeeksShape:
    def test_the_mix_follows_the_shape(self, pool_2025, board):
        shape = {"player_by_pick": 4, "position_in_round": 2}
        out = suggest(pool_2025, board, shape=shape, limit=6)
        kinds = [m["kind"] for m in out]
        assert kinds.count("player_by_pick") == 4
        assert kinds.count("position_in_round") == 2

    def test_a_shape_it_cannot_fill_tops_up_rather_than_coming_back_short(
        self, pool_2025, board
    ):
        """One market per position, and only four positions are ever arguable.

        Backs and receivers have no round near even -- they go in the first and
        the answer is never in doubt -- so a shape asking for five position
        markets is asking for one that does not exist. Six suggestions with the
        wrong mix beats four with the right one.
        """
        out = suggest(pool_2025, board, shape={"position_in_round": 5}, limit=5)
        assert len(out) == 5
        positional = [m for m in out if m["kind"] == "position_in_round"]
        assert len(positional) == 4, "every one there is"
        assert out[:4] == positional, "and they come first"

    def test_it_tops_up_when_the_shape_is_short(self, pool_2025, board):
        """Six wanted, a shape naming two. The rest come from the shortlist."""
        out = suggest(pool_2025, board, shape={"player_by_pick": 2}, limit=6)
        assert len(out) == 6

    def test_it_is_still_one_per_subject(self, pool_2025, board):
        out = suggest(pool_2025, board,
                      shape={"player_by_pick": 5, "position_in_round": 3},
                      limit=8)
        assert len({m["subject"] for m in out}) == len(out)

    def test_no_shape_is_just_the_shortlist(self, pool_2025, board):
        assert (suggest(pool_2025, board, limit=5)
                == suggest(pool_2025, board, shape=None, limit=5))
