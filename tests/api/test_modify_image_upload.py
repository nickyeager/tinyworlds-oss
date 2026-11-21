"""Tests for image upload on POST /api/v1/godot/games/{id}/modify/stream.

Pattern matches ``test_bevy_routes.py``:
- ``httpx.AsyncClient`` + ``ASGITransport``
- Monkeypatch ``godot_games.settings.GODOT_GAMES_DIR``
- Override ``get_current_user`` so auth isn't required
- Stub ``GodotModificationService.modify_game`` so we don't spawn the CLI
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.dependencies import get_current_user, get_optional_current_user
from src.api.main import app
from src.api.services.game_access import create_access
from src.api.routes import godot_games
from tests.fixtures.images import png_bytes as _png_bytes


@pytest.fixture
def games_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    games = tmp_path / "workspace" / "generated_games"
    games.mkdir(parents=True)
    monkeypatch.setattr(godot_games.settings, "GODOT_GAMES_DIR", str(games))
    return games


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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def godot_game(games_dir: Path, fake_user) -> tuple[str, Path]:
    gid = "godot-uploadtest"
    gdir = games_dir / gid
    gdir.mkdir()
    (gdir / "project.godot").write_text("")
    create_access(gid, str(fake_user.id))
    return gid, gdir


def _stub_modify(monkeypatch: pytest.MonkeyPatch, captured: dict) -> None:
    """Replace GodotModificationService.modify_game with a no-op async generator
    that captures the request instruction for assertion."""

    async def fake_modify(self, request) -> AsyncIterator:
        captured["instruction"] = request.instruction
        # Empty generator — yields nothing so the SSE stream is empty.
        if False:
            yield None

    monkeypatch.setattr(
        "src.api.services.godot_modification_service.GodotModificationService.modify_game",
        fake_modify,
    )


@pytest.mark.asyncio
async def test_multipart_with_image_saves_file_under_user_uploads(
    client: AsyncClient,
    godot_game: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
):
    gid, gdir = godot_game
    captured: dict = {}
    _stub_modify(monkeypatch, captured)

    r = await client.post(
        f"/api/v1/godot/games/{gid}/modify/stream",
        files={"image": ("ref.png", _png_bytes(), "image/png")},
        data={"instruction": "make it look like this"},
    )
    assert r.status_code == 200, r.text
    uploads = list((gdir / "_user_uploads").glob("*_ref.png"))
    assert len(uploads) == 1
    assert "Reference image attached at" in captured["instruction"]
    assert str(uploads[0]) in captured["instruction"]


@pytest.mark.asyncio
async def test_multipart_rejects_oversized(
    client: AsyncClient,
    godot_game: tuple[str, Path],
):
    gid, _ = godot_game
    big = b"x" * (11 * 1024 * 1024)  # 11 MB
    r = await client.post(
        f"/api/v1/godot/games/{gid}/modify/stream",
        files={"image": ("big.png", big, "image/png")},
        data={"instruction": "x"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_multipart_rejects_wrong_mime(
    client: AsyncClient,
    godot_game: tuple[str, Path],
):
    gid, _ = godot_game
    r = await client.post(
        f"/api/v1/godot/games/{gid}/modify/stream",
        files={"image": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")},
        data={"instruction": "x"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"json": {"instruction": ""}},
        {"data": {"instruction": "   "}},
    ],
    ids=["json", "multipart"],
)
async def test_empty_instruction_returns_400(
    client: AsyncClient,
    godot_game: tuple[str, Path],
    kwargs: dict,
):
    gid, _ = godot_game
    r = await client.post(f"/api/v1/godot/games/{gid}/modify/stream", **kwargs)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_json_path_still_works(
    client: AsyncClient,
    godot_game: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
):
    gid, gdir = godot_game
    captured: dict = {}
    _stub_modify(monkeypatch, captured)

    r = await client.post(
        f"/api/v1/godot/games/{gid}/modify/stream",
        json={"instruction": "no image here"},
    )
    assert r.status_code == 200, r.text
    assert captured["instruction"] == "no image here"
    assert not (gdir / "_user_uploads").exists()
