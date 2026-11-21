"""Real filesystem/configuration and request-boundary checks; no provider doubles."""
import json
from pathlib import Path
import secrets
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from src.api.core.config import Settings
from src.api.routes.provider_connection import local_operator
from src.api.services.executors import get_executor
from src.api.services.personal_provider import Connection, PersonalProvider, private_write, resolve_personal_settings


def settings(tmp_path, **kwargs):
    return Settings(_env_file=None, SECRET_KEY="personal-provider-test-only",
                    PERSONAL_PROVIDER_DIR=str(tmp_path / "providers"), **kwargs)


def request(host="localhost:8515", peer="127.0.0.1", origin="http://localhost:3336", header=True):
    headers = [(b"host", host.encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if header:
        headers.append((b"x-tinyworlds-local", b"1"))
    return Request({"type": "http", "scheme": "http", "path": "/api/v1/provider-connection", "query_string": b"", "headers": headers, "client": (peer, 1234), "server": ("127.0.0.1", 8515), "method": "POST"})


@pytest.mark.parametrize("overrides", [
    {"peer": "203.0.113.8"}, {"host": "evil.example"},
    {"origin": "https://evil.example"}, {"origin": "null"},
    {"origin": "http://localhost:8515"}, {"header": False},
])
def test_setup_rejects_remote_hosts_origins_and_missing_header(tmp_path, overrides):
    config = settings(tmp_path, PERSONAL_MODE=True, CORS_ORIGINS=["http://localhost:3336"])
    with pytest.raises(HTTPException) as failure:
        local_operator(request(**overrides), Response(), config)
    assert failure.value.status_code == 403


@pytest.mark.parametrize("config", [{}, {"PERSONAL_MODE": True, "AGENT_EXECUTION_MODE": "worker"}, {"PERSONAL_MODE": True, "REQUIRE_PRODUCTION_SECRETS": True}])
def test_setup_is_unavailable_outside_personal_local_mode(tmp_path, config):
    with pytest.raises(HTTPException) as failure:
        local_operator(request(), Response(), settings(tmp_path, **config))
    assert failure.value.status_code == 404


def test_local_operator_response_is_not_cached(tmp_path):
    response = Response()
    local_operator(request(), response, settings(tmp_path, PERSONAL_MODE=True, CORS_ORIGINS=["http://localhost:3336"]))
    assert response.headers["cache-control"] == "no-store"


def test_personal_mode_never_silently_uses_host_credentials(tmp_path):
    with pytest.raises(HTTPException) as failure:
        get_executor(settings(tmp_path, PERSONAL_MODE=True))
    assert failure.value.status_code == 409


def test_credentials_cannot_be_stored_in_a_game_directory(tmp_path):
    config = settings(tmp_path, PERSONAL_MODE=True, GODOT_GAMES_DIR=str(tmp_path))
    with pytest.raises(HTTPException) as failure:
        PersonalProvider(config)
    assert failure.value.status_code == 503


def test_profile_selects_only_its_provider_and_keeps_key_out_of_serialized_settings(tmp_path):
    config = settings(tmp_path, PERSONAL_MODE=True, GAME_AGENT_PROVIDER="codex")
    service = PersonalProvider(config)
    profile = uuid4()
    # Storage fixture only; never sent to an inference provider or called a valid credential.
    credential = secrets.token_urlsafe(32)
    private_write(service.root / str(profile) / "api-key", credential)
    service.save(Connection(provider="claude", kind="managed", profile=profile, model="operator-selected-model"))
    executor = get_executor(config)
    assert executor.provider == "claude"
    assert executor.settings.CLAUDE_CLI_MODEL == "operator-selected-model"
    env = executor._build_env()
    assert env["ANTHROPIC_API_KEY"] == credential
    assert "OPENAI_API_KEY" not in env and "CLAUDE_CODE_OAUTH_TOKEN" not in env
    assert credential not in executor.settings.model_dump_json()
    assert credential not in json.dumps(service.status())
    assert config.GAME_AGENT_PROVIDER == "codex"  # No shared settings mutation.
    assert (service.root.stat().st_mode & 0o777) == 0o700
    assert ((service.root / str(profile) / "api-key").stat().st_mode & 0o777) == 0o600
    assert ((service.root / "connection.json").stat().st_mode & 0o777) == 0o600


@pytest.mark.asyncio
async def test_disconnect_removes_only_app_managed_credentials(tmp_path):
    config = settings(tmp_path, PERSONAL_MODE=True)
    service = PersonalProvider(config)
    outside = tmp_path / "operator-cli-login"
    outside.write_text("untouched")
    profile = uuid4()
    private_write(service.root / str(profile) / "api-key", secrets.token_urlsafe(32))
    service.save(Connection(provider="claude", kind="managed", profile=profile))
    await service.disconnect()
    assert not (service.root / str(profile)).exists()
    assert service.status()["connection"] is None
    assert outside.read_text() == "untouched"


def test_malformed_or_missing_profile_fails_closed(tmp_path):
    config = settings(tmp_path, PERSONAL_MODE=True)
    private_write(Path(config.PERSONAL_PROVIDER_DIR) / "connection.json", '{"provider":"codex","kind":"managed","profile":"../../outside"}')
    with pytest.raises(HTTPException) as failure:
        resolve_personal_settings(config)
    assert failure.value.status_code == 503


def test_sentry_drops_credential_entry_events():
    from src.api.main import _filter_provider_setup_events
    assert _filter_provider_setup_events({"request": {"url": "http://localhost:8515/api/v1/provider-connection"}}, {}) is None
    assert _filter_provider_setup_events({"transaction": "POST /api/v1/provider-connection/check"}, {}) is None
    ordinary = {"request": {"url": "http://localhost:8515/health"}}
    assert _filter_provider_setup_events(ordinary, {}) is ordinary
