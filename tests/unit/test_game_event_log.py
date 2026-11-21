"""Unit tests for GameEventLog tail + replay."""
import asyncio
import json
from pathlib import Path

import pytest

from src.api.services.game_event_log import GameEventLog


def _setup_log(tmp_path: Path) -> Path:
    """Make a fake game dir with a .creation/ subdir; return game_path."""
    game_path = tmp_path / "godot-test"
    (game_path / ".creation").mkdir(parents=True)
    return game_path


def _append_events(log: GameEventLog, events: list[dict]) -> None:
    with log.events_file.open("a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


@pytest.mark.asyncio
async def test_tail_replays_history_then_terminates_on_terminal_event(tmp_path):
    game_path = _setup_log(tmp_path)
    log = GameEventLog(game_path)
    _append_events(log, [
        {"event_type": "init", "n": 0},
        {"event_type": "CLIStreamEvent", "n": 1},
        {"event_type": "done", "n": 2},
    ])

    seen: list[tuple[int, dict]] = []
    async for seq, event in log.tail(poll_interval=0.05):
        seen.append((seq, event))

    assert [s for s, _ in seen] == [0, 1, 2]
    assert seen[-1][1]["event_type"] == "done"


@pytest.mark.asyncio
async def test_tail_yields_new_appends_after_eof(tmp_path):
    game_path = _setup_log(tmp_path)
    log = GameEventLog(game_path)
    _append_events(log, [{"event_type": "init"}])

    # Start the tail, drain the first event, then append + terminate.
    async def _consume() -> list[dict]:
        out: list[dict] = []
        async for _seq, event in log.tail(poll_interval=0.05):
            out.append(event)
        return out

    consume_task = asyncio.create_task(_consume())
    await asyncio.sleep(0.1)  # let it read the existing event
    _append_events(log, [
        {"event_type": "CLIStreamEvent"},
        {"event_type": "done"},
    ])
    result = await asyncio.wait_for(consume_task, timeout=2.0)
    assert [e["event_type"] for e in result] == ["init", "CLIStreamEvent", "done"]


@pytest.mark.asyncio
async def test_tail_resumes_from_since_seq(tmp_path):
    game_path = _setup_log(tmp_path)
    log = GameEventLog(game_path)
    _append_events(log, [
        {"event_type": "init"},
        {"event_type": "CLIStreamEvent", "marker": "skip-me"},
        {"event_type": "CLIStreamEvent", "marker": "yield-me"},
        {"event_type": "done"},
    ])

    out: list[tuple[int, dict]] = []
    async for seq, event in log.tail(since_seq=1, poll_interval=0.05):
        out.append((seq, event))

    assert [s for s, _ in out] == [2, 3]
    assert out[0][1]["marker"] == "yield-me"


@pytest.mark.asyncio
async def test_tail_can_explicitly_stop_on_summary_for_legacy_consumers(tmp_path):
    game_path = _setup_log(tmp_path)
    log = GameEventLog(game_path)
    _append_events(log, [{"event_type": "CLIStreamEvent"}])

    async def _consume() -> list[dict]:
        return [e async for _, e in log.tail(poll_interval=0.05, stop_on_summary=True)]

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.1)
    log.summary_file.write_text(json.dumps({"status": "success"}))
    result = await asyncio.wait_for(task, timeout=2.0)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_tail_yields_interrupted_on_idle_timeout(tmp_path):
    game_path = _setup_log(tmp_path)
    log = GameEventLog(game_path)
    _append_events(log, [{"event_type": "CLIStreamEvent"}])

    out = []
    async for _seq, event in log.tail(poll_interval=0.05, idle_timeout_seconds=0.2):
        out.append(event)

    # First the historical event, then the synthetic interrupted marker.
    assert out[0]["event_type"] == "CLIStreamEvent"
    assert out[1]["event_type"] == "interrupted"
    assert "orphaned" in out[1]["reason"]


@pytest.mark.asyncio
async def test_summary_alone_does_not_mark_browser_verification_terminal(tmp_path):
    game_path = _setup_log(tmp_path)
    log = GameEventLog(game_path)
    _append_events(log, [{"event_type": "CLIStreamEvent"}])
    assert log.has_terminal() is False
    log.summary_file.write_text("{}")
    assert log.has_terminal() is False
    _append_events(log, [{"event_type": "done"}])
    assert log.has_terminal() is True


def test_read_all_skips_malformed_lines(tmp_path):
    game_path = _setup_log(tmp_path)
    log = GameEventLog(game_path)
    log.events_file.write_text(
        json.dumps({"event_type": "a"}) + "\n"
        "not valid json\n"
        + json.dumps({"event_type": "b"}) + "\n"
    )
    out = log.read_all()
    assert [e["event_type"] for e in out] == ["a", "b"]


def test_custom_log_dir_append_and_summary(tmp_path):
    game_path = tmp_path / "godot-test"
    log = GameEventLog(game_path, log_dir=".modifications/run-1")

    log.append({"event_type": "init", "content": "queued"})
    log.write_summary({"status": "success"})

    assert log.read_all() == [{"event_type": "init", "content": "queued"}]
    assert log.read_summary() == {"status": "success"}
    assert log.events_file == game_path / ".modifications/run-1/events.jsonl"
