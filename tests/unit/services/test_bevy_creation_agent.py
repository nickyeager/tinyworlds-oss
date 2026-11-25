"""Unit tests for BevyCreationAgent.

Mirrors the mock-based pattern from
``tests/unit/test_godot_creation_agent_enriched.py`` — the executor and
game_service are mocked so we don't pay real dollars (or wall-clock minutes)
invoking Claude CLI per test. End-to-end coverage with the real CLI is
covered separately under tests/e2e (Workstream 8).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.observability.events import CompletionEvent
from src.api.services.bevy_creation_agent import (
    BevyCreationAgent,
    BevyCreationRequest,
)
from src.api.services.godot_executor import ExecutorEvent


def _make_executor(*executor_events: ExecutorEvent) -> MagicMock:
    executor = MagicMock()

    async def fake_run_stage(*args, **kwargs):
        for ev in executor_events:
            yield ev

    executor.run_stage = fake_run_stage
    return executor


def _make_game_service(*, build_wasm_return=None, build_wasm_raises=None) -> MagicMock:
    game_service = MagicMock()
    game_service.read_skill.return_value = "fake bevy skill content"

    if build_wasm_raises is not None:
        game_service.build_wasm = MagicMock(side_effect=build_wasm_raises)
    else:
        game_service.build_wasm = MagicMock(return_value=build_wasm_return)
    return game_service


async def _collect(agent: BevyCreationAgent, game_path: Path, intent: str = "test"):
    events = []
    async for ev in agent.create_game(
        BevyCreationRequest(intent=intent),
        game_path,
    ):
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Skill loading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_game_uses_native_runtime_without_duplicate_skill_content(tmp_path: Path):
    """The renderer owns engine guidance; the task retains the touch contract."""
    captured = {}

    executor = MagicMock()

    async def fake_run_stage(skill_content, user_prompt, game_path, *args, **kwargs):
        captured["skill_content"] = skill_content
        captured["user_prompt"] = user_prompt
        if False:
            yield  # make this an async generator

    executor.run_stage = fake_run_stage

    game_service = _make_game_service(build_wasm_return=tmp_path / "dist")
    game_service.read_skill.return_value = "BEVY_SKILL_BODY"

    agent = BevyCreationAgent(executor, game_service)
    await _collect(agent, tmp_path)

    game_service.read_skill.assert_not_called()
    assert captured["skill_content"] == ""
    assert "Project Lessons" not in captured["skill_content"]
    assert "Mobile and Touch Runtime Requirement" in captured["user_prompt"]
    assert "Keyboard-only" in captured["user_prompt"]


@pytest.mark.asyncio
async def test_create_game_does_not_load_godot_orchestrator_fallback(tmp_path: Path):
    """The Bevy agent must NOT ask for ``../godogen/SKILL.md`` — that path
    was a Godot-historical fallback and would FileNotFoundError on Bevy."""
    executor = _make_executor()
    game_service = _make_game_service(build_wasm_return=tmp_path / "dist")

    agent = BevyCreationAgent(executor, game_service)
    await _collect(agent, tmp_path)

    requested = [call.args[0] for call in game_service.read_skill.call_args_list]
    assert "../godogen/SKILL.md" not in requested


# ---------------------------------------------------------------------------
# Build invocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_game_calls_build_wasm_after_executor(tmp_path: Path):
    """build_wasm must be called exactly once with the game_path after the
    executor stream has been drained."""
    executor = _make_executor(
        ExecutorEvent(type="complete", content="done", metadata={"cost_usd": 0.0})
    )
    game_service = _make_game_service(build_wasm_return=tmp_path / "dist")

    agent = BevyCreationAgent(executor, game_service)
    await _collect(agent, tmp_path)

    game_service.build_wasm.assert_called_once_with(tmp_path)


@pytest.mark.asyncio
async def test_create_game_emits_completion_with_dist_when_build_succeeds(tmp_path: Path):
    """build_wasm returning a dist path produces a CompletionEvent whose
    result_path ends with index.html."""
    fake_dist = Path("/fake/dist")
    executor = _make_executor()
    game_service = _make_game_service(build_wasm_return=fake_dist)

    agent = BevyCreationAgent(executor, game_service)
    events = await _collect(agent, tmp_path)

    completions = [e for e in events if isinstance(e, CompletionEvent)]
    assert len(completions) == 1
    assert completions[0].result_path.endswith("index.html")
    assert completions[0].result_path == str(fake_dist / "index.html")


@pytest.mark.asyncio
async def test_create_game_emits_video_completion_when_build_fails_but_video_present(
    tmp_path: Path,
):
    """If build_wasm raises but a presentation video exists, the completion
    points at the video (degraded but recoverable path)."""
    executor = _make_executor()
    game_service = _make_game_service(
        build_wasm_raises=FileNotFoundError("no Cargo.toml"),
    )

    presentation = tmp_path / "screenshots" / "presentation"
    presentation.mkdir(parents=True)
    video_path = presentation / "gameplay.mp4"
    video_path.write_bytes(b"fake-video-bytes")

    agent = BevyCreationAgent(executor, game_service)
    events = await _collect(agent, tmp_path)

    completions = [e for e in events if isinstance(e, CompletionEvent)]
    assert len(completions) == 1
    assert completions[0].result_path == str(video_path)


# ---------------------------------------------------------------------------
# _promote_capture_artifacts
# ---------------------------------------------------------------------------


def test_promote_capture_artifacts_copies_highest_numbered_result(tmp_path: Path):
    """Among multiple result/{N}/ dirs, the highest-numbered one wins."""
    r1 = tmp_path / "screenshots" / "result" / "1"
    r3 = tmp_path / "screenshots" / "result" / "3"
    r1.mkdir(parents=True)
    r3.mkdir(parents=True)
    (r1 / "gameplay.mp4").write_bytes(b"OLD-VIDEO-1")
    (r3 / "gameplay.mp4").write_bytes(b"NEW-VIDEO-3")

    BevyCreationAgent._promote_capture_artifacts(tmp_path)

    promoted = tmp_path / "screenshots" / "presentation" / "gameplay.mp4"
    assert promoted.exists()
    assert promoted.read_bytes() == b"NEW-VIDEO-3"


def test_promote_capture_artifacts_handles_missing_result_dir(tmp_path: Path):
    """No result directory: helper must not raise and must not create
    a presentation directory."""
    BevyCreationAgent._promote_capture_artifacts(tmp_path)

    assert not (tmp_path / "screenshots" / "presentation").exists()


def test_promote_capture_artifacts_copies_screenshot_when_video_absent(tmp_path: Path):
    """A result/{N}/ with only gameplay.png produces only the png — no
    spurious gameplay.mp4 is created."""
    r1 = tmp_path / "screenshots" / "result" / "1"
    r1.mkdir(parents=True)
    (r1 / "gameplay.png").write_bytes(b"PNG-BYTES")

    BevyCreationAgent._promote_capture_artifacts(tmp_path)

    presentation = tmp_path / "screenshots" / "presentation"
    assert (presentation / "gameplay.png").exists()
    assert (presentation / "gameplay.png").read_bytes() == b"PNG-BYTES"
    assert not (presentation / "gameplay.mp4").exists()
