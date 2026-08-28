from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from app import main
from app.store import SessionStore


@pytest.fixture
def client(tmp_path, monkeypatch, rankings_dir_2025):
    """A client with its own database and the 2025 fixture rankings."""
    monkeypatch.setattr(app_config, "RANKINGS_DIR", rankings_dir_2025)
    monkeypatch.setattr(app_config, "SEASON", 2025)
    monkeypatch.setattr(main, "_store", SessionStore(tmp_path / "test.db"))
    with TestClient(main.app) as c:
        yield c


def new_session(client, **overrides):
    body = {"name": "test", "your_slot": 6, "seed": 42}
    body.update(overrides)
    response = client.post("/api/sessions", json=body)
    assert response.status_code == 200, response.text
    return response.json()


class TestCreate:
    def test_bots_pick_up_to_your_slot(self, client):
        state = new_session(client, your_slot=6)
        assert len(state["picks"]) == 5
        assert state["your_turn"] is True
        assert state["on_the_clock"]["overall"] == 6

    def test_slot_one_picks_immediately(self, client):
        state = new_session(client, your_slot=1)
        assert state["picks"] == []
        assert state["on_the_clock"]["overall"] == 1

    def test_slot_twelve_waits_for_eleven_bots(self, client):
        state = new_session(client, your_slot=12)
        assert len(state["picks"]) == 11
        assert all(p["source"] == "bot" for p in state["picks"])

    def test_seed_makes_it_reproducible(self, client):
        a = new_session(client, seed=1234)
        b = new_session(client, seed=1234)
        assert [p["player_name"] for p in a["picks"]] == [p["player_name"] for p in b["picks"]]

    def test_different_seeds_diverge(self, client):
        a = new_session(client, seed=1)
        b = new_session(client, seed=99999)
        assert [p["player_name"] for p in a["picks"]] != [p["player_name"] for p in b["picks"]]

    def test_bad_slot_is_rejected(self, client):
        assert client.post("/api/sessions", json={"your_slot": 99, "teams": 12}).status_code == 422


class TestPicking:
    def test_pick_advances_to_your_next_turn(self, client):
        state = new_session(client)
        key = client.get(f"/api/sessions/{state['id']}/available").json()["players"][0]["key"]

        after = client.post(f"/api/sessions/{state['id']}/pick", json={"player_key": key}).json()
        assert len(after["your_roster"]) == 1
        assert after["your_turn"] is True
        # Slot 6 picks at 6 then 19, so 18 picks are on the board.
        assert len(after["picks"]) == 18

    def test_cannot_draft_someone_already_gone(self, client):
        state = new_session(client)
        taken = state["picks"][0]["player_name"]
        pool = client.get(f"/api/sessions/{state['id']}/available?limit=300").json()
        assert taken not in {p["name"] for p in pool["players"]}

    def test_double_pick_is_rejected(self, client):
        state = new_session(client)
        key = client.get(f"/api/sessions/{state['id']}/available").json()["players"][0]["key"]
        client.post(f"/api/sessions/{state['id']}/pick", json={"player_key": key})
        second = client.post(f"/api/sessions/{state['id']}/pick", json={"player_key": key})
        assert second.status_code == 409
        assert "already drafted" in second.json()["detail"]

    def test_unknown_player_is_rejected(self, client):
        state = new_session(client)
        r = client.post(f"/api/sessions/{state['id']}/pick", json={"player_key": "nope"})
        assert r.status_code == 409


class TestUndo:
    def test_undo_returns_you_to_your_own_pick(self, client):
        state = new_session(client)
        before = len(state["picks"])
        key = client.get(f"/api/sessions/{state['id']}/available").json()["players"][0]["key"]

        client.post(f"/api/sessions/{state['id']}/pick", json={"player_key": key})
        after = client.post(f"/api/sessions/{state['id']}/undo").json()

        # Back to exactly where you were, not to some bot's decision.
        assert len(after["picks"]) == before
        assert after["your_roster"] == []
        assert after["your_turn"] is True

    def test_undo_with_nothing_to_undo(self, client):
        state = new_session(client, your_slot=1)
        assert client.post(f"/api/sessions/{state['id']}/undo").status_code == 409


class TestAutopickAndSimulate:
    def test_autopick_fills_one_slot(self, client):
        state = new_session(client)
        after = client.post(f"/api/sessions/{state['id']}/autopick").json()
        assert len(after["your_roster"]) == 1

    def test_simulate_runs_the_draft_out(self, client):
        state = new_session(client)
        final = client.post(f"/api/sessions/{state['id']}/simulate").json()
        assert final["complete"] is True
        assert len(final["picks"]) == 12 * 15
        assert len(final["your_roster"]) == 15
        assert final["on_the_clock"] is None

    def test_a_completed_roster_respects_limits(self, client):
        state = new_session(client)
        final = client.post(f"/api/sessions/{state['id']}/simulate").json()
        counts = {}
        for p in final["your_roster"]:
            counts[p["position"]] = counts.get(p["position"], 0) + 1
        for position, count in counts.items():
            assert count <= final["config"]["position_limits"][position]


class TestPersistence:
    def test_a_session_survives_reload(self, client):
        state = new_session(client)
        key = client.get(f"/api/sessions/{state['id']}/available").json()["players"][0]["key"]
        client.post(f"/api/sessions/{state['id']}/pick", json={"player_key": key})

        fetched = client.get(f"/api/sessions/{state['id']}").json()
        assert len(fetched["your_roster"]) == 1
        assert fetched["id"] == state["id"]

    def test_sessions_are_listed(self, client):
        new_session(client, name="one")
        new_session(client, name="two")
        listing = client.get("/api/sessions").json()["sessions"]
        assert {s["name"] for s in listing} >= {"one", "two"}

    def test_missing_session_is_404(self, client):
        assert client.get("/api/sessions/deadbeef").status_code == 404

    def test_delete(self, client):
        state = new_session(client)
        assert client.delete(f"/api/sessions/{state['id']}").status_code == 200
        assert client.get(f"/api/sessions/{state['id']}").status_code == 404


class TestAvailable:
    def test_position_filter(self, client):
        state = new_session(client)
        players = client.get(f"/api/sessions/{state['id']}/available?position=QB").json()["players"]
        assert players and {p["position"] for p in players} == {"QB"}

    def test_search(self, client):
        state = new_session(client)
        players = client.get(f"/api/sessions/{state['id']}/available?search=jamarr").json()["players"]
        # Chase may already be drafted by a bot; either way the filter must not error.
        assert all("chase" in p["name"].lower() or "ja" in p["name"].lower() for p in players)


class TestKeepersOptional:
    def test_a_session_with_no_keepers_is_normal(self, client):
        state = new_session(client)
        assert state["unresolved_keepers"] == []
        assert all(p["source"] != "keeper" for p in state["picks"])

    def test_keepers_can_be_supplied(self, client):
        state = new_session(client, your_slot=2, keepers=[
            {"team_slot": 1, "round": 1, "player_name": "Ja'Marr Chase"},
        ])
        keeper_picks = [p for p in state["picks"] if p["source"] == "keeper"]
        assert len(keeper_picks) == 1
        assert keeper_picks[0]["player_name"] == "Ja'Marr Chase"

    def test_a_bad_keeper_name_does_not_break_the_session(self, client):
        state = new_session(client, keepers=[
            {"team_slot": 1, "round": 1, "player_name": "Nobody McFake"},
        ])
        assert state["unresolved_keepers"] == ["Nobody McFake"]
        assert state["your_turn"] is True
