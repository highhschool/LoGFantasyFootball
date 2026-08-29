"""The season pot.

The only real money in the tool. The property worth guarding is that it pays
out exactly what went in -- a pot that can pay more than it holds makes the
commissioner a counterparty again, which is the thing play money was chosen to
avoid.
"""

from __future__ import annotations

import pytest

from app.core.pot import Payout, payouts, split


def table(*names):
    return [
        {"rank": i, "user_id": n, "manager": n.title(), "equity": 100_000 - i}
        for i, n in enumerate(names, 1)
    ]


class TestSplitting:
    def test_it_divides_by_the_shares(self):
        assert split(24_000, [50, 33, 17]) == [12_000, 7_920, 4_080]

    def test_nothing_is_lost_to_rounding(self):
        """A pot that does not add up is a pot somebody argues about."""
        for pot in range(1, 5_000, 7):
            for shares in ([50, 33, 17], [60, 40], [100], [34, 33, 33]):
                assert sum(split(pot, shares)) == pot, (pot, shares)

    def test_the_remainder_goes_to_the_winner(self):
        parts = split(100, [34, 33, 33])
        assert parts[0] >= parts[1] >= parts[2]
        assert sum(parts) == 100

    def test_an_empty_pot_pays_nobody(self):
        assert split(0, [50, 33, 17]) == [0, 0, 0]
        assert split(-5, [50, 33, 17]) == [0, 0, 0]

    def test_one_share_takes_everything(self):
        assert split(24_000, [100]) == [24_000]


class TestPayouts:
    def test_the_top_places_are_paid_in_order(self):
        out = payouts(24_000, [50, 33, 17], table("a", "b", "c", "d"))
        assert [p.manager for p in out] == ["A", "B", "C"]
        assert [p.amount for p in out] == [12_000, 7_920, 4_080]

    def test_it_pays_out_exactly_the_pot(self):
        out = payouts(24_000, [50, 33, 17], table("a", "b", "c", "d"))
        assert sum(p.amount for p in out) == 24_000

    def test_fewer_players_than_places_still_spends_it_all(self):
        """Early in a season, or a small league. The rest would go to nobody."""
        out = payouts(4_000, [50, 33, 17], table("a", "b"))
        assert len(out) == 2
        assert sum(p.amount for p in out) == 4_000

    def test_a_single_entrant_takes_the_pot(self):
        out = payouts(2_000, [50, 33, 17], table("a"))
        assert [p.amount for p in out] == [2_000]

    def test_nobody_playing_pays_nothing(self):
        assert payouts(2_000, [50, 33, 17], []) == []

    def test_an_unfunded_pot_pays_nothing(self):
        out = payouts(0, [50, 33, 17], table("a", "b", "c"))
        assert [p.amount for p in out] == [0, 0, 0]

    def test_it_carries_the_rank_it_was_given(self):
        out = payouts(24_000, [50, 33, 17], table("a", "b", "c"))
        assert [p.rank for p in out] == [1, 2, 3]


class TestOnlyEntrantsWin:
    """You have to be in it to win it.

    Paying out on the standings alone lets somebody who never anted take a
    share of other people's money, which is the one way a self-funding pot
    stops being fair.
    """

    def test_the_unpaid_are_left_out_of_the_split(self, tmp_path):
        from app.store import SessionStore

        store = SessionStore(tmp_path / "p.db")
        store.sync_managers([(f"u{i}", f"m{i}", "") for i in range(1, 5)])
        store.set_ante("u2", 2_000)
        store.set_ante("u3", 2_000)
        paid = store.antes()
        assert set(paid) == {"u2", "u3"}

        # u1 tops the table but never paid; the pot is u2 and u3's to split.
        board = [{"user_id": u, "manager": u, "equity": 100_000 - i}
                 for i, u in enumerate(["u1", "u2", "u3", "u4"])]
        entered = [r for r in board if r["user_id"] in paid]
        out = payouts(sum(p["amount"] for p in paid.values()), [50, 33, 17], entered)

        assert [p.user_id for p in out] == ["u2", "u3"]
        assert sum(p.amount for p in out) == 4_000

    def test_an_ante_can_be_undone(self, tmp_path):
        from app.store import SessionStore

        store = SessionStore(tmp_path / "p.db")
        store.sync_managers([("u1", "m1", "")])
        store.set_ante("u1", 2_000)
        assert store.clear_ante("u1") is True
        assert store.antes() == {}
        assert store.clear_ante("u1") is False, "and only once"

    def test_paying_twice_does_not_double_the_pot(self, tmp_path):
        from app.store import SessionStore

        store = SessionStore(tmp_path / "p.db")
        store.sync_managers([("u1", "m1", "")])
        store.set_ante("u1", 2_000)
        store.set_ante("u1", 2_000)
        assert sum(a["amount"] for a in store.antes().values()) == 2_000
