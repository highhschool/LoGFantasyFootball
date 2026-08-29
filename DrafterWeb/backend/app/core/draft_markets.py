"""What a draft-night market can be about.

Markets are templates rather than free text, and the reason is real money: a
market the app cannot resolve is a market the commissioner has to rule on, and
every ruling is an argument about actual dollars with the person holding them.
A template knows three things a sentence does not -- what it is asking, what it
opens at, and how the picks feed answers it.

The opening price comes free. `advisor.survival_probability` already models a
player's draft position as normal around his ADP with the spread the feed
reports, which is exactly the number a market on "taken by pick 20" needs. So
the line opens honest without anybody setting it by hand, and the league spends
the evening arguing with the model rather than with the commissioner.

Resolution returns None while a market is genuinely undecided. That matters at
both ends: a market that cannot yet be called must stay open, and a market that
is *already* decided must never be opened at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from .advisor import survival_probability
from .lmsr import DOLLAR
from .models import Player
from .rankings import PlayerPool

# Openings are clamped away from certainty. A market at 99c has nothing to
# argue about and, worse, carries the house's largest exposure for the least
# interesting question.
FLOOR, CEILING = 10, 90


class TemplateError(ValueError):
    """A market that cannot be built from what was asked for."""


@dataclass(frozen=True, slots=True)
class Board:
    """The draft as it stands, which is all any of these need to resolve."""

    picks: list           # SleeperPick
    teams: int
    rounds: int

    @property
    def made(self) -> int:
        """The highest pick number reached. Keepers count -- they occupy a slot."""
        return max((p.pick_no for p in self.picks), default=0)

    @property
    def complete(self) -> bool:
        return self.made >= self.teams * self.rounds

    def through(self, pick_no: int) -> bool:
        """Whether the draft has passed a given overall pick."""
        return self.made >= pick_no

    def in_round(self, rnd: int) -> list:
        return [p for p in self.picks if p.round == rnd]

    def round_done(self, rnd: int) -> bool:
        return self.through(rnd * self.teams)

    def by_slot(self, slot: int, keepers: bool = True) -> list:
        picks = [p for p in self.picks if p.draft_slot == slot]
        if not keepers:
            picks = [p for p in picks if not p.is_keeper]
        return sorted(picks, key=lambda p: p.pick_no)


def _clamp(cents: float) -> int:
    return min(CEILING, max(FLOOR, round(cents)))


def _player(pool: PlayerPool, key: str) -> Player:
    found = pool.by_key.get(key)
    if found is None:
        raise TemplateError(f"no player on this year's board with key {key!r}")
    return found


def _taken(board: Board, player: Player):
    """The pick that took this player, if any. Matched on normalized name."""
    from .names import normalize_name

    wanted = normalize_name(player.name)
    return next((p for p in board.picks if normalize_name(p.name) == wanted), None)


# --------------------------------------------------------------------- kinds

class PlayerByPick:
    """Will this player be gone by pick N?

    The showcase: ADP and its spread already answer this, so the opening line
    is the model's own belief and the evening is spent disagreeing with it.
    """

    key = "player_by_pick"
    label = "Player gone by a pick"

    @staticmethod
    def question(params: dict, pool: PlayerPool) -> str:
        return f"{_player(pool, params['player_key']).name} drafted by pick {params['pick']}?"

    @staticmethod
    def opening(params: dict, pool: PlayerPool) -> int:
        player = _player(pool, params["player_key"])
        # now=0: nothing has happened yet, so this is the unconditional chance.
        lasts = survival_probability(player, 0, int(params["pick"]))
        return _clamp((1.0 - lasts) * DOLLAR)

    @staticmethod
    def resolve(params: dict, board: Board, pool: PlayerPool) -> bool | None:
        pick_no = int(params["pick"])
        taken = _taken(board, _player(pool, params["player_key"]))
        if taken is not None:
            return taken.pick_no <= pick_no
        return False if board.through(pick_no) else None


class PositionInRound:
    """Will any POSITION be taken in round N?"""

    key = "position_in_round"
    label = "A position taken in a round"

    @staticmethod
    def question(params: dict, pool: PlayerPool) -> str:
        return f"Any {params['position']} taken in round {params['round']}?"

    @staticmethod
    def opening(params: dict, pool: PlayerPool) -> int:
        """The chance at least one goes, from each candidate's own ADP curve.

        The per-player curves have to be normalized to the round first. Taken
        raw they are badly over-subscribed late: summed across the board they
        expect 26 players to go in round 13, where only twelve picks exist,
        because ADP spreads out there are wide (stdev 20 on a kicker) and
        nothing ties them to the slots available. Left uncorrected every
        late-round market opens too high, and the house carries the difference.

        Independence between players is still wrong -- runs are the whole
        texture of a draft -- but it is wrong in a direction everyone can see,
        and the line is there to be argued with.
        """
        rnd, teams = int(params["round"]), int(params.get("teams", 12))
        lo, hi = (rnd - 1) * teams, rnd * teams

        window = []
        for player in pool.players:
            gone_by_lo = 1.0 - survival_probability(player, 0, lo) if lo else 0.0
            gone_by_hi = 1.0 - survival_probability(player, 0, hi)
            window.append((player, max(0.0, gone_by_hi - gone_by_lo)))

        expected = sum(w for _, w in window)
        scale = (teams / expected) if expected > 0 else 0.0

        none_of_them = 1.0
        for player, weight in window:
            if player.position == params["position"]:
                none_of_them *= 1.0 - min(1.0, weight * scale)

        return _clamp((1.0 - none_of_them) * DOLLAR)

    @staticmethod
    def resolve(params: dict, board: Board, pool: PlayerPool) -> bool | None:
        rnd = int(params["round"])
        if any(p.position == params["position"] for p in board.in_round(rnd)):
            return True
        return False if board.round_done(rnd) else None


class ManagerFirstPick:
    """Will this manager open with a POSITION?

    Keepers are excluded. A keeper is a decision made in August, not on the
    night, and counting it would settle the market before it opened for the six
    managers who kept somebody.
    """

    key = "manager_first_pick"
    label = "A manager's opening pick"

    @staticmethod
    def question(params: dict, pool: PlayerPool) -> str:
        return f"{params['manager']} takes a {params['position']} with their first pick?"

    @staticmethod
    def opening(params: dict, pool: PlayerPool) -> int:
        """Unpriceable from ADP -- it is a person, not a distribution.

        Opens where the commissioner puts it, defaulting to a coin flip, which
        is also the cheapest market for the house to run.
        """
        return _clamp(params.get("opening", 50))

    @staticmethod
    def resolve(params: dict, board: Board, pool: PlayerPool) -> bool | None:
        made = board.by_slot(int(params["slot"]), keepers=False)
        if made:
            return made[0].position == params["position"]
        return False if board.complete else None


TEMPLATES = {t.key: t for t in (PlayerByPick, PositionInRound, ManagerFirstPick)}


def template(key: str):
    found = TEMPLATES.get(key)
    if found is None:
        raise TemplateError(
            f"unknown market type {key!r}; known types are {sorted(TEMPLATES)}"
        )
    return found


def build(key: str, params: dict, pool: PlayerPool, board: Board) -> dict:
    """Everything needed to open a market, or a refusal.

    Refuses a market the board has already answered. Opening one would be
    selling contracts on a coin that has landed -- and on draft night, with the
    feed visible to everyone, somebody would notice within the minute.
    """
    kind = template(key)
    settled = kind.resolve(params, board, pool)
    if settled is not None:
        raise TemplateError(
            f"that is already decided ({'yes' if settled else 'no'}), "
            "so there is nothing to trade"
        )

    return {
        "kind": key,
        "params": params,
        "question": kind.question(params, pool),
        "opening": kind.opening(params, pool),
    }


# ------------------------------------------------------------- suggestions

# Where a market is worth opening. A line at 90c has no argument in it --
# everyone takes the same side, the price never moves, and it settles as
# everybody expected. The interesting ones sit near a coin flip.
ARGUABLE = 25          # cents either side of even
DEPTH = 80             # players deep enough to matter in a fifteen-round draft
PICKS = (3, 6, 12, 18, 24, 36, 48, 60, 84, 120)


def _subject(kind: str, params: dict) -> str:
    """What a candidate is *about*, so a shortlist is not ten of one player."""
    if kind == PlayerByPick.key:
        return f"player:{params['player_key']}"
    if kind == PositionInRound.key:
        return f"position:{params['position']}"
    return f"{kind}:{sorted(params.items())}"


def suggest(
    pool: PlayerPool,
    board: Board,
    exclude: set[str] | None = None,
    shape: dict[str, int] | None = None,
    limit: int = 10,
) -> list[dict]:
    """The most arguable markets this board can still offer.

    Every player against every plausible pick, and every position against every
    round, ranked by how close the model puts them to even. Anything the draft
    has already answered is dropped -- the same check that refuses to open one.

    One candidate per subject, so a shortlist is ten different arguments rather
    than ten framings of the same player. `exclude` takes the subjects already
    on a slate; `shape` weights the mix towards a previous slate's kinds, which
    is what makes "the same questions as last week" mean anything.

    Manager markets are left out on purpose. They open where the commissioner
    puts them rather than where ADP does, so there is no model opinion to rank
    them by -- and picking which manager to needle is the fun part.
    """
    taken = exclude or set()
    found: list[tuple[int, dict]] = []

    def consider(kind, params):
        subject = _subject(kind, params)
        if subject in taken:
            return
        try:
            made = build(kind, params, pool, board)
        except TemplateError:
            return                       # already decided, or unbuildable
        found.append((abs(made["opening"] - 50), {**made, "subject": subject}))

    for player in pool.players[:DEPTH]:
        for pick in PICKS:
            consider(PlayerByPick.key, {"player_key": player.key, "pick": pick})

    for position in sorted({p.position for p in pool.players}):
        for rnd in range(1, board.rounds + 1):
            consider(PositionInRound.key, {"position": position, "round": rnd})

    # Closest to even first, then thinned to one per subject.
    found.sort(key=lambda row: row[0])
    best: dict[str, dict] = {}
    for distance, made in found:
        if distance > ARGUABLE:
            break
        best.setdefault(made["subject"], made)

    ordered = sorted(best.values(), key=lambda m: abs(m["opening"] - 50))
    if not shape:
        return ordered[:limit]

    # Fill each kind to the share it had last week, then top up from the rest.
    out: list[dict] = []
    for kind, wanted in sorted(shape.items(), key=lambda kv: -kv[1]):
        matching = [m for m in ordered if m["kind"] == kind and m not in out]
        out.extend(matching[:wanted])
    for made in ordered:
        if len(out) >= limit:
            break
        if made not in out:
            out.append(made)
    return out[:limit]
