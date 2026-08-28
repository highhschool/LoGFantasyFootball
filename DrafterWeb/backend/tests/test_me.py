"""Identity, and the picture attached to it.

Identity is cross-tool now, so these are about it working without the keeper
tool in the picture -- and about an upload being an image, since a data URL is
a file somebody else's browser will render.
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from app import main
from app.integrations.sleeper import DraftInfo, Manager
from app.store import SessionStore

ADMIN = {"X-Admin-Token": "adm1n"}
PNG = "data:image/png;base64," + base64.b64encode(b"x" * 60).decode()


@pytest.fixture
def app(tmp_path, monkeypatch, rankings_dir_2025):
    from app.integrations.sleeper import SleeperClient

    class Fake(SleeperClient):
        def league_managers(self, league_id):
            return [
                Manager(user_id="u1", display_name="brayden", team_name="Phoenix",
                        avatar="abc123"),
                Manager(user_id="u2", display_name="jed", team_name="", avatar=None),
            ]

        def latest_draft(self, league_id):
            return DraftInfo(
                draft_id="d", status="pre_draft", draft_type="snake", season="2025",
                teams=12, rounds=15, slot_to_roster={}, slots={},
                draft_order={"u1": 4, "u2": 9},
            )

    monkeypatch.setattr(app_config, "RANKINGS_DIR", rankings_dir_2025)
    monkeypatch.setattr(app_config, "SEASON", 2025)
    monkeypatch.setattr(app_config, "SLEEPER_LEAGUE_ID", "L")
    monkeypatch.setattr(app_config, "ADMIN_TOKEN", "adm1n")
    monkeypatch.setattr(app_config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(main, "_store", SessionStore(tmp_path / "m.db"))
    monkeypatch.setattr(main, "_sleeper", Fake(cache_dir=tmp_path))
    return main.app


@pytest.fixture
def codes(app):
    with TestClient(app) as owner:
        owner.post("/api/admin/keepers/sync", headers=ADMIN)
        listed = owner.get("/api/admin/keepers/codes", headers=ADMIN).json()["managers"]
    return {m["user_id"]: m for m in listed}


def signed_in(app, manager):
    client = TestClient(app)
    client.__enter__()
    r = client.post("/api/keeper/claim",
                    json={"user_id": manager["user_id"], "code": manager["code"]})
    assert r.status_code == 200, r.text
    return client


class TestKnowingWhoYouAre:
    def test_signed_out_is_an_answer_not_an_error(self, app, codes):
        with TestClient(app) as anyone:
            r = anyone.get("/api/me")
        assert r.status_code == 200
        assert r.json()["you"] is None

    def test_it_names_you_once_signed_in(self, app, codes):
        you = signed_in(app, codes["u1"]).get("/api/me").json()["you"]
        assert you["display_name"] == "brayden"
        assert you["draft_slot"] == 4

    def test_it_does_not_need_the_keeper_tool(self, app, codes):
        """The whole reason this route exists rather than /api/keeper."""
        from app.api.me import router

        assert all("keeper" not in r.path for r in router.routes)


class TestPictures:
    def test_sleeper_supplies_one_for_free(self, app, codes):
        you = signed_in(app, codes["u1"]).get("/api/me").json()["you"]
        assert you["avatar_url"].endswith("abc123")
        assert you["custom"] is False

    def test_a_manager_without_a_sleeper_avatar_has_none(self, app, codes):
        you = signed_in(app, codes["u2"]).get("/api/me").json()["you"]
        assert you["avatar_url"] is None

    def test_an_upload_overrides_it(self, app, codes):
        client = signed_in(app, codes["u1"])
        you = client.put("/api/me/photo", json={"photo": PNG}).json()["you"]
        assert you["photo"] == PNG
        assert you["custom"] is True
        assert you["avatar_url"], "Sleeper's is kept, so removing can fall back"

    def test_removing_it_falls_back_to_sleeper(self, app, codes):
        client = signed_in(app, codes["u1"])
        client.put("/api/me/photo", json={"photo": PNG})
        you = client.delete("/api/me/photo").json()["you"]
        assert you["photo"] is None
        assert you["custom"] is False
        assert you["avatar_url"].endswith("abc123")

    def test_it_survives_a_league_sync(self, app, codes):
        """Sync rewrites the row; an upload is not Sleeper's to overwrite."""
        client = signed_in(app, codes["u1"])
        client.put("/api/me/photo", json={"photo": PNG})
        with TestClient(app) as owner:
            owner.post("/api/admin/keepers/sync", headers=ADMIN)
        assert client.get("/api/me").json()["you"]["photo"] == PNG


class TestWhatCountsAsAPicture:
    @pytest.mark.parametrize("bad", [
        "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",   # markup, and scriptable
        "data:text/html;base64,PGgxPmhpPC9oMT4=",
        "javascript:alert(1)",
        "https://example.com/cat.png",                   # a request we would make
        "not a url at all",
        "data:image/png;base64,not valid base64!!",
    ])
    def test_only_raster_data_urls_are_taken(self, app, codes, bad):
        client = signed_in(app, codes["u1"])
        r = client.put("/api/me/photo", json={"photo": bad})
        assert r.status_code == 422, bad

    def test_an_enormous_picture_is_refused(self, app, codes):
        huge = "data:image/png;base64," + "A" * 300_000
        r = signed_in(app, codes["u1"]).put("/api/me/photo", json={"photo": huge})
        assert r.status_code == 413

    def test_the_size_check_runs_before_the_pattern(self, app, codes):
        """So a megabyte of junk is rejected without matching a regex against it."""
        huge = "x" * 300_000
        r = signed_in(app, codes["u1"]).put("/api/me/photo", json={"photo": huge})
        assert r.status_code == 413

    def test_a_stranger_cannot_set_one(self, app, codes):
        with TestClient(app) as anyone:
            assert anyone.put("/api/me/photo", json={"photo": PNG}).status_code == 403


class TestPhotosAreNotPublic:
    def test_the_public_picker_does_not_carry_them(self, app, codes):
        """The site is public. A face uploaded for the league stays in it."""
        signed_in(app, codes["u1"]).put("/api/me/photo", json={"photo": PNG})
        with TestClient(app) as anyone:
            listed = anyone.get("/api/keeper/managers").json()["managers"]
        assert all("photo" not in m for m in listed)
