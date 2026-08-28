"""Bot drafting.

The CLI tool picks `iloc[0]` of the ADP-sorted pool every time, so every mock
draft it runs is byte-identical -- which makes it useless for the thing a mock
draft is for, namely seeing how differently a round can break.

Here each bot draws a *perceived* ADP per player, jittered by that player's own
STDEV, and takes the lowest. STDEV comes straight from the rankings CSV, where
it has been sitting unused: it is the real spread across thousands of drafts, so
consensus picks stay put and genuinely contested players move around by roughly
as much as they do in reality.
"""

from __future__ import annotations

import random

from .engine import DraftState
from .models import Player
from .rankings import PlayerPool

# Bots only consider this many of the best available players. Without a window,
# a large jitter on a deep sleeper could out-rank a first-rounder and produce a
# reach nobody would ever make.
CONSIDERATION_WINDOW = 40

# Floor on the jitter so players with a tiny STDEV are not perfectly rigid.
MIN_STDEV = 0.4


def perceived_adp(player: Player, rng: random.Random, randomness: float = 1.0) -> float:
    """The player's ADP as this bot sees it on this pick."""
    if randomness <= 0:
        return player.adp
    spread = max(player.stdev, MIN_STDEV) * randomness
    return player.adp + rng.gauss(0, spread)


def choose(
    state: DraftState,
    pool: PlayerPool,
    slot: int,
    rng: random.Random,
    randomness: float = 1.0,
) -> Player | None:
    """Pick for one bot team, respecting its remaining position limits."""
    eligible = state.eligible(pool, slot)
    if not eligible:
        return None

    window = eligible[:CONSIDERATION_WINDOW]
    return min(window, key=lambda p: perceived_adp(p, rng, randomness))


def rng_for(seed: int, overall_pick: int) -> random.Random:
    """A generator keyed to the seed and pick number.

    Deriving it per pick rather than threading one stream through the draft
    keeps replay deterministic: rebuilding state from the log reproduces the
    same bot decisions regardless of how many times it is replayed, or where an
    undo left off.
    """
    return random.Random((seed << 16) ^ overall_pick)
