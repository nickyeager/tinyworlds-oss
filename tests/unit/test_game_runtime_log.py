"""Unit tests for GameRuntimeLog — the in-game telemetry pipe."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api.services.game_runtime_log import (
    GameRuntimeLog,
    RATE_LIMIT_PER_MINUTE,
    RateLimitedError,
)


def _log(tmp_path: Path) -> GameRuntimeLog:
    return GameRuntimeLog(log_path=tmp_path / "game_runtime.jsonl")


def test_append_writes_jsonl(tmp_path: Path):
    log = _log(tmp_path)
    log.append("godot-1", "session_start", {"build": "test"}, session_id="sess-a")
    log.append("godot-1", "pickup", {"kind": "pot"}, session_id="sess-a")
    lines = (tmp_path / "game_runtime.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    rec0 = json.loads(lines[0])
    assert rec0["game_id"] == "godot-1"
    assert rec0["kind"] == "session_start"
    assert rec0["session_id"] == "sess-a"


def test_per_game_rate_limit_429(tmp_path: Path):
    log = _log(tmp_path)
    # Fill the bucket for one game.
    for _ in range(RATE_LIMIT_PER_MINUTE):
        log.append("godot-A", "ping", {})
    with pytest.raises(RateLimitedError):
        log.append("godot-A", "ping", {})
    # Other games are unaffected — separate buckets.
    log.append("godot-B", "ping", {})


def test_oversized_payload_truncated_not_dropped(tmp_path: Path):
    log = _log(tmp_path)
    big = "X" * 5000  # > MAX_PAYLOAD_BYTES (2048)
    log.append("godot-1", "weird", {"blob": big})
    line = (tmp_path / "game_runtime.jsonl").read_text().strip().splitlines()[0]
    rec = json.loads(line)
    # Truncated marker present, original key removed/replaced.
    assert rec["overflow"] is True
    assert "_truncated_repr" in rec["data"]


def test_events_for_game_filters_by_id_and_kind(tmp_path: Path):
    log = _log(tmp_path)
    log.append("godot-1", "player_pos", {"x": 1.0})
    log.append("godot-2", "player_pos", {"x": 2.0})  # other game — should not appear
    log.append("godot-1", "pickup", {"kind": "pot"})
    log.append("godot-1", "error", {"msg": "boom"})

    all_for_1 = log.events_for_game("godot-1")
    assert len(all_for_1) == 3
    # Newest first.
    kinds = [e["kind"] for e in all_for_1]
    assert kinds == ["error", "pickup", "player_pos"]

    just_errors = log.events_for_game("godot-1", kinds={"error"})
    assert len(just_errors) == 1
    assert just_errors[0]["kind"] == "error"


def test_summary_aggregates_kinds_and_sessions(tmp_path: Path):
    log = _log(tmp_path)
    log.append("godot-1", "session_start", {}, session_id="s1")
    log.append("godot-1", "player_pos", {"x": 1}, session_id="s1")
    log.append("godot-1", "player_pos", {"x": 2}, session_id="s1")
    log.append("godot-1", "pickup", {}, session_id="s1")
    log.append("godot-1", "error", {"msg": "x"}, session_id="s2")

    summary = log.summary_for_game("godot-1")
    assert summary["total_events"] == 5
    assert summary["kind_counts"] == {
        "session_start": 1, "player_pos": 2, "pickup": 1, "error": 1,
    }
    assert summary["session_count"] == 2
    assert summary["error_count"] == 1
    assert summary["last_event_ts"] is not None


def test_non_json_serializable_value_is_coerced(tmp_path: Path):
    log = _log(tmp_path)
    # Non-JSON-serializable object (a set) — handler uses default=str, so
    # the set lands as its repr. The record still writes (zero data loss).
    log.append("godot-1", "weird", {"s": {1, 2, 3}})
    lines = (tmp_path / "game_runtime.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    # Set rendered as a string via default=str — exact format isn't
    # contract-stable, but the record exists and the field is present.
    assert rec["kind"] == "weird"
    assert "s" in rec["data"]


def test_kind_and_session_id_length_capped(tmp_path: Path):
    log = _log(tmp_path)
    long_kind = "k" * 100
    long_sess = "s" * 100
    log.append("godot-1", long_kind, {}, session_id=long_sess)
    rec = json.loads((tmp_path / "game_runtime.jsonl").read_text().strip())
    # Both clamp to 64 chars to bound the ledger.
    assert len(rec["kind"]) == 64
    assert len(rec["session_id"]) == 64


def test_rate_limit_window_expires(tmp_path: Path):
    """Saturating the bucket blocks, but 61s later events flow again — the
    cap is a rolling window, not a permanent ban."""
    log = _log(tmp_path)
    for _ in range(RATE_LIMIT_PER_MINUTE):
        log.append("godot-W", "ping", {}, ts=100.0)
    with pytest.raises(RateLimitedError):
        log.append("godot-W", "ping", {}, ts=100.5)
    log.append("godot-W", "ping", {}, ts=161.0)
