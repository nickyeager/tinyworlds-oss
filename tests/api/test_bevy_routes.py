"""Integration tests for the Bevy routes (v1 core surface).

Strategy:
- Use ``httpx.AsyncClient`` + ``ASGITransport`` — matches this repo's
  pre-existing pattern (``tests/api/conftest.py``, ``tests/e2e/conftest.py``).
  Starlette's bundled ``TestClient`` is incompatible with httpx 0.28 here.
- Repoint ``settings.GODOT_GAMES_DIR`` at ``tmp_path`` by monkeypatching
  the module-level ``settings`` reference inside ``bevy_games`` (the route
  reads it via ``Path(settings.GODOT_GAMES_DIR) / game_id`` rather than
  re-resolving each call).
- Override ``get_current_user`` and ``check_game_creation_rate_limit`` so
  the auth-gated routes don't need a database / token.
- Stub ``BevyCreationAgent`` for the create endpoint to avoid spawning
  the real Claude CLI.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.dependencies import get_current_user, get_optional_current_user
from src.api.main import app
from src.api.services.game_access import create_access
from src.api.middleware.rate_limit import check_game_creation_rate_limit
from src.api.observability.events import CompletionEvent
from src.api.routes import bevy_games


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def games_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Repoint GODOT_GAMES_DIR for the bevy_games module at a tmp dir."""
    games = tmp_path / "workspace" / "generated_games"
    games.mkdir(parents=True)
    monkeypatch.setattr(bevy_games.settings, "GODOT_GAMES_DIR", str(games))
    return games


@pytest.fixture
def fake_user():
    """A minimal stand-in for the User dep — routes only need a truthy value."""
    return SimpleNamespace(
        id="test-user-id",
        email="test@example.com",
        username="tester",
        is_active=True,
        is_admin=False,
    )


@pytest_asyncio.fixture
async def client(fake_user):
    """AsyncClient with auth + rate-limit overrides applied."""
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_optional_current_user] = lambda: fake_user
    app.dependency_overrides[check_game_creation_rate_limit] = lambda: None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _make_bevy_game(games_dir: Path, game_id: str = "bevy-aaaaaaaa") -> Path:
    """Create a minimal Bevy game directory (just Cargo.toml + src/main.rs)."""
    g = games_dir / game_id
    g.mkdir()
    (g / "Cargo.toml").write_text(
        '[package]\nname = "test_game"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )
    (g / "src").mkdir()
    (g / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    create_access(game_id, "test-user-id")
    return g


# ---------------------------------------------------------------------------
# POST /games — SSE create
# ---------------------------------------------------------------------------


class _FakeAgent:
    """Stub creation agent that emits a single CompletionEvent."""

    def __init__(self, *args, **kwargs):
        pass

    async def create_game(self, request, game_path) -> AsyncIterator:
        yield CompletionEvent(
            service="bevy_creation_agent",
            message="stubbed",
            result_path=str(game_path),
        )

    async def attempt_fix(self, game_path, failures) -> AsyncIterator:
        if False:
            yield  # pragma: no cover — empty async iterator


async def test_create_game_returns_bevy_prefixed_id_in_init_event(
    client: AsyncClient,
    games_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """POST /games streams an init event whose game_id is bevy-prefixed."""
    monkeypatch.setattr(bevy_games, "BevyCreationAgent", _FakeAgent)
    suggestions = AsyncMock(return_value=None)
    monkeypatch.setattr("src.api.services.suggestions_generator.generate_suggestions", suggestions)
    monkeypatch.setattr(bevy_games, "generate_suggestions", suggestions, raising=False)

    resp = await client.post(
        "/api/v1/bevy/games",
        json={"description": "a tiny world"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200, resp.text

    body = resp.text
    first_data_line = next(
        (l for l in body.splitlines() if l.startswith("data: ")), None
    )
    assert first_data_line is not None, f"no data lines in body: {body!r}"
    init = json.loads(first_data_line[len("data: "):])
    assert init["event_type"] == "init"
    assert init["game_id"].startswith("bevy-")
    assert len(init["game_id"]) == len("bevy-") + 8


# ---------------------------------------------------------------------------
# GET /games — list filtered by Cargo.toml
# ---------------------------------------------------------------------------


async def test_list_games_filters_to_bevy_via_cargo_toml(
    client: AsyncClient, games_dir: Path
):
    bevy = games_dir / "bevy-aaaaaaaa"
    bevy.mkdir()
    (bevy / "Cargo.toml").write_text("[package]\nname = \"x\"\n", encoding="utf-8")

    godot = games_dir / "godot-bbbbbbbb"
    godot.mkdir()
    (godot / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    (games_dir / "random").mkdir()

    resp = await client.get("/api/v1/bevy/games")
    assert resp.status_code == 200
    data = resp.json()
    ids = [g["game_id"] for g in data]
    assert ids == ["bevy-aaaaaaaa"]
    assert data[0]["engine"] == "bevy"


# ---------------------------------------------------------------------------
# GET /games/{id} — info
# ---------------------------------------------------------------------------


async def test_get_game_404_when_missing(client: AsyncClient, games_dir: Path):
    resp = await client.get("/api/v1/bevy/games/bevy-deadbeef")
    assert resp.status_code == 404


async def test_get_game_404_when_godot(client: AsyncClient, games_dir: Path):
    """A godot-prefixed dir without Cargo.toml must 404 on the bevy route."""
    g = games_dir / "godot-xxxxxxxx"
    g.mkdir()
    (g / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    resp = await client.get("/api/v1/bevy/games/godot-xxxxxxxx")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /games/{id}/play
# ---------------------------------------------------------------------------


async def test_play_redirect_404_when_no_dist(client: AsyncClient, games_dir: Path):
    _make_bevy_game(games_dir)
    resp = await client.get(
        "/api/v1/bevy/games/bevy-aaaaaaaa/play", follow_redirects=False
    )
    assert resp.status_code == 404
    assert "exported" in resp.json()["detail"].lower()


async def test_play_redirect_returns_redirect_when_dist_exists(
    client: AsyncClient, games_dir: Path
):
    g = _make_bevy_game(games_dir)
    (g / "dist").mkdir()
    (g / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")

    resp = await client.get(
        "/api/v1/bevy/games/bevy-aaaaaaaa/play", follow_redirects=False
    )
    assert resp.status_code == 307
    assert resp.headers["location"] == "/api/v1/bevy/games/bevy-aaaaaaaa/play/index.html"


async def test_play_static_wasm_mime(client: AsyncClient, games_dir: Path):
    g = _make_bevy_game(games_dir)
    (g / "dist").mkdir()
    (g / "dist" / "foo_bg.wasm").write_bytes(b"\0asm")

    resp = await client.get("/api/v1/bevy/games/bevy-aaaaaaaa/play/foo_bg.wasm")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/wasm"


async def test_play_index_injects_mobile_touch_shim(client: AsyncClient, games_dir: Path):
    g = _make_bevy_game(games_dir)
    (g / "dist").mkdir()
    (g / "dist" / "index.html").write_text(
        "<html><head></head><body><canvas></canvas></body></html>",
        encoding="utf-8",
    )

    resp = await client.get("/api/v1/bevy/games/bevy-aaaaaaaa/play/index.html")

    assert resp.status_code == 200
    assert "tinyworlds-mobile-play-style" in resp.text
    assert "touch-action: none" in resp.text
    assert 'name="viewport"' in resp.text


async def test_play_index_injects_mobile_overlay(client: AsyncClient, games_dir: Path):
    g = _make_bevy_game(games_dir)
    (g / "dist").mkdir()
    (g / "dist" / "index.html").write_text(
        "<html><head></head><body><canvas></canvas></body></html>",
        encoding="utf-8",
    )

    resp = await client.get("/api/v1/bevy/games/bevy-aaaaaaaa/play/index.html")

    assert resp.status_code == 200
    assert 'id="tinyworlds-mobile-overlay"' in resp.text
    assert "tinyworlds-mobile-overlay-style" in resp.text
    assert "tinyworlds-mobile-overlay-script" in resp.text
    assert "data-tw-overlay" in resp.text
    assert "overlay=off" in resp.text


async def test_play_static_rejects_path_traversal(client: AsyncClient, games_dir: Path):
    g = _make_bevy_game(games_dir)
    (g / "dist").mkdir()

    # Encoded slashes survive httpx's path normalisation, so the route must
    # defensively resolve the candidate path back under dist/. Either a
    # 403/404 is acceptable; what matters is no leak of Cargo.toml.
    resp = await client.get(
        "/api/v1/bevy/games/bevy-aaaaaaaa/play/..%2F..%2FCargo.toml"
    )
    assert resp.status_code in (403, 404)
    assert "[package]" not in resp.text


# ---------------------------------------------------------------------------
# GET /games/{id}/screenshot
# ---------------------------------------------------------------------------


async def test_screenshot_404_when_missing(client: AsyncClient, games_dir: Path):
    _make_bevy_game(games_dir)
    resp = await client.get("/api/v1/bevy/games/bevy-aaaaaaaa/screenshot")
    assert resp.status_code == 404


async def test_screenshot_serves_when_present(client: AsyncClient, games_dir: Path):
    g = _make_bevy_game(games_dir)
    pres = g / "screenshots" / "presentation"
    pres.mkdir(parents=True)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
        b"\xc0\x00\x00\x00\x03\x00\x01\xc8\xd7\xc0\xb1\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (pres / "gameplay.png").write_bytes(png_bytes)

    resp = await client.get("/api/v1/bevy/games/bevy-aaaaaaaa/screenshot")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


# ---------------------------------------------------------------------------
# GET /games/{id}/video
# ---------------------------------------------------------------------------


async def test_video_404_when_missing(client: AsyncClient, games_dir: Path):
    _make_bevy_game(games_dir)
    resp = await client.get("/api/v1/bevy/games/bevy-aaaaaaaa/video")
    assert resp.status_code == 404


async def test_video_serves_when_present(client: AsyncClient, games_dir: Path):
    g = _make_bevy_game(games_dir)
    pres = g / "screenshots" / "presentation"
    pres.mkdir(parents=True)
    (pres / "gameplay.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")

    resp = await client.get("/api/v1/bevy/games/bevy-aaaaaaaa/video")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp4"


# ---------------------------------------------------------------------------
# PATCH /games/{id} — rename
# ---------------------------------------------------------------------------


async def test_patch_rename_writes_cargo_metadata(client: AsyncClient, games_dir: Path):
    _make_bevy_game(games_dir)

    resp = await client.patch(
        "/api/v1/bevy/games/bevy-aaaaaaaa",
        json={"name": "Cool Game"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Cool Game"

    info = await client.get("/api/v1/bevy/games/bevy-aaaaaaaa")
    assert info.status_code == 200
    assert info.json()["name"] == "Cool Game"


@pytest.mark.asyncio
async def test_create_game_401_without_auth(games_dir: Path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/v1/bevy/games", json={"description": "a game"})
    assert r.status_code == 401
