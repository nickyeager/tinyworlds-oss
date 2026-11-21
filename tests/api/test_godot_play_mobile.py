"""Tests for mobile/touch hardening on served Godot play HTML."""
from pathlib import Path

import pytest
from httpx import AsyncClient

from src.api.routes import godot_games


@pytest.fixture
def games_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    games = tmp_path / "generated_games"
    games.mkdir()
    monkeypatch.setattr(godot_games.settings, "GODOT_GAMES_DIR", str(games))
    return games


async def test_godot_play_index_injects_mobile_touch_shim(
    client: AsyncClient,
    games_dir: Path,
):
    game_id = "godot-mobiletest"
    game = games_dir / game_id
    (game / "dist").mkdir(parents=True)
    (game / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (game / "dist" / "index.html").write_text(
        "<html><head></head><body><canvas id=\"canvas\"></canvas></body></html>",
        encoding="utf-8",
    )

    resp = await client.get(f"/api/v1/godot/games/{game_id}/play/index.html")

    assert resp.status_code == 200
    assert "tinyworlds-mobile-play-style" in resp.text
    assert "touch-action: none" in resp.text
    assert 'name="viewport"' in resp.text


async def test_godot_play_index_injects_mobile_overlay(
    client: AsyncClient,
    games_dir: Path,
):
    game_id = "godot-overlaytest"
    game = games_dir / game_id
    (game / "dist").mkdir(parents=True)
    (game / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (game / "dist" / "index.html").write_text(
        "<html><head></head><body><canvas id=\"canvas\"></canvas></body></html>",
        encoding="utf-8",
    )

    resp = await client.get(f"/api/v1/godot/games/{game_id}/play/index.html")

    assert resp.status_code == 200
    assert 'id="tinyworlds-mobile-overlay"' in resp.text
    assert "tinyworlds-mobile-overlay-style" in resp.text
    assert "tinyworlds-mobile-overlay-script" in resp.text
    assert 'data-key="Space"' in resp.text
    assert 'data-key="Enter"' in resp.text
    # Opt-out hooks present in JS
    assert "data-tw-overlay" in resp.text
    assert "overlay=off" in resp.text



async def test_embedded_preview_preserves_editor_focus_and_standalone_play(
    client: AsyncClient,
    games_dir: Path,
):
    game_id = "godot-embeddedtest"
    game = games_dir / game_id
    (game / "dist").mkdir(parents=True)
    (game / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    html = '<html><head></head><body><canvas id="canvas"></canvas></body></html>'
    (game / "dist" / "index.html").write_text(html, encoding="utf-8")

    redirect = await client.get(f"/api/v1/godot/games/{game_id}/play?embedded=1", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"].endswith("/play/index.html?embedded=1")
    embedded = await client.get(redirect.headers["location"])
    assert embedded.status_code == 200
    assert 'id="tinyworlds-embedded-focus"' in embedded.text
    assert "event.source !== window.parent" in embedded.text
    assert "tinyworlds:activate-preview" in embedded.text
    standalone = await client.get(f"/api/v1/godot/games/{game_id}/play/index.html")
    assert standalone.status_code == 200
    assert 'id="tinyworlds-embedded-focus"' not in standalone.text
    assert (game / "dist" / "index.html").read_text() == html
