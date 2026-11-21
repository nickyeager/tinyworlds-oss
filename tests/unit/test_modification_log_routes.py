import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.api.core.config import get_settings
from src.api.dependencies import get_current_user, get_optional_current_user
from src.api.services.game_access import create_access


@pytest.fixture
def stage_engine_game(tmp_path: Path, monkeypatch):
    games = tmp_path / "workspace" / "generated_games"
    games.mkdir(parents=True)
    monkeypatch.setattr(get_settings(), "GODOT_GAMES_DIR", str(games))
    user = SimpleNamespace(id="modification-log-owner", is_admin=False, is_active=True)
    prior = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_current_user] = lambda: user

    def _stage(engine: str, game_id: str, run_id: str) -> Path:
        game_path = games / game_id
        game_path.mkdir(parents=True)
        if engine == "godot":
            (game_path / "project.godot").write_text("[application]\n")
        else:
            (game_path / "Cargo.toml").write_text("[package]\nname=\"x\"\n")
        run_dir = game_path / ".modifications" / run_id
        run_dir.mkdir(parents=True)
        events = [
            {
                "event_type": "init",
                "type": "status",
                "content": "Modification queued",
                "metadata": {
                    "run_id": run_id,
                    "engine": engine,
                    "instruction": "add coins",
                },
            },
            {"event_type": "done", "type": "complete", "content": "done"},
        ]
        with (run_dir / "events.jsonl").open("w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")
        (run_dir / "summary.json").write_text(json.dumps({
            "run_id": run_id,
            "game_id": game_id,
            "engine": engine,
            "instruction": "add coins",
            "status": "success",
            "started_at": "2026-06-05T00:00:00Z",
            "event_count": len(events),
        }))
        create_access(game_id, str(user.id))
        return game_path

    yield _stage
    app.dependency_overrides.clear()
    app.dependency_overrides.update(prior)


@pytest.mark.asyncio
async def test_godot_lists_and_reads_modification_runs(stage_engine_game):
    stage_engine_game("godot", "godot-test", "abc123def4")

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            listing = await ac.get("/api/v1/godot/games/godot-test/modifications")
            assert listing.status_code == 200
            assert listing.json()["runs"][0]["run_id"] == "abc123def4"

            detail = await ac.get(
                "/api/v1/godot/games/godot-test/modifications/abc123def4/events"
            )
            assert detail.status_code == 200
            body = detail.json()
            assert body["summary"]["instruction"] == "add coins"
            assert body["events"][0]["event_type"] == "init"

    await _run()


@pytest.mark.asyncio
async def test_bevy_lists_reads_and_streams_modification_runs(stage_engine_game):
    stage_engine_game("bevy", "bevy-test", "abc123def4")

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            listing = await ac.get("/api/v1/bevy/games/bevy-test/modifications")
            assert listing.status_code == 200
            assert listing.json()["runs"][0]["engine"] == "bevy"

            detail = await ac.get(
                "/api/v1/bevy/games/bevy-test/modifications/abc123def4/events"
            )
            assert detail.status_code == 200
            assert detail.json()["summary"]["status"] == "success"

            stream = await ac.get(
                "/api/v1/bevy/games/bevy-test/modifications/abc123def4/events/stream"
            )
            assert stream.status_code == 200
            assert '"seq": 0' in stream.text

    await _run()


@pytest.mark.asyncio
async def test_modification_run_id_validation(stage_engine_game):
    stage_engine_game("godot", "godot-test", "abc123def4")

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/v1/godot/games/godot-test/modifications/..bad/events"
            )
            assert response.status_code in (400, 404)

    await _run()
