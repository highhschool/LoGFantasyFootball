"""Session ownership.

The site is public with no login, so this is ownership rather than
authorization: it stops a friend deleting your mock draft, not a determined
person. These tests pin down that separate browsers cannot see or touch each
other's sessions, and that the boundary is uniform across every route.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from app import main
from app.owner import ACCESS_EMAIL_HEADER, COOKIE
from app.store import SessionStore


@pytest.fixture
def shared_app(tmp_path, monkeypatch, rankings_dir_2025):
    """One server, so separate clients are separate browsers on one site."""
    monkeypatch.setattr(app_config, "RANKINGS_DIR", rankings_dir_2025)
    monkeypatch.setattr(app_config, "SEASON", 2025)
    monkeypatch.setattr(main, "_store", SessionStore(tmp_path / "own.db"))
    return main.app


@pytest.fixture
def alice(shared_app):
    with TestClient(shared_app) as c:
        yield c


@pytest.fixture
def bob(shared_app):
    with TestClient(shared_app) as c:
        yield c


def start(client, **body):
    payload = {"your_slot": 4, "seed": 7}
    payload.update(body)
    r = client.post("/api/sessions", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


class TestIdentity:
    def test_a_cookie_is_issued_on_first_use(self, alice):
        alice.get("/api/sessions")
        assert COOKIE in alice.cookies

    def test_the_cookie_is_not_readable_by_scripts(self, alice):
        r = alice.get("/api/sessions")
        header = r.headers.get("set-cookie", "")
        assert "httponly" in header.lower()
        assert "samesite=lax" in header.lower()

    def test_identity_is_stable_across_requests(self, alice):
        first = start(alice, name="one")["id"]
        start(alice, name="two")
        names = {s["name"] for s in alice.get("/api/sessions").json()["sessions"]}
        assert names == {"one", "two"}
        assert alice.get(f"/api/sessions/{first}").status_code == 200

    def test_two_clients_get_different_identities(self, alice, bob):
        alice.get("/api/sessions")
        bob.get("/api/sessions")
        assert alice.cookies[COOKIE] != bob.cookies[COOKIE]


class TestIsolation:
    def test_the_listing_hides_other_peoples_drafts(self, alice, bob):
        start(alice, name="alice only")
        start(bob, name="bob only")

        assert [s["name"] for s in alice.get("/api/sessions").json()["sessions"]] == ["alice only"]
        assert [s["name"] for s in bob.get("/api/sessions").json()["sessions"]] == ["bob only"]

    @pytest.mark.parametrize(
        "method,path,body",
        [
            ("get", "", None),
            ("delete", "", None),
            ("patch", "", {"name": "taken over"}),
            ("post", "/pick", {"player_key": "whatever"}),
            ("post", "/undo", None),
            ("post", "/autopick", None),
            ("post", "/simulate", None),
            ("get", "/available", None),
        ],
    )
    def test_every_route_refuses_someone_elses_session(self, alice, bob, method, path, body):
        session = start(alice, name="alice draft")
        url = f"/api/sessions/{session['id']}{path}"

        call = getattr(bob, method)
        response = call(url, json=body) if body is not None else call(url)
        assert response.status_code == 404, f"{method.upper()} {path} leaked"

    def test_refusal_is_404_not_403(self, alice, bob):
        """403 would confirm the id exists, letting anyone probe for drafts."""
        session = start(alice)
        real = bob.delete(f"/api/sessions/{session['id']}")
        fake = bob.delete("/api/sessions/000000000000")
        assert real.status_code == fake.status_code == 404
        assert real.json() == fake.json()

    def test_a_failed_delete_leaves_the_draft_untouched(self, alice, bob):
        session = start(alice, name="keep me")
        bob.delete(f"/api/sessions/{session['id']}")
        assert alice.get(f"/api/sessions/{session['id']}").json()["name"] == "keep me"

    def test_a_failed_rename_leaves_the_name_alone(self, alice, bob):
        session = start(alice, name="original")
        bob.patch(f"/api/sessions/{session['id']}", json={"name": "hijacked"})
        assert alice.get(f"/api/sessions/{session['id']}").json()["name"] == "original"

    def test_you_can_still_manage_your_own(self, alice):
        session = start(alice, name="mine")
        assert alice.patch(
            f"/api/sessions/{session['id']}", json={"name": "renamed"}
        ).json()["name"] == "renamed"
        assert alice.delete(f"/api/sessions/{session['id']}").status_code == 200
        assert alice.get(f"/api/sessions/{session['id']}").status_code == 404


class TestAccessUpgrade:
    """With Cloudflare Access in front, a verified email replaces the cookie."""

    def test_a_verified_email_owns_its_sessions(self, shared_app):
        headers = {ACCESS_EMAIL_HEADER: "manager@example.com"}
        with TestClient(shared_app) as c:
            created = c.post("/api/sessions", json={"name": "via access"}, headers=headers).json()
            listed = c.get("/api/sessions", headers=headers).json()["sessions"]
            assert [s["name"] for s in listed] == ["via access"]
            assert c.get(f"/api/sessions/{created['id']}", headers=headers).status_code == 200

    def test_a_different_email_is_a_different_owner(self, shared_app):
        with TestClient(shared_app) as c:
            created = c.post(
                "/api/sessions", json={"name": "hers"},
                headers={ACCESS_EMAIL_HEADER: "one@example.com"},
            ).json()
            other = c.get(
                f"/api/sessions/{created['id']}",
                headers={ACCESS_EMAIL_HEADER: "two@example.com"},
            )
            assert other.status_code == 404

    def test_email_case_does_not_split_an_identity(self, shared_app):
        with TestClient(shared_app) as c:
            created = c.post(
                "/api/sessions", json={"name": "mixed case"},
                headers={ACCESS_EMAIL_HEADER: "Manager@Example.COM"},
            ).json()
            same = c.get(
                f"/api/sessions/{created['id']}",
                headers={ACCESS_EMAIL_HEADER: "manager@example.com"},
            )
            assert same.status_code == 200
