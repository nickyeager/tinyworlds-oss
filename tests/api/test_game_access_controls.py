"""Independent ownership contracts through the public ASGI application."""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.core.config import get_settings
from src.api.dependencies import get_current_user, get_optional_current_user
from src.api.main import app
from src.api.services.game_access import create_access


OWNER = SimpleNamespace(
    id=UUID("00000000-0000-0000-0000-000000000001"), email="owner@example.test",
    username="owner", is_active=True, is_admin=False,
)
OTHER = SimpleNamespace(
    id=UUID("00000000-0000-0000-0000-000000000002"), email="other@example.test",
    username="other", is_active=True, is_admin=False,
)
RUN_ID = "abc123def4"


@pytest.fixture
def access_world(tmp_path, monkeypatch):
    root = tmp_path / "workspace" / "generated_games"
    root.mkdir(parents=True)
    monkeypatch.setattr(get_settings(), "GODOT_GAMES_DIR", str(root))
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec",
        AsyncMock(side_effect=AssertionError("authorization tests must not launch an agent")),
    )
    state = {"user": OTHER}
    prior = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[get_optional_current_user] = lambda: state["user"]

    def stage(engine, *, visibility="public", legacy=False, game_id=None):
        game_id = game_id or f"{engine}-aaaaaaaa"
        game = root / game_id
        game.mkdir()
        if engine == "godot":
            (game / "project.godot").write_text(
                'config_version=5\n[application]\nconfig/name="Original Game"\n',
            )
        else:
            (game / "Cargo.toml").write_text(
                '[package]\nname="original_game"\nversion="0.1.0"\nedition="2021"\n',
            )
            (game / "src").mkdir()
            (game / "src" / "main.rs").write_text("fn main() {}\n")
        (game / "dist").mkdir()
        (game / "dist" / "index.html").write_text("<html><body>public gameplay</body></html>")
        (game / "assets").mkdir()
        (game / "assets" / "private-source.gd").write_text("owner-only source content")
        (game / "STRUCTURE.md").write_text("owner-only structure\n")
        (game / "MEMORY.md").write_text("# Modification History\nowner-only history\n")
        events = [{"event_type": "done", "type": "complete", "content": "owner-only debug content"}]
        for directory in (game / ".creation", game / ".modifications" / RUN_ID):
            directory.mkdir(parents=True)
            (directory / "events.jsonl").write_text("\n".join(map(json.dumps, events)) + "\n")
            (directory / "summary.json").write_text(json.dumps({
                "status": "success", "game_id": game_id, "run_id": RUN_ID,
                "engine": engine, "instruction": "owner-only instruction",
            }))
        if not legacy:
            create_access(game_id, str(OWNER.id), visibility=visibility)
        return game_id, game

    yield SimpleNamespace(root=root, state=state, stage=stage)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(prior)


@pytest_asyncio.fixture
async def access_client(access_world):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.parametrize("engine", ["godot", "bevy"])
@pytest.mark.parametrize("viewer", [OTHER, None], ids=["other-user", "anonymous"])
async def test_public_basic_metadata_listing_and_play_remain_readable(
    access_client, access_world, engine, viewer,
):
    game_id, _ = access_world.stage(engine)
    access_world.state["user"] = viewer
    base = f"/api/v1/{engine}/games"
    info = await access_client.get(f"{base}/{game_id}")
    assert info.status_code == 200, info.text
    assert info.json()["can_edit"] is False
    listing = await access_client.get(base)
    assert listing.status_code == 200, listing.text
    assert game_id in {item["game_id"] for item in listing.json()}
    play = await access_client.get(f"{base}/{game_id}/play/index.html")
    assert play.status_code == 200, play.text


SENSITIVE_READS = [
    (engine, suffix)
    for engine in ("godot", "bevy")
    for suffix in (
        "/events/stream", "/modifications", f"/modifications/{RUN_ID}/events",
        f"/modifications/{RUN_ID}/events/stream",
    )
] + [("godot", suffix) for suffix in (
    "/log", "/history", "/events", "/structure", "/assets/assets/private-source.gd",
)]


@pytest.mark.parametrize("engine", ["godot", "bevy"])
async def test_editor_image_preview_is_readable_only_by_owner(access_client, access_world, engine):
    game_id, game = access_world.stage(engine)
    image = game / "assets" / "preview.png"
    image.write_bytes(b"owner-only image fixture")
    url = f"/api/v1/{engine}/games/{game_id}/assets/assets/preview.png"
    access_world.state["user"] = OWNER
    response = await access_client.get(url)
    assert response.status_code == 200
    assert response.content == image.read_bytes()
    for viewer, expected in [(OTHER, 404), (None, 401)]:
        access_world.state["user"] = viewer
        assert (await access_client.get(url)).status_code == expected


@pytest.mark.parametrize("engine,suffix", SENSITIVE_READS)
async def test_other_user_cannot_read_owner_logs_history_events_or_source(
    access_client, access_world, engine, suffix,
):
    game_id, _ = access_world.stage(engine)
    url = f"/api/v1/{engine}/games/{game_id}{suffix}"
    access_world.state["user"] = OWNER
    owned = await asyncio.wait_for(access_client.get(url), timeout=5)
    assert owned.status_code == 200, owned.text
    access_world.state["user"] = OTHER
    denied = await asyncio.wait_for(access_client.get(url), timeout=5)
    assert denied.status_code == 404, denied.text
    assert "owner-only" not in denied.text


@pytest.mark.parametrize("engine", ["godot", "bevy"])
@pytest.mark.parametrize("method,suffix", [
    ("DELETE", ""), ("PATCH", ""), ("POST", "/modify"), ("POST", "/modify/stream"),
])
@pytest.mark.parametrize("legacy", [False, True], ids=["owned-by-another", "legacy-owner-unknown"])
async def test_other_user_and_unknown_legacy_owner_cannot_mutate_games(
    access_client, access_world, engine, method, suffix, legacy,
):
    game_id, game = access_world.stage(engine, legacy=legacy)
    kwargs = {"json": {"name": "Unauthorized Rename"}} if method == "PATCH" else {}
    if method == "POST":
        kwargs = {"json": {"instruction": "unauthorized modification"}}
    response = await access_client.request(
        method, f"/api/v1/{engine}/games/{game_id}{suffix}", **kwargs,
    )
    assert response.status_code == 404, response.text
    assert game.exists(), "denied deletion must leave the game intact"
    assert "Unauthorized Rename" not in (game / ("project.godot" if engine == "godot" else "Cargo.toml")).read_text()


@pytest.mark.parametrize("engine", ["godot", "bevy"])
@pytest.mark.parametrize("visibility", ["public", "private"])
async def test_owner_can_read_private_games_and_rename_with_edit_capability(
    access_client, access_world, engine, visibility,
):
    game_id, _ = access_world.stage(engine, visibility=visibility)
    access_world.state["user"] = OWNER
    base = f"/api/v1/{engine}/games"
    info = await access_client.get(f"{base}/{game_id}")
    assert info.status_code == 200, info.text
    assert info.json()["can_edit"] is True
    renamed = await access_client.patch(f"{base}/{game_id}", json={"name": "Owner Renamed Game"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Owner Renamed Game"
    info = await access_client.get(f"{base}/{game_id}")
    assert info.json()["name"] == "Owner Renamed Game"
    assert (await access_client.get(f"{base}/{game_id}/play/index.html")).status_code == 200
    listed = await access_client.get(base)
    assert game_id in {item["game_id"] for item in listed.json()}


@pytest.mark.parametrize("engine", ["godot", "bevy"])
@pytest.mark.parametrize("viewer", [OTHER, None], ids=["other-user", "anonymous"])
async def test_private_games_are_hidden_from_nonowners_info_play_and_lists(
    access_client, access_world, engine, viewer,
):
    game_id, _ = access_world.stage(engine, visibility="private")
    access_world.state["user"] = viewer
    for suffix in ("", "/play", "/play/index.html"):
        response = await access_client.get(f"/api/v1/{engine}/games/{game_id}{suffix}")
        assert response.status_code == 404, response.text
    for endpoint in (f"/api/v1/{engine}/games", "/api/v1/games"):
        listing = await access_client.get(endpoint)
        assert listing.status_code == 200, listing.text
        assert game_id not in {item["game_id"] for item in listing.json()}


@pytest.mark.parametrize("engine", ["godot", "bevy"])
@pytest.mark.parametrize("unsafe", ["malformed", "traversal", "symlink"])
async def test_invalid_and_symlink_escape_game_ids_return_404(
    access_client, access_world, tmp_path, engine, unsafe,
):
    access_world.state["user"] = OWNER
    if unsafe == "symlink":
        game_id, game = access_world.stage(engine)
        outside = tmp_path / "outside-game"
        game.rename(outside)
        game.symlink_to(outside, target_is_directory=True)
    else:
        game_id = f"{engine}-..invalid" if unsafe == "malformed" else "..%2Foutside-game"
    for suffix in ("", "/play/index.html", "/modifications"):
        response = await access_client.get(f"/api/v1/{engine}/games/{game_id}{suffix}")
        assert response.status_code == 404, response.text
    deleted = await access_client.delete(f"/api/v1/{engine}/games/{game_id}")
    assert deleted.status_code == 404, deleted.text
    if unsafe == "symlink":
        assert outside.exists(), "a rejected symlink deletion must preserve its target"


@pytest.mark.parametrize("engine", ["godot", "bevy"])
async def test_scoped_media_cookie_does_not_authenticate_owner_mutations(
    access_client, access_world, engine, monkeypatch,
):
    from src.api.core.security import create_access_token

    game_id, game = access_world.stage(engine, visibility="private")
    app.dependency_overrides.pop(get_current_user)
    app.dependency_overrides.pop(get_optional_current_user)
    monkeypatch.setattr(
        "src.api.repositories.user_repository.UserRepository.get",
        AsyncMock(return_value=OWNER),
    )
    cookie = create_access_token(
        {"sub": str(OWNER.id), "purpose": "game-media", "game_id": game_id},
        timedelta(minutes=5),
    )
    access_client.cookies.set("tw_game_media", cookie)
    playable = await access_client.get(f"/api/v1/{engine}/games/{game_id}/play/index.html")
    assert playable.status_code == 200, "the signed cookie must authorize its intended media"
    other_id, _ = access_world.stage(engine, visibility="private", game_id=f"{engine}-bbbbbbbb")
    other_media = await access_client.get(f"/api/v1/{engine}/games/{other_id}/play/index.html")
    assert other_media.status_code == 404, "media authorization must be scoped to one game"
    renamed = await access_client.patch(
        f"/api/v1/{engine}/games/{game_id}", json={"name": "Cookie Escalation"},
    )
    assert renamed.status_code in (401, 403), renamed.text
    deleted = await access_client.delete(f"/api/v1/{engine}/games/{game_id}")
    assert deleted.status_code in (401, 403), deleted.text
    assert game.exists()
