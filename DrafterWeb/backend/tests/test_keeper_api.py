"""The keeper tool.

Nobody signs in -- Sleeper cannot authenticate anyone -- so a manager proves
which of twelve known people they are with a code. Most of these are about
that boundary and the deadline, since those are what a keeper board is for.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from app import main
from app.integrations.sleeper import Manager
from app.store import SessionStore

LEAGUE = "test-league"


@pytest.fixture
def fake_sleeper(tmp_path, pool_2025):
    """A two-manager league whose rosters are real ranked players."""
    from app.integrations.sleeper import SleeperClient

    top = pool_2025.players[:4]
    deep = pool_2025.players[80:82]

    class Fake(SleeperClient):
        def league_managers(self, league_id):
            return [
                Manager(user_id="u1", display_name="brayden", team_name="Team Phoenix"),
                Manager(user_id="u2", display_name="jed", team_name="Slamwich"),
            ]

        def league_rosters(self, league_id):
            return {
                "u1": ["p0", "p1", "gone"],
                "u2": ["p2", "p3", "p4", "p5"],
            }

        def player_directory(self):
            everyone = list(top) + list(deep)
            directory = {
                f"p{i}": {
                    "first_name": p.name.split()[0],
                    "last_name": " ".join(p.name.split()[1:]),
                    "position": p.position,
                    "team": p.team,
                }
                for i, p in enumerate(everyone)
            }
            directory["gone"] = {
                "first_name": "Retired", "last_name": "Fellow",
                "position": "RB", "team": "FA",
            }
            return directory

    return Fake(cache_dir=tmp_path)


@pytest.fixture
def app(tmp_path, monkeypatch, rankings_dir_2025, fake_sleeper):
    monkeypatch.setattr(app_config, "RANKINGS_DIR", rankings_dir_2025)
    monkeypatch.setattr(app_config, "SEASON", 2025)
    monkeypatch.setattr(app_config, "SLEEPER_LEAGUE_ID", LEAGUE)
    monkeypatch.setattr(app_config, "KEEPER_DEADLINE", None)
    monkeypatch.setattr(app_config, "ADMIN_TOKEN", "adm1n")
    monkeypatch.setattr(app_config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(main, "_store", SessionStore(tmp_path / "k.db"))
    monkeypatch.setattr(main, "_sleeper", fake_sleeper)
    return main.app


ADMIN = {"X-Admin-Token": "adm1n"}


@pytest.fixture
def synced(app):
    """The league pulled in, with codes minted."""
    with TestClient(app) as owner:
        owner.post("/api/admin/keepers/sync", headers=ADMIN)
        codes = owner.get("/api/admin/keepers/codes", headers=ADMIN).json()["managers"]
    return {m["user_id"]: m for m in codes}


def claim(client, manager):
    r = client.post(
        "/api/keeper/claim",
        json={"user_id": manager["user_id"], "code": manager["code"]},
    )
    assert r.status_code == 200, r.text
    return r


class TestSyncingTheLeague:
    def test_it_pulls_every_manager(self, app, synced):
        assert len(synced) == 2

    def test_each_gets_a_code(self, synced):
        codes = {m["code"] for m in synced.values()}
        assert len(codes) == 2, "codes must not collide"
        assert all(len(c) == 6 for c in codes)

    def test_codes_avoid_glyphs_people_confuse(self, synced):
        for m in synced.values():
            assert not set(m["code"]) & set("O0I1L")

    def test_syncing_again_keeps_the_codes(self, app, synced):
        """Re-syncing must not invalidate a code already sent out."""
        with TestClient(app) as owner:
            again = owner.post("/api/admin/keepers/sync", headers=ADMIN).json()
            assert again["added"] == 0
            after = owner.get("/api/admin/keepers/codes", headers=ADMIN).json()["managers"]
        assert {m["code"] for m in after} == {m["code"] for m in synced.values()}

    def test_codes_are_admin_only(self, app, synced):
        with TestClient(app) as anyone:
            listed = anyone.get("/api/keeper/managers").json()["managers"]
            assert listed, "the teams themselves are public, to choose from"
            assert all("code" not in m for m in listed)
            assert anyone.get("/api/admin/keepers/codes").status_code == 404


class TestClaiming:
    def test_nothing_is_readable_before_claiming(self, app, synced):
        with TestClient(app) as c:
            assert c.get("/api/keeper/roster").status_code == 403
            assert c.get("/api/keeper").json()["you"] is None

    def test_a_wrong_code_is_refused(self, app, synced):
        with TestClient(app) as c:
            r = c.post("/api/keeper/claim", json={"user_id": "u1", "code": "NOPE99"})
            assert r.status_code == 403

    def test_a_code_for_another_team_does_not_work(self, app, synced):
        with TestClient(app) as c:
            r = c.post(
                "/api/keeper/claim",
                json={"user_id": "u1", "code": synced["u2"]["code"]},
            )
            assert r.status_code == 403

    def test_the_right_code_claims_the_team(self, app, synced):
        with TestClient(app) as c:
            assert claim(c, synced["u1"]).json()["you"]["team_name"] == "Team Phoenix"

    def test_the_code_is_not_case_sensitive(self, app, synced):
        with TestClient(app) as c:
            lower = dict(synced["u1"], code=synced["u1"]["code"].lower())
            claim(c, lower)

    def test_the_claim_sticks_across_requests(self, app, synced):
        with TestClient(app) as c:
            claim(c, synced["u1"])
            assert c.get("/api/keeper").json()["you"]["user_id"] == "u1"


class TestTheRoster:
    def test_it_is_your_own_roster_priced(self, app, synced):
        with TestClient(app) as c:
            claim(c, synced["u1"])
            data = c.get("/api/keeper/roster").json()

        assert len(data["options"]) == 3
        keepable = [o for o in data["options"] if o["keepable"]]
        assert all(o["round"] >= 1 for o in keepable)

    def test_the_cheapest_round_is_first(self, app, synced):
        with TestClient(app) as c:
            claim(c, synced["u2"])
            options = c.get("/api/keeper/roster").json()["options"]
        rounds = [o["round"] for o in options if o["round"]]
        assert rounds == sorted(rounds)

    def test_a_player_off_this_years_board_costs_the_last_round(self, app, synced):
        """He is the cheapest keeper there is, not an ineligible one."""
        with TestClient(app) as c:
            claim(c, synced["u1"])
            data = c.get("/api/keeper/roster").json()
            options = data["options"]

        gone = [o for o in options if not o["ranked"]]
        assert len(gone) == 1
        assert gone[0]["name"] == "Retired Fellow"
        assert gone[0]["round"] == data["rounds"]
        assert gone[0]["adp"] is None
        assert gone[0]["keepable"] is True

    def test_an_unranked_player_can_actually_be_kept(self, app, synced):
        """The whole point of the change -- the round trip has to work."""
        with TestClient(app) as c:
            claim(c, synced["u1"])
            data = c.get("/api/keeper/roster").json()
            unranked = next(o for o in data["options"] if not o["ranked"])

            r = c.post("/api/keeper/pick", json={"player_key": unranked["key"]})
            assert r.status_code == 200, r.text
            assert r.json()["pick"]["round"] == data["rounds"]

            state = c.get("/api/keeper").json()

        assert state["pick"]["player_name"] == "Retired Fellow"
        assert state["pick"]["adp"] is None
        assert state["pick_key"] == unranked["key"]

    def test_someone_elses_unranked_player_is_still_refused(self, app, synced):
        """Keepable everywhere must not mean keepable from anyone's roster."""
        with TestClient(app) as a, TestClient(app) as b:
            claim(a, synced["u1"])
            theirs = next(o for o in a.get("/api/keeper/roster").json()["options"]
                          if not o["ranked"])
            claim(b, synced["u2"])
            r = b.post("/api/keeper/pick", json={"player_key": theirs["key"]})

        assert r.status_code == 422

    def test_you_see_only_your_own(self, app, synced):
        with TestClient(app) as a, TestClient(app) as b:
            claim(a, synced["u1"])
            claim(b, synced["u2"])
            mine = {o["name"] for o in a.get("/api/keeper/roster").json()["options"]}
            theirs = {o["name"] for o in b.get("/api/keeper/roster").json()["options"]}
        assert not (mine & theirs)


class TestPicking:
    def test_you_may_keep_someone_on_your_roster(self, app, synced):
        with TestClient(app) as c:
            claim(c, synced["u1"])
            options = c.get("/api/keeper/roster").json()["options"]
            first = next(o for o in options if o["keepable"])

            r = c.post("/api/keeper/pick", json={"player_key": first["key"]})
            assert r.status_code == 200
            assert r.json()["pick"]["round"] == first["round"]

    def test_you_may_not_keep_someone_elses_player(self, app, synced):
        with TestClient(app) as a, TestClient(app) as b:
            claim(a, synced["u1"])
            claim(b, synced["u2"])
            theirs = next(
                o for o in b.get("/api/keeper/roster").json()["options"] if o["keepable"]
            )
            r = a.post("/api/keeper/pick", json={"player_key": theirs["key"]})
        assert r.status_code == 422
        assert "not on your roster" in r.json()["detail"]

    def test_an_unknown_player_is_refused(self, app, synced):
        with TestClient(app) as c:
            claim(c, synced["u1"])
            r = c.post("/api/keeper/pick", json={"player_key": "RB:XXX:nobody"})
        assert r.status_code == 422

    def test_picking_without_claiming_is_refused(self, app, synced):
        with TestClient(app) as c:
            assert c.post("/api/keeper/pick", json={"player_key": "x"}).status_code == 403

    def test_you_may_change_your_mind(self, app, synced):
        with TestClient(app) as c:
            claim(c, synced["u2"])
            options = [o for o in c.get("/api/keeper/roster").json()["options"] if o["keepable"]]

            c.post("/api/keeper/pick", json={"player_key": options[0]["key"]})
            c.post("/api/keeper/pick", json={"player_key": options[1]["key"]})

            pick = c.get("/api/keeper").json()["pick"]
        assert pick["player_name"] == options[1]["name"]

    def test_only_one_keeper_is_held_at_a_time(self, app, synced):
        with TestClient(app) as c:
            claim(c, synced["u2"])
            options = [o for o in c.get("/api/keeper/roster").json()["options"] if o["keepable"]]
            for o in options[:2]:
                c.post("/api/keeper/pick", json={"player_key": o["key"]})

        with TestClient(app) as owner:
            rows = owner.get("/api/admin/keepers", headers=ADMIN).json()["keepers"]
        assert sum(1 for r in rows if r["user_id"] == "u2" and r["player_name"]) == 1

    def test_the_selection_records_the_price_it_was_made_at(self, app, synced):
        """ADP moves, so what was agreed to has to be recoverable."""
        with TestClient(app) as c:
            claim(c, synced["u1"])
            first = next(o for o in c.get("/api/keeper/roster").json()["options"] if o["keepable"])
            c.post("/api/keeper/pick", json={"player_key": first["key"]})
            pick = c.get("/api/keeper").json()["pick"]

        assert pick["adp"] == pytest.approx(first["adp"], abs=0.05)
        assert pick["round"] == first["round"]
        assert pick["submitted_at"]

    def test_it_can_be_cleared(self, app, synced):
        with TestClient(app) as c:
            claim(c, synced["u1"])
            first = next(o for o in c.get("/api/keeper/roster").json()["options"] if o["keepable"])
            c.post("/api/keeper/pick", json={"player_key": first["key"]})
            assert c.delete("/api/keeper/pick").status_code == 200
            assert c.get("/api/keeper").json()["pick"] is None


class TestTheDeadline:
    @staticmethod
    def _passed(monkeypatch):
        monkeypatch.setattr(
            app_config, "KEEPER_DEADLINE",
            datetime.now(timezone.utc) - timedelta(minutes=1),
        )

    def test_open_until_it_passes(self, app, synced, monkeypatch):
        monkeypatch.setattr(
            app_config, "KEEPER_DEADLINE",
            datetime.now(timezone.utc) + timedelta(days=1),
        )
        with TestClient(app) as c:
            assert c.get("/api/keeper").json()["open"] is True

    def test_picking_stops_once_it_passes(self, app, synced, monkeypatch):
        with TestClient(app) as c:
            claim(c, synced["u1"])
            first = next(o for o in c.get("/api/keeper/roster").json()["options"] if o["keepable"])

            self._passed(monkeypatch)
            r = c.post("/api/keeper/pick", json={"player_key": first["key"]})
        assert r.status_code == 409
        assert "deadline" in r.json()["detail"]

    def test_clearing_stops_too(self, app, synced, monkeypatch):
        with TestClient(app) as c:
            claim(c, synced["u1"])
            self._passed(monkeypatch)
            assert c.delete("/api/keeper/pick").status_code == 409

    def test_no_deadline_leaves_it_open(self, app, synced):
        with TestClient(app) as c:
            assert c.get("/api/keeper").json()["open"] is True


class TestWhoSeesWhat:
    def test_nobody_sees_another_pick_before_the_deadline(self, app, synced):
        with TestClient(app) as a:
            claim(a, synced["u1"])
            first = next(o for o in a.get("/api/keeper/roster").json()["options"] if o["keepable"])
            a.post("/api/keeper/pick", json={"player_key": first["key"]})

        with TestClient(app) as b:
            board = b.get("/api/keeper/board").json()
        assert board["open"] is True
        assert board["keepers"] == [], "keeping is decided against the board, not each other"
        assert board["chosen"] == 1, "how many have answered is fair game"

    def test_everything_opens_once_the_deadline_passes(self, app, synced, monkeypatch):
        with TestClient(app) as a:
            claim(a, synced["u1"])
            first = next(o for o in a.get("/api/keeper/roster").json()["options"] if o["keepable"])
            a.post("/api/keeper/pick", json={"player_key": first["key"]})

        monkeypatch.setattr(
            app_config, "KEEPER_DEADLINE",
            datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        with TestClient(app) as b:
            board = b.get("/api/keeper/board").json()
        assert board["open"] is False
        assert any(k["player_name"] for k in board["keepers"])

    def test_the_owner_sees_them_before_the_deadline(self, app, synced):
        """Chasing whoever has not picked is the reason to look."""
        with TestClient(app) as a:
            claim(a, synced["u1"])
            first = next(o for o in a.get("/api/keeper/roster").json()["options"] if o["keepable"])
            a.post("/api/keeper/pick", json={"player_key": first["key"]})

        with TestClient(app) as owner:
            view = owner.get("/api/admin/keepers", headers=ADMIN).json()
        assert view["chosen"] == 1
        assert view["total"] == 2
        assert any(k["player_name"] is None for k in view["keepers"]), "shows who has not"

    def test_the_owner_view_is_gated(self, app, synced):
        with TestClient(app) as anyone:
            assert anyone.get("/api/admin/keepers").status_code == 404


class TestManagersLeavingTheLeague:
    """A new season brings new members, and loses some.

    Only ever adding left a departed manager holding a working code and a row
    on the board -- and a twelve-team league offering fourteen names.
    """

    def test_a_departed_manager_is_removed(self, app, synced, monkeypatch):
        from app.integrations.sleeper import Manager

        # u2 leaves, u3 joins.
        monkeypatch.setattr(
            main._sleeper, "league_managers",
            lambda league_id: [
                Manager(user_id="u1", display_name="brayden", team_name="Team Phoenix"),
                Manager(user_id="u3", display_name="newcomer", team_name="Newcomer FC"),
            ],
        )
        with TestClient(app) as owner:
            result = owner.post("/api/admin/keepers/sync", headers=ADMIN).json()
            listed = owner.get("/api/admin/keepers/codes", headers=ADMIN).json()["managers"]

        assert result["added"] == 1
        assert result["removed"] == 1
        assert {m["user_id"] for m in listed} == {"u1", "u3"}

    def test_a_departed_manager_keeps_no_selection(self, app, synced, monkeypatch):
        from app.integrations.sleeper import Manager

        with TestClient(app) as c:
            claim(c, synced["u2"])
            first = next(
                o for o in c.get("/api/keeper/roster").json()["options"] if o["keepable"]
            )
            c.post("/api/keeper/pick", json={"player_key": first["key"]})

        monkeypatch.setattr(
            main._sleeper, "league_managers",
            lambda league_id: [
                Manager(user_id="u1", display_name="brayden", team_name="Team Phoenix"),
            ],
        )
        with TestClient(app) as owner:
            owner.post("/api/admin/keepers/sync", headers=ADMIN)
            rows = owner.get("/api/admin/keepers", headers=ADMIN).json()["keepers"]

        assert {r["user_id"] for r in rows} == {"u1"}

    def test_a_remaining_manager_keeps_their_code_and_pick(self, app, synced, monkeypatch):
        from app.integrations.sleeper import Manager

        with TestClient(app) as c:
            claim(c, synced["u1"])
            first = next(
                o for o in c.get("/api/keeper/roster").json()["options"] if o["keepable"]
            )
            c.post("/api/keeper/pick", json={"player_key": first["key"]})

        monkeypatch.setattr(
            main._sleeper, "league_managers",
            lambda league_id: [
                Manager(user_id="u1", display_name="brayden", team_name="Team Phoenix"),
            ],
        )
        with TestClient(app) as owner:
            owner.post("/api/admin/keepers/sync", headers=ADMIN)
            after = owner.get("/api/admin/keepers/codes", headers=ADMIN).json()["managers"]
            rows = owner.get("/api/admin/keepers", headers=ADMIN).json()["keepers"]

        assert after[0]["code"] == synced["u1"]["code"], "a sent code must survive"
        assert rows[0]["player_name"] == first["name"]

    def test_the_departed_manager_can_no_longer_claim(self, app, synced, monkeypatch):
        from app.integrations.sleeper import Manager

        monkeypatch.setattr(
            main._sleeper, "league_managers",
            lambda league_id: [
                Manager(user_id="u1", display_name="brayden", team_name="Team Phoenix"),
            ],
        )
        with TestClient(app) as owner:
            owner.post("/api/admin/keepers/sync", headers=ADMIN)

        with TestClient(app) as c:
            r = c.post(
                "/api/keeper/claim",
                json={"user_id": "u2", "code": synced["u2"]["code"]},
            )
        assert r.status_code == 403, "their code must stop working"
