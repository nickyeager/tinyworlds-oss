"""Codex noninteractive executor and public JSON event normalization."""

from __future__ import annotations

from src.api.services.executors.cli_executor import CLIExecutor
from src.api.services.agent_commands import agent_model, codex_flags
from src.api.services.godot_executor import ExecutorEvent


def parse_codex_event(obj: dict) -> list[ExecutorEvent]:
    """Normalize native Codex JSON events without treating failed turns as success."""
    event_type = obj.get("type", "")
    item = obj.get("item") or {}
    item_type = item.get("type", "")
    metadata = {"item_id": item.get("id", "")}
    if event_type in {"error", "turn.failed"} or item_type == "error":
        error = obj.get(
            "error", item.get("message", obj.get("message", "Codex execution failed"))
        )
        if isinstance(error, dict):
            error = error.get("message", str(error))
        return [ExecutorEvent("error", str(error))]
    if event_type == "turn.completed":
        return [
            ExecutorEvent(
                "complete", "", {"usage": obj.get("usage", {}), "success": True}
            )
        ]
    if event_type == "item.started" and item_type in {
        "command_execution",
        "mcp_tool_call",
        "web_search",
    }:
        name = item.get("command", item.get("tool", item_type))
        return [
            ExecutorEvent(
                "tool_use",
                str(name),
                {**metadata, "tool_name": item_type, "input": item},
            )
        ]
    if event_type == "item.completed":
        if item_type in {"agent_message", "reasoning"}:
            return [ExecutorEvent("thinking", str(item.get("text", "")), metadata)]
        if item_type == "command_execution":
            result = [
                ExecutorEvent(
                    "tool_result",
                    str(item.get("aggregated_output", "")),
                    {
                        **metadata,
                        "exit_code": item.get("exit_code"),
                        "command": item.get("command", ""),
                        "success": item.get("status") != "failed"
                        and item.get("exit_code", 0) in {0, None},
                    },
                )
            ]
            return result
        if item_type == "file_change":
            return [
                ExecutorEvent("file_changed", str(change.get("path", "")), change)
                for change in item.get("changes", [])
            ]
        if item_type == "mcp_tool_call":
            if item.get("status") == "failed" or item.get("error"):
                return [
                    ExecutorEvent(
                        "error", str(item.get("error", "Tool call failed")), metadata
                    )
                ]
            return [ExecutorEvent("tool_result", str(item.get("result", "")), metadata)]
    if event_type in {"thread.started", "turn.started"}:
        return [ExecutorEvent("status", event_type, obj)]
    return []


class CodexExecutor(CLIExecutor):
    """Run Codex with the native workspace-write sandbox and isolated config."""

    provider = "codex"

    def _command(self, prompt: str, settings_path: str | None = None) -> list[str]:
        model = agent_model(self.settings, self.provider)
        return [self.settings.CODEX_CLI_BINARY, *codex_flags(model), prompt]

    def _events(self, obj: dict) -> list[ExecutorEvent]:
        return parse_codex_event(obj)
