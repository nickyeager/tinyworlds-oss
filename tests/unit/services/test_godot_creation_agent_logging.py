"""Integration test: GodotCreationAgent.create_game writes a per-game log.

Drives the agent's async generator with a fake executor so we can assert that
events.jsonl and summary.json are produced without invoking Claude CLI.
"""
import json
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

import pytest

from src.api.services.godot_creation_agent import (
    GodotCreationAgent,
    GodotCreationRequest,
)
from src.api.services.godot_executor import ExecutorEvent, GodotExecutor


class _FakeExecutor(GodotExecutor):
    def __init__(self, events: List[ExecutorEvent]):
        self._events = events

    async def run_stage(
        self,
        skill_content: str,
        user_prompt: str,
        game_path: Path,
        image_paths: Optional[List[str]] = None,
        context_files: Optional[Dict[str, str]] = None,
        mode: str = "create",
        **kwargs,
    ) -> AsyncIterator[ExecutorEvent]:
        for ev in self._events:
            yield ev

    async def run_stage_sync(self, *a, **kw):  # noqa: D401
        raise NotImplementedError


class _FakeGameService:
    def read_skill(self, name: str) -> str:
        if name.startswith(".."):
            raise FileNotFoundError(name)
        return "fake skill content"

    def verify_playable(self, game_path: Path):
        return []

    def ensure_capture_wrapper(self, game_path: Path) -> None:
        (game_path / ".capture").mkdir(parents=True, exist_ok=True)

    async def export_html5(self, game_path: Path) -> Optional[Path]:
        # Simulate successful export so summary status == "success".
        dist = game_path / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("<html></html>")
        return dist


async def _drain(agent, request, game_path):
    events = []
    async for ev in agent.create_game(request, game_path):
        events.append(ev)
    return events


@pytest.mark.asyncio
async def test_successful_run_writes_events_and_success_summary(tmp_path: Path):
    fake_events = [
        ExecutorEvent(type="thinking", content="planning..."),
        ExecutorEvent(type="tool_use", content="Write", metadata={"input": {"file_path": "x.cs"}}),
        ExecutorEvent(type="complete", content="ok", metadata={"cost_usd": 0.42}),
    ]
    agent = GodotCreationAgent(_FakeExecutor(fake_events), _FakeGameService())

    yielded = await _drain(agent, GodotCreationRequest(intent="test game"), tmp_path)
    assert yielded, "agent must yield at least one event"

    log_dir = tmp_path / ".creation"
    events_file = log_dir / "events.jsonl"
    summary_file = log_dir / "summary.json"

    assert events_file.exists()
    persisted = [json.loads(line) for line in events_file.read_text().splitlines() if line]
    types = [e["event_type"] for e in persisted]
    # Pipeline emits a starting Status, three CLIStream events, two export Status events,
    # and a final Completion. The exact order matters less than the presence of each.
    assert "StatusEvent" in types
    assert "CLIStreamEvent" in types
    assert "CompletionEvent" in types

    summary = json.loads(summary_file.read_text())
    assert summary["status"] == "success"
    assert summary["has_export"] is True
    assert summary["error"] is None
    assert summary["total_cost_usd"] == pytest.approx(0.42)


@pytest.mark.asyncio
async def test_executor_error_event_marks_run_failed(tmp_path: Path):
    fake_events = [
        ExecutorEvent(type="thinking", content="thinking..."),
        ExecutorEvent(type="error", content="claude exited with code 1"),
    ]

    class _NoExportService(_FakeGameService):
        async def export_html5(self, game_path: Path):
            return None

    agent = GodotCreationAgent(_FakeExecutor(fake_events), _NoExportService())
    await _drain(agent, GodotCreationRequest(intent="test"), tmp_path)

    summary = json.loads((tmp_path / ".creation" / "summary.json").read_text())
    # Pipeline finished without an export OR a CLI error event escalating to ErrorEvent;
    # A provider failure stays failed even if it writes partial artifacts.
    assert summary["status"] == "failed"
    assert summary["has_export"] is False


class _AttemptCountingExecutor(GodotExecutor):
    """Yields different events per call so we can tell attempts apart."""

    def __init__(self, per_attempt: List[List[ExecutorEvent]]):
        self._per_attempt = per_attempt
        self.calls = 0

    async def run_stage(
        self,
        skill_content: str,
        user_prompt: str,
        game_path: Path,
        image_paths: Optional[List[str]] = None,
        context_files: Optional[Dict[str, str]] = None,
        mode: str = "create",
        **kwargs,
    ) -> AsyncIterator[ExecutorEvent]:
        idx = min(self.calls, len(self._per_attempt) - 1)
        self.calls += 1
        for ev in self._per_attempt[idx]:
            yield ev

    async def run_stage_sync(self, *a, **kw):  # noqa: D401
        raise NotImplementedError


@pytest.mark.asyncio
async def test_zero_cost_partial_triggers_one_auto_retry(tmp_path: Path):
    """Mirrors prod incident godot-52297b1e: agent emits `complete` with $0
    cost, no artifacts. Should auto-retry once. Second attempt succeeds."""

    class _ExportOnlyOnSecondAttempt(_FakeGameService):
        def __init__(self):
            self.export_calls = 0

        def read_skill(self, name: str) -> str:
            if name.startswith(".."):
                raise FileNotFoundError(name)
            return "fake skill"

        def ensure_capture_wrapper(self, game_path: Path) -> None:
            (game_path / ".capture").mkdir(parents=True, exist_ok=True)

        async def export_html5(self, game_path: Path):
            self.export_calls += 1
            if self.export_calls < 2:
                return None
            dist = game_path / "dist"
            dist.mkdir(parents=True, exist_ok=True)
            (dist / "index.html").write_text("<html></html>")
            return dist

    executor = _AttemptCountingExecutor([
        # Attempt 1: bare complete with no cost — zero-cost partial.
        [ExecutorEvent(type="complete", content="result", metadata={"cost_usd": 0.0})],
        # Attempt 2: real work with cost.
        [
            ExecutorEvent(type="tool_use", content="Write", metadata={"input": {}}),
            ExecutorEvent(type="complete", content="ok", metadata={"cost_usd": 2.5}),
        ],
    ])
    service = _ExportOnlyOnSecondAttempt()
    agent = GodotCreationAgent(executor, service)

    await _drain(agent, GodotCreationRequest(intent="test"), tmp_path)

    assert executor.calls == 2, "expected exactly one auto-retry"
    summary = json.loads((tmp_path / ".creation" / "summary.json").read_text())
    assert summary["status"] == "success"
    assert summary["has_export"] is True


@pytest.mark.asyncio
async def test_no_retry_when_first_attempt_succeeds(tmp_path: Path):
    executor = _AttemptCountingExecutor([
        [ExecutorEvent(type="complete", content="ok", metadata={"cost_usd": 1.0})],
    ])
    agent = GodotCreationAgent(executor, _FakeGameService())
    await _drain(agent, GodotCreationRequest(intent="test"), tmp_path)
    assert executor.calls == 1, "successful run must not retry"


@pytest.mark.asyncio
async def test_no_retry_when_partial_has_real_cost(tmp_path: Path):
    """Real generation that produces no artifacts (but spent money) is a real
    failure, not the zero-cost early-stop pattern — do not retry."""

    class _NoExport(_FakeGameService):
        async def export_html5(self, game_path: Path):
            return None

    executor = _AttemptCountingExecutor([
        [ExecutorEvent(type="complete", content="ok", metadata={"cost_usd": 3.5})],
    ])
    agent = GodotCreationAgent(executor, _NoExport())
    await _drain(agent, GodotCreationRequest(intent="test"), tmp_path)
    assert executor.calls == 1
    summary = json.loads((tmp_path / ".creation" / "summary.json").read_text())
    assert summary["status"] == "partial"


@pytest.mark.asyncio
async def test_export_crash_marks_run_crashed(tmp_path: Path):
    class _CrashingService(_FakeGameService):
        async def export_html5(self, game_path: Path):
            raise RuntimeError("godot binary missing")

    fake_events = [ExecutorEvent(type="complete", content="ok")]
    agent = GodotCreationAgent(_FakeExecutor(fake_events), _CrashingService())
    await _drain(agent, GodotCreationRequest(intent="test"), tmp_path)

    summary = json.loads((tmp_path / ".creation" / "summary.json").read_text())
    # The agent catches the exception, emits an ErrorEvent, and stores the
    # exception so close() can label the run "crashed" (more specific than
    # "failed", which is reserved for ErrorEvents the executor itself emits).
    assert summary["status"] == "crashed"
    assert "RuntimeError" in (summary["error"] or "")
    assert "godot binary missing" in (summary["error"] or "")


@pytest.mark.asyncio
async def test_second_zero_cost_partial_does_not_retry_again(tmp_path: Path):
    """The auto-retry is capped at one: if the retry ALSO ends as a zero-cost
    partial, the run must stop at two attempts, not loop."""

    class _NeverExports(_FakeGameService):
        async def export_html5(self, game_path: Path):
            return None

    executor = _AttemptCountingExecutor([
        [ExecutorEvent(type="complete", content="r", metadata={"cost_usd": 0.0})],
        [ExecutorEvent(type="complete", content="r", metadata={"cost_usd": 0.0})],
        [ExecutorEvent(type="complete", content="r", metadata={"cost_usd": 0.0})],
    ])
    agent = GodotCreationAgent(executor, _NeverExports())
    await _drain(agent, GodotCreationRequest(intent="test"), tmp_path)

    assert executor.calls == 2, "auto-retry must fire exactly once"
