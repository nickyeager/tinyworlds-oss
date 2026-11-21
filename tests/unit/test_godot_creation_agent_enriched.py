"""Tests that GodotCreationAgent yields enriched CLIStreamEvents, not flattened StatusEvents."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.api.services.godot_creation_agent import GodotCreationAgent, GodotCreationRequest
from src.api.services.godot_executor import ExecutorEvent
from src.api.observability.events import CLIStreamEvent, StatusEvent


async def _make_agent(*executor_events):
    """Create a GodotCreationAgent with a mock executor yielding the given events."""
    executor = MagicMock()
    game_service = MagicMock()
    game_service.read_skill.return_value = "fake skill content"
    game_service.export_html5 = AsyncMock(return_value=None)

    async def fake_run_stage(*args, **kwargs):
        for ev in executor_events:
            yield ev

    executor.run_stage = fake_run_stage
    return GodotCreationAgent(executor, game_service)


async def _collect_events(agent, intent="test"):
    events = []
    async for ev in agent.create_game(
        GodotCreationRequest(intent=intent),
        Path("/tmp/fake-game"),
    ):
        events.append(ev)
    return events


@pytest.mark.asyncio
async def test_tool_use_write_yields_cli_stream_event():
    """Write tool_use must yield CLIStreamEvent with tool_name and file content."""
    agent = await _make_agent(
        ExecutorEvent(
            type="tool_use",
            content="Write",
            metadata={"input": {"file_path": "scripts/player.gd", "content": "extends Node2D"}},
        ),
    )
    events = await _collect_events(agent)

    cli_events = [e for e in events if isinstance(e, CLIStreamEvent)]
    assert len(cli_events) >= 1
    write_ev = next(e for e in cli_events if e.tool_name == "Write")
    assert write_ev.stream_type == "tool_use"
    assert write_ev.tool_input["file_path"] == "scripts/player.gd"
    assert "extends Node2D" in write_ev.tool_input["content"]


@pytest.mark.asyncio
async def test_tool_use_bash_yields_cli_stream_event():
    """Bash tool_use must yield CLIStreamEvent with the command."""
    agent = await _make_agent(
        ExecutorEvent(
            type="tool_use",
            content="Bash",
            metadata={"input": {"command": "godot --headless --quit"}},
        ),
    )
    events = await _collect_events(agent)

    cli_events = [e for e in events if isinstance(e, CLIStreamEvent)]
    bash_ev = next(e for e in cli_events if e.tool_name == "Bash")
    assert bash_ev.tool_input["command"] == "godot --headless --quit"


@pytest.mark.asyncio
async def test_thinking_yields_cli_stream_event():
    """Thinking events must yield CLIStreamEvent with stream_type='thinking'."""
    agent = await _make_agent(
        ExecutorEvent(type="thinking", content="I'll create the player script first."),
    )
    events = await _collect_events(agent)

    cli_events = [e for e in events if isinstance(e, CLIStreamEvent)]
    thinking_ev = next(e for e in cli_events if e.stream_type == "thinking")
    assert "player script" in thinking_ev.content


@pytest.mark.asyncio
async def test_tool_result_yields_cli_stream_event():
    """Tool results must yield CLIStreamEvent with stream_type='tool_result'."""
    agent = await _make_agent(
        ExecutorEvent(
            type="tool_result",
            content="File created: scripts/player.gd",
            metadata={"tool_use_id": "toolu_123"},
        ),
    )
    events = await _collect_events(agent)

    cli_events = [e for e in events if isinstance(e, CLIStreamEvent)]
    result_ev = next(e for e in cli_events if e.stream_type == "tool_result")
    assert "player.gd" in result_ev.content


@pytest.mark.asyncio
async def test_no_flattened_status_events_for_tool_use():
    """Agent must NOT yield plain StatusEvent for tool_use — only CLIStreamEvent."""
    agent = await _make_agent(
        ExecutorEvent(
            type="tool_use",
            content="Write",
            metadata={"input": {"file_path": "test.gd", "content": "extends Node"}},
        ),
    )
    events = await _collect_events(agent)

    status_events = [
        e for e in events
        if isinstance(e, StatusEvent) and "Using Write" in (e.message or "")
    ]
    assert len(status_events) == 0, "tool_use still being flattened to StatusEvent"


@pytest.mark.asyncio
async def test_create_game_appends_mobile_touch_requirement():
    captured = {}
    executor = MagicMock()
    game_service = MagicMock()
    game_service.read_skill.return_value = "fake skill content"
    game_service.export_html5 = AsyncMock(return_value=None)

    async def fake_run_stage(skill_content, user_prompt, game_path, *args, **kwargs):
        captured["user_prompt"] = user_prompt
        if False:
            yield

    executor.run_stage = fake_run_stage
    agent = GodotCreationAgent(executor, game_service)

    await _collect_events(agent, intent="make a platformer")

    assert "Mobile and Touch Runtime Requirement" in captured["user_prompt"]
    assert "Keyboard-only" in captured["user_prompt"]


@pytest.mark.asyncio
async def test_complete_event_with_cost():
    """Complete event should forward cost_usd from executor metadata."""
    agent = await _make_agent(
        ExecutorEvent(
            type="complete",
            content="Done",
            metadata={"cost_usd": 0.15, "subtype": "success"},
        ),
    )
    events = await _collect_events(agent)

    cli_events = [e for e in events if isinstance(e, CLIStreamEvent) and e.stream_type == "complete"]
    assert len(cli_events) >= 1
    assert cli_events[0].cost_usd == 0.15
