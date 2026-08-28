"""Name normalization, so the same player from two sources resolves to one key.

Sleeper and Fantasy Football Calculator disagree about suffixes and punctuation:
Sleeper says "Patrick Mahomes II" where FFC says "Patrick Mahomes", and the CLI
tool's validate_keepers() already documents this exact mismatch. Team defenses
are worse -- FFC ships them as "Seattle Defense", Sleeper as "Seahawks".

Matching strategy, most to least confident:
  1. (normalized name, position, team)  -- near-certain
  2. (normalized name, position)        -- handles mid-season team changes
  3. normalized name                    -- last resort

Anything still unresolved is reported, never guessed at.
"""

from __future__ import annotations

import re
import unicodedata

# Stripped from the end of a name. "II"/"III"/"IV" are Roman numerals rather
# than initials, so they only count as suffixes in final position.
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

_PUNCT = re.compile(r"[.’'`\-,]")
_WS = re.compile(r"\s+")

# Sleeper labels a defense by nickname; FFC uses "<City> Defense". The team
# abbreviation is what actually identifies them, so DST keys drop the name.
_DEF_WORDS = {"defense", "dst", "d/st", "def"}


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_name(name: str) -> str:
    """Casefold, strip accents and punctuation, and drop a trailing suffix."""
    cleaned = _PUNCT.sub("", _strip_accents(name)).casefold()
    parts = _WS.sub(" ", cleaned).strip().split(" ")
    while len(parts) > 1 and parts[-1] in _SUFFIXES:
        parts.pop()
    return " ".join(parts)


def player_key(name: str, position: str, team: str) -> str:
    """A stable identity for a player across sources.

    Defenses key on team alone, because the two feeds name them differently and
    a team can only have one.
    """
    # Normalized here too, so a caller passing a source's own label -- DEF for
    # a defense, RB1 for a running back -- cannot silently produce a key that
    # matches nothing.
    pos = normalize_position(position)
    tm = (team or "").strip().upper()

    if pos == "DST":
        return f"DST:{tm}"

    return f"{pos}:{tm}:{normalize_name(name)}"


def normalize_position(raw: str) -> str:
    """Coerce a source's position label to ours.

    Handles FFC's DEF/PK aliases and the old FantasyPros habit of fusing the
    positional rank onto the position ("RB1" -> "RB").
    """
    pos = re.sub(r"\d+", "", (raw or "")).strip().upper()
    return {"DEF": "DST", "D/ST": "DST", "PK": "K"}.get(pos, pos)


def is_defense_name(name: str) -> bool:
    return any(word in name.casefold() for word in _DEF_WORDS)
