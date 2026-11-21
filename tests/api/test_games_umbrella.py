"""Integration tests for the umbrella ``/api/v1/games`` router.

Mirrors the testing strategy of ``tests/api/test_bevy_routes.py``
(httpx ``AsyncClient`` + ``ASGITransport``, override auth + rate-limit
deps, point ``GODOT_GAMES_DIR`` at ``tmp_path``).

Covers:

* POST dispatches to the godot pipeline by default and emits an init
  event with ``engine="godot"`` and a ``godot-`` prefixed id.
* POST dispatches to bevy when the setting is flipped, emits
  ``engine="bevy"`` and a ``bevy-`` prefixed id, and never instantiates
  the godot agent.
* GET merges both engines' games into one response.
* GET continues with one engine when the other's service raises.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.dependencies import get_current_user, get_optional_current_user
from src.api.main import app
from src.api.middleware.rate_limit import check_game_creation_rate_limit
from src.api.observability.events import CompletionEvent
from src.api.routes import games as games_route, godot_games, bevy_games


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def games_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Repoint GODOT_GAMES_DIR for the umbrella module at a tmp dir."""
    base = tmp_path / "workspace" / "generated_games"
    base.mkdir(parents=True)
    monkeypatch.setattr(games_route.settings, "GODOT_GAMES_DIR", str(base))
    return base


@pytest.fixture
def fake_user():
    return SimpleNamespace(
        id="test-user-id",
        email="test@example.com",
        username="tester",
        is_active=True,
        is_admin=False,
    )


@pytest_asyncio.fixture
async def client(fake_user):
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_optional_current_user] = lambda: fake_user
    app.dependency_overrides[check_game_creation_rate_limit] = lambda: None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /games — engine dispatch
# ---------------------------------------------------------------------------


class _FakeGodotAgent:
    """Stub creation agent for godot — emits one CompletionEvent."""

    instantiated = 0

    def __init__(self, *args, **kwargs):
        type(self).instantiated += 1

    async def create_game(self, request, game_path) -> AsyncIterator:
        yield CompletionEvent(
            service="godot_creation_agent",
            message="stubbed",
            result_path=str(game_path),
        )

    async def attempt_fix(self, game_path, failures, **kwargs) -> AsyncIterator:
        if False:
            yield  # pragma: no cover


class _FakeBevyAgent:
    instantiated = 0

    def __init__(self, *args, **kwargs):
        type(self).instantiated += 1

    async def create_game(self, request, game_path) -> AsyncIterator:
        yield CompletionEvent(
            service="bevy_creation_agent",
            message="stubbed",
            result_path=str(game_path),
        )

    async def attempt_fix(self, game_path, failures, **kwargs) -> AsyncIterator:
        if False:
            yield  # pragma: no cover


def _stub_verification(monkeypatch):
    suggestions = AsyncMock(return_value=None)
    monkeypatch.setattr("src.api.services.suggestions_generator.generate_suggestions", suggestions)
    monkeypatch.setattr(godot_games, "generate_suggestions", suggestions, raising=False)
    monkeypatch.setattr(bevy_games, "generate_suggestions", suggestions, raising=False)
    monkeypatch.setattr(godot_games, "verify_browser", AsyncMock(return_value=[]))
    monkeypatch.setattr(bevy_games, "verify_browser", AsyncMock(return_value=[]))
    monkeypatch.setattr("src.api.services.godot_game_service.GodotGameService.export_html5", AsyncMock(return_value=None))
    monkeypatch.setattr("src.api.services.godot_game_service.GodotGameService.verify_playable", MagicMock(return_value=[]))
    monkeypatch.setattr("src.api.services.bevy_game_service.BevyGameService.build_wasm", MagicMock(return_value=None))
    monkeypatch.setattr("src.api.services.bevy_game_service.BevyGameService.verify_playable", MagicMock(return_value=[]))


def _parse_init(body: str) -> dict:
    line = next((ln for ln in body.splitlines() if ln.startswith("data: ")), None)
    assert line is not None, f"no SSE data lines in body: {body!r}"
    return json.loads(line[len("data: "):])


@pytest.mark.parametrize("engine", ["godot", "bevy"])
@pytest.mark.parametrize("failure", [
    {"event_type": "ErrorEvent", "error_message": "Repair provider failed"},
    {"event_type": "CLIStreamEvent", "stream_type": "error", "content": "Repair provider failed"},
])
async def test_failed_repair_cannot_report_done(
    client, games_dir, monkeypatch, engine, failure,
):
    monkeypatch.setattr(games_route.settings, "DEFAULT_GAME_ENGINE", engine)
    _stub_verification(monkeypatch)
    route = godot_games if engine == "godot" else bevy_games
    verify = AsyncMock(side_effect=[["Initial render failed"], []])
    monkeypatch.setattr(route, "verify_browser", verify)

    class RepairFailureAgent(_FakeGodotAgent):
        async def attempt_fix(self, game_path, failures, **kwargs):
            yield SimpleNamespace(to_sse_dict=lambda: failure)

    monkeypatch.setattr(route, "GodotCreationAgent" if engine == "godot" else "BevyCreationAgent", RepairFailureAgent)
    response = await client.post("/api/v1/games", json={"description": "repair regression"})
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["event_type"] == "failed"
    assert events[-1]["failures"] == ["Repair provider failed"]
    assert not any(event["event_type"] == "done" for event in events)
    assert verify.await_count == 1


async def test_create_game_dispatches_to_godot_when_default(
    client: AsyncClient,
    games_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Default flag (``godot``) routes through the godot creation agent."""
    monkeypatch.setattr(games_route.settings, "DEFAULT_GAME_ENGINE", "godot")
    _stub_verification(monkeypatch)

    _FakeGodotAgent.instantiated = 0
    _FakeBevyAgent.instantiated = 0
    monkeypatch.setattr(godot_games, "GodotCreationAgent", _FakeGodotAgent)
    monkeypatch.setattr(bevy_games, "BevyCreationAgent", _FakeBevyAgent)

    resp = await client.post(
        "/api/v1/games",
        json={"description": "a tiny world"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200, resp.text

    init = _parse_init(resp.text)
    assert init["event_type"] == "init"
    assert init["engine"] == "godot"
    assert init["game_id"].startswith("godot-")
    assert len(init["game_id"]) == len("godot-") + 8

    assert _FakeGodotAgent.instantiated == 1
    assert _FakeBevyAgent.instantiated == 0


async def test_create_game_dispatches_to_bevy_when_flagged(
    client: AsyncClient,
    games_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Setting ``DEFAULT_GAME_ENGINE=bevy`` routes through the bevy agent."""
    monkeypatch.setattr(games_route.settings, "DEFAULT_GAME_ENGINE", "bevy")
    _stub_verification(monkeypatch)

    _FakeGodotAgent.instantiated = 0
    _FakeBevyAgent.instantiated = 0
    monkeypatch.setattr(godot_games, "GodotCreationAgent", _FakeGodotAgent)
    monkeypatch.setattr(bevy_games, "BevyCreationAgent", _FakeBevyAgent)

    resp = await client.post(
        "/api/v1/games",
        json={"description": "a tiny rust world"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200, resp.text

    init = _parse_init(resp.text)
    assert init["event_type"] == "init"
    assert init["engine"] == "bevy"
    assert init["game_id"].startswith("bevy-")
    assert len(init["game_id"]) == len("bevy-") + 8

    assert _FakeBevyAgent.instantiated == 1
    assert _FakeGodotAgent.instantiated == 0


# ---------------------------------------------------------------------------
# GET /games — merge + degrade
# ---------------------------------------------------------------------------


async def test_list_games_merges_both_engines(client: AsyncClient, games_dir: Path):
    """Both godot and bevy game directories surface in the merged response."""
    godot = games_dir / "godot-aaaaaaaa"
    godot.mkdir()
    (godot / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    bevy = games_dir / "bevy-bbbbbbbb"
    bevy.mkdir()
    (bevy / "Cargo.toml").write_text(
        '[package]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (bevy / "src").mkdir()
    (bevy / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")

    resp = await client.get("/api/v1/games")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    by_id = {item["game_id"]: item for item in data}
    assert "godot-aaaaaaaa" in by_id
    assert "bevy-bbbbbbbb" in by_id
    assert by_id["godot-aaaaaaaa"]["engine"] == "godot"
    assert by_id["bevy-bbbbbbbb"]["engine"] == "bevy"


async def test_list_games_continues_when_one_engine_errors(
    client: AsyncClient,
    games_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """If the godot service raises, bevy games still come through."""
    bevy = games_dir / "bevy-cccccccc"
    bevy.mkdir()
    (bevy / "Cargo.toml").write_text(
        '[package]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (bevy / "src").mkdir()
    (bevy / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")

    class _BoomGodotService:
        def __init__(self, *_a, **_kw):
            pass

        def list_games(self, base):
            raise RuntimeError("godot listing exploded")

    monkeypatch.setattr(games_route, "GodotGameService", _BoomGodotService)

    resp = await client.get("/api/v1/games")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ids = [item["game_id"] for item in data]
    assert ids == ["bevy-cccccccc"]
    assert data[0]["engine"] == "bevy"


@pytest.mark.asyncio
async def test_umbrella_create_401_without_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r_post = await ac.post("/api/v1/games", json={"description": "a game"})
        # Listing is deliberately public today (games have no ownership —
        # security finding #2, docs/plans/2026-07-17-security-remediation.md).
        # When ownership lands this assertion should flip to 401.
        r_get = await ac.get("/api/v1/games")
    assert r_post.status_code == 401
    assert r_get.status_code == 200
