"""The rankings reload is the only state-changing route on a public site."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config, main


@pytest.fixture
def client(monkeypatch, rankings_dir_2025):
    """Built against the 2025 fixture rather than the live ADP feed.

    Starting the app loads rankings, so without the override these tests
    fetched from Fantasy Football Calculator -- and passed or failed on
    whether the one-hour disk cache happened to be warm.
    """
    monkeypatch.setattr(config, "RANKINGS_DIR", rankings_dir_2025)
    monkeypatch.setattr(config, "SEASON", 2025)

    def _make(token: str):
        monkeypatch.setattr(config, "ADMIN_TOKEN", token)
        return TestClient(main.app)

    return _make


class TestReloadIsGated:
    def test_disabled_when_no_token_configured(self, client):
        with client("") as c:
            r = c.post("/api/rankings/reload")
        # 404 rather than 403: a public scan should not learn the route exists.
        assert r.status_code == 404

    def test_rejects_a_missing_token(self, client):
        with client("s3cret") as c:
            r = c.post("/api/rankings/reload")
        assert r.status_code == 403

    def test_rejects_a_wrong_token(self, client):
        with client("s3cret") as c:
            r = c.post("/api/rankings/reload", headers={"X-Admin-Token": "guess"})
        assert r.status_code == 403

    def test_accepts_the_right_token(self, client):
        with client("s3cret") as c:
            r = c.post("/api/rankings/reload", headers={"X-Admin-Token": "s3cret"})
        assert r.status_code == 200
        assert r.json()["status"] in {"ok", "degraded"}


class TestPublicRoutesStayOpen:
    """Gating the admin route must not gate the app itself."""

    @pytest.mark.parametrize("route", ["/api/health", "/api/players?limit=1", "/api/board"])
    def test_read_routes_need_no_token(self, client, route):
        with client("s3cret") as c:
            assert c.get(route).status_code == 200


class TestHealthLeaksNothing:
    def test_no_absolute_path_in_payload(self, client):
        with client("") as c:
            body = c.get("/api/health").json()
        assert "rankings_dir" not in body
        assert ":\\" not in str(body) and "/srv" not in str(body)
