"""The owner's view across every session.

It crosses the ownership boundary the rest of the app enforces, so most of
these are about the gate rather than the data: it fails closed, it refuses a
stranger, and it never turns into a way to change anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from app import main
from app.owner import ACCESS_EMAIL_HEADER
from app.store import SessionStore

OWNER = "bschaffer3@live.com"
ADMIN = {ACCESS_EMAIL_HEADER: OWNER}


@pytest.fixture
def shared_app(tmp_path, monkeypatch, rankings_dir_2025):
    monkeypatch.setattr(app_config, "RANKINGS_DIR", rankings_dir_2025)
    monkeypatch.setattr(app_config, "SEASON", 2025)
    monkeypatch.setattr(main, "_store", SessionStore(tmp_path / "admin.db"))
    monkeypatch.setattr(app_config, "ADMIN_EMAILS", {OWNER})
    monkeypatch.setattr(app_config, "ADMIN_TOKEN", "")
    return main.app


@pytest.fixture
def client(shared_app):
    with TestClient(shared_app) as c:
        yield c


def _draft(order):
    from app.integrations.sleeper import DraftInfo

    return DraftInfo(
        draft_id="d", status="pre_draft", draft_type="snake", season="2026",
        teams=12, rounds=15, slot_to_roster={}, slots={}, draft_order=order,
    )


def make_session(client, **body):
    payload = {"your_slot": 1, "seed": 5}
    payload.update(body)
    r = client.post("/api/sessions", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


class TestTheGate:
    def test_a_visitor_gets_nothing(self, client):
        for path in ("/api/admin/whoami", "/api/admin/sessions", "/api/admin/sessions/x"):
            assert client.get(path).status_code == 404, path

    def test_it_is_404_not_403(self, client):
        """A distinct status confirms the route exists and invites knocking."""
        assert client.get("/api/admin/sessions").status_code == 404

    def test_the_owner_is_admitted(self, client):
        r = client.get("/api/admin/whoami", headers=ADMIN)
        assert r.status_code == 200
        assert r.json()["admin"] == OWNER

    def test_another_verified_person_is_not(self, client):
        """Access lets a whole organisation in; the allowlist picks one of them."""
        other = {ACCESS_EMAIL_HEADER: "someone.else@example.com"}
        assert client.get("/api/admin/sessions", headers=other).status_code == 404

    def test_the_address_is_matched_case_insensitively(self, client):
        shouty = {ACCESS_EMAIL_HEADER: OWNER.upper()}
        assert client.get("/api/admin/whoami", headers=shouty).status_code == 200

    def test_with_nothing_configured_it_is_shut(self, shared_app, monkeypatch):
        monkeypatch.setattr(app_config, "ADMIN_EMAILS", set())
        monkeypatch.setattr(app_config, "ADMIN_TOKEN", "")
        with TestClient(shared_app) as c:
            assert c.get("/api/admin/sessions", headers=ADMIN).status_code == 404

    def test_a_token_also_works(self, shared_app, monkeypatch):
        """So the view is usable locally, and before Access is configured."""
        monkeypatch.setattr(app_config, "ADMIN_EMAILS", set())
        monkeypatch.setattr(app_config, "ADMIN_TOKEN", "s3cret")
        with TestClient(shared_app) as c:
            assert c.get("/api/admin/whoami", headers={"X-Admin-Token": "s3cret"}).status_code == 200
            assert c.get("/api/admin/whoami", headers={"X-Admin-Token": "wrong"}).status_code == 404


class TestSeeingEverySession:
    def test_it_crosses_the_ownership_boundary(self, shared_app):
        """The whole point: sessions the admin's own browser cannot open."""
        with TestClient(shared_app) as alice, TestClient(shared_app) as bob:
            make_session(alice, name="alice draft")
            make_session(bob, name="bob draft")

            with TestClient(shared_app) as admin:
                listing = admin.get("/api/admin/sessions", headers=ADMIN).json()

                names = {s["name"] for s in listing["sessions"]}
                assert names == {"alice draft", "bob draft"}
                assert listing["owners"] == 2
                # And that third browser sees none of them as its own.
                assert admin.get("/api/sessions").json()["sessions"] == []

    def test_owners_are_shown_as_a_digest_not_their_key(self, client):
        make_session(client, name="mine")
        session = client.get("/api/admin/sessions", headers=ADMIN).json()["sessions"][0]

        assert session["owner"]
        assert len(session["owner"]) <= 12, "a label, not the cookie value"
        assert "@" not in session["owner"], "cookie-owned sessions are anonymous"

    def test_it_can_be_filtered_by_tool(self, client):
        make_session(client, name="a mock")
        assert client.get("/api/admin/sessions?mode=mock", headers=ADMIN).json()["count"] == 1
        assert client.get("/api/admin/sessions?mode=assistant", headers=ADMIN).json()["count"] == 0

    def test_a_board_can_be_opened(self, shared_app):
        with TestClient(shared_app) as maker:
            session = make_session(maker, name="theirs", your_slot=3)
            maker.post(f"/api/sessions/{session['id']}/simulate")

        with TestClient(shared_app) as admin:
            board = admin.get(f"/api/admin/sessions/{session['id']}", headers=ADMIN).json()
            assert board["complete"] is True
            assert len(board["picks"]) == 12 * 15
            assert len(board["rosters"]) == 12
            assert board["config"]["your_slot"] == 3

    def test_a_missing_session_is_404(self, client):
        assert client.get("/api/admin/sessions/nope", headers=ADMIN).status_code == 404


class TestTheListingReportsItsOwnLimit:
    """The page filters and pages what it is given, so what it is given matters.

    A listing that quietly stops at its limit looks like the whole set, and
    the oldest sessions vanish with nothing on the page saying so.
    """

    def test_the_total_counts_past_the_limit(self, shared_app):
        with TestClient(shared_app) as maker:
            for i in range(5):
                make_session(maker, name=f"draft {i}")

            with TestClient(shared_app) as admin:
                listing = admin.get(
                    "/api/admin/sessions?limit=2", headers=ADMIN
                ).json()

        assert listing["count"] == 2, "the page asked for two"
        assert listing["total"] >= 5, "but must be told how many there are"
        assert len(listing["sessions"]) == 2

    def test_the_total_matches_when_nothing_is_cut(self, client):
        make_session(client, name="only one")
        listing = client.get("/api/admin/sessions", headers=ADMIN).json()
        assert listing["total"] == listing["count"]

    def test_the_total_respects_the_mode_filter(self, shared_app):
        """Otherwise the note would claim rows the filter already excluded."""
        with TestClient(shared_app) as maker:
            make_session(maker, name="a mock")

            with TestClient(shared_app) as admin:
                mock = admin.get(
                    "/api/admin/sessions?mode=mock", headers=ADMIN
                ).json()
                live = admin.get(
                    "/api/admin/sessions?mode=assistant", headers=ADMIN
                ).json()

        assert mock["total"] == mock["count"] >= 1
        assert live["total"] == live["count"] == 0

    def test_every_row_carries_what_the_filters_need(self, client):
        """The page buckets by progress, which needs the shape of the draft."""
        make_session(client, name="shapely")
        row = client.get("/api/admin/sessions", headers=ADMIN).json()["sessions"][0]
        for field in ("id", "name", "mode", "owner", "picks_made", "teams", "rounds",
                      "updated_at"):
            assert field in row, field


class TestWhatItIsAllowedToDestroy:
    """Viewing is one thing; deleting someone's draft is a larger blast radius.

    This has been narrowed three times by real changes, and the wording kept
    overreaching. It began as "no route changes anything", which the keeper
    sync broke by being a POST. Then "nothing here destroys what anyone made",
    which sync broke again by dropping managers who left the league. Now a
    session can be purged outright -- deliberately, because the alternative
    was worse: the owner's delete used to remove the row, so anybody could
    quietly erase a draft from the one view meant to see all of them.

    So the invariant is no longer about destroying nothing. It is that the
    destructive surface is small, named, and changes only on purpose. Adding a
    route that removes something breaks the list below, which is the point.
    """

    #: Every route behind this gate that removes or rewrites anything.
    DESTRUCTIVE = {
        ("DELETE", "/api/admin/sessions/{session_id}"),
        ("POST", "/api/admin/keepers/sync"),
    }

    def test_the_destructive_routes_are_exactly_these(self):
        """A new one has to be added here, which is the review moment."""
        from app.api.admin import router

        found = {
            (method, route.path)
            for route in router.routes
            for method in (route.methods - {"GET", "HEAD", "OPTIONS"})
        }
        assert found == self.DESTRUCTIVE

    def test_everything_else_only_reads(self):
        from app.api.admin import router

        reading = [
            route.path for route in router.routes
            if not (route.methods - {"GET", "HEAD", "OPTIONS"})
        ]
        assert len(reading) >= 4, "the panel is mostly a view, and should stay one"

    def test_a_purge_needs_the_gate(self, shared_app):
        with TestClient(shared_app) as maker:
            session = make_session(maker, name="not yours to bin")

        with TestClient(shared_app) as stranger:
            assert stranger.delete(
                f"/api/admin/sessions/{session['id']}"
            ).status_code == 404

        with TestClient(shared_app) as admin:
            assert admin.get(
                f"/api/admin/sessions/{session['id']}", headers=ADMIN
            ).status_code == 200, "still there"

    def test_purging_something_that_is_gone_is_a_404(self, client):
        assert client.delete(
            "/api/admin/sessions/nope", headers=ADMIN
        ).status_code == 404

    def test_that_sync_is_idempotent(self, client, monkeypatch):
        """It mints codes for new managers and leaves existing ones alone."""
        from app.integrations.sleeper import Manager, SleeperClient

        class Fake(SleeperClient):
            def league_managers(self, league_id):
                return [Manager(user_id="m1", display_name="a", team_name="A")]

            def latest_draft(self, league_id):
                return _draft({"m1": 1})

        monkeypatch.setattr(main, "_sleeper", Fake(cache_dir=Path(".")))
        monkeypatch.setattr(app_config, "SLEEPER_LEAGUE_ID", "L")

        first = client.post("/api/admin/keepers/sync", headers=ADMIN).json()
        again = client.post("/api/admin/keepers/sync", headers=ADMIN).json()

        assert first["added"] == 1
        assert again["added"] == 0, "re-syncing must not re-mint anyone's code"
        assert again["removed"] == 0, "and must not drop anyone still in the league"

    def test_that_sync_leaves_drafted_sessions_alone(self, shared_app, monkeypatch):
        """Its reach stops at the league roster.

        Removing a departed manager deletes rows; nothing it deletes may be
        somebody's draft.
        """
        from app.integrations.sleeper import Manager, SleeperClient

        with TestClient(shared_app) as maker:
            session = make_session(maker, name="untouched")

        class Fake(SleeperClient):
            def league_managers(self, league_id):
                return [Manager(user_id="m9", display_name="z", team_name="Z")]

            def latest_draft(self, league_id):
                return _draft({"m9": 1})

        monkeypatch.setattr(main, "_sleeper", Fake(cache_dir=Path(".")))
        monkeypatch.setattr(app_config, "SLEEPER_LEAGUE_ID", "L")

        with TestClient(shared_app) as admin:
            admin.post("/api/admin/keepers/sync", headers=ADMIN)
            after = admin.get(f"/api/admin/sessions/{session['id']}", headers=ADMIN)

        assert after.status_code == 200
        assert after.json()["name"] == "untouched"

    def test_the_admin_gate_does_not_leak_into_the_session_routes(self, shared_app):
        """Being the owner must not grant a browser someone else's sessions."""
        with TestClient(shared_app) as maker:
            session = make_session(maker, name="not yours")

        with TestClient(shared_app) as admin:
            assert admin.get(f"/api/sessions/{session['id']}", headers=ADMIN).status_code == 404
            assert admin.delete(f"/api/sessions/{session['id']}", headers=ADMIN).status_code == 404


class TestThePage:
    def test_admin_is_served_when_the_page_is_built(self, client):
        """Unauthenticated on purpose -- Cloudflare Access guards the path.

        The page itself holds no data; every figure on it comes from
        /api/admin, which is gated regardless.
        """
        assert client.get("/admin").status_code in (200, 404)


class TestTheTwoDeletes:
    """A user binning a mock draft and the league losing it are different acts.

    They used to be the same one. The owner's delete dropped the row, so the
    admin table -- the only place meant to see every session -- quietly lost
    drafts, and nobody could tell a deleted session from one that never
    existed. Now the owner's delete hides and the admin's delete removes.
    """

    def test_a_binned_session_is_gone_for_its_owner(self, shared_app):
        with TestClient(shared_app) as owner:
            session = make_session(owner, name="mine")
            assert owner.delete(f"/api/sessions/{session['id']}").status_code == 200

            assert owner.get(f"/api/sessions/{session['id']}").status_code == 404
            listed = owner.get("/api/sessions").json()["sessions"]
            assert session["id"] not in {s["id"] for s in listed}

    def test_but_the_admin_still_sees_it(self, shared_app):
        with TestClient(shared_app) as owner:
            session = make_session(owner, name="binned but drafted")
            owner.delete(f"/api/sessions/{session['id']}")

        with TestClient(shared_app) as admin:
            listing = admin.get("/api/admin/sessions", headers=ADMIN).json()
            row = next(s for s in listing["sessions"] if s["id"] == session["id"])
            assert row["deleted"] is True, "and it says so"
            assert row["deleted_at"]
            assert row["name"] == "binned but drafted"

            board = admin.get(
                f"/api/admin/sessions/{session['id']}", headers=ADMIN
            )
            assert board.status_code == 200, "the board is still readable"

    def test_a_live_session_is_not_marked_deleted(self, client):
        session = make_session(client, name="still here")
        listing = client.get("/api/admin/sessions", headers=ADMIN).json()
        row = next(s for s in listing["sessions"] if s["id"] == session["id"])
        assert row["deleted"] is False
        assert row["deleted_at"] is None

    def test_binning_twice_is_not_an_error_the_second_time(self, client):
        """The row is already hidden; there is nothing left to hide."""
        session = make_session(client)
        assert client.delete(f"/api/sessions/{session['id']}").status_code == 200
        assert client.delete(f"/api/sessions/{session['id']}").status_code == 404

    def test_the_count_includes_binned_sessions(self, shared_app):
        """Otherwise the total disagrees with the rows underneath it."""
        with TestClient(shared_app) as owner:
            a = make_session(owner, name="a")
            make_session(owner, name="b")
            owner.delete(f"/api/sessions/{a['id']}")

        with TestClient(shared_app) as admin:
            listing = admin.get("/api/admin/sessions", headers=ADMIN).json()
            assert listing["total"] == len(listing["sessions"])
            assert any(s["deleted"] for s in listing["sessions"])

    def test_the_admin_delete_is_the_one_that_removes_it(self, shared_app):
        with TestClient(shared_app) as owner:
            session = make_session(owner, name="for good")

        with TestClient(shared_app) as admin:
            gone = admin.delete(
                f"/api/admin/sessions/{session['id']}", headers=ADMIN
            )
            assert gone.status_code == 200
            assert gone.json()["name"] == "for good"

            listing = admin.get("/api/admin/sessions", headers=ADMIN).json()
            assert session["id"] not in {s["id"] for s in listing["sessions"]}
            assert admin.get(
                f"/api/admin/sessions/{session['id']}", headers=ADMIN
            ).status_code == 404

    def test_it_can_purge_one_the_owner_already_binned(self, shared_app):
        """Which is the usual case: clearing out what people have thrown away."""
        with TestClient(shared_app) as owner:
            session = make_session(owner, name="twice dead")
            owner.delete(f"/api/sessions/{session['id']}")

        with TestClient(shared_app) as admin:
            assert admin.delete(
                f"/api/admin/sessions/{session['id']}", headers=ADMIN
            ).status_code == 200
            listing = admin.get("/api/admin/sessions", headers=ADMIN).json()
            assert session["id"] not in {s["id"] for s in listing["sessions"]}

    def test_purging_one_leaves_the_others(self, shared_app):
        with TestClient(shared_app) as owner:
            doomed = make_session(owner, name="doomed")
            spared = make_session(owner, name="spared")

        with TestClient(shared_app) as admin:
            admin.delete(f"/api/admin/sessions/{doomed['id']}", headers=ADMIN)
            listing = admin.get("/api/admin/sessions", headers=ADMIN).json()
            assert spared["id"] in {s["id"] for s in listing["sessions"]}
