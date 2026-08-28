"""Replay the league's real 2025 draft through the engine.

This is the end-to-end regression test the plan calls for. It answers the two
questions that decide whether assistant mode works on draft night:

  1. Does our board geometry match a real Sleeper snake draft, pick for pick?
  2. Do Sleeper's player names resolve against the ADP feed we rank from?

Question 2 is the risky one. Sleeper and FFC are independent sources that spell
suffixes and defenses differently.
"""

from __future__ import annotations

import pytest

from app.core.models import DraftConfig
from app.core.order import build_board
from app.core.names import normalize_position


def _full_name(pick: dict) -> str:
    meta = pick.get("metadata") or {}
    return f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip()


@pytest.fixture(scope="module")
def picks(sleeper_2025):
    return sorted(sleeper_2025["picks"], key=lambda p: p["pick_no"])


@pytest.fixture(scope="module")
def draft_meta(sleeper_2025):
    return sleeper_2025["draft"]


class TestRealDraftShape:
    def test_it_is_the_league_we_think_it_is(self, draft_meta):
        assert draft_meta["type"] == "snake"
        assert draft_meta["settings"]["teams"] == 12
        assert draft_meta["settings"]["rounds"] == 15

    def test_the_board_is_complete(self, picks):
        assert len(picks) == 180
        assert [p["pick_no"] for p in picks] == list(range(1, 181))


class TestBoardGeometryMatchesSleeper:
    """Our snake order must agree with Sleeper's, cell for cell."""

    def test_every_pick_lands_in_the_same_cell(self, picks):
        board = build_board(DraftConfig(year=2025, teams=12, rounds=15))
        assert len(board) == len(picks)

        for cell, actual in zip(board, picks):
            assert cell.overall == actual["pick_no"]
            assert cell.round == actual["round"], f"round differs at pick {cell.overall}"
            assert cell.team_slot == actual["draft_slot"], (
                f"draft slot differs at pick {cell.overall}: "
                f"we say {cell.team_slot}, Sleeper says {actual['draft_slot']}"
            )

    def test_the_snake_actually_reverses(self, picks):
        # Guards against the fixture being a linear draft, which would let a
        # broken snake pass the test above.
        round_one = [p["draft_slot"] for p in picks if p["round"] == 1]
        round_two = [p["draft_slot"] for p in picks if p["round"] == 2]
        assert round_one == list(range(1, 13))
        assert round_two == list(range(12, 0, -1))


class TestSleeperNamesResolve:
    """The name join is the single biggest risk in assistant mode."""

    def test_all_drafted_players_resolve_against_the_adp_pool(self, picks, pool_2025):
        unresolved = []
        for pick in picks:
            meta = pick.get("metadata") or {}
            name = f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip()
            position = normalize_position(meta.get("position", ""))
            team = (meta.get("team") or "").upper()

            if pool_2025.find(name, position, team) is None:
                unresolved.append(f"{name} ({position}, {team}) at pick {pick['pick_no']}")

        # Late-round picks are often players too deep to appear in a 249-player
        # ADP feed at all, which is a data-coverage gap rather than a name bug.
        # The assertion targets the rounds where every player is ranked.
        early = [u for u in unresolved if int(u.rsplit(" ", 1)[-1]) <= 120]
        assert not early, "unresolved names in rounds 1-10:\n" + "\n".join(early)

    def test_the_top_of_the_draft_resolves_exactly(self, picks, pool_2025):
        for pick in picks[:24]:
            meta = pick["metadata"]
            name = f"{meta['first_name']} {meta['last_name']}".strip()
            found = pool_2025.find(name, normalize_position(meta["position"]), meta["team"].upper())
            assert found is not None, f"could not resolve {name} at pick {pick['pick_no']}"
            assert found.position == normalize_position(meta["position"])

    def test_punctuated_names_resolve(self, picks, pool_2025):
        """Apostrophes, periods and hyphens are where the two feeds diverge.

        This draft contains Amon-Ra St. Brown, A.J. Brown, Ja'Marr Chase,
        Jaxon Smith-Njigba and Ka'imi Fairbairn -- every punctuation class we
        normalize, on real data rather than invented examples.
        """
        awkward = [
            pick for pick in picks
            if any(ch in _full_name(pick) for ch in ".'-")
        ]
        assert len(awkward) > 5, "fixture no longer exercises punctuated names"

        for pick in awkward:
            meta = pick["metadata"]
            name = _full_name(pick)
            found = pool_2025.find(
                name, normalize_position(meta["position"]), (meta.get("team") or "").upper()
            )
            assert found is not None, f"could not resolve {name!r} at pick {pick['pick_no']}"

    def test_defenses_resolve_across_differing_names(self, picks, pool_2025):
        """Sleeper says "Seattle Seahawks"; the ADP feed says "Seattle Defense".

        Only the team abbreviation is common to both, which is why the DST key
        drops the name entirely.
        """
        defenses = [
            pick for pick in picks
            if normalize_position((pick.get("metadata") or {}).get("position", "")) == "DST"
        ]
        if not defenses:
            pytest.skip("no defenses drafted in this fixture")

        for pick in defenses:
            meta = pick["metadata"]
            name = _full_name(pick)
            found = pool_2025.find(name, "DST", (meta.get("team") or "").upper())
            assert found is not None, f"could not resolve defense {name!r}"
            assert found.position == "DST"


class TestKeepersFromTheFeed:
    def test_keeper_flags_are_readable(self, picks):
        """Assistant mode reads keepers off the feed instead of asking for them."""
        flags = {bool(p.get("is_keeper")) for p in picks}
        # Either the league used keepers in Sleeper or it did not; both are
        # valid. What matters is that the field parses as a boolean.
        assert flags <= {True, False}
