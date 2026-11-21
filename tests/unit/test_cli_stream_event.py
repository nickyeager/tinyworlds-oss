"""Tests for CLIStreamEvent serialization — all structured fields must survive SSE."""
import pytest
from src.api.observability.events import CLIStreamEvent


class TestCLIStreamEventSerialization:
    """CLIStreamEvent should serialize all structured fields for SSE."""

    def test_tool_use_write_serializes_file_content(self):
        event = CLIStreamEvent(
            service="godot_creation_agent",
            stream_type="tool_use",
            tool_name="Write",
            tool_input={
                "file_path": "scripts/player.gd",
                "content": "extends CharacterBody2D\n\nfunc _ready():\n\tpass",
            },
        )
        d = event.to_sse_dict()
        assert d["event_type"] == "CLIStreamEvent"
        assert d["stream_type"] == "tool_use"
        assert d["tool_name"] == "Write"
        assert d["tool_input"]["file_path"] == "scripts/player.gd"
        assert "extends CharacterBody2D" in d["tool_input"]["content"]

    def test_tool_use_edit_serializes_diff(self):
        event = CLIStreamEvent(
            service="godot_creation_agent",
            stream_type="tool_use",
            tool_name="Edit",
            tool_input={
                "file_path": "scripts/player.gd",
                "old_string": "var speed = 100",
                "new_string": "var speed = 200",
            },
        )
        d = event.to_sse_dict()
        assert d["tool_name"] == "Edit"
        assert d["tool_input"]["old_string"] == "var speed = 100"
        assert d["tool_input"]["new_string"] == "var speed = 200"

    def test_tool_use_bash_serializes_command(self):
        event = CLIStreamEvent(
            service="godot_creation_agent",
            stream_type="tool_use",
            tool_name="Bash",
            tool_input={"command": "python3 asset_gen.py image --prompt 'a cat'"},
        )
        d = event.to_sse_dict()
        assert d["tool_name"] == "Bash"
        assert "asset_gen.py" in d["tool_input"]["command"]

    def test_thinking_event_serializes_content(self):
        event = CLIStreamEvent(
            service="godot_creation_agent",
            stream_type="thinking",
            content="I need to create a player script with movement and collision.",
        )
        d = event.to_sse_dict()
        assert d["stream_type"] == "thinking"
        assert "player script" in d["content"]

    def test_tool_result_serializes_content(self):
        event = CLIStreamEvent(
            service="godot_creation_agent",
            stream_type="tool_result",
            content="File written successfully: scripts/player.gd (42 lines)",
        )
        d = event.to_sse_dict()
        assert d["stream_type"] == "tool_result"
        assert "player.gd" in d["content"]

    def test_error_event_serializes(self):
        event = CLIStreamEvent(
            service="godot_creation_agent",
            stream_type="error",
            content="Parser Error: unexpected token",
        )
        d = event.to_sse_dict()
        assert d["stream_type"] == "error"
        assert "Parser Error" in d["content"]

    def test_complete_event_includes_cost(self):
        event = CLIStreamEvent(
            service="godot_creation_agent",
            stream_type="complete",
            content="Pipeline finished",
            cost_usd=0.42,
        )
        d = event.to_sse_dict()
        assert d["stream_type"] == "complete"
        assert d["cost_usd"] == 0.42

    def test_complete_event_cost_defaults_to_none(self):
        event = CLIStreamEvent(
            service="godot_creation_agent",
            stream_type="complete",
            content="Done",
        )
        d = event.to_sse_dict()
        assert d["cost_usd"] is None

    def test_empty_tool_input_defaults_to_empty_dict(self):
        event = CLIStreamEvent(
            service="test",
            stream_type="tool_use",
            tool_name="Read",
        )
        d = event.to_sse_dict()
        assert d["tool_input"] == {}
