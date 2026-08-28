"""Bot behaviour.

The headline requirement is that two mock drafts must not come out identical --
that is the whole reason to run one. These tests pin that down, and also pin the
opposite: with randomness disabled, behaviour must be exactly reproducible.
"""

from __future__ import annotations

import pytest

from app.core import bots
from app.core.engine import LoggedPick, replay
from app.core.models import DraftConfig


@pytest.fixture
def config():
    return DraftConfig(year=2025, teams=12, rounds=15, your_slot=6)


def run_draft(config, pool, seed: int, randomness: float = 1.0) -> list[str]:
    """Simulate a whole draft with bots in every seat."""
    log: list[LoggedPick] = []
    state = replay(config, pool, log)
    while not state.complete:
        cell = state.current
        rng = bots.rng_for(seed, cell.overall)
        choice = bots.choose(state, pool, cell.team_slot, rng, randomness)
        if choice is None:
            break
        log = log + [LoggedPick(choice.key, "bot")]
        state = replay(config, pool, log)
    return [p.player_name for p in state.picks]


class TestVariety:
    def test_two_seeds_produce_different_drafts(self, config, pool_2025):
        a = run_draft(config, pool_2025, seed=1)
        b = run_draft(config, pool_2025, seed=2)
        assert a != b, "different seeds must not produce identical drafts"

    def test_the_difference_is_substantial(self, config, pool_2025):
        a = run_draft(config, pool_2025, seed=1)
        b = run_draft(config, pool_2025, seed=2)
        differing = sum(1 for x, y in zip(a, b) if x != y)
        # The CLI tool's behaviour would score 0 here.
        assert differing > 20, f"only {differing} of {len(a)} picks differed"

    def test_first_overall_can_vary_across_seeds(self, config, pool_2025):
        firsts = {run_draft(config, pool_2025, seed=s)[0] for s in range(12)}
        assert len(firsts) > 1, "the 1.01 pick was identical across every seed"


class TestDeterminism:
    def test_same_seed_reproduces_the_draft(self, config, pool_2025):
        assert run_draft(config, pool_2025, seed=7) == run_draft(config, pool_2025, seed=7)

    def test_zero_randomness_is_pure_adp_order(self, config, pool_2025):
        picks = run_draft(config, pool_2025, seed=99, randomness=0.0)
        top = [p.name for p in pool_2025.players[:5]]
        assert picks[:5] == top

    def test_zero_randomness_ignores_the_seed(self, config, pool_2025):
        a = run_draft(config, pool_2025, seed=1, randomness=0.0)
        b = run_draft(config, pool_2025, seed=2, randomness=0.0)
        assert a == b


class TestSanity:
    def test_a_full_draft_has_no_duplicates(self, config, pool_2025):
        picks = run_draft(config, pool_2025, seed=3)
        assert len(picks) == len(set(picks))

    def test_a_full_draft_fills_the_board(self, config, pool_2025):
        picks = run_draft(config, pool_2025, seed=3)
        assert len(picks) == config.teams * config.rounds

    def test_position_limits_are_respected(self, config, pool_2025):
        log: list[LoggedPick] = []
        state = replay(config, pool_2025, log)
        while not state.complete:
            cell = state.current
            choice = bots.choose(state, pool_2025, cell.team_slot,
                                 bots.rng_for(5, cell.overall), 1.0)
            log = log + [LoggedPick(choice.key, "bot")]
            state = replay(config, pool_2025, log)

        for slot, team in state.teams.items():
            for position, count in team.position_counts.items():
                limit = config.position_limits[position]
                assert count <= limit, f"slot {slot} has {count} {position}, limit {limit}"

    def test_bots_do_not_reach_absurdly(self, config, pool_2025):
        """Jitter must not let a deep sleeper jump the first round."""
        picks = run_draft(config, pool_2025, seed=11)
        by_name = {p.name: p for p in pool_2025.players}
        first_round_adps = [by_name[n].adp for n in picks[:12] if n in by_name]
        # Everyone taken in round 1 should at least be a top-40 ADP player.
        assert max(first_round_adps) < 40, f"someone reached badly: {max(first_round_adps)}"


class TestPerceivedAdp:
    def test_no_randomness_returns_true_adp(self, pool_2025):
        player = pool_2025.players[0]
        assert bots.perceived_adp(player, bots.rng_for(1, 1), 0.0) == player.adp

    def test_randomness_moves_the_value(self, pool_2025):
        player = pool_2025.players[30]
        seen = {bots.perceived_adp(player, bots.rng_for(s, 1), 1.0) for s in range(8)}
        assert len(seen) > 1
