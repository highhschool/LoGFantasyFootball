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


class TestPickClock:
    def test_defaults_to_off(self, client):
        assert new_session(client)["pick_seconds"] == 0

    def test_can_be_set_at_creation(self, client):
        assert new_session(client, pick_seconds=60)["pick_seconds"] == 60

    def test_can_be_changed_mid_draft(self, client):
        state = new_session(client, pick_seconds=30)
        patched = client.patch(
            f"/api/sessions/{state['id']}", json={"pick_seconds": 90}
        ).json()
        assert patched["pick_seconds"] == 90

    def test_can_be_disabled(self, client):
        state = new_session(client, pick_seconds=60)
        patched = client.patch(f"/api/sessions/{state['id']}", json={"pick_seconds": 0}).json()
        assert patched["pick_seconds"] == 0

    def test_absurd_clocks_are_rejected(self, client):
        assert client.post("/api/sessions", json={"pick_seconds": 99999}).status_code == 422
        assert client.post("/api/sessions", json={"pick_seconds": -5}).status_code == 422


class TestRename:
    def test_rename_persists(self, client):
        state = new_session(client, name="first")
        patched = client.patch(f"/api/sessions/{state['id']}", json={"name": "second"}).json()
        assert patched["name"] == "second"
        assert client.get(f"/api/sessions/{state['id']}").json()["name"] == "second"

    def test_rename_shows_in_the_listing(self, client):
        state = new_session(client, name="before")
        client.patch(f"/api/sessions/{state['id']}", json={"name": "after"})
        names = {s["name"] for s in client.get("/api/sessions").json()["sessions"]}
        assert "after" in names and "before" not in names

    def test_whitespace_is_trimmed(self, client):
        state = new_session(client)
        patched = client.patch(f"/api/sessions/{state['id']}", json={"name": "  spaced  "}).json()
        assert patched["name"] == "spaced"

    def test_rename_does_not_disturb_the_draft(self, client):
        state = new_session(client)
        before = [p["player_name"] for p in state["picks"]]
        patched = client.patch(f"/api/sessions/{state['id']}", json={"name": "x"}).json()
        assert [p["player_name"] for p in patched["picks"]] == before

    def test_patching_a_missing_session_is_404(self, client):
        assert client.patch("/api/sessions/nope", json={"name": "x"}).status_code == 404

    def test_an_empty_patch_changes_nothing(self, client):
        state = new_session(client, name="keep", pick_seconds=45)
        patched = client.patch(f"/api/sessions/{state['id']}", json={}).json()
        assert patched["name"] == "keep"
        assert patched["pick_seconds"] == 45


class TestDraftPositionSelection:
    @pytest.mark.parametrize("slot", [1, 6, 12])
    def test_any_slot_is_usable(self, client, slot):
        state = new_session(client, your_slot=slot, teams=12)
        assert state["config"]["your_slot"] == slot
        assert len(state["picks"]) == slot - 1

    def test_slot_must_fit_the_league(self, client):
        assert client.post(
            "/api/sessions", json={"teams": 10, "your_slot": 12}
        ).status_code == 422


class TestKeepersPerTeam:
    def test_one_keeper_for_every_team(self, client):
        keepers = [
            {"team_slot": slot, "round": 1, "player_name": name}
            for slot, name in enumerate(
                ["Ja'Marr Chase", "Bijan Robinson", "Saquon Barkley", "Jahmyr Gibbs"], start=1
            )
        ]
        state = new_session(client, teams=12, your_slot=12, keepers=keepers)
        kept = [p for p in state["picks"] if p["source"] == "keeper"]
        assert len(kept) == 4
        assert state["unresolved_keepers"] == []

    def test_multiple_keepers_for_one_team(self, client):
        keepers = [
            {"team_slot": 1, "round": 1, "player_name": "Ja'Marr Chase"},
            {"team_slot": 1, "round": 2, "player_name": "Bijan Robinson"},
        ]
        state = new_session(client, your_slot=6, keepers=keepers)
        assert len([p for p in state["picks"] if p["source"] == "keeper"]) >= 1

    def test_a_keeper_outside_the_league_is_rejected(self, client):
        r = client.post("/api/sessions", json={
            "teams": 10, "your_slot": 1,
            "keepers": [{"team_slot": 11, "round": 1, "player_name": "Ja'Marr Chase"}],
        })
        assert r.status_code == 422
        assert "slot 11" in r.json()["detail"]


class TestRoundCap:
    """The league drafts 15 rounds, and the default roster holds 15 players."""

    def test_fifteen_rounds_is_the_default(self, client):
        assert new_session(client)["config"]["rounds"] == 15

    def test_a_full_fifteen_round_draft_completes(self, client):
        state = new_session(client, rounds=15, teams=12)
        final = client.post(f"/api/sessions/{state['id']}/simulate").json()
        assert final["complete"] is True
        assert len(final["picks"]) == 180
        assert len(final["your_roster"]) == 15

    def test_no_duplicate_players_in_a_full_draft(self, client):
        state = new_session(client, rounds=15, teams=12)
        final = client.post(f"/api/sessions/{state['id']}/simulate").json()
        names = [p["player_name"] for p in final["picks"]]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("rounds", [16, 20, 40])
    def test_more_than_fifteen_is_rejected(self, client, rounds):
        assert client.post(
            "/api/sessions", json={"teams": 12, "rounds": rounds, "your_slot": 1}
        ).status_code == 422

    def test_shorter_drafts_are_still_allowed(self, client):
        state = new_session(client, rounds=8)
        final = client.post(f"/api/sessions/{state['id']}/simulate").json()
        assert final["complete"] and len(final["your_roster"]) == 8

    def test_a_pool_too_thin_for_the_league_fails_cleanly(self, client):
        """Must read as a rejected config, never a 500 mid-creation."""
        r = client.post("/api/sessions", json={"teams": 32, "rounds": 15, "your_slot": 1})
        assert r.status_code in (200, 422)
        if r.status_code == 422:
            assert "pool" in r.json()["detail"].lower()

    def test_every_offered_team_size_completes(self, client):
        """A draft that stops short reads like success, so it must not happen."""
        for teams in (8, 10, 12):
            state = new_session(client, teams=teams, rounds=15, your_slot=1)
            final = client.post(f"/api/sessions/{state['id']}/simulate").json()
            assert final["complete"] is True, f"{teams} teams did not finish"
            assert len(final["picks"]) == teams * 15

    def test_a_league_the_pool_cannot_fill_is_rejected(self, client):
        r = client.post("/api/sessions", json={"teams": 14, "rounds": 15, "your_slot": 1})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert "player pool only has" in detail


class TestKeeperOnYourOwnSlot:
    """A keeper on your own draft slot in round 1.

    Reported as the keeper not being applied; the cause was in the setup UI,
    but the engine path is worth pinning down so it cannot regress.
    """

    def test_it_is_applied_and_appears_on_your_roster(self, client):
        state = new_session(client, your_slot=6, keepers=[
            {"team_slot": 6, "round": 1, "player_name": "Ja'Marr Chase"},
        ])
        assert state["unresolved_keepers"] == []

        pick_six = next(p for p in state["picks"] if p["overall"] == 6)
        assert pick_six["player_name"] == "Ja'Marr Chase"
        assert pick_six["source"] == "keeper"
        assert pick_six["team_slot"] == 6

        assert [(r["player_name"], r["round"]) for r in state["your_roster"]] == [
            ("Ja'Marr Chase", 1)
        ]

    def test_the_clock_skips_past_the_kept_pick(self, client):
        state = new_session(client, your_slot=6, keepers=[
            {"team_slot": 6, "round": 1, "player_name": "Ja'Marr Chase"},
        ])
        # Round 1 was spent on the keeper, so you are next up in round 2.
        assert state["on_the_clock"]["round"] == 2
        assert state["on_the_clock"]["team_slot"] == 6

    @pytest.mark.parametrize("slot", [1, 6, 12])
    def test_it_works_on_any_slot(self, client, slot):
        state = new_session(client, your_slot=slot, keepers=[
            {"team_slot": slot, "round": 1, "player_name": "Bijan Robinson"},
        ])
        assert [r["player_name"] for r in state["your_roster"]] == ["Bijan Robinson"]

    def test_a_blank_keeper_name_is_reported_not_swallowed(self, client):
        state = new_session(client, your_slot=6, keepers=[
            {"team_slot": 6, "round": 1, "player_name": "   "},
        ])
        # The UI blocks this, but if one arrives it must be visible, not silent.
        assert state["unresolved_keepers"] == ["   "]
