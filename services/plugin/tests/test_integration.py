"""Exercise actual OAuth HTTP endpoints, SDK sessions, and filesystem-backed API."""

import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from jsonschema import validate
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def link(
    gateway,
    *,
    account="owner",
    scope="games:read games:write games:play",
    check_rejections=False,
    auth_method="none",
):
    app, client, config, _ = gateway
    redirect = "http://127.0.0.1:54321/callback"
    registration = await client.post(
        "/register",
        json={
            "client_name": "TinyWorlds Test Client",
            "redirect_uris": [redirect],
            "token_endpoint_auth_method": auth_method,
            "scope": scope,
        },
    )
    assert registration.status_code == 201, registration.text
    identity = registration.json()
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    authorize = await client.get(
        "/authorize",
        params={
            "client_id": identity["client_id"],
            "response_type": "code",
            "redirect_uri": redirect,
            "scope": scope,
            "state": "test-state",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": config.resource,
        },
    )
    assert authorize.status_code == 302, authorize.text
    ticket = parse_qs(urlsplit(authorize.headers["location"]).query)["ticket"][0]
    page = await client.get(authorize.headers["location"])
    assert page.status_code == 200
    csrf = client.cookies.get("tw_plugin_csrf")
    consent = await client.post(
        "/connect",
        data={
            "ticket": ticket,
            "csrf": csrf,
            "decision": "allow",
            "email": f"plugin-{account}@example.com",
            "password": "local-plugin-test-password",
        },
        headers={"Origin": config.public_url},
    )
    assert consent.status_code == 303, consent.text
    callback = parse_qs(urlsplit(consent.headers["location"]).query)
    assert callback["state"] == ["test-state"]
    assert callback["iss"] == [config.issuer]
    form = {
        "client_id": identity["client_id"],
        "grant_type": "authorization_code",
        "code": callback["code"][0],
        "redirect_uri": redirect,
        "code_verifier": verifier,
        "resource": config.resource,
    }
    if auth_method == "client_secret_post":
        form["client_secret"] = identity["client_secret"]
    if check_rejections:
        for changes in (
            {"code_verifier": "incorrect-verifier"},
            {"redirect_uri": "http://127.0.0.1:54321/other"},
            {"resource": "https://wrong.example/mcp"},
        ):
            rejected = await client.post("/token", data={**form, **changes})
            assert rejected.status_code == 400, rejected.text
    token = await client.post("/token", data=form)
    assert token.status_code == 200, token.text
    return identity, token.json(), form


async def call(config, token, name, arguments=None):
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}) as http:
        async with streamable_http_client(config.resource, http_client=http) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments or {})
                if not result.isError:
                    assert result.structuredContent is not None, name
                    tools = await session.list_tools()
                    tool = next(tool for tool in tools.tools if tool.name == name)
                    if tool.outputSchema is not None:
                        validate(result.structuredContent, tool.outputSchema)
                return result


@pytest.mark.asyncio
async def test_oauth_discovery_pkce_resource_replay_refresh_and_revoke(gateway):
    _, client, config, _ = gateway
    unauthorized = await client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    )
    assert unauthorized.status_code == 401
    assert "resource_metadata=" in unauthorized.headers["www-authenticate"]
    protected = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert protected.json()["resource"] == config.resource
    metadata = (await client.get("/.well-known/oauth-authorization-server")).json()
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert metadata["revocation_endpoint"] == config.public_url + "/revoke"
    preflight = await client.options(
        "/revoke",
        headers={
            "Origin": "https://chatgpt.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert preflight.status_code == 200
    assert "POST" in preflight.headers["access-control-allow-methods"]
    identity, token, form = await link(gateway, check_rejections=True)
    assert (await client.post("/token", data=form)).status_code == 400
    wrong_resource = await client.post(
        "/token", data={**form, "resource": "https://wrong.example/mcp"}
    )
    assert wrong_resource.status_code == 400
    rotated = await client.post(
        "/token",
        data={
            "client_id": identity["client_id"],
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "resource": config.resource,
        },
    )
    assert rotated.status_code == 200, rotated.text
    new = rotated.json()
    assert new["access_token"] != token["access_token"]
    profile = await call(config, new["access_token"], "get_profile")
    assert not profile.isError
    revoked = await client.post(
        "/revoke",
        data={"client_id": identity["client_id"], "token": new["refresh_token"]},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.headers["cache-control"] == "no-store"
    denied = await client.post(
        "/mcp", headers={"Authorization": "Bearer " + new["access_token"]}, json={}
    )
    assert denied.status_code == 401
    refresh_denied = await client.post(
        "/token",
        data={
            "client_id": identity["client_id"],
            "grant_type": "refresh_token",
            "refresh_token": new["refresh_token"],
            "resource": config.resource,
        },
    )
    assert refresh_denied.status_code == 400


@pytest.mark.asyncio
async def test_revocation_client_binding_and_refresh_reuse(gateway):
    _, client, config, _ = gateway
    identity, token, _ = await link(gateway)
    other, _, _ = await link(gateway, account="other")
    foreign = await client.post(
        "/revoke",
        data={"client_id": other["client_id"], "token": token["access_token"]},
    )
    assert foreign.status_code == 200, foreign.text
    assert not (await call(config, token["access_token"], "get_profile")).isError
    missing = await client.post("/revoke", data={"client_id": identity["client_id"]})
    assert missing.status_code == 400
    unknown = await client.post(
        "/revoke",
        data={
            "client_id": identity["client_id"],
            "token": "unknown-token",
            "token_type_hint": "unknown-type",
        },
    )
    assert unknown.status_code == 200
    refresh_form = {
        "client_id": identity["client_id"],
        "grant_type": "refresh_token",
        "refresh_token": token["refresh_token"],
        "resource": config.resource,
    }
    rotated = await client.post("/token", data=refresh_form)
    assert rotated.status_code == 200, rotated.text
    reuse = await client.post("/token", data=refresh_form)
    assert reuse.status_code == 400
    denied = await client.post(
        "/mcp",
        headers={"Authorization": "Bearer " + rotated.json()["access_token"]},
        json={},
    )
    assert denied.status_code == 401

    identity, token, _ = await link(gateway)
    revoked = await client.post(
        "/revoke",
        data={"client_id": identity["client_id"], "token": token["access_token"]},
    )
    assert revoked.status_code == 200, revoked.text
    denied = await client.post(
        "/mcp", headers={"Authorization": "Bearer " + token["access_token"]}, json={}
    )
    assert denied.status_code == 401


@pytest.mark.asyncio
async def test_oauth_confidential_client_requires_secret_on_revocation(gateway):
    _, client, config, _ = gateway
    identity, token, _ = await link(gateway, auth_method="client_secret_post")
    form = {"client_id": identity["client_id"], "token": token["refresh_token"]}
    for changes in ({}, {"client_secret": "incorrect-secret"}):
        rejected = await client.post("/revoke", data={**form, **changes})
        assert rejected.status_code == 401, rejected.text
    assert not (await call(config, token["access_token"], "get_profile")).isError
    revoked = await client.post(
        "/revoke", data={**form, "client_secret": identity["client_secret"]}
    )
    assert revoked.status_code == 200, revoked.text
    denied = await client.post(
        "/mcp", headers={"Authorization": "Bearer " + token["access_token"]}, json={}
    )
    assert denied.status_code == 401


@pytest.mark.asyncio
async def test_private_games_profile_preview_and_unverified_status(gateway):
    _, _, config, root = gateway
    _, owner, _ = await link(gateway)
    profile = await call(config, owner["access_token"], "get_profile")
    assert (
        profile.structuredContent["id"]
        == json.loads((root / "fixture-users.json").read_text())["owner"]
    )
    listed = await call(config, owner["access_token"], "list_games")
    assert not listed.isError
    assert {g["game_id"] for g in listed.structuredContent["games"]} >= {
        "godot-pluginfixture",
        "bevy-pluginfixture",
    }
    assert all(
        "game_path" not in game and "play_url" not in game
        for game in listed.structuredContent["games"]
    )
    for target in ("godot", "bevy"):
        game_id = target + "-pluginfixture"
        game = await call(
            config, owner["access_token"], "get_game", {"game_id": game_id}
        )
        assert not game.isError
        assert game.structuredContent["game_id"] == game_id
        assert game.structuredContent["visibility"] == "private"
        assert "play_url" not in game.structuredContent
        job = await call(config, owner["access_token"], "get_job", {"game_id": game_id})
        # Startup marks these preexisting unfinished jobs interrupted; a success
        # summary must not override that terminal event or claim verification.
        assert job.structuredContent["status"] == "interrupted"
        assert job.structuredContent["browser_verified"] is False
        assert (
            job.structuredContent["reason"]
            == "Backend restarted before verification completed"
        )
        preview = await call(
            config, owner["access_token"], "get_game_preview", {"game_id": game_id}
        )
        assert not preview.isError
        assert any(block.type == "image" for block in preview.content)
    _, other, _ = await link(gateway, account="other")
    forbidden_list = await call(config, other["access_token"], "list_games")
    assert not forbidden_list.structuredContent["games"]
    for name in (
        "get_game",
        "get_job",
        "get_game_preview",
        "cancel_job",
        "modify_game",
    ):
        args = {"game_id": "godot-pluginfixture"}
        if name == "modify_game":
            args.update(
                instruction="Change the background", request_id="forbidden-modify-0001"
            )
        denied = await call(config, other["access_token"], name, args)
        assert denied.isError, name


@pytest.mark.asyncio
async def test_real_queue_idempotency_poll_and_cancel(gateway):
    _, _, config, root = gateway
    _, token, _ = await link(gateway)
    for target in ("godot", "bevy"):
        args = {
            "description": "Make a minimal game with a moving square. Use no paid assets.",
            "request_id": "plugin-create-queue-" + target,
            "engine": target,
        }
        started = await call(config, token["access_token"], "create_game", args)
        assert not started.isError, started
        receipt = started.structuredContent
        assert receipt["status"] == "queued"
        try:
            repeated = await call(config, token["access_token"], "create_game", args)
            assert repeated.structuredContent == receipt
            metadata = json.loads(
                (
                    root / "data/game-metadata" / (receipt["game_id"] + ".json")
                ).read_text()
            )
            assert metadata["visibility"] == "private"
            initial = json.loads(
                (
                    root
                    / "generated_games"
                    / receipt["game_id"]
                    / ".creation/events.jsonl"
                )
                .read_text()
                .splitlines()[0]
            )
            assert initial["budget_cents"] == 0
            progress = await call(
                config,
                token["access_token"],
                "get_job",
                {"game_id": receipt["game_id"]},
            )
            assert not progress.isError
            conflict = await call(
                config,
                token["access_token"],
                "create_game",
                {**args, "description": "Different request"},
            )
            assert conflict.isError
        finally:
            cancelled = await call(
                config,
                token["access_token"],
                "cancel_job",
                {"game_id": receipt["game_id"]},
            )
            assert not cancelled.isError


@pytest.mark.asyncio
async def test_real_modification_receipt_idempotency_poll_and_cancel(gateway):
    _, _, config, _ = gateway
    _, token, _ = await link(gateway)
    for target in ("godot", "bevy"):
        game_id = target + "-pluginfixture"
        args = {
            "game_id": game_id,
            "instruction": "Change the background color. Use no paid assets.",
            "request_id": "plugin-modify-queue-" + target,
        }
        started = await call(config, token["access_token"], "modify_game", args)
        assert not started.isError, started
        receipt = started.structuredContent
        assert receipt["status"] == "queued"
        assert receipt["game_id"] == game_id
        assert receipt["engine"] == target
        assert receipt["run_id"]
        try:
            repeated = await call(config, token["access_token"], "modify_game", args)
            assert repeated.structuredContent == receipt
            progress = await call(
                config,
                token["access_token"],
                "get_job",
                {"game_id": game_id, "run_id": receipt["run_id"]},
            )
            assert not progress.isError, progress
            assert progress.structuredContent["run_id"] == receipt["run_id"]
            assert progress.structuredContent["engine"] == target
        finally:
            cancelled = await call(
                config, token["access_token"], "cancel_job", {"game_id": game_id}
            )
            assert not cancelled.isError, cancelled


@pytest.mark.asyncio
async def test_read_scope_csrf_redirect_validation_and_secret_storage(gateway):
    app, client, config, _ = gateway
    invalid = await client.post(
        "/register", json={"redirect_uris": ["https://attacker.example/callback"]}
    )
    assert invalid.status_code == 400
    forged = await client.post(
        "/connect",
        data={"ticket": "forged", "csrf": "forged"},
        headers={"Origin": config.public_url},
    )
    assert forged.status_code == 403
    _, token, _ = await link(gateway, scope="games:read")
    denied = await call(
        config,
        token["access_token"],
        "create_game",
        {"description": "A game", "request_id": "read-scope-write-0001"},
    )
    assert denied.isError
    stored = app.state.store.path.read_bytes()
    assert token["access_token"].encode() not in stored
    assert token["refresh_token"].encode() not in stored
    assert b"local-plugin-test-password" not in stored
    assert b"plugin-owner@example.com" not in stored


@pytest.mark.asyncio
async def test_tool_schemas_annotations_and_unsafe_ids(gateway):
    _, _, config, _ = gateway
    _, token, _ = await link(gateway)
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + token["access_token"]}
    ) as http:
        async with streamable_http_client(config.resource, http_client=http) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                tools = {tool.name: tool for tool in listing.tools}
                assert len(tools) == 13
                for name, tool in tools.items():
                    if name != "get_game_preview":
                        assert tool.outputSchema is not None, name
                        assert tool.outputSchema["type"] == "object", name
                assert tools["get_profile"].meta["openai/profile"] is True
                assert tools["get_profile"].outputSchema["required"] == [
                    "id",
                    "name",
                    "email",
                ]
                assert tools["create_game"].annotations.readOnlyHint is False
                assert tools["cancel_job"].annotations.destructiveHint is True
                assert tools["get_job"].annotations.readOnlyHint is True
                bad = await session.call_tool("get_game", {"game_id": "../../secrets"})
                assert bad.isError


@pytest.mark.asyncio
async def test_agent_play_uses_same_account_and_cannot_replay_a_turn(gateway):
    _, _, config, _ = gateway
    _, owner, _ = await link(gateway)
    started = await call(config, owner["access_token"], "start_play_session", {"mode": "versus"})
    assert not started.isError
    state = started.structuredContent
    session_id = state["session_id"]
    assert state["turn"] == "human"
    assert state["controller"] == "auto"
    assert state["agent_name"] == "Pip"
    joined = await call(config, owner["access_token"], "join_play_session")
    assert joined.structuredContent["session_id"] == session_id
    discovered = await call(config, owner["access_token"], "get_play_state")
    assert discovered.structuredContent["session_id"] == session_id
    assert state["url"].endswith(session_id)
    _, other, _ = await link(gateway, account="other")
    assert (await call(config, other["access_token"], "get_play_state", {"session_id": session_id})).isError
    # The human browser and MCP agent share the owner's game session, not an API token.
    # Before the human moves, the agent must wait; tools cannot bypass turn order.
    result = await call(config, owner["access_token"], "play_action", {"session_id": session_id, "action": "left", "expected_revision": 0})
    assert result.isError
    readback = await call(config, owner["access_token"], "get_play_state", {"session_id": session_id})
    assert readback.structuredContent["revision"] == 0
    async with httpx.AsyncClient(base_url=config.backend_url) as browser:
        login = await browser.post("/api/v1/auth/login", data={"username": "plugin-owner@example.com", "password": "local-plugin-test-password"})
        assert login.status_code == 200
        human_move = await browser.post(f"/api/v1/agent-play/{session_id}/actions", headers={"Authorization": "Bearer " + login.json()["access_token"]}, json={"player": "human", "action": "right", "expected_revision": 0})
        assert human_move.status_code == 200
    action = {"session_id": session_id, "action": "left", "expected_revision": 1}
    moved = await call(config, owner["access_token"], "play_action", action)
    assert not moved.isError
    assert moved.structuredContent["positions"]["agent"] == [5, 3]
    assert moved.structuredContent["turn"] == "human"
    assert (await call(config, owner["access_token"], "play_action", action)).isError
    _, readonly, _ = await link(gateway, scope="games:read")
    assert (await call(config, readonly["access_token"], "start_play_session", {"mode": "coop"})).isError
    assert (await call(config, readonly["access_token"], "join_play_session")).isError
    _, playonly, _ = await link(gateway, scope="games:read games:play")
    played = await call(config, playonly["access_token"], "get_play_state", {"session_id": session_id})
    assert not played.isError
    denied = await call(config, playonly["access_token"], "modify_game", {"game_id": "godot-pluginfixture", "instruction": "Change the title", "request_id": "play-only-cannot-edit-source"})
    assert denied.isError
    closed = await call(config, owner["access_token"], "end_play_session", {"session_id": session_id})
    assert not closed.isError
    assert closed.structuredContent["cancelled"] is True
    assert (await call(config, owner["access_token"], "get_play_state", {"session_id": session_id})).isError


@pytest.mark.asyncio
@pytest.mark.parametrize('engine', ['godot', 'bevy'])
async def test_generated_game_is_discovered_and_native_command_is_acknowledged(gateway, engine):
    _, _, config, _ = gateway
    _, owner, _ = await link(gateway)
    async with httpx.AsyncClient(base_url=config.backend_url) as browser:
        login = await browser.post('/api/v1/auth/login', data={'username':'plugin-owner@example.com','password':'local-plugin-test-password'})
        assert login.is_success
        headers = {'Authorization':'Bearer '+login.json()['access_token']}
        payload = {'client_id':'b'*32,'actions':['jump_pip','wait'],'observation':{'human':{'x':1},'pip':{'x':5},'goal':'reach flag'}}
        sync = await browser.post(f'/api/v1/agent-play/games/{engine}-pluginfixture/sync', headers=headers, json=payload)
        assert sync.is_success
        joined = await call(config, owner['access_token'], 'join_play_session')
        assert not joined.isError
        state = joined.structuredContent
        assert state['game'] == engine+'-pluginfixture'
        assert state['url'].endswith('/games/'+state['game'])
        result = await call(config, owner['access_token'], 'play_action', {'session_id':state['session_id'],'action':'jump_pip','expected_revision':state['revision']})
        assert not result.isError
        command = result.structuredContent['command']
        assert command['action'] == 'jump_pip'
        received = (await browser.post(f'/api/v1/agent-play/games/{engine}-pluginfixture/sync', headers=headers, json=payload)).json()
        assert received['command'] == command
        payload['acknowledgement'] = {'id':command['id'],'accepted':True}
        payload['observation']['pip']['x'] = 6
        assert (await browser.post(f'/api/v1/agent-play/games/{engine}-pluginfixture/sync', headers=headers, json=payload)).is_success
        readback = await call(config, owner['access_token'], 'get_play_state', {'session_id':state['session_id']})
        assert readback.structuredContent['command'] is None
        assert readback.structuredContent['acknowledgement']['accepted'] is True
        assert readback.structuredContent['observation']['pip']['x'] == 6
        _, other, _ = await link(gateway, account='other')
        assert (await call(config, other['access_token'], 'get_play_state', {'session_id':state['session_id']})).isError
        assert not (await call(config, owner['access_token'], 'end_play_session', {'session_id':state['session_id']})).isError
        assert not (await browser.get('/api/v1/agent-play/auto/state',headers=headers)).json()['agent_connected']
