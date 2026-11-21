"""Real account-scoped state transitions; no generation/provider inference."""
from concurrent.futures import ThreadPoolExecutor
import time

import pytest
from fastapi import HTTPException

from src.api.services.agent_play import Arena, Session, TTL_SECONDS


@pytest.mark.asyncio
async def test_external_agent_turns_conflicts_and_private_access(client, auth_token):
    headers = {"Authorization": f"Bearer {auth_token}"}
    assert (await client.post("/api/v1/agent-play", json={})).status_code == 401
    response = await client.post("/api/v1/agent-play", headers=headers, json={"mode": "coop", "controller": "external"})
    assert response.status_code == 201
    state = response.json()
    path = f"/api/v1/agent-play/{state['session_id']}"
    assert "owner" not in state
    anonymous = await client.post("/api/v1/auth/anonymous")
    other = {"Authorization": f"Bearer {anonymous.json()['access_token']}"}
    for method, suffix, payload in [("GET", "", None), ("POST", "/actions", {"player": "agent", "action": "left", "expected_revision": 0}), ("DELETE", "", None)]:
        assert (await client.request(method, path + suffix, headers=other, json=payload)).status_code == 404
    action = {"player": "human", "action": "right", "expected_revision": 0}
    state = (await client.post(path + "/actions", headers=headers, json=action)).json()
    assert state["positions"]["human"] == [1, 3]
    assert state["turn"] == "agent"
    assert (await client.post(path + "/actions", headers=headers, json=action)).status_code == 409
    assert (await client.post(path + "/actions", headers=headers, json={"player": "agent", "action": "left", "expected_revision": True})).status_code == 422
    state = (await client.post(path + "/actions", headers=headers, json={"player": "agent", "action": "left", "expected_revision": 1})).json()
    assert state["positions"]["agent"] == [5, 3]
    assert state["turn"] == "human"
    current = await client.get(path, headers=headers)
    assert current.headers["cache-control"] == "no-store"
    assert (await client.delete(path, headers=headers)).status_code == 204
    assert (await client.get(path, headers=headers)).status_code == 404


def test_competing_requests_cannot_apply_the_same_turn_twice():
    arena = Arena()
    state = arena.create("owner", "versus", "external")
    def act():
        try:
            return arena.action(state["session_id"], "owner", "human", "right", 0)
        except HTTPException as e:
            return e.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: act(), range(2)))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert 409 in results
    assert arena.read(state["session_id"], "owner")["positions"]["human"] == [1, 3]


@pytest.mark.parametrize("mode,outcome", [("coop", "team"), ("versus", "human")])
def test_final_star_ends_game_and_cannot_be_scored_twice(mode, outcome):
    arena = Arena()
    session = Session("owner", mode, "external")
    session.positions["human"] = [2, 3]
    session.scores = {"human": 5 if mode == "coop" else 2, "agent": 0}
    arena.sessions[session.id] = session
    state = arena.action(session.id, "owner", "human", "right", 0)
    assert state["outcome"] == outcome
    assert state["turn"] is None
    assert not any(state["legal_actions"].values())
    with pytest.raises(HTTPException) as error:
        arena.action(session.id, "owner", "agent", "left", 1)
    assert error.value.status_code == 409


def test_builtin_coop_waits_for_nearer_human_and_replies_once():
    arena = Arena()
    state = arena.create("owner", "coop", "builtin")
    state = arena.action(state["session_id"], "owner", "human", "right", 0)
    assert state["revision"] == 2
    assert state["positions"] == {"human": [1, 3], "agent": [6, 3]}
    assert state["turn"] == "human"
    state["positions"]["human"][0] = 99
    assert arena.read(state["session_id"], "owner")["positions"]["human"] == [1, 3]


def test_session_expiry_and_account_quota_are_bounded():
    arena = Arena()
    states = [arena.create("owner", "versus", "external") for _ in range(8)]
    with pytest.raises(HTTPException) as error:
        arena.create("owner", "versus", "external")
    assert error.value.status_code == 429
    arena.sessions[states[0]["session_id"]].updated = time.monotonic() - TTL_SECONDS - 1
    with pytest.raises(HTTPException) as error:
        arena.read(states[0]["session_id"], "owner")
    assert error.value.status_code == 404
    arena.create("owner", "coop", "external")


def test_automatic_connect_is_atomic_and_resumes_progress():
    arena = Arena()
    with ThreadPoolExecutor(max_workers=4) as pool:
        states = list(pool.map(lambda _: arena.connect("owner"), range(12)))
    assert len({s["session_id"] for s in states}) == 1
    assert len(arena.sessions) == 1
    state = states[0]
    assert state["agent_name"] == "Pip"
    assert state["agent_connected"] is False
    moved = arena.action(state["session_id"], "owner", "human", "right", 0)
    assert arena.connect("owner") == moved
    assert moved["revision"] == 2
    assert moved["turn"] == "human"
    challenge = arena.connect("owner", mode="versus")
    assert challenge["session_id"] != state["session_id"]
    assert len(arena.sessions) == 1


def test_agent_discovers_and_joins_same_round_without_resetting_it():
    arena = Arena()
    state = arena.connect("owner", mode="versus")
    moved = arena.action(state["session_id"], "owner", "human", "right", 0)
    joined = arena.connect("owner", join=True)
    assert joined["session_id"] == state["session_id"]
    assert joined["mode"] == "versus"
    assert joined["positions"] == moved["positions"]
    assert joined["agent_connected"] is True
    pending = arena.action(state["session_id"], "owner", "human", "right", joined["revision"])
    assert pending["turn"] == "agent"
    reply_by = arena.sessions[state["session_id"]].reply_by
    arena.connect("owner", join=True)
    assert arena.sessions[state["session_id"]].reply_by == reply_by
    reply = arena.action(state["session_id"], "owner", "agent", "left", pending["revision"])
    assert reply["turn"] == "human"


def test_disconnected_agent_cannot_strand_human_or_replay_fallback_turn():
    arena = Arena()
    state = arena.connect("owner", join=True)
    pending = arena.action(state["session_id"], "owner", "human", "right", 0)
    assert pending["turn"] == "agent"
    arena.sessions[state["session_id"]].reply_by = time.monotonic() - 1
    resumed = arena.read(state["session_id"], "owner")
    assert resumed["revision"] == 2
    assert resumed["turn"] == "human"
    assert resumed["agent_connected"] is False
    assert arena.read(state["session_id"], "owner") == resumed
    with pytest.raises(HTTPException) as error:
        arena.action(state["session_id"], "owner", "agent", "left", pending["revision"])
    assert error.value.status_code == 409


def test_joining_an_existing_external_turn_preserves_progress():
    arena = Arena()
    state = arena.create("owner", "versus", "external")
    pending = arena.action(state["session_id"], "owner", "human", "right", 0)
    joined = arena.connect("owner", join=True)
    assert joined["revision"] == pending["revision"]
    assert joined["positions"] == pending["positions"]
    reply = arena.action(state["session_id"], "owner", "agent", "left", 1)
    assert reply["revision"] == 2


@pytest.mark.asyncio
async def test_connect_and_discovery_keep_account_boundaries(client, auth_token):
    headers = {"Authorization": f"Bearer {auth_token}"}
    assert (await client.post("/api/v1/agent-play/connect", json={})).status_code == 401
    state = (await client.post("/api/v1/agent-play/connect", headers=headers, json={})).json()
    joined = await client.post("/api/v1/agent-play/join", headers=headers, json={})
    assert joined.json()["session_id"] == state["session_id"]
    assert joined.json()["agent_connected"] is True
    other = await client.post("/api/v1/auth/anonymous")
    other_headers = {"Authorization": "Bearer " + other.json()["access_token"]}
    assert (await client.get("/api/v1/agent-play/current", headers=other_headers)).status_code == 404
    assert (await client.post("/api/v1/agent-play/join", headers=other_headers, json={"session_id": state["session_id"]})).status_code == 404
