"""Tests for the suggestions generator service."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.services.suggestions_generator import (
    generate_suggestions,
    parse_suggestions_json,
)


def test_parse_well_formed_json_returns_list():
    raw = '{"suggestions": ["Add music", "Make harder", "Add boss", "Color shift", "More enemies"]}'
    assert parse_suggestions_json(raw) == [
        "Add music", "Make harder", "Add boss", "Color shift", "More enemies",
    ]


def test_parse_extracts_json_block_from_prose():
    # Claude often wraps JSON in prose / fences. Tolerate that.
    raw = "Here are the suggestions:\n```json\n" \
          '{"suggestions": ["A", "B", "C", "D", "E"]}\n```\n'
    assert parse_suggestions_json(raw) == ["A", "B", "C", "D", "E"]


def test_parse_malformed_returns_empty():
    assert parse_suggestions_json("not json at all") == []
    assert parse_suggestions_json('{"wrong_key": []}') == []
    assert parse_suggestions_json('{"suggestions": "not a list"}') == []


def test_parse_truncates_to_five_and_drops_non_strings():
    raw = '{"suggestions": ["a", "b", "c", "d", "e", "f", 123, null]}'
    assert parse_suggestions_json(raw) == ["a", "b", "c", "d", "e"]


@pytest.mark.asyncio
async def test_generate_writes_sidecar_file(tmp_path, monkeypatch):
    game_path = tmp_path / "godot-test"
    game_path.mkdir()
    (game_path / "PLAN.md").write_text("A platformer with a frog.")
    (game_path / "project.godot").write_text("")

    fake_executor = MagicMock()
    fake_executor.run_oneshot = AsyncMock(
        return_value='{"suggestions": ["Add music", "Make harder", "Add boss", "Color shift", "More enemies"]}'
    )

    result = await generate_suggestions(game_path, "godot", executor=fake_executor)

    assert result == ["Add music", "Make harder", "Add boss", "Color shift", "More enemies"]
    sidecar = game_path / "suggestions.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text())
    assert data["suggestions"] == result
    assert "generated_at" in data


@pytest.mark.asyncio
async def test_generate_swallows_executor_errors(tmp_path):
    game_path = tmp_path / "godot-test"
    game_path.mkdir()

    fake_executor = MagicMock()
    fake_executor.run_oneshot = AsyncMock(side_effect=RuntimeError("boom"))

    # Best-effort: never raises, returns empty, writes nothing.
    result = await generate_suggestions(game_path, "godot", executor=fake_executor)
    assert result == []
    assert not (game_path / "suggestions.json").exists()


@pytest.mark.asyncio
async def test_generate_prompt_includes_engine_plan_and_files(tmp_path):
    game_path = tmp_path / "godot-test"
    game_path.mkdir()
    (game_path / "PLAN.md").write_text("TESTPLAN frog platformer")
    (game_path / "project.godot").write_text("")
    (game_path / "STRUCTURE.md").write_text("structure notes")

    fake_executor = MagicMock()
    fake_executor.run_oneshot = AsyncMock(
        return_value='{"suggestions": ["a", "b", "c", "d", "e"]}'
    )

    await generate_suggestions(game_path, "godot", executor=fake_executor)

    fake_executor.run_oneshot.assert_awaited_once()
    prompt = fake_executor.run_oneshot.call_args.args[0]
    assert "godot" in prompt
    assert "TESTPLAN frog platformer" in prompt
    assert "PLAN.md" in prompt
    assert "project.godot" in prompt


@pytest.mark.asyncio
async def test_generate_skips_when_parse_fails(tmp_path):
    game_path = tmp_path / "godot-test"
    game_path.mkdir()

    fake_executor = MagicMock()
    fake_executor.run_oneshot = AsyncMock(return_value="garbage output")

    result = await generate_suggestions(game_path, "godot", executor=fake_executor)
    assert result == []
    assert not (game_path / "suggestions.json").exists()
