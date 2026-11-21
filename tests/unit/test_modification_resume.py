"""Unit tests for GET /games/{id}/modifications/{run_id}/events/stream.

Modifications run as background tasks writing to
`<game>/.modifications/<run_id>/events.jsonl`. The resume endpoint
tails that log so a disconnected client can re-attach without
re-firing the modification subprocess.
"""
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
def stage_modification_log(tmp_path: Path, monkeypatch):
    """Stage an owned game and completed log under a temporary games root."""
    games = tmp_path / "workspace" / "generated_games"
    games.mkdir(parents=True)
    monkeypatch.setattr(get_settings(), "GODOT_GAMES_DIR", str(games))
    user = SimpleNamespace(id="modification-resume-owner", is_admin=False, is_active=True)
    prior = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_current_user] = lambda: user

    def _stage(game_id: str, run_id: str, events: list[dict]) -> Path:
        log_dir = games / game_id / ".modifications" / run_id
        log_dir.mkdir(parents=True)
        with (log_dir / "events.jsonl").open("w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        (games / game_id / "project.godot").write_text("[application]\n")
        create_access(game_id, str(user.id))
        return log_dir

    yield _stage
    app.dependency_overrides.clear()
    app.dependency_overrides.update(prior)


@pytest.mark.asyncio
async def test_resume_returns_404_for_missing_run(stage_modification_log):
    stage_modification_log("godot-test1", "abcd1234ef", [{"event_type": "done"}])

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # nonexistent game
            r = await ac.get(
                "/api/v1/godot/games/godot-nonexistent/modifications/abcd1234ef/events/stream",
            )
            assert r.status_code == 404
            # wrong run id
            r = await ac.get(
                "/api/v1/godot/games/godot-test1/modifications/zzzzzzzzzz/events/stream",
            )
            assert r.status_code == 404

    await _run()


@pytest.mark.asyncio
async def test_resume_replays_history_to_done(stage_modification_log):
    """Existing run with terminal `done` event → stream replays everything
    and closes."""
    events = [
        {"event_type": "init", "metadata": {"run_id": "aaaa1111bb"}},
        {"type": "status", "content": "working"},
        {"event_type": "done", "type": "complete", "content": "modification complete"},
    ]
    stage_modification_log("godot-test3", "aaaa1111bb", events)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get(
                "/api/v1/godot/games/godot-test3/modifications/aaaa1111bb/events/stream",
            )
            assert r.status_code == 200
            # Collect all SSE data lines
            body = r.text
            data_lines = [l for l in body.split("\n") if l.startswith("data: ")]
            # Three events + each gets a seq stamped by the tail wrapper
            assert len(data_lines) == 3
            parsed = [json.loads(l[len("data: "):]) for l in data_lines]
            assert parsed[0]["event_type"] == "init"
            assert parsed[-1]["event_type"] == "done"
            # seq stamping confirms the tail path is being used
            assert all("seq" in e for e in parsed)

    await _run()


@pytest.mark.asyncio
async def test_resume_with_since_skips_replayed_events(stage_modification_log):
    events = [
        {"event_type": "init"},
        {"type": "status", "content": "step1"},
        {"type": "status", "content": "step2"},
        {"event_type": "done", "type": "complete"},
    ]
    stage_modification_log("godot-test4", "bbbb2222cc", events)

    async def _run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get(
                "/api/v1/godot/games/godot-test4/modifications/bbbb2222cc/events/stream?since=1",
            )
            assert r.status_code == 200
            parsed = [
                json.loads(l[len("data: "):])
                for l in r.text.split("\n")
                if l.startswith("data: ")
            ]
            # Since=1 → events with seq 2 and 3 (step2 + done)
            assert [e["seq"] for e in parsed] == [2, 3]

    await _run()
