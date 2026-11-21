"""Tests for GET /api/v1/{godot,bevy,}/games/{id}/suggestions.

Mirrors the test patterns in ``test_bevy_routes.py``:
- ``httpx.AsyncClient`` + ``ASGITransport`` (httpx 0.28 is incompatible
  with the bundled Starlette ``TestClient`` here).
- Repoint ``GODOT_GAMES_DIR`` by monkeypatching the route modules'
  module-level ``settings`` references (both godot and bevy routers read
  via ``Path(settings.GODOT_GAMES_DIR) / game_id``).

Suggestions are owner-only editing data. Fixtures provide trusted ownership
and both authentication dependency overrides.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.dependencies import get_current_user, get_optional_current_user
from src.api.main import app
from src.api.services.game_access import create_access
from src.api.routes import bevy_games, games as games_umbrella, godot_games


@pytest.fixture
def games_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Repoint GODOT_GAMES_DIR across all three route modules."""
    games = tmp_path / "workspace" / "generated_games"
    games.mkdir(parents=True)
    monkeypatch.setattr(godot_games.settings, "GODOT_GAMES_DIR", str(games))
    monkeypatch.setattr(bevy_games.settings, "GODOT_GAMES_DIR", str(games))
    monkeypatch.setattr(games_umbrella.settings, "GODOT_GAMES_DIR", str(games))
    return games


@pytest_asyncio.fixture
async def http_client() -> AsyncClient:
    user = SimpleNamespace(id="suggestions-test-owner", is_admin=False, is_active=True)
    prior = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_current_user] = lambda: user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    app.dependency_overrides.update(prior)


def _make_godot_game(games_dir: Path, gid: str, suggestions: list[str] | None = None) -> Path:
    gdir = games_dir / gid
    gdir.mkdir()
    (gdir / "project.godot").write_text("")
    if suggestions is not None:
        (gdir / "suggestions.json").write_text(
            json.dumps(
                {
                    "suggestions": suggestions,
                    "generated_at": "2026-05-12T00:00:00+00:00",
                }
            )
        )
    create_access(gid, "suggestions-test-owner")
    return gdir


def _make_bevy_game(games_dir: Path, gid: str, suggestions: list[str] | None = None) -> Path:
    gdir = games_dir / gid
    gdir.mkdir()
    (gdir / "Cargo.toml").write_text("[package]\nname = \"x\"\n")
    if suggestions is not None:
        (gdir / "suggestions.json").write_text(
            json.dumps(
                {
                    "suggestions": suggestions,
                    "generated_at": "2026-05-12T00:00:00+00:00",
                }
            )
        )
    create_access(gid, "suggestions-test-owner")
    return gdir


@pytest.mark.asyncio
async def test_returns_suggestions_when_present(http_client: AsyncClient, games_dir: Path):
    gid = "godot-suggtest"
    _make_godot_game(
        games_dir,
        gid,
        ["Add music", "Make harder", "Add boss", "Color shift", "More enemies"],
    )

    r = await http_client.get(f"/api/v1/godot/games/{gid}/suggestions")
    assert r.status_code == 200
    body = r.json()
    assert body["suggestions"] == [
        "Add music",
        "Make harder",
        "Add boss",
        "Color shift",
        "More enemies",
    ]
    assert body.get("pending") is not True
    assert "generated_at" in body


@pytest.mark.asyncio
async def test_returns_pending_when_file_absent(http_client: AsyncClient, games_dir: Path):
    gid = "godot-pendingtest"
    _make_godot_game(games_dir, gid, suggestions=None)

    r = await http_client.get(f"/api/v1/godot/games/{gid}/suggestions")
    assert r.status_code == 200
    body = r.json()
    assert body["suggestions"] == []
    assert body["pending"] is True


@pytest.mark.asyncio
async def test_returns_404_when_game_missing(http_client: AsyncClient, games_dir: Path):
    r = await http_client.get("/api/v1/godot/games/godot-doesnotexist/suggestions")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_umbrella_resolves_godot_game(http_client: AsyncClient, games_dir: Path):
    gid = "umbrella-godot"
    _make_godot_game(
        games_dir,
        gid,
        ["Add music", "Make harder", "Add boss", "Color shift", "More enemies"],
    )

    r = await http_client.get(f"/api/v1/games/{gid}/suggestions")
    assert r.status_code == 200
    body = r.json()
    assert body["suggestions"] == [
        "Add music",
        "Make harder",
        "Add boss",
        "Color shift",
        "More enemies",
    ]
    assert body.get("pending") is not True
    assert "generated_at" in body


@pytest.mark.asyncio
async def test_umbrella_resolves_bevy_game(http_client: AsyncClient, games_dir: Path):
    gid = "umbrella-bevy"
    _make_bevy_game(
        games_dir,
        gid,
        ["Tweak gravity", "Add pickups", "Slower foes", "New palette", "Boss wave"],
    )

    r = await http_client.get(f"/api/v1/games/{gid}/suggestions")
    assert r.status_code == 200
    body = r.json()
    assert body["suggestions"] == [
        "Tweak gravity",
        "Add pickups",
        "Slower foes",
        "New palette",
        "Boss wave",
    ]
    assert body.get("pending") is not True
    assert "generated_at" in body


@pytest.mark.asyncio
async def test_umbrella_404_when_directory_has_no_engine_marker(
    http_client: AsyncClient, games_dir: Path
):
    gid = "umbrella-no-marker"
    gdir = games_dir / gid
    gdir.mkdir()
    # Intentionally no project.godot and no Cargo.toml
    (gdir / "suggestions.json").write_text(
        json.dumps({"suggestions": ["x"], "generated_at": "2026-05-12T00:00:00+00:00"})
    )

    r = await http_client.get(f"/api/v1/games/{gid}/suggestions")
    assert r.status_code == 404
