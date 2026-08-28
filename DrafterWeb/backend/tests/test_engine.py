from __future__ import annotations

import pytest

from app.core.engine import DraftError, LoggedPick, append_pick, replay, undo
from app.core.models import DraftConfig, Keeper


@pytest.fixture
def config():
    return DraftConfig(year=2025, teams=12, rounds=15, your_slot=6)


def key_of(pool, name):
    player = pool.find(name)
    assert player is not None, f"{name} not in the fixture pool"
    return player.key


class TestReplayIsDerivation:
    def test_empty_log_gives_an_empty_draft(self, config, pool_2025):
        state = replay(config, pool_2025, [])
        assert state.picks == []
        assert state.current.overall == 1
        assert not state.complete
        assert len(state.teams) == 12

    def test_state_is_a_pure_function_of_the_log(self, config, pool_2025):
        log = [LoggedPick(key_of(pool_2025, n)) for n in
               ("Ja'Marr Chase", "Bijan Robinson", "Saquon Barkley")]
        first = replay(config, pool_2025, log)
        second = replay(config, pool_2025, log)
        assert [p.player_name for p in first.picks] == [p.player_name for p in second.picks]
        assert first.drafted == second.drafted

    def test_picks_land_on_the_right_cells(self, config, pool_2025):
        log = [LoggedPick(key_of(pool_2025, n)) for n in ("Ja'Marr Chase", "Bijan Robinson")]
        state = replay(config, pool_2025, log)
        assert (state.picks[0].overall, state.picks[0].team_slot) == (1, 1)
        assert (state.picks[1].overall, state.picks[1].team_slot) == (2, 2)
        assert state.current.overall == 3

    def test_roster_counts_track_picks(self, config, pool_2025):
        # Slot 1 picks at overall 1; slot 12 at 12 and 13.
        names = ["Ja'Marr Chase"] + [f"_{i}" for i in range(0)]
        log = [LoggedPick(key_of(pool_2025, names[0]))]
        state = replay(config, pool_2025, log)
        assert state.team(1).position_counts["WR"] == 1
        assert state.team(2).position_counts.get("WR", 0) == 0


class TestUndo:
    def test_undo_removes_exactly_one_pick(self, config, pool_2025):
        log = [LoggedPick(key_of(pool_2025, n)) for n in ("Ja'Marr Chase", "Bijan Robinson")]
        state = replay(config, pool_2025, undo(log))
        assert len(state.picks) == 1
        assert state.current.overall == 2

    def test_undo_frees_the_player_again(self, config, pool_2025):
        chase = key_of(pool_2025, "Ja'Marr Chase")
        state = replay(config, pool_2025, undo([LoggedPick(chase)]))
        assert chase not in state.drafted
        assert any(p.key == chase for p in state.available(pool_2025))

    def test_undo_on_an_empty_log_is_harmless(self):
        assert undo([]) == []


class TestLegality:
    def test_cannot_draft_the_same_player_twice(self, config, pool_2025):
        chase = key_of(pool_2025, "Ja'Marr Chase")
        with pytest.raises(DraftError, match="already drafted"):
            append_pick(config, pool_2025, [LoggedPick(chase)], chase)

    def test_cannot_exceed_a_position_limit(self, pool_2025):
        # One team, one round each -- easiest way to fill a position.
        config = DraftConfig(
            year=2025, teams=1, rounds=3, your_slot=1,
            position_limits={"QB": 1, "RB": 1, "WR": 1, "TE": 1, "K": 0, "DST": 0},
        )
        qbs = [p for p in pool_2025.by_position("QB")][:2]
        log = [LoggedPick(qbs[0].key)]
        with pytest.raises(DraftError, match="roster is full at QB"):
            append_pick(config, pool_2025, log, qbs[1].key)

    def test_unknown_player_is_rejected(self, config, pool_2025):
        with pytest.raises(DraftError, match="cannot draft"):
            append_pick(config, pool_2025, [], "QB:XXX:nobody at all")

    def test_cannot_pick_past_the_end(self, pool_2025):
        config = DraftConfig(
            year=2025, teams=1, rounds=1, your_slot=1,
            position_limits={"QB": 1, "RB": 1, "WR": 1, "TE": 1, "K": 1, "DST": 1},
        )
        first = pool_2025.players[0]
        log = [LoggedPick(first.key)]
        with pytest.raises(DraftError, match="already complete"):
            append_pick(config, pool_2025, log, pool_2025.players[1].key)


class TestKeepersInReplay:
    def test_keeper_fills_its_cell_without_a_log_entry(self, pool_2025):
        config = DraftConfig(
            year=2025, teams=12, rounds=15, your_slot=6,
            keepers=(Keeper(team_slot=1, round=1, player_name="Ja'Marr Chase"),),
        )
        state = replay(config, pool_2025, [])
        assert len(state.picks) == 1
        assert state.picks[0].source == "keeper"
        assert state.picks[0].player_name == "Ja'Marr Chase"
        # The keeper consumed no log entry, so pick 2 is next.
        assert state.current.overall == 2

    def test_keeper_is_unavailable_to_everyone_else(self, pool_2025):
        config = DraftConfig(
            year=2025, teams=12, rounds=15, your_slot=6,
            keepers=(Keeper(team_slot=3, round=2, player_name="Bijan Robinson"),),
        )
        state = replay(config, pool_2025, [])
        bijan = key_of(pool_2025, "Bijan Robinson")
        assert bijan in state.drafted

    def test_unresolvable_keeper_warns_instead_of_raising(self, pool_2025):
        config = DraftConfig(
            year=2025, teams=12, rounds=15, your_slot=6,
            keepers=(Keeper(team_slot=1, round=1, player_name="Nobody McFake"),),
        )
        state = replay(config, pool_2025, [])
        assert state.unresolved_keepers == ["Nobody McFake"]
        assert state.picks == []

    def test_a_later_round_keeper_cannot_be_drafted_early(self, pool_2025):
        """The bug this test caught: a round-5 keeper must be off the board in
        round 1, not merely when their own cell comes up."""
        config = DraftConfig(
            year=2025, teams=12, rounds=15, your_slot=6,
            keepers=(Keeper(team_slot=3, round=5, player_name="Bijan Robinson"),),
        )
        state = replay(config, pool_2025, [])
        bijan = key_of(pool_2025, "Bijan Robinson")

        assert bijan in state.drafted
        assert bijan not in {p.key for p in state.available(pool_2025)}
        ok, reason = state.can_draft(pool_2025, 1, bijan)
        assert not ok and reason == "kept by another team"

    def test_keeper_counts_against_the_keeping_team_limits(self, pool_2025):
        config = DraftConfig(
            year=2025, teams=12, rounds=15, your_slot=6,
            keepers=(Keeper(team_slot=3, round=5, player_name="Bijan Robinson"),),
        )
        state = replay(config, pool_2025, [])
        assert state.team(3).position_counts["RB"] == 1
        assert state.team(4).position_counts.get("RB", 0) == 0

    def test_keeper_is_not_double_counted_when_its_cell_arrives(self, pool_2025):
        config = DraftConfig(
            year=2025, teams=2, rounds=2, your_slot=1,
            position_limits={"QB": 1, "RB": 1, "WR": 1, "TE": 1, "K": 0, "DST": 0},
            keepers=(Keeper(team_slot=1, round=1, player_name="Bijan Robinson"),),
        )
        state = replay(config, pool_2025, [])
        assert state.team(1).position_counts["RB"] == 1

    def test_no_keepers_is_the_normal_path(self, config, pool_2025):
        state = replay(config, pool_2025, [])
        assert state.unresolved_keepers == []
        assert all(p.source != "keeper" for p in state.picks)


class TestRosterInsight:
    def test_needs_count_down(self, config, pool_2025):
        state = replay(config, pool_2025, [LoggedPick(key_of(pool_2025, "Ja'Marr Chase"))])
        needs = state.team(1).needs(config.position_limits)
        assert needs["WR"] == config.position_limits["WR"] - 1
        assert needs["RB"] == config.position_limits["RB"]

    def test_bye_clash_detection(self, config, pool_2025):
        state = replay(config, pool_2025, [])
        team = state.team(1)
        assert team.bye_clashes() == {}

    def test_eligible_excludes_full_positions(self, pool_2025):
        config = DraftConfig(
            year=2025, teams=1, rounds=1, your_slot=1,
            position_limits={"QB": 1, "RB": 0, "WR": 0, "TE": 0, "K": 0, "DST": 0},
        )
        state = replay(config, pool_2025, [])
        eligible = state.eligible(pool_2025, 1)
        assert eligible, "expected at least one QB"
        assert {p.position for p in eligible} == {"QB"}
