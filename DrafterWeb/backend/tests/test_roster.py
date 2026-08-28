"""Roster depth: limits must fit both the round count and the player pool."""

from __future__ import annotations

import pytest

from app.core.models import ConfigError
from app.core.roster import auto_limits, pool_capacity


class TestCapacity:
    def test_capacity_divides_the_pool_by_team_count(self, pool_2025):
        capacity = pool_capacity(pool_2025, 12)
        for position, per_team in capacity.items():
            available = len(pool_2025.by_position(position))
            # Integer division: every team must be able to fill the limit.
            assert per_team * 12 <= available

    def test_more_teams_means_less_depth(self, pool_2025):
        assert sum(pool_capacity(pool_2025, 14).values()) <= sum(
            pool_capacity(pool_2025, 8).values()
        )

    def test_zero_teams_is_rejected(self, pool_2025):
        with pytest.raises(ConfigError):
            pool_capacity(pool_2025, 0)


class TestAutoLimits:
    def test_fifteen_rounds_keeps_the_league_defaults(self, pool_2025):
        limits = auto_limits(pool_2025, 12, 15)
        assert sum(limits.values()) == 15
        assert limits["WR"] == 5 and limits["RB"] == 4

    def test_limits_always_cover_the_rounds(self, pool_2025):
        # Up to whatever this pool actually supports -- the ceiling is a
        # property of the feed, not a constant.
        ceiling = sum(pool_capacity(pool_2025, 12).values())
        for rounds in range(15, ceiling + 1):
            limits = auto_limits(pool_2025, 12, rounds)
            assert sum(limits.values()) >= rounds, f"{rounds} rounds under-allocated"

    def test_growth_never_exceeds_pool_depth(self, pool_2025):
        capacity = pool_capacity(pool_2025, 12)
        limits = auto_limits(pool_2025, 12, sum(capacity.values()))
        for position, limit in limits.items():
            assert limit <= capacity[position], f"{position} over-allocated"

    def test_extra_spots_go_to_skill_positions(self, pool_2025):
        ceiling = sum(pool_capacity(pool_2025, 12).values())
        base = auto_limits(pool_2025, 12, 15)
        deep = auto_limits(pool_2025, 12, ceiling)
        # Nobody carries a third kicker before a seventh receiver.
        assert deep["WR"] > base["WR"]
        assert deep["WR"] - base["WR"] >= deep["K"] - base["K"]

    def test_an_impossible_draft_is_rejected_clearly(self, pool_2025):
        with pytest.raises(ConfigError, match="cannot run"):
            auto_limits(pool_2025, 12, 40)

    def test_the_error_names_the_real_ceiling(self, pool_2025):
        ceiling = sum(pool_capacity(pool_2025, 12).values())
        with pytest.raises(ConfigError, match=f"at most {ceiling}"):
            auto_limits(pool_2025, 12, ceiling + 1)

    def test_exactly_at_the_ceiling_still_works(self, pool_2025):
        ceiling = sum(pool_capacity(pool_2025, 12).values())
        limits = auto_limits(pool_2025, 12, ceiling)
        assert sum(limits.values()) == ceiling

    def test_a_caller_limit_above_pool_depth_is_clamped(self, pool_2025):
        capacity = pool_capacity(pool_2025, 12)
        greedy = {"QB": 99, "RB": 99, "WR": 99, "TE": 99, "K": 99, "DST": 99}
        limits = auto_limits(pool_2025, 12, 15, base=greedy)
        for position, limit in limits.items():
            assert limit <= capacity[position]
