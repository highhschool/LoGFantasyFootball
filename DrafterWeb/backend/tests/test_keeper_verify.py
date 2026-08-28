"""Diffing our keeper board against Sleeper's.

Sleeper is read-only, so twelve keepers get typed in by hand once a year.
These are about the ways that goes wrong quietly -- and about not crying wolf,
since a check that flags healthy rows gets ignored on the night it matters.
"""

from __future__ import annotations

import pytest

from app.core.keeper_verify import (
    MATCH,
    MISMATCH,
    MISSING,
    PENDING,
    UNEXPECTED,
    WRONG_ROUND,
    compare,
    summarize,
)
from app.integrations.sleeper import SleeperPick


def ours(slot, manager, name="", rnd=None):
    return {
        "user_id": f"u{slot}", "display_name": manager, "team_name": "",
        "draft_slot": slot, "player_name": name, "position": "RB",
        "nfl_team": "DET", "adp": 1.5, "round": rnd,
    }


def theirs(slot, name, rnd, is_keeper=True, position="RB", team="DET"):
    return SleeperPick(
        pick_no=slot, round=rnd, draft_slot=slot, player_id="1",
        name=name, position=position, team=team, is_keeper=is_keeper,
    )


def status_at(rows, slot):
    return next(r.status for r in rows if r.draft_slot == slot)


class TestAgreement:
    def test_the_same_player_in_the_same_round_agrees(self):
        rows = compare([ours(6, "CommishSchaffer", "Jahmyr Gibbs", 1)],
                       [theirs(6, "Jahmyr Gibbs", 1)])
        assert status_at(rows, 6) == MATCH
        assert not rows[0].needs_action

    def test_a_suffix_is_not_a_different_player(self):
        """Sleeper and the ADP feed disagree about Jr. constantly."""
        rows = compare([ours(3, "gkabler", "Chris Godwin Jr.", 7)],
                       [theirs(3, "Chris Godwin", 7)])
        assert status_at(rows, 3) == MATCH

    def test_a_defense_agrees_across_the_two_dialects(self):
        rows = compare([ours(4, "mstika", "Houston Defense", 9)],
                       [theirs(4, "Houston Defense", 9, position="DEF")])
        assert status_at(rows, 4) == MATCH


class TestTheMistakesWorthCatching:
    def test_the_wrong_round_is_flagged(self):
        """The expensive one: it silently costs somebody a pick."""
        rows = compare([ours(6, "CommishSchaffer", "Jahmyr Gibbs", 1)],
                       [theirs(6, "Jahmyr Gibbs", 2)])
        row = rows[0]
        assert row.status == WRONG_ROUND
        assert (row.ours_round, row.theirs_round) == (1, 2)
        assert row.needs_action

    def test_the_wrong_player_is_flagged(self):
        rows = compare([ours(6, "CommishSchaffer", "Jahmyr Gibbs", 1)],
                       [theirs(6, "Bijan Robinson", 1)])
        row = rows[0]
        assert row.status == MISMATCH
        assert row.ours_name == "Jahmyr Gibbs"
        assert row.theirs_name == "Bijan Robinson"

    def test_a_keeper_not_yet_entered_is_flagged(self):
        rows = compare([ours(6, "CommishSchaffer", "Jahmyr Gibbs", 1)], [])
        assert rows[0].status == MISSING
        assert rows[0].needs_action

    def test_a_keeper_nobody_chose_here_is_flagged(self):
        """Typed against the wrong manager, most likely."""
        rows = compare([ours(6, "CommishSchaffer")],
                       [theirs(6, "Jahmyr Gibbs", 1)])
        assert rows[0].status == UNEXPECTED

    def test_a_keeper_on_a_slot_with_no_manager_still_appears(self):
        """Dropping it would hide the draft order itself being out of step."""
        rows = compare([ours(1, "BigJedd")], [theirs(9, "Jahmyr Gibbs", 1)])
        assert status_at(rows, 9) == UNEXPECTED
        assert len(rows) == 2

    def test_a_keeper_entered_against_the_wrong_manager_shows_as_two_faults(self):
        """It is two problems, and reporting one would hide the other."""
        rows = compare(
            [ours(6, "CommishSchaffer", "Jahmyr Gibbs", 1), ours(7, "JDWarren042")],
            [theirs(7, "Jahmyr Gibbs", 1)],
        )
        assert status_at(rows, 6) == MISSING
        assert status_at(rows, 7) == UNEXPECTED


class TestNotCryingWolf:
    def test_a_manager_who_has_not_chosen_is_not_a_fault(self):
        rows = compare([ours(2, "dnabulsi")], [])
        assert rows[0].status == PENDING
        assert not rows[0].needs_action

    def test_ordinary_draft_picks_are_ignored(self):
        """Once the draft runs the feed fills up; none of that is a keeper."""
        rows = compare(
            [ours(6, "CommishSchaffer", "Jahmyr Gibbs", 1)],
            [theirs(6, "Jahmyr Gibbs", 1),
             theirs(1, "Ja'Marr Chase", 1, is_keeper=False),
             theirs(2, "Bijan Robinson", 1, is_keeper=False)],
        )
        assert [r.status for r in rows] == [MATCH]

    def test_an_empty_league_is_not_a_pile_of_faults(self):
        rows = compare([ours(i, f"m{i}") for i in range(1, 13)], [])
        assert summarize(rows)["needs_action"] == 0


class TestTheReport:
    def test_faults_come_first(self):
        """The view exists to show what needs fixing."""
        rows = compare(
            [ours(1, "a", "Jahmyr Gibbs", 1),
             ours(2, "b"),
             ours(3, "c", "Bijan Robinson", 2),
             ours(4, "d", "Puka Nacua", 3)],
            [theirs(1, "Jahmyr Gibbs", 1),
             theirs(3, "Saquon Barkley", 2),
             theirs(4, "Puka Nacua", 9)],
        )
        assert [r.status for r in rows] == [MISMATCH, WRONG_ROUND, MATCH, PENDING]

    def test_it_counts_what_needs_doing(self):
        rows = compare(
            [ours(1, "a", "Jahmyr Gibbs", 1), ours(2, "b", "Bijan Robinson", 2)],
            [theirs(1, "Jahmyr Gibbs", 1)],
        )
        summary = summarize(rows)
        assert summary["agreed"] == 1
        assert summary["needs_action"] == 1
        assert summary["counts"][MISSING] == 1

    @pytest.mark.parametrize("slot", [None, 0])
    def test_a_manager_with_no_draft_slot_does_not_match_anything(self, slot):
        """Slot 0 is not a slot, and None is not a lookup key.

        Their keeper reads as unentered and Sleeper's reads as unaccounted
        for, which is the honest description of a manager missing from the
        draft order.
        """
        rows = compare([ours(slot, "unordered", "Jahmyr Gibbs", 1)],
                       [theirs(6, "Jahmyr Gibbs", 1)])
        by_manager = {r.manager: r.status for r in rows}
        assert by_manager["unordered"] == MISSING
        assert by_manager[""] == UNEXPECTED
