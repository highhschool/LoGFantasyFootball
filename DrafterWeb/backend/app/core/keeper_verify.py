"""Comparing our keeper board against the one in Sleeper.

Sleeper's API is read-only, so keepers have to be entered in its commissioner
UI by hand. Twelve rows typed once a year is exactly the kind of job that goes
wrong quietly: the wrong round costs somebody a pick they thought they had, and
nobody finds out until the draft is running.

So the direction that is possible is the one that catches it. Sleeper publishes
assigned keepers before the draft starts -- flagged `is_keeper`, with a round
and a slot -- which is everything needed to diff them against what the league
chose here.

Matched on draft slot rather than on name or user id: the slot is what a pick
actually occupies, it is what both sides agree on, and a keeper entered against
the wrong manager is precisely the error worth catching rather than papering
over.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..integrations.sleeper import SleeperPick
from .names import normalize_name

# What a row can be. Ordered by how much attention it wants.
MISMATCH = "mismatch"       # a different player is in Sleeper
WRONG_ROUND = "wrong_round"  # right player, wrong round
MISSING = "missing"         # chosen here, not yet entered in Sleeper
UNEXPECTED = "unexpected"   # in Sleeper, not chosen here
MATCH = "match"
PENDING = "pending"         # nobody has chosen, nothing entered

# Rows are listed worst-first: the point of the view is what needs fixing.
SEVERITY = {
    MISMATCH: 0,
    WRONG_ROUND: 1,
    UNEXPECTED: 2,
    MISSING: 3,
    MATCH: 4,
    PENDING: 5,
}

NEEDS_ACTION = frozenset({MISMATCH, WRONG_ROUND, MISSING, UNEXPECTED})


@dataclass(frozen=True, slots=True)
class Row:
    """One draft slot, as both sides see it."""

    draft_slot: int | None
    manager: str
    status: str
    ours_name: str = ""
    ours_round: int | None = None
    theirs_name: str = ""
    theirs_round: int | None = None

    @property
    def needs_action(self) -> bool:
        return self.status in NEEDS_ACTION

    def as_dict(self) -> dict:
        return {
            "draft_slot": self.draft_slot,
            "manager": self.manager,
            "status": self.status,
            "needs_action": self.needs_action,
            "ours_name": self.ours_name,
            "ours_round": self.ours_round,
            "theirs_name": self.theirs_name,
            "theirs_round": self.theirs_round,
        }


def _same_player(left: str, right: str) -> bool:
    """Compared on the normalized name, which already handles suffixes.

    Not on our player key: it carries the NFL team, and a keeper who changed
    teams in the offseason would read as a different person.
    """
    return bool(left) and normalize_name(left) == normalize_name(right)


def _classify(ours_name: str, ours_round, theirs: SleeperPick | None) -> str:
    if theirs is None:
        return MISSING if ours_name else PENDING
    if not ours_name:
        return UNEXPECTED
    if not _same_player(ours_name, theirs.name):
        return MISMATCH
    return MATCH if ours_round == theirs.round else WRONG_ROUND


def compare(ours: list[dict], theirs: list[SleeperPick]) -> list[Row]:
    """Diff the league's chosen keepers against the draft board in Sleeper.

    `ours` is the keeper board as stored -- one entry per manager, whether or
    not they have chosen. `theirs` is the draft's full pick feed; only the
    keeper picks are considered, because an ordinary pick made once the draft
    is running is not a keeper going wrong.
    """
    by_slot = {p.draft_slot: p for p in theirs if p.is_keeper}
    rows: list[Row] = []
    seen: set[int] = set()

    for entry in ours:
        slot = entry.get("draft_slot")
        pick = by_slot.get(slot) if slot is not None else None
        if pick is not None:
            seen.add(slot)

        name = entry.get("player_name") or ""
        rnd = entry.get("round")
        rows.append(
            Row(
                draft_slot=slot,
                manager=entry.get("display_name") or entry.get("team_name") or "",
                status=_classify(name, rnd, pick),
                ours_name=name,
                ours_round=rnd,
                theirs_name=pick.name if pick else "",
                theirs_round=pick.round if pick else None,
            )
        )

    # A keeper on a slot we know no manager for. Rare, but silently dropping it
    # would hide the one case where the draft order itself is out of step.
    for slot, pick in sorted(by_slot.items()):
        if slot in seen:
            continue
        rows.append(
            Row(
                draft_slot=slot,
                manager="",
                status=UNEXPECTED,
                theirs_name=pick.name,
                theirs_round=pick.round,
            )
        )

    rows.sort(key=lambda r: (SEVERITY[r.status], r.draft_slot or 0))
    return rows


def summarize(rows: list[Row]) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return {
        "counts": counts,
        "needs_action": sum(1 for r in rows if r.needs_action),
        "agreed": counts.get(MATCH, 0),
    }
