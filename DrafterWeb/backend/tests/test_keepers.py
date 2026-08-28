"""Keeper pricing.

Keeping a player costs the round his ADP falls in, so the arithmetic at the
round boundaries is the whole game: getting pick 12 or pick 13 wrong moves a
keeper a full round.
"""

from __future__ import annotations

import pytest

from app.core.keepers import (
    BOUNDARY_MARGIN,
    keeper_round,
    price,
    roster_options,
    rounds_apart,
)


class TestKeeperRound:
    @pytest.mark.parametrize(
        "adp,expected",
        [
            (1.0, 1), (1.5, 1), (11.9, 1), (12.0, 1),   # first round ends at 12
            (12.1, 2), (13.0, 2), (24.0, 2),            # second runs 13 to 24
            (24.1, 3), (36.0, 3),
            (180.0, 15),
        ],
    )
    def test_a_twelve_team_board(self, adp, expected):
        assert keeper_round(adp, teams=12) == expected

    def test_the_boundary_is_inclusive_at_the_top(self):
        """Pick 12 is still the first round; 13 opens the second."""
        assert keeper_round(12.0, 12) == 1
        assert keeper_round(12.01, 12) == 2

    def test_the_league_size_sets_the_boundaries(self):
        assert keeper_round(11.0, teams=10) == 2
        assert keeper_round(11.0, teams=12) == 1
        assert keeper_round(11.0, teams=14) == 1

    def test_the_first_pick_is_the_first_round(self):
        assert keeper_round(0.5, 12) == 1
        assert keeper_round(1.0, 12) == 1

    def test_a_nonsense_league_is_rejected(self):
        with pytest.raises(ValueError):
            keeper_round(10.0, teams=0)


class TestBoundaryWarning:
    def test_a_player_just_inside_a_round_is_flagged(self):
        # ADP 11.5 in a twelve-team league: half a pick from round two.
        assert rounds_apart(11.5, 12) == pytest.approx(0.5)
        _, near = price(_fake(adp=11.5), 12)
        assert near is True

    def test_a_player_comfortably_inside_is_not(self):
        assert rounds_apart(3.0, 12) == pytest.approx(9.0)
        _, near = price(_fake(adp=3.0), 12)
        assert near is False

    def test_the_margin_is_what_decides_it(self):
        just_over = 12 - BOUNDARY_MARGIN - 0.1
        just_under = 12 - BOUNDARY_MARGIN + 0.1
        assert price(_fake(adp=just_over), 12)[1] is False
        assert price(_fake(adp=just_under), 12)[1] is True


class TestRosterOptions:
    def test_it_prices_a_real_roster(self, pool_2025):
        best = pool_2025.players[0]
        directory = {
            "1": {"first_name": best.name.split()[0],
                  "last_name": " ".join(best.name.split()[1:]),
                  "position": best.position, "team": best.team},
        }
        options = roster_options(["1"], directory, pool_2025, teams=12, rounds=15)

        assert len(options) == 1
        assert options[0].keepable
        assert options[0].round == 1
        assert options[0].name == best.name

    def test_an_unranked_player_costs_the_last_round(self, pool_2025):
        """A roster is last season's, so some of it has left the board.

        Refusing them had the rule backwards: keeping costs the round a
        player's ADP falls in, and no ADP means nobody drafts him, which makes
        him the cheapest keeper available rather than an ineligible one.
        """
        directory = {"9": {"first_name": "Nobody", "last_name": "McFake",
                           "position": "RB", "team": "FA"}}
        options = roster_options(["9"], directory, pool_2025, teams=12, rounds=15)

        assert len(options) == 1
        assert options[0].keepable is True
        assert options[0].ranked is False
        assert options[0].round == 15
        assert options[0].adp is None
        assert options[0].name == "Nobody McFake"

    def test_the_last_round_follows_the_league_length(self, pool_2025):
        directory = {"9": {"first_name": "Nobody", "last_name": "McFake",
                           "position": "RB", "team": "FA"}}
        assert roster_options(["9"], directory, pool_2025, teams=12, rounds=12)[0].round == 12

    def test_an_unranked_player_still_gets_a_key(self, pool_2025):
        """Without one there is nothing for a pick to name."""
        directory = {"9": {"first_name": "Nobody", "last_name": "McFake",
                           "position": "RB", "team": "FA"}}
        option = roster_options(["9"], directory, pool_2025, teams=12, rounds=15)[0]
        assert option.key
        assert option.key not in pool_2025.by_key

    def test_the_cheapest_round_comes_first(self, pool_2025):
        players = [pool_2025.players[i] for i in (40, 2, 90)]
        directory = {
            str(i): {"first_name": p.name.split()[0],
                     "last_name": " ".join(p.name.split()[1:]),
                     "position": p.position, "team": p.team}
            for i, p in enumerate(players)
        }
        options = roster_options(list(directory), directory, pool_2025, teams=12, rounds=15)

        adps = [o.adp for o in options if o.adp is not None]
        assert adps == sorted(adps)

    def test_unranked_players_sink_to_the_bottom(self, pool_2025):
        """They cost the last round, which is the most a keeper can cost."""
        real = pool_2025.players[5]
        directory = {
            "1": {"first_name": "Nobody", "last_name": "McFake",
                  "position": "RB", "team": "FA"},
            "2": {"first_name": real.name.split()[0],
                  "last_name": " ".join(real.name.split()[1:]),
                  "position": real.position, "team": real.team},
        }
        options = roster_options(["1", "2"], directory, pool_2025, teams=12, rounds=15)
        assert options[0].ranked and not options[-1].ranked
        assert options[0].round < options[-1].round

    def test_a_player_missing_from_the_directory_still_appears(self, pool_2025):
        options = roster_options(["unknown-id"], {}, pool_2025, teams=12, rounds=15)
        assert len(options) == 1
        assert options[0].name == "unknown-id"
        assert not options[0].ranked

    def test_an_empty_roster_is_fine(self, pool_2025):
        assert roster_options([], {}, pool_2025, teams=12, rounds=15) == []

    def test_it_serializes(self, pool_2025):
        import json

        best = pool_2025.players[0]
        directory = {"1": {"first_name": best.name.split()[0],
                           "last_name": " ".join(best.name.split()[1:]),
                           "position": best.position, "team": best.team}}
        options = roster_options(["1"], directory, pool_2025, teams=12, rounds=15)
        json.dumps([o.as_dict() for o in options])


def _fake(adp: float):
    from app.core.models import Player

    return Player(
        key="RB:FA:test", name="Test Player", position="RB", team="FA",
        rank=1, pos_rank=1, bye_week=9, adp=adp, adp_round="",
        times_drafted=0, high=0, low=0, stdev=1.0,
    )


class TestTheAdpMigration:
    """The live database predates unranked keepers.

    Its keeper_picks.adp is NOT NULL, so the first unranked selection would
    have failed on a constraint rather than a rule.
    """

    OLD_SCHEMA = """
    CREATE TABLE keeper_picks (
        user_id      TEXT PRIMARY KEY,
        player_key   TEXT NOT NULL,
        player_name  TEXT NOT NULL,
        position     TEXT NOT NULL,
        nfl_team     TEXT NOT NULL,
        adp          REAL NOT NULL,
        round        INTEGER NOT NULL,
        submitted_at TEXT NOT NULL,
        updated_at   TEXT NOT NULL
    );
    """

    def _old_db(self, tmp_path):
        import sqlite3

        path = tmp_path / "old.db"
        conn = sqlite3.connect(path)
        conn.executescript(self.OLD_SCHEMA)
        conn.execute(
            "INSERT INTO keeper_picks VALUES"
            " ('u1','RB:BUF:jamescook','James Cook','RB','BUF',18.4,2,'t','t')"
        )
        conn.commit()
        conn.close()
        return path

    def test_it_relaxes_the_constraint(self, tmp_path):
        from app.store import SessionStore

        store = SessionStore(self._old_db(tmp_path))
        store.set_keeper("u2", {
            "player_key": "TE:LAR:colbyparkinson", "player_name": "Colby Parkinson",
            "position": "TE", "nfl_team": "LAR", "adp": None, "round": 15,
        })
        assert store.keeper("u2")["adp"] is None

    def test_it_keeps_the_selections_already_made(self, tmp_path):
        """A rebuild that loses somebody's keeper is worse than the bug."""
        from app.store import SessionStore

        store = SessionStore(self._old_db(tmp_path))
        kept = store.keeper("u1")
        assert kept["player_name"] == "James Cook"
        assert kept["adp"] == 18.4
        assert kept["round"] == 2

    def test_it_runs_only_once(self, tmp_path):
        from app.store import SessionStore

        path = self._old_db(tmp_path)
        SessionStore(path)
        store = SessionStore(path)  # reopening must not rebuild again
        assert store.keeper("u1")["player_name"] == "James Cook"
