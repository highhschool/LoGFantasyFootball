"""The draft state machine.

State is derived, never stored:

    DraftState = replay(config, pool, log)

The log holds only the picks somebody actually made. Keeper cells are filled in
during replay from the config, so they never occupy a log entry -- which means
undo pops a real pick and can never strand a keeper.

Everything else (who is on the clock, who is available, roster counts, bye
clashes) is computed from that walk, so there is exactly one source of truth and
undo is just `log[:-1]`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .models import DraftConfig, PickSlot, Player
from .order import build_board
from .rankings import PlayerPool


class DraftError(RuntimeError):
    """An illegal pick."""


# Sits beyond any ranked player, so an unranked pick never sorts as a bargain.
UNRANKED_ADP = 999.0


@dataclass(frozen=True, slots=True)
class LoggedPick:
    """One entry in the event log: who was taken, and by what mechanism.

    A real draft reaches players the rankings do not cover -- the 2025 board
    took a round-15 back who is not in a 249-player ADP feed at all. Rather
    than stall, the log describes such a pick itself, so the seat is filled
    and every later pick stays in the right place.
    """

    player_key: str
    source: str = "user"
    name: str = ""
    position: str = ""
    team: str = ""

    @property
    def is_unranked(self) -> bool:
        return bool(self.name)


@dataclass(frozen=True, slots=True)
class Pick:
    """A log entry resolved against the board and the player pool."""

    overall: int
    round: int
    pick_in_round: int
    team_slot: int
    player_key: str
    player_name: str
    position: str
    team: str
    bye_week: int | None
    adp: float
    source: str


@dataclass
class TeamState:
    slot: int
    picks: list[Pick] = field(default_factory=list)
    position_counts: Counter = field(default_factory=Counter)

    @property
    def bye_weeks(self) -> list[int]:
        return [p.bye_week for p in self.picks if p.bye_week is not None]

    def bye_clashes(self, threshold: int = 3) -> dict[int, int]:
        """Bye weeks shared by `threshold` or more players on this roster."""
        counts = Counter(self.bye_weeks)
        return {week: n for week, n in counts.items() if n >= threshold}

    def needs(self, limits: dict[str, int]) -> dict[str, int]:
        return {pos: limit - self.position_counts.get(pos, 0) for pos, limit in limits.items()}


@dataclass
class DraftState:
    config: DraftConfig
    board: list[PickSlot]
    picks: list[Pick] = field(default_factory=list)
    teams: dict[int, TeamState] = field(default_factory=dict)
    drafted: set[str] = field(default_factory=set)
    keeper_keys: set[str] = field(default_factory=set)
    unresolved_keepers: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return len(self.picks) >= len(self.board)

    @property
    def current(self) -> PickSlot | None:
        """The cell on the clock, or None when the draft is over."""
        if self.complete:
            return None
        return self.board[len(self.picks)]

    @property
    def your_turn(self) -> bool:
        cell = self.current
        return cell is not None and cell.team_slot == self.config.your_slot

    def team(self, slot: int) -> TeamState:
        return self.teams[slot]

    def available(self, pool: PlayerPool) -> list[Player]:
        return [p for p in pool.players if p.key not in self.drafted]

    def eligible(self, pool: PlayerPool, slot: int) -> list[Player]:
        """Available players this team can still legally roster."""
        counts = self.teams[slot].position_counts
        limits = self.config.position_limits
        return [
            p for p in self.available(pool)
            if counts.get(p.position, 0) < limits.get(p.position, 0)
        ]

    def can_draft(self, pool: PlayerPool, slot: int, player_key: str) -> tuple[bool, str]:
        if player_key in self.keeper_keys and not any(
            p.player_key == player_key for p in self.picks
        ):
            return False, "kept by another team"
        if player_key in self.drafted:
            return False, "already drafted"

        player = pool.by_key.get(player_key)
        if player is None:
            return False, "no such player"

        limit = self.config.position_limits.get(player.position, 0)
        taken = self.teams[slot].position_counts.get(player.position, 0)
        if taken >= limit:
            return False, f"roster is full at {player.position} ({taken}/{limit})"

        return True, ""


def _blank_state(config: DraftConfig) -> DraftState:
    return DraftState(
        config=config,
        board=build_board(config),
        teams={slot: TeamState(slot=slot) for slot in range(1, config.teams + 1)},
    )


def _place(
    state: DraftState,
    cell: PickSlot,
    player: Player,
    source: str,
    count_position: bool = True,
) -> None:
    """Record a ranked player on the board.

    `count_position` is False for keepers, whose position was already counted
    when they were reserved before the draft began.
    """
    _record(
        state, cell,
        key=player.key, name=player.name, position=player.position,
        team=player.team, bye_week=player.bye_week, adp=player.adp,
        source=source, count_position=count_position,
    )


def _place_unranked(state: DraftState, cell: PickSlot, entry: LoggedPick) -> None:
    """Record a pick whose player is not in the rankings."""
    _record(
        state, cell,
        key=entry.player_key, name=entry.name, position=entry.position,
        team=entry.team, bye_week=None, adp=UNRANKED_ADP,
        source=entry.source, count_position=True,
    )


def _record(
    state: DraftState,
    cell: PickSlot,
    *,
    key: str,
    name: str,
    position: str,
    team: str,
    bye_week: int | None,
    adp: float,
    source: str,
    count_position: bool,
) -> None:
    pick = Pick(
        overall=cell.overall,
        round=cell.round,
        pick_in_round=cell.pick_in_round,
        team_slot=cell.team_slot,
        player_key=key,
        player_name=name,
        position=position,
        team=team,
        bye_week=bye_week,
        adp=adp,
        source=source,
    )
    state.picks.append(pick)
    state.drafted.add(key)
    roster = state.teams[cell.team_slot]
    roster.picks.append(pick)
    if count_position and position in state.config.position_limits:
        roster.position_counts[position] += 1


def replay(config: DraftConfig, pool: PlayerPool, log: list[LoggedPick]) -> DraftState:
    """Rebuild the whole draft from its event log.

    A keeper whose name does not resolve is recorded and its cell left to the
    log, rather than raising -- one bad keeper name must not make a session
    unopenable.
    """
    state = _blank_state(config)

    # Resolve and reserve every keeper before the draft starts. A keeper slotted
    # into round 5 has to be off the board in round 1 -- otherwise a bot drafts
    # a player who is already spoken for. Their position also counts against the
    # keeping team's limits from the outset, so those roster spots are honestly
    # accounted for rather than appearing free until the keeper's round arrives.
    keeper_at: dict[int, Player] = {}
    for cell in state.board:
        if cell.keeper is None:
            continue
        player = pool.find(cell.keeper)
        if player is None or player.key in state.keeper_keys:
            if cell.keeper not in state.unresolved_keepers:
                state.unresolved_keepers.append(cell.keeper)
            continue
        keeper_at[cell.overall] = player
        state.keeper_keys.add(player.key)
        state.drafted.add(player.key)
        state.teams[cell.team_slot].position_counts[player.position] += 1

    pending = list(log)

    for cell in state.board:
        keeper = keeper_at.get(cell.overall)
        if keeper is not None:
            _place(state, cell, keeper, "keeper", count_position=False)
            continue

        if not pending:
            break

        entry = pending.pop(0)
        player = pool.by_key.get(entry.player_key)
        if player is not None:
            _place(state, cell, player, entry.source)
        elif entry.is_unranked:
            _place_unranked(state, cell, entry)
        else:
            raise DraftError(f"log references unknown player {entry.player_key!r}")

    return state


def append_pick(
    config: DraftConfig,
    pool: PlayerPool,
    log: list[LoggedPick],
    player_key: str,
    source: str = "user",
) -> list[LoggedPick]:
    """Validate a pick against the current state and return the extended log."""
    state = replay(config, pool, log)
    cell = state.current
    if cell is None:
        raise DraftError("the draft is already complete")

    ok, reason = state.can_draft(pool, cell.team_slot, player_key)
    if not ok:
        name = pool.by_key[player_key].name if player_key in pool.by_key else player_key
        raise DraftError(f"cannot draft {name}: {reason}")

    return log + [LoggedPick(player_key=player_key, source=source)]


def undo(log: list[LoggedPick]) -> list[LoggedPick]:
    """Drop the most recent logged pick. Keepers are not in the log, so they
    cannot be undone by accident."""
    return log[:-1]
