"""The trading tool end to end.

Real money settles off this, so the tests worth having are the ones about money
moving: that the cap holds when two people buy at once, that a quote cannot be
turned into a stale price, that nothing settles on a judgment call, and that
the ledger closes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from app import main
from app.integrations.sleeper import DraftInfo, Manager, SleeperPick
from app.store import SessionStore

CENTRAL = timezone(timedelta(hours=-5))
LEAGUE = "test-league"
ADMIN = {"X-Admin-Token": "adm1n"}

OPENS = datetime(2026, 9, 1, 9, 0, tzinfo=CENTRAL)
DRAFT = datetime(2026, 9, 1, 18, 30, tzinfo=CENTRAL)


def pick(no, name, position="RB", slot=None, is_keeper=False):
    return SleeperPick(
        pick_no=no, round=(no - 1) // 12 + 1,
        draft_slot=slot if slot is not None else (no - 1) % 12 + 1,
        player_id=str(no), name=name, position=position, team="DET",
        is_keeper=is_keeper,
    )


@pytest.fixture
def picks():
    """Mutable, so a test can advance the draft under a live market."""
    return []


@pytest.fixture
def app(tmp_path, monkeypatch, rankings_dir_2025, picks):
    from app.integrations.sleeper import SleeperClient

    class Fake(SleeperClient):
        def league_managers(self, league_id):
            return [
                Manager(user_id=f"u{i}", display_name=f"m{i}", team_name="")
                for i in range(1, 13)
            ]

        def latest_draft(self, league_id):
            return DraftInfo(
                draft_id="d1", status="pre_draft", draft_type="snake", season="2025",
                teams=12, rounds=15, slot_to_roster={}, slots={},
                draft_order={f"u{i}": i for i in range(1, 13)},
            )

        def picks(self, draft_id):
            return list(picks)

        def league_rosters(self, league_id):
            return {}

        def player_directory(self):
            return {}

    monkeypatch.setattr(app_config, "RANKINGS_DIR", rankings_dir_2025)
    monkeypatch.setattr(app_config, "SEASON", 2025)
    monkeypatch.setattr(app_config, "SLEEPER_LEAGUE_ID", LEAGUE)
    monkeypatch.setattr(app_config, "ADMIN_TOKEN", "adm1n")
    monkeypatch.setattr(app_config, "ADMIN_EMAILS", set())
    # The numbers that ship, so this file tests what the league plays.
    monkeypatch.setattr(app_config, "CONTRACTS_CAP", 25)
    monkeypatch.setattr(app_config, "CONTRACTS_B", 50.0)
    monkeypatch.setattr(app_config, "CONTRACTS_SPREAD", 1)
    monkeypatch.setattr(app_config, "CONTRACTS_START", 100_000)
    monkeypatch.setattr(main, "_store", SessionStore(tmp_path / "c.db"))
    monkeypatch.setattr(main, "_sleeper", Fake(cache_dir=tmp_path))
    return main.app


@pytest.fixture
def codes(app):
    with TestClient(app) as owner:
        owner.post("/api/admin/keepers/sync", headers=ADMIN)
        listed = owner.get("/api/admin/keepers/codes", headers=ADMIN).json()["managers"]
    return {m["user_id"]: m for m in listed}


@pytest.fixture
def slate(app):
    with TestClient(app) as owner:
        r = owner.post(
            "/api/admin/contracts/slates",
            headers=ADMIN,
            json={"name": "Draft night", "kind": "draft",
                  "draft_start": DRAFT.isoformat()},
        )
    assert r.status_code == 200, r.text
    return r.json()["slate"]


@pytest.fixture
def player(pool_2025):
    return pool_2025.players[30]


@pytest.fixture
def market(app, slate, player):
    with TestClient(app) as owner:
        r = owner.post(
            "/api/admin/contracts/markets",
            headers=ADMIN,
            json={"slate_id": slate["slate_id"], "kind": "player_by_pick",
                  "params": {"player_key": player.key, "pick": 30}},
        )
    assert r.status_code == 200, r.text
    return r.json()["market"]


def signed_in(app, manager):
    """A client holding a claimed manager code."""
    client = TestClient(app)
    client.__enter__()
    r = client.post(
        "/api/keeper/claim",
        json={"user_id": manager["user_id"], "code": manager["code"]},
    )
    assert r.status_code == 200, r.text
    return client


def freeze(monkeypatch, when):
    """Pin the clock inside the trading window."""
    import app.api.contracts as mod

    monkeypatch.setattr(mod, "_now", lambda: when)


@pytest.fixture
def during(monkeypatch):
    freeze(monkeypatch, datetime(2026, 9, 1, 12, 0, tzinfo=CENTRAL))


class TestOpeningMarkets:
    def test_a_draft_slate_opens_on_the_tuesday_and_closes_at_the_first_pick(self, slate):
        assert slate["opens_at"].startswith("2026-09-01T09:00")
        assert slate["closes_at"].startswith("2026-09-01T18:30")

    def test_a_market_is_priced_from_adp(self, market, player):
        assert player.name in market["question"]
        assert 10 <= market["opening"] <= 90

    def test_it_reports_what_it_will_cost_the_house(self, app, slate, player):
        with TestClient(app) as owner:
            made = owner.post(
                "/api/admin/contracts/markets", headers=ADMIN,
                json={"slate_id": slate["slate_id"], "kind": "player_by_pick",
                      "params": {"player_key": player.key, "pick": 40}},
            ).json()
        assert made["exposure"] >= 694, "at least b*ln2"

    def test_a_market_the_board_already_answered_is_refused(self, app, slate, player, picks):
        picks.append(pick(2, player.name))
        with TestClient(app) as owner:
            r = owner.post(
                "/api/admin/contracts/markets", headers=ADMIN,
                json={"slate_id": slate["slate_id"], "kind": "player_by_pick",
                      "params": {"player_key": player.key, "pick": 30}},
            )
        assert r.status_code == 422
        assert "already decided" in r.json()["detail"]

    def test_opening_markets_is_admin_only(self, app, slate, player):
        with TestClient(app) as anyone:
            r = anyone.post(
                "/api/admin/contracts/markets",
                json={"slate_id": slate["slate_id"], "kind": "player_by_pick",
                      "params": {"player_key": player.key, "pick": 30}},
            )
        assert r.status_code == 404, "the admin surface does not announce itself"


class TestWhoMayTrade:
    def test_a_stranger_cannot_trade(self, app, market, during):
        with TestClient(app) as anyone:
            r = anyone.post("/api/contracts/trade",
                            json={"market_id": market["market_id"], "side": "yes",
                                  "shares": 1})
        assert r.status_code == 403

    def test_a_stranger_can_still_read_the_board(self, app, slate, market):
        with TestClient(app) as anyone:
            r = anyone.get(f"/api/contracts/slates/{slate['slate_id']}")
        assert r.status_code == 200
        assert len(r.json()["markets"]) == 1
        assert "you" not in r.json()["markets"][0]

    def test_a_manager_code_is_the_sign_in(self, app, market, codes, during):
        client = signed_in(app, codes["u1"])
        r = client.post("/api/contracts/trade",
                        json={"market_id": market["market_id"], "side": "yes",
                              "shares": 1})
        assert r.status_code == 200, r.text


class TestTrading:
    def test_buying_moves_the_price_and_gives_you_contracts(self, app, market, codes, during):
        client = signed_in(app, codes["u1"])
        before = market["opening"]
        out = client.post("/api/contracts/trade",
                          json={"market_id": market["market_id"], "side": "yes",
                                "shares": 5}).json()
        assert out["market"]["price_yes"] > before
        assert out["market"]["you"]["yes"] == 5
        assert out["traded"]["cash"] > 0

    def test_a_quote_costs_nothing_and_changes_nothing(self, app, market, codes, during):
        client = signed_in(app, codes["u1"])
        quoted = client.post("/api/contracts/quote",
                             json={"market_id": market["market_id"], "side": "yes",
                                   "shares": 5}).json()
        assert quoted["indicative"] is True

        slate_id = market["slate_id"]
        board = client.get(f"/api/contracts/slates/{slate_id}").json()
        assert board["markets"][0]["traded"] == 0, "a quote is not a trade"

    def test_the_cap_holds(self, app, market, codes, during):
        client = signed_in(app, codes["u1"])
        client.post("/api/contracts/trade",
                    json={"market_id": market["market_id"], "side": "yes",
                          "shares": app_config.CONTRACTS_CAP})
        r = client.post("/api/contracts/trade",
                        json={"market_id": market["market_id"], "side": "yes",
                              "shares": 1})
        assert r.status_code == 409
        assert "limit" in r.json()["detail"]

    def test_two_managers_have_their_own_caps(self, app, market, codes, during):
        for who in ("u1", "u2"):
            client = signed_in(app, codes[who])
            r = client.post("/api/contracts/trade",
                            json={"market_id": market["market_id"], "side": "yes",
                                  "shares": 5})
            assert r.status_code == 200, (who, r.text)

    def test_the_second_buyer_pays_more(self, app, market, codes, during):
        first = signed_in(app, codes["u1"]).post(
            "/api/contracts/trade",
            json={"market_id": market["market_id"], "side": "yes", "shares": 5},
        ).json()["traded"]["cash"]
        second = signed_in(app, codes["u2"]).post(
            "/api/contracts/trade",
            json={"market_id": market["market_id"], "side": "yes", "shares": 5},
        ).json()["traded"]["cash"]
        assert second > first

    def test_selling_returns_money(self, app, market, codes, during):
        client = signed_in(app, codes["u1"])
        client.post("/api/contracts/trade",
                    json={"market_id": market["market_id"], "side": "yes", "shares": 5})
        out = client.post("/api/contracts/trade",
                          json={"market_id": market["market_id"], "side": "yes",
                                "shares": -5}).json()
        assert out["traded"]["cash"] < 0
        assert out["market"]["you"]["yes"] == 0

    def test_a_stale_quote_cannot_be_held_to(self, app, market, codes, during):
        """The price charged is computed after everyone who got there first."""
        one = signed_in(app, codes["u1"])
        two = signed_in(app, codes["u2"])

        quoted = one.post("/api/contracts/quote",
                          json={"market_id": market["market_id"], "side": "yes",
                                "shares": 5}).json()["cash"]
        two.post("/api/contracts/trade",
                 json={"market_id": market["market_id"], "side": "yes", "shares": 5})
        charged = one.post("/api/contracts/trade",
                           json={"market_id": market["market_id"], "side": "yes",
                                 "shares": 5}).json()["traded"]["cash"]

        assert charged > quoted, "u2 got there first and the line moved"


class TestTheWindow:
    def test_nothing_trades_before_the_slate_opens(self, app, market, codes, monkeypatch):
        freeze(monkeypatch, datetime(2026, 8, 30, 12, tzinfo=CENTRAL))
        client = signed_in(app, codes["u1"])
        r = client.post("/api/contracts/trade",
                        json={"market_id": market["market_id"], "side": "yes",
                              "shares": 1})
        assert r.status_code == 409
        assert "not opened" in r.json()["detail"]

    def test_nothing_trades_once_the_draft_starts(self, app, market, codes, monkeypatch):
        freeze(monkeypatch, datetime(2026, 9, 1, 18, 30, tzinfo=CENTRAL))
        client = signed_in(app, codes["u1"])
        r = client.post("/api/contracts/trade",
                        json={"market_id": market["market_id"], "side": "yes",
                              "shares": 1})
        assert r.status_code == 409
        assert "trading closed" in r.json()["detail"]

    def test_the_board_still_reads_after_the_close(self, app, slate, market, monkeypatch):
        freeze(monkeypatch, datetime(2026, 9, 1, 19, 0, tzinfo=CENTRAL))
        with TestClient(app) as anyone:
            board = anyone.get(f"/api/contracts/slates/{slate['slate_id']}").json()
        assert board["markets"][0]["phase"] == "closed"


class TestSettlement:
    def test_it_will_not_settle_what_the_draft_has_not_answered(self, app, market):
        with TestClient(app) as owner:
            r = owner.post(
                f"/api/admin/contracts/markets/{market['market_id']}/resolve",
                headers=ADMIN,
            )
        assert r.status_code == 409
        assert "not answered" in r.json()["detail"]

    def test_there_is_no_route_to_declare_an_outcome(self, app):
        """A commissioner who can overrule the feed will be asked to."""
        from app.api.contracts_admin import router

        for route in router.routes:
            assert "outcome" not in getattr(route, "path", "")

    def test_a_settled_market_pays_the_winners(self, app, market, codes, picks,
                                               during, player):
        client = signed_in(app, codes["u1"])
        client.post("/api/contracts/trade",
                    json={"market_id": market["market_id"], "side": "yes", "shares": 5})

        picks.append(pick(4, player.name))
        with TestClient(app) as owner:
            out = owner.post(
                f"/api/admin/contracts/markets/{market['market_id']}/resolve",
                headers=ADMIN,
            ).json()

        assert out["outcome"] == "yes"
        assert out["managers"]["u1"] > 0, "bought at under a dollar, paid a dollar"

    def test_settling_twice_is_refused(self, app, market, picks, player):
        picks.append(pick(4, player.name))
        with TestClient(app) as owner:
            first = owner.post(
                f"/api/admin/contracts/markets/{market['market_id']}/resolve",
                headers=ADMIN)
            again = owner.post(
                f"/api/admin/contracts/markets/{market['market_id']}/resolve",
                headers=ADMIN)
        assert first.status_code == 200
        assert again.status_code == 409

    def test_the_whole_slate_settles_in_one_pass(self, app, slate, codes, picks,
                                                 pool_2025, during):
        """The draft answers in bursts; calling these one at a time is a job."""
        with TestClient(app) as owner:
            for i, p in enumerate(pool_2025.players[:3]):
                owner.post("/api/admin/contracts/markets", headers=ADMIN,
                           json={"slate_id": slate["slate_id"], "kind": "player_by_pick",
                                 "params": {"player_key": p.key, "pick": 24}})

        picks.extend(pick(i + 1, p.name) for i, p in enumerate(pool_2025.players[:2]))
        with TestClient(app) as owner:
            out = owner.post("/api/admin/contracts/resolve", headers=ADMIN).json()

        assert len(out["settled"]) == 2
        assert len(out["waiting"]) == 1, "the third is genuinely undecided"

    def test_the_ledger_closes(self, app, market, codes, picks, during, player):
        """What the house keeps is exactly what the league loses."""
        for who in ("u1", "u2"):
            signed_in(app, codes[who]).post(
                "/api/contracts/trade",
                json={"market_id": market["market_id"], "side": "yes", "shares": 3})
        signed_in(app, codes["u3"]).post(
            "/api/contracts/trade",
            json={"market_id": market["market_id"], "side": "no", "shares": 4})

        picks.append(pick(4, player.name))
        with TestClient(app) as owner:
            owner.post(f"/api/admin/contracts/markets/{market['market_id']}/resolve",
                       headers=ADMIN)
            ledger = owner.get("/api/admin/contracts/ledger", headers=ADMIN).json()

        league = sum(row["net"] for row in ledger["managers"])
        assert league + ledger["house"] == 0
        assert ledger["settled_markets"] == 1

    def test_the_ledger_names_managers(self, app, market, codes, picks, during, player):
        signed_in(app, codes["u1"]).post(
            "/api/contracts/trade",
            json={"market_id": market["market_id"], "side": "yes", "shares": 2})
        picks.append(pick(4, player.name))
        with TestClient(app) as owner:
            owner.post(f"/api/admin/contracts/markets/{market['market_id']}/resolve",
                       headers=ADMIN)
            ledger = owner.get("/api/admin/contracts/ledger", headers=ADMIN).json()
        assert ledger["managers"][0]["manager"] == "m1"


class TestYourBook:
    def test_it_shows_open_positions(self, app, market, codes, during):
        client = signed_in(app, codes["u1"])
        client.post("/api/contracts/trade",
                    json={"market_id": market["market_id"], "side": "yes", "shares": 4})
        book = client.get("/api/contracts/me").json()
        assert len(book["open"]) == 1
        assert book["open"][0]["yes"] == 4

    def test_a_settled_position_moves_to_realised(self, app, market, codes, picks,
                                                  during, player):
        client = signed_in(app, codes["u1"])
        client.post("/api/contracts/trade",
                    json={"market_id": market["market_id"], "side": "yes", "shares": 4})
        picks.append(pick(4, player.name))
        with TestClient(app) as owner:
            owner.post(f"/api/admin/contracts/markets/{market['market_id']}/resolve",
                       headers=ADMIN)

        book = client.get("/api/contracts/me").json()
        assert book["open"] == []
        assert len(book["settled"]) == 1
        assert book["realised"] > 0

    def test_it_needs_a_sign_in(self, app):
        with TestClient(app) as anyone:
            assert anyone.get("/api/contracts/me").status_code == 403


class TestItHoldsUnderConcurrency:
    """SQLite plus a position cap plus real money.

    The sequential tests prove the rules; these prove the transaction. Two
    managers pressing buy at the same instant must not both price against the
    same log -- that is the difference between five contracts and ten, and
    between the house's exposure being what it budgeted and being double.
    """

    def test_one_manager_pressing_twice_cannot_exceed_the_cap(
        self, app, market, codes, during
    ):
        import threading

        client = signed_in(app, codes["u1"])
        cap = app_config.CONTRACTS_CAP
        results, lock = [], threading.Lock()

        def buy():
            r = client.post(
                "/api/contracts/trade",
                json={"market_id": market["market_id"], "side": "yes",
                      "shares": cap // 2 + 1},
            )
            with lock:
                results.append(r.status_code)

        threads = [threading.Thread(target=buy) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        board = client.get("/api/contracts/me").json()
        held = board["open"][0]["yes"] if board["open"] else 0
        assert held <= cap, f"cap breached: {held} contracts from {results}"
        assert 200 in results, "at least one should have gone through"

    def test_simultaneous_buyers_each_get_their_own_price(
        self, app, market, codes, during
    ):
        import threading

        clients = [signed_in(app, codes[f"u{i}"]) for i in range(1, 5)]
        charged, lock = [], threading.Lock()

        def buy(client):
            r = client.post(
                "/api/contracts/trade",
                json={"market_id": market["market_id"], "side": "yes", "shares": 5},
            )
            if r.status_code == 200:
                with lock:
                    charged.append(r.json()["traded"]["cash"])

        threads = [threading.Thread(target=buy, args=(c,)) for c in clients]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(charged) == 4, "all four should trade"
        assert len(set(charged)) == 4, "each priced against a different book"

    def test_the_books_still_balance_after_a_race(
        self, app, market, codes, picks, during, player
    ):
        """The property that matters: whatever the interleaving, it closes."""
        import threading

        def buy(who, side):
            signed_in(app, codes[who]).post(
                "/api/contracts/trade",
                json={"market_id": market["market_id"], "side": side, "shares": 4},
            )

        threads = [
            threading.Thread(target=buy, args=(f"u{i}", "yes" if i % 2 else "no"))
            for i in range(1, 9)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        picks.append(pick(4, player.name))
        with TestClient(app) as owner:
            owner.post(
                f"/api/admin/contracts/markets/{market['market_id']}/resolve",
                headers=ADMIN,
            )
            ledger = owner.get("/api/admin/contracts/ledger", headers=ADMIN).json()

        league = sum(row["net"] for row in ledger["managers"])
        assert league + ledger["house"] == 0


class TestRemovingAMarket:
    """The only destructive route, and it is narrow on purpose."""

    def test_an_untraded_market_can_be_dropped(self, app, market):
        with TestClient(app) as owner:
            r = owner.delete(
                f"/api/admin/contracts/markets/{market['market_id']}", headers=ADMIN
            )
        assert r.status_code == 200
        with TestClient(app) as anyone:
            board = anyone.get(
                f"/api/contracts/slates/{market['slate_id']}").json()
        assert board["markets"] == []

    def test_a_traded_market_stays(self, app, market, codes, during):
        """It is somebody's position, and real money."""
        signed_in(app, codes["u1"]).post(
            "/api/contracts/trade",
            json={"market_id": market["market_id"], "side": "yes", "shares": 1})

        with TestClient(app) as owner:
            r = owner.delete(
                f"/api/admin/contracts/markets/{market['market_id']}", headers=ADMIN)
        assert r.status_code == 409
        assert "traded" in r.json()["detail"]

    def test_a_settled_market_stays(self, app, market, picks, player):
        picks.append(pick(4, player.name))
        with TestClient(app) as owner:
            owner.post(
                f"/api/admin/contracts/markets/{market['market_id']}/resolve",
                headers=ADMIN)
            r = owner.delete(
                f"/api/admin/contracts/markets/{market['market_id']}", headers=ADMIN)
        assert r.status_code == 409

    def test_it_is_admin_only(self, app, market):
        with TestClient(app) as anyone:
            r = anyone.delete(f"/api/admin/contracts/markets/{market['market_id']}")
        assert r.status_code == 404


@pytest.fixture
def play_slate(app):
    with TestClient(app) as owner:
        r = owner.post(
            "/api/admin/contracts/slates", headers=ADMIN,
            json={"name": "Play night", "kind": "draft", "stakes": "play",
                  "draft_start": DRAFT.isoformat()},
        )
    return r.json()["slate"]


@pytest.fixture
def real_slate(app):
    with TestClient(app) as owner:
        r = owner.post(
            "/api/admin/contracts/slates", headers=ADMIN,
            json={"name": "For money", "kind": "draft", "stakes": "real",
                  "draft_start": DRAFT.isoformat()},
        )
    return r.json()["slate"]


def a_market(app, slate, player, pick_no=30):
    with TestClient(app) as owner:
        r = owner.post(
            "/api/admin/contracts/markets", headers=ADMIN,
            json={"slate_id": slate["slate_id"], "kind": "player_by_pick",
                  "params": {"player_key": player.key, "pick": pick_no}},
        )
    assert r.status_code == 200, r.text
    return r.json()["market"]


def store_of():
    from app import main

    return main._store


class TestWhichMoney:
    def test_play_is_the_default(self, slate):
        assert slate["stakes"] == "play", "the safe one wins a tie"

    def test_a_real_slate_can_be_opened(self, real_slate):
        assert real_slate["stakes"] == "real"

    def test_a_market_carries_the_stakes_of_its_slate(self, app, play_slate, player):
        made = a_market(app, play_slate, player)
        with TestClient(app) as anyone:
            board = anyone.get(
                f"/api/contracts/slates/{made['slate_id']}").json()["markets"]
        assert board[0]["stakes"] == "play"

    def test_a_real_market_says_so_too(self, app, real_slate, player):
        made = a_market(app, real_slate, player)
        with TestClient(app) as anyone:
            board = anyone.get(
                f"/api/contracts/slates/{made['slate_id']}").json()["markets"]
        assert board[0]["stakes"] == "real"


class TestTheBankroll:
    def test_everyone_starts_with_the_full_amount(self, app, codes):
        client = signed_in(app, codes["u1"])
        assert client.get("/api/contracts").json()["balance"] == 100_000

    def test_buying_spends_it(self, app, play_slate, player, codes, during):
        made = a_market(app, play_slate, player)
        client = signed_in(app, codes["u1"])
        out = client.post("/api/contracts/trade",
                          json={"market_id": made["market_id"], "side": "yes",
                                "shares": 25}).json()
        assert out["balance"] == 100_000 - out["traded"]["cash"]

    def test_selling_gives_most_of_it_back(self, app, play_slate, player,
                                           codes, during):
        made = a_market(app, play_slate, player)
        client = signed_in(app, codes["u1"])
        client.post("/api/contracts/trade",
                    json={"market_id": made["market_id"], "side": "yes", "shares": 25})
        out = client.post("/api/contracts/trade",
                          json={"market_id": made["market_id"], "side": "yes",
                                "shares": -25}).json()
        assert 99_000 < out["balance"] < 100_000, "back, less the spread both ways"

    def test_winning_puts_more_in_than_came_out(self, app, play_slate, player,
                                                codes, picks, during):
        made = a_market(app, play_slate, player)
        client = signed_in(app, codes["u1"])
        client.post("/api/contracts/trade",
                    json={"market_id": made["market_id"], "side": "yes", "shares": 20})
        picks.append(pick(4, player.name))
        with TestClient(app) as owner:
            owner.post(f"/api/admin/contracts/markets/{made['market_id']}/resolve",
                       headers=ADMIN)
        assert client.get("/api/contracts/me").json()["balance"] > 100_000


class TestTheTwoBalancesAgree:
    """One is SQL, the other replays every market.

    `store.balance` exists because the affordability check has to run inside
    the trade's write transaction. Two implementations of the same money
    calculation is exactly the pair that drifts, so they are checked together.
    """

    def test_after_trading_across_markets(self, app, play_slate, codes,
                                          during, pool_2025):
        client = signed_in(app, codes["u1"])
        for i, p in enumerate(pool_2025.players[10:14]):
            made = a_market(app, play_slate, p, pick_no=40 + i)
            client.post("/api/contracts/trade",
                        json={"market_id": made["market_id"], "side": "yes",
                              "shares": 5 + i})

        assert store_of().balance("u1", 100_000) == \
            client.get("/api/contracts/me").json()["balance"]

    def test_after_settlement(self, app, play_slate, player, codes, picks, during):
        made = a_market(app, play_slate, player)
        client = signed_in(app, codes["u1"])
        client.post("/api/contracts/trade",
                    json={"market_id": made["market_id"], "side": "yes", "shares": 20})
        picks.append(pick(4, player.name))
        with TestClient(app) as owner:
            owner.post(f"/api/admin/contracts/markets/{made['market_id']}/resolve",
                       headers=ADMIN)

        assert store_of().balance("u1", 100_000) == \
            client.get("/api/contracts/me").json()["balance"]

    def test_after_a_losing_market(self, app, play_slate, player, codes,
                                   picks, during, pool_2025):
        made = a_market(app, play_slate, player, pick_no=3)
        client = signed_in(app, codes["u1"])
        client.post("/api/contracts/trade",
                    json={"market_id": made["market_id"], "side": "yes", "shares": 20})
        picks.extend(pick(i, f"Somebody {i}") for i in range(1, 4))
        with TestClient(app) as owner:
            owner.post(f"/api/admin/contracts/markets/{made['market_id']}/resolve",
                       headers=ADMIN)

        assert store_of().balance("u1", 100_000) < 100_000
        assert store_of().balance("u1", 100_000) == \
            client.get("/api/contracts/me").json()["balance"]


class TestRealMoneyKeepsOut:
    def test_it_never_touches_the_wallet(self, app, real_slate, player,
                                         codes, during):
        made = a_market(app, real_slate, player)
        client = signed_in(app, codes["u1"])
        r = client.post("/api/contracts/trade",
                        json={"market_id": made["market_id"], "side": "yes",
                              "shares": 25})
        assert r.status_code == 200, r.text
        assert store_of().balance("u1", 100_000) == 100_000
        assert r.json()["balance"] is None

    def test_an_empty_wallet_still_trades_a_real_market(self, app, real_slate,
                                                        player, codes, during,
                                                        monkeypatch):
        """There is no wallet to be empty. It settles up afterwards."""
        monkeypatch.setattr(app_config, "CONTRACTS_START", 0)
        made = a_market(app, real_slate, player)
        r = signed_in(app, codes["u1"]).post(
            "/api/contracts/trade",
            json={"market_id": made["market_id"], "side": "yes", "shares": 25})
        assert r.status_code == 200, r.text


class TestYouCannotOverspend:
    def test_a_trade_beyond_the_balance_is_refused(self, app, play_slate, player,
                                                   codes, during, monkeypatch):
        monkeypatch.setattr(app_config, "CONTRACTS_START", 100)
        made = a_market(app, play_slate, player)
        r = signed_in(app, codes["u1"]).post(
            "/api/contracts/trade",
            json={"market_id": made["market_id"], "side": "yes", "shares": 25})
        assert r.status_code == 409
        assert "you have" in r.json()["detail"]

    def test_selling_is_allowed_with_nothing_left(self, app, play_slate, player,
                                                  codes, during, monkeypatch):
        made = a_market(app, play_slate, player)
        client = signed_in(app, codes["u1"])
        client.post("/api/contracts/trade",
                    json={"market_id": made["market_id"], "side": "yes", "shares": 25})
        monkeypatch.setattr(app_config, "CONTRACTS_START", 0)
        out = client.post("/api/contracts/trade",
                          json={"market_id": made["market_id"], "side": "yes",
                                "shares": -25})
        assert out.status_code == 200, "selling returns money rather than costing it"

    def test_two_fast_clicks_cannot_spend_it_twice(self, app, play_slate, player,
                                                   codes, during, monkeypatch):
        """Why the check reads on the transaction's own connection."""
        import threading

        monkeypatch.setattr(app_config, "CONTRACTS_START", 1_600)
        made = a_market(app, play_slate, player)
        client = signed_in(app, codes["u1"])

        codes_seen, lock = [], threading.Lock()

        def buy():
            r = client.post("/api/contracts/trade",
                            json={"market_id": made["market_id"], "side": "yes",
                                  "shares": 20})
            with lock:
                codes_seen.append(r.status_code)

        threads = [threading.Thread(target=buy) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        left = store_of().balance("u1", 1_600)
        assert left >= 0, f"overspent to {left} from {codes_seen}"


class TestStandings:
    def test_the_whole_league_appears(self, app, codes):
        table = signed_in(app, codes["u1"]).get(
            "/api/contracts/leaderboard").json()["standings"]
        assert len(table) == 12
        assert {r["equity"] for r in table} == {100_000}

    def test_a_winner_rises(self, app, play_slate, player, codes, picks, during):
        made = a_market(app, play_slate, player)
        signed_in(app, codes["u1"]).post(
            "/api/contracts/trade",
            json={"market_id": made["market_id"], "side": "yes", "shares": 25})
        picks.append(pick(4, player.name))
        with TestClient(app) as owner:
            owner.post(f"/api/admin/contracts/markets/{made['market_id']}/resolve",
                       headers=ADMIN)

        table = signed_in(app, codes["u2"]).get(
            "/api/contracts/leaderboard").json()["standings"]
        assert table[0]["user_id"] == "u1"
        assert table[0]["rank"] == 1
        assert table[0]["profit"] > 0

    def test_a_loser_sinks_below_the_untraded(self, app, play_slate, player,
                                              codes, picks, during):
        made = a_market(app, play_slate, player, pick_no=3)
        signed_in(app, codes["u1"]).post(
            "/api/contracts/trade",
            json={"market_id": made["market_id"], "side": "yes", "shares": 25})
        picks.extend(pick(i, f"Somebody {i}") for i in range(1, 4))
        with TestClient(app) as owner:
            owner.post(f"/api/admin/contracts/markets/{made['market_id']}/resolve",
                       headers=ADMIN)

        table = signed_in(app, codes["u2"]).get(
            "/api/contracts/leaderboard").json()["standings"]
        assert table[-1]["user_id"] == "u1"

    def test_it_marks_which_row_is_yours(self, app, codes):
        client = signed_in(app, codes["u3"])
        assert client.get("/api/contracts/leaderboard").json()["you"] == "u3"

    def test_real_money_stays_off_it(self, app, real_slate, player, codes, during):
        """Two kinds of money in one column would measure nothing."""
        made = a_market(app, real_slate, player)
        signed_in(app, codes["u1"]).post(
            "/api/contracts/trade",
            json={"market_id": made["market_id"], "side": "yes", "shares": 25})

        table = signed_in(app, codes["u2"]).get(
            "/api/contracts/leaderboard").json()["standings"]
        assert {r["equity"] for r in table} == {100_000}
