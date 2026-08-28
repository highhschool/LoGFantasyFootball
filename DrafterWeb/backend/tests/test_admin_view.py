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


class TestItDestroysNothing:
    """Viewing is one thing; deleting someone's draft is a larger blast radius.

    This invariant has been narrowed twice by real changes. First it read "no
    route changes anything", which the keeper sync broke by being a POST. Then
    it read "nothing here destroys what anyone made", which sync broke again by
    dropping managers who left the league -- deliberately, since their code and
    their selection have to go with them. What survives is the part that was
    always the point: the sync mirrors the league roster and touches nothing
    else, and no drafted session can be deleted or rewritten from here.
    """

    def test_nothing_deletes_or_replaces(self):
        from app.api.admin import router

        for route in router.routes:
            assert not route.methods & {"DELETE", "PUT", "PATCH"}, route.path

    def test_the_only_write_is_the_league_sync(self):
        from app.api.admin import router

        writes = {
            route.path for route in router.routes if route.methods - {"GET", "HEAD"}
        }
        assert writes == {"/api/admin/keepers/sync"}

    def test_that_sync_is_idempotent(self, client, monkeypatch):
        """It mints codes for new managers and leaves existing ones alone."""
        from app.integrations.sleeper import Manager, SleeperClient

        class Fake(SleeperClient):
            def league_managers(self, league_id):
                return [Manager(user_id="m1", display_name="a", team_name="A")]

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
