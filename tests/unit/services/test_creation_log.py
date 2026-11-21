"""Tests for _CreationLog used by GodotCreationAgent.

The log must always write a summary on close, including when the pipeline
crashed mid-run, and must persist every event so failures are diagnosable
after the SSE stream closes.
"""
import json
from pathlib import Path

import pytest

from src.api.observability.events import (
    CLIStreamEvent,
    CompletionEvent,
    ErrorEvent,
    StatusEvent,
)
from src.api.services.godot_creation_agent import _CreationLog


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_writes_each_event_as_jsonl(tmp_path: Path):
    log = _CreationLog(tmp_path)
    log.write(StatusEvent(service="t", message="starting", step="pipeline", status="started"))
    log.write(CLIStreamEvent(service="t", stream_type="thinking", content="hello"))
    log.close(has_export=True, has_video=True)

    events = _read_jsonl(tmp_path / ".creation" / "events.jsonl")
    assert len(events) == 2
    assert events[0]["event_type"] == "StatusEvent"
    assert events[0]["message"] == "starting"
    assert events[1]["event_type"] == "CLIStreamEvent"
    assert events[1]["content"] == "hello"


def test_summary_marks_success_when_export_present(tmp_path: Path):
    log = _CreationLog(tmp_path)
    log.write(CompletionEvent(service="t", message="done", result_path="/tmp/x"))
    log.close(has_export=True, has_video=False)

    summary = json.loads((tmp_path / ".creation" / "summary.json").read_text())
    assert summary["status"] == "success"
    assert summary["error"] is None
    assert summary["has_export"] is True
    assert summary["event_count"] == 1
    assert summary["final_message"] == "done"


def test_summary_marks_partial_when_no_artifacts(tmp_path: Path):
    log = _CreationLog(tmp_path)
    log.write(StatusEvent(service="t", message="started", step="pipeline", status="started"))
    log.close(has_export=False, has_video=False)

    summary = json.loads((tmp_path / ".creation" / "summary.json").read_text())
    assert summary["status"] == "partial"
    assert "without producing" in summary["error"]


def test_summary_marks_failed_when_error_event_emitted(tmp_path: Path):
    log = _CreationLog(tmp_path)
    log.write(ErrorEvent(service="t", error_message="boom", suggestion="retry"))
    log.close(has_export=False, has_video=False)

    summary = json.loads((tmp_path / ".creation" / "summary.json").read_text())
    assert summary["status"] == "failed"


def test_summary_marks_crashed_when_exception_passed(tmp_path: Path):
    log = _CreationLog(tmp_path)
    log.write(StatusEvent(service="t", message="m", step="x", status="started"))
    log.close(has_export=False, has_video=False, exception=RuntimeError("kaboom"))

    summary = json.loads((tmp_path / ".creation" / "summary.json").read_text())
    assert summary["status"] == "crashed"
    assert "RuntimeError" in summary["error"]
    assert "kaboom" in summary["error"]


def test_summary_aggregates_cost(tmp_path: Path):
    log = _CreationLog(tmp_path)
    log.write(CLIStreamEvent(service="t", stream_type="complete", content="ok", cost_usd=0.10))
    log.write(CLIStreamEvent(service="t", stream_type="complete", content="ok", cost_usd=0.25))
    log.close(has_export=True, has_video=True)

    summary = json.loads((tmp_path / ".creation" / "summary.json").read_text())
    assert summary["total_cost_usd"] == pytest.approx(0.35)
