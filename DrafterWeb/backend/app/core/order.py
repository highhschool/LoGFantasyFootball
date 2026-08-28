"""Snake draft order, and the optional keeper overlay on top of it.

The board is derived, never stored: given a config, these functions produce the
same list of pick slots every time. Keepers are an overlay -- a config with none
produces a plain snake draft, which is the default state.
"""

from __future__ import annotations

from collections import Counter

from .models import ConfigError, DraftConfig, Keeper, PickSlot


def snake_order(teams: int, rounds: int) -> list[list[int]]:
    """Draft slots in pick order, one list per round.

    Odd rounds run 1..teams, even rounds run back down. Slots are 1-based.
    """
    if teams < 1:
        raise ConfigError(f"teams must be at least 1, got {teams}")
    if rounds < 1:
        raise ConfigError(f"rounds must be at least 1, got {rounds}")

    board = []
    for round_index in range(rounds):
        slots = list(range(1, teams + 1))
        if round_index % 2:
            slots.reverse()
        board.append(slots)
    return board


def validate_config(config: DraftConfig) -> None:
    """Reject a config that cannot produce a coherent board.

    Keeper *names* are deliberately not checked here -- an unknown name is a
    warning surfaced next to the player, not a crash that takes down the
    session. See core.rankings.resolve_keepers.
    """
    if not 1 <= config.your_slot <= config.teams:
        raise ConfigError(
            f"your_slot must be between 1 and {config.teams}, got {config.your_slot}"
        )

    for pos, limit in config.position_limits.items():
        if limit < 0:
            raise ConfigError(f"position limit for {pos} cannot be negative, got {limit}")

    roster_capacity = sum(config.position_limits.values())
    if roster_capacity < config.rounds:
        raise ConfigError(
            f"position limits allow only {roster_capacity} players per team but the "
            f"draft runs {config.rounds} rounds, so the last "
            f"{config.rounds - roster_capacity} round(s) could never be filled"
        )

    _validate_keepers(config)


def _validate_keepers(config: DraftConfig) -> None:
    if not config.keepers:
        return

    for keeper in config.keepers:
        if not 1 <= keeper.team_slot <= config.teams:
            raise ConfigError(
                f"keeper {keeper.player_name!r} is assigned to slot {keeper.team_slot}, "
                f"outside 1..{config.teams}"
            )
        if not 1 <= keeper.round <= config.rounds:
            raise ConfigError(
                f"keeper {keeper.player_name!r} is assigned to round {keeper.round}, "
                f"outside 1..{config.rounds}"
            )

    cells = Counter((k.team_slot, k.round) for k in config.keepers)
    clashes = [cell for cell, count in cells.items() if count > 1]
    if clashes:
        slot, rnd = clashes[0]
        raise ConfigError(
            f"two keepers are assigned to slot {slot} in round {rnd}; each cell holds one player"
        )

    names = Counter(k.player_name for k in config.keepers)
    duplicates = sorted(name for name, count in names.items() if count > 1)
    if duplicates:
        raise ConfigError(f"the same player is kept by more than one team: {duplicates}")

    per_team = Counter(k.team_slot for k in config.keepers)
    over = {slot: n for slot, n in per_team.items() if n > config.rounds}
    if over:
        raise ConfigError(f"more keepers than rounds for slot(s): {sorted(over)}")


def build_board(config: DraftConfig) -> list[PickSlot]:
    """Every cell of the draft board in pick order, keepers marked."""
    validate_config(config)

    keeper_cells = {(k.team_slot, k.round): k.player_name for k in config.keepers}

    board: list[PickSlot] = []
    overall = 0
    for round_index, slots in enumerate(snake_order(config.teams, config.rounds)):
        round_no = round_index + 1
        for pick_index, team_slot in enumerate(slots):
            overall += 1
            board.append(
                PickSlot(
                    overall=overall,
                    round=round_no,
                    pick_in_round=pick_index + 1,
                    team_slot=team_slot,
                    keeper=keeper_cells.get((team_slot, round_no)),
                )
            )
    return board


def picks_for_slot(config: DraftConfig, team_slot: int) -> list[int]:
    """Overall pick numbers belonging to one draft slot."""
    return [cell.overall for cell in build_board(config) if cell.team_slot == team_slot]


def next_pick_for_slot(config: DraftConfig, team_slot: int, after: int) -> int | None:
    """The slot's next overall pick number strictly after ``after``.

    This is what the advisor measures survival probability against: the gap
    between now and here is how long a player has to last.
    """
    for overall in picks_for_slot(config, team_slot):
        if overall > after:
            return overall
    return None


def picks_until_next(config: DraftConfig, team_slot: int, after: int) -> int | None:
    """How many picks elapse before this slot is on the clock again."""
    nxt = next_pick_for_slot(config, team_slot, after)
    return None if nxt is None else nxt - after
