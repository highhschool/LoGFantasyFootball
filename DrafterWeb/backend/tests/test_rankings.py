from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.core.models import Keeper, RankingsError
from app.core.names import normalize_name, normalize_position, player_key
from app.core.rankings import REQUIRED_COLUMNS, load_pool, resolve_keepers

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_2025 = REPO_ROOT / "FantasyDrafterAI" / "2025_Rankings"


class TestLoader:
    def test_loads_the_2025_pool(self, pool_2025):
        assert len(pool_2025) > 200
        assert pool_2025.year == 2025

    def test_players_are_adp_ordered(self, pool_2025):
        adps = [p.adp for p in pool_2025.players]
        assert adps == sorted(adps)

    def test_first_pick_matches_the_feed(self, pool_2025):
        top = pool_2025.players[0]
        assert top.name == "Ja'Marr Chase"
        assert top.position == "WR"
        assert top.adp < 2

    def test_every_position_is_present(self, pool_2025):
        found = {p.position for p in pool_2025.players}
        assert found == {"QB", "RB", "WR", "TE", "K", "DST"}

    def test_positional_ranks_are_dense(self, pool_2025):
        for position in ("QB", "RB", "WR", "TE"):
            ranks = sorted(p.pos_rank for p in pool_2025.by_position(position))
            assert ranks == list(range(1, len(ranks) + 1))

    def test_stdev_is_populated(self, pool_2025):
        # The advisor's survival probability is meaningless without it.
        assert all(p.stdev >= 0 for p in pool_2025.players)
        assert any(p.stdev > 0 for p in pool_2025.players)


class TestSchemaGuard:
    def test_missing_directory_names_the_fix(self, tmp_path):
        with pytest.raises(RankingsError, match="build_rankings.py"):
            load_pool(tmp_path / "nope", 2026)

    def test_missing_column_is_reported_by_name(self, tmp_path, ffc_2025):
        path = tmp_path / "OVR_Rankings.csv"
        columns = [c for c in REQUIRED_COLUMNS if c != "STDEV"]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerow({c: "1" for c in columns} | {"PLAYER NAME": "A Player"})

        with pytest.raises(RankingsError, match=r"\['STDEV'\]"):
            load_pool(tmp_path, 2026)

    def test_header_without_rows_is_rejected(self, tmp_path):
        path = tmp_path / "OVR_Rankings.csv"
        path.write_text(",".join(REQUIRED_COLUMNS) + "\n", encoding="utf-8")
        with pytest.raises(RankingsError, match="no players"):
            load_pool(tmp_path, 2026)

    @pytest.mark.skipif(
        not (LEGACY_2025 / "OVR_Rankings.csv").is_file(),
        reason="legacy 2025_Rankings not present",
    )
    def test_legacy_fantasypros_file_is_rejected(self):
        """The guard's real-world case.

        FantasyDrafterAI/2025_Rankings/ predates build_rankings.py and has no
        ADP or STDEV columns, but is named exactly like a valid directory.
        Loading it must fail loudly rather than half-work.
        """
        with pytest.raises(RankingsError, match="missing required column"):
            load_pool(LEGACY_2025, 2025)


class TestNameNormalization:
    @pytest.mark.parametrize(
        "left,right",
        [
            ("Patrick Mahomes II", "Patrick Mahomes"),
            ("Michael Pittman Jr.", "Michael Pittman"),
            ("Amon-Ra St. Brown", "AmonRa St Brown"),
            ("Ja'Marr Chase", "JaMarr Chase"),
            ("Kenneth Walker III", "Kenneth Walker"),
            ("  Travis   Kelce  ", "Travis Kelce"),
        ],
    )
    def test_variants_collapse_to_one_form(self, left, right):
        assert normalize_name(left) == normalize_name(right)

    def test_distinct_players_stay_distinct(self):
        assert normalize_name("Justin Jefferson") != normalize_name("Justin Herbert")

    def test_a_medial_numeral_is_not_a_suffix(self):
        # Only a trailing suffix is dropped, so a real surname survives.
        assert normalize_name("Vi Nguyen") == "vi nguyen"

    @pytest.mark.parametrize(
        "raw,expected",
        [("RB1", "RB"), ("WR12", "WR"), ("DEF", "DST"), ("PK", "K"), ("qb", "QB")],
    )
    def test_position_labels_are_coerced(self, raw, expected):
        assert normalize_position(raw) == expected

    def test_defenses_key_on_team_only(self):
        # "Seattle Defense" and "Seahawks" are the same entry to us.
        assert player_key("Seattle Defense", "DST", "SEA") == player_key(
            "Seahawks", "DST", "SEA"
        )


class TestKeeperResolution:
    def test_known_names_resolve(self, pool_2025):
        keepers = (Keeper(1, 2, "Ja'Marr Chase"), Keeper(2, 3, "Bijan Robinson"))
        resolved, unresolved = resolve_keepers(pool_2025, keepers)
        assert unresolved == []
        assert resolved["Ja'Marr Chase"].position == "WR"

    def test_suffix_mismatch_still_resolves(self, pool_2025):
        # The exact failure the CLI tool's validate_keepers() documents.
        resolved, unresolved = resolve_keepers(
            pool_2025, (Keeper(1, 1, "Patrick Mahomes II"),)
        )
        assert unresolved == []
        assert resolved["Patrick Mahomes II"].position == "QB"

    def test_unknown_name_is_returned_not_raised(self, pool_2025):
        resolved, unresolved = resolve_keepers(
            pool_2025, (Keeper(1, 1, "Ja'Marr Chase"), Keeper(2, 1, "Fake McPlayer"))
        )
        assert unresolved == ["Fake McPlayer"]
        assert "Ja'Marr Chase" in resolved

    def test_no_keepers_resolves_to_nothing(self, pool_2025):
        assert resolve_keepers(pool_2025, ()) == ({}, [])


class TestSearch:
    def test_prefix_match(self, pool_2025):
        names = [p.name for p in pool_2025.search("bijan")]
        assert "Bijan Robinson" in names

    def test_partial_surname_matches(self, pool_2025):
        assert any(p.name == "Ja'Marr Chase" for p in pool_2025.search("chase"))

    def test_apostrophes_are_optional(self, pool_2025):
        assert any(p.name == "Ja'Marr Chase" for p in pool_2025.search("jamarr"))

    def test_empty_query_returns_nothing(self, pool_2025):
        assert pool_2025.search("   ") == []
