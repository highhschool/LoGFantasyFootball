"""The live draft assistant.

Driven by the cached 2025 draft standing in for a live one, so the suite stays
offline. Two properties matter most: syncing is idempotent, and an unresolvable
name stops the board rather than shifting every seat after it.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from app import main
from app.api.assistant import sync_log
from app.integrations.sleeper import SleeperClient, SleeperError, parse_draft, parse_picks
from app.store import SessionStore


@pytest.fixture
def picks(sleeper_2025):
    return parse_picks(sleeper_2025["picks"])


@pytest.fixture
def fake_sleeper(sleeper_2025, tmp_path):
    """A client serving the fixture draft, revealing picks a slice at a time."""

    class Fake(SleeperClient):
        visible = len(sleeper_2025["picks"])

        def draft(self, draft_id):
            return parse_draft(dict(sleeper_2025["draft"], draft_id=draft_id))

        def picks(self, draft_id):
            return parse_picks(sleeper_2025["picks"][: self.visible])

    return Fake(cache_dir=tmp_path)


@pytest.fixture
def client(tmp_path, monkeypatch, rankings_dir_2025, fake_sleeper):
    monkeypatch.setattr(app_config, "RANKINGS_DIR", rankings_dir_2025)
    monkeypatch.setattr(app_config, "SEASON", 2025)
    monkeypatch.setattr(main, "_store", SessionStore(tmp_path / "a.db"))
    monkeypatch.setattr(main, "_sleeper", fake_sleeper)
    with TestClient(main.app) as c:
        yield c


def connect(client, **body):
    payload = {"draft": "1261437960088195073", "your_slot": 6}
    payload.update(body)
    r = client.post("/api/assistant", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def unknown_player(pick):
    return replace(pick, name="Nobody McFake", position="RB", team="FA")


class TestConnecting:
    def test_the_draft_shape_comes_from_sleeper(self, client):
        state = connect(client)
        assert state["config"]["teams"] == 12
        assert state["config"]["rounds"] == 15
        assert state["mode"] == "assistant"

    def test_a_draft_url_works_as_well_as_an_id(self, client):
        state = connect(client, draft="https://sleeper.com/draft/nfl/1261437960088195073")
        assert state["picks"]

    def test_a_slot_the_draft_does_not_have_is_rejected(self, client):
        r = client.post("/api/assistant", json={"draft": "123", "your_slot": 30})
        assert r.status_code == 422
        assert "does not exist" in r.json()["detail"]

    def test_a_draft_from_another_season_is_refused(self, client, monkeypatch, sleeper_2025):
        """Mismatched seasons leave most picks unmatched, which reads as broken."""
        wrong = dict(sleeper_2025["draft"], season="2019")
        monkeypatch.setattr(main._sleeper, "draft", lambda _id: parse_draft(wrong))
        r = client.post("/api/assistant", json={"draft": "123", "your_slot": 1})
        assert r.status_code == 422
        assert "2019" in r.json()["detail"] and "2025" in r.json()["detail"]

    def test_a_non_snake_draft_is_refused(self, client, monkeypatch, sleeper_2025):
        auction = dict(sleeper_2025["draft"], type="auction")
        monkeypatch.setattr(main._sleeper, "draft", lambda _id: parse_draft(auction))
        r = client.post("/api/assistant", json={"draft": "123", "your_slot": 1})
        assert r.status_code == 422
        assert "snake" in r.json()["detail"]


class TestSyncing:
    def test_it_reads_the_live_board(self, client):
        state = connect(client)
        assert len(state["picks"]) == 180
        assert state["complete"] is True

    def test_picks_land_in_the_right_seats(self, client, picks):
        state = connect(client)
        for ours, theirs in zip(state["picks"], picks):
            assert ours["overall"] == theirs.pick_no
            assert ours["team_slot"] == theirs.draft_slot

    def test_your_roster_is_the_slot_you_claimed(self, client, picks):
        state = connect(client, your_slot=6)
        theirs = [p for p in picks if p.draft_slot == 6]
        assert len(state["your_roster"]) == len(theirs)

    def test_syncing_again_changes_nothing(self, client):
        state = connect(client)
        again = client.post(f"/api/assistant/{state['id']}/sync").json()
        assert len(again["picks"]) == len(state["picks"])

    def test_it_follows_a_draft_in_progress(self, client, fake_sleeper):
        fake_sleeper.visible = 5
        state = connect(client)
        assert len(state["picks"]) == 5
        assert state["on_the_clock"]["overall"] == 6

        fake_sleeper.visible = 11
        state = client.post(f"/api/assistant/{state['id']}/sync").json()
        assert len(state["picks"]) == 11
        assert state["on_the_clock"]["overall"] == 12

    def test_an_outage_keeps_the_board_and_reports_it(self, client, fake_sleeper):
        fake_sleeper.visible = 20
        state = connect(client)

        def down(_id):
            raise SleeperError("simulated outage")

        fake_sleeper.picks = down
        after = client.post(f"/api/assistant/{state['id']}/sync").json()

        assert len(after["picks"]) == 20, "the board must survive Sleeper going away"
        assert "simulated outage" in after["sync_error"]


class TestUnrankedPicks:
    """A positional log cannot skip a pick, so it describes what it cannot rank."""

    def test_a_real_draft_contains_an_unranked_player(self, pool_2025, picks):
        # The 2025 board took a round-15 back the ADP feed does not carry.
        missing = [p for p in picks if pool_2025.find(p.name, p.position, p.team) is None]
        assert len(missing) == 1
        assert missing[0].round == 15

    def test_the_board_still_completes(self, pool_2025, picks):
        log, unranked = sync_log(pool_2025, [], picks)
        assert len(log) == 180, "one unranked player must not stall the board"
        assert [p.name for p in unranked] == ["Isaac Guerendo"]

    def test_an_unranked_pick_keeps_its_seat(self, client, picks):
        state = connect(client, your_slot=6)
        odd = next(p for p in state["picks"] if p["adp"] >= 999)
        actual = next(p for p in picks if p.pick_no == odd["overall"])
        assert odd["player_name"] == actual.name
        assert odd["team_slot"] == actual.draft_slot

    def test_later_picks_are_still_in_the_right_seats(self, client, picks, pool_2025):
        """Seats must stay aligned past the unranked pick.

        Compared by identity, not display name: a resolved player is shown
        under the rankings' name, and the two feeds disagree about defenses --
        Sleeper's "Kansas City Chiefs" is the feed's "Kansas City Defense".
        """
        state = connect(client)
        for ours, theirs in zip(state["picks"][-10:], picks[-10:]):
            assert ours["overall"] == theirs.pick_no
            assert ours["team_slot"] == theirs.draft_slot

            ranked = pool_2025.find(theirs.name, theirs.position, theirs.team)
            expected = ranked.name if ranked else theirs.name
            assert ours["player_name"] == expected

    def test_it_is_reported_rather_than_hidden(self, client):
        state = connect(client)
        assert [u["name"] for u in state["unranked"]] == ["Isaac Guerendo"]

    def test_an_unranked_player_still_fills_a_roster_spot(self, pool_2025, picks):
        from app.core.engine import replay
        from app.core.models import DraftConfig

        log, _ = sync_log(pool_2025, [], picks)
        state = replay(DraftConfig(year=2025, teams=12, rounds=15, your_slot=1), pool_2025, log)
        assert all(len(t.picks) == 15 for t in state.teams.values())

    def test_a_gap_in_the_feed_still_stops_it(self, pool_2025, picks):
        # Pick 3 missing: continuing would seat pick 4 in slot 3.
        gapped = [p for p in picks[:6] if p.pick_no != 3]
        log, _ = sync_log(pool_2025, [], gapped)
        assert len(log) == 2

    def test_keepers_are_marked_from_the_feed(self, pool_2025, picks):
        feed = [replace(picks[0], is_keeper=True), picks[1], picks[2]]
        log, _ = sync_log(pool_2025, [], feed)
        assert log[0].source == "keeper"
        assert log[1].source == "sleeper"


class TestToolsStaySeparate:
    """The mock simulator and the assistant are different tools."""

    def test_a_mock_draft_is_not_listed_by_the_assistant(self, client):
        client.post("/api/sessions", json={"name": "a mock", "your_slot": 1})
        assert client.get("/api/assistant").json()["sessions"] == []

    def test_a_live_draft_is_not_listed_by_the_mock_tool(self, client):
        connect(client, name="a live draft")
        assert client.get("/api/sessions").json()["sessions"] == []

    def test_the_mock_routes_refuse_an_assistant_session(self, client):
        state = connect(client)
        assert client.get(f"/api/sessions/{state['id']}").status_code == 404
        assert client.post(f"/api/sessions/{state['id']}/undo").status_code == 404

    def test_the_assistant_routes_refuse_a_mock_session(self, client):
        mock = client.post("/api/sessions", json={"your_slot": 1}).json()
        assert client.get(f"/api/assistant/{mock['id']}").status_code == 404
        assert client.post(f"/api/assistant/{mock['id']}/sync").status_code == 404

    def test_each_tool_lists_only_its_own(self, client):
        client.post("/api/sessions", json={"name": "mock one", "your_slot": 1})
        connect(client, name="live one")

        mocks = [s["name"] for s in client.get("/api/sessions").json()["sessions"]]
        lives = [s["name"] for s in client.get("/api/assistant").json()["sessions"]]
        assert mocks == ["mock one"]
        assert lives == ["live one"]


class TestOwnership:
    def test_another_browser_cannot_see_your_live_draft(self, client, tmp_path, shared=None):
        state = connect(client, name="mine")
        with TestClient(main.app) as other:
            assert other.get("/api/assistant").json()["sessions"] == []
            assert other.get(f"/api/assistant/{state['id']}").status_code == 404
            assert other.delete(f"/api/assistant/{state['id']}").status_code == 404
