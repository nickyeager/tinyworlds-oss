"""Public generation contracts, exercised without launching either agent CLI."""
from __future__ import annotations

import asyncio
import builtins
import importlib
import io
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.core.config import Settings


def _settings(**overrides):
    return Settings(SECRET_KEY="unit-test-secret", _env_file=None, **overrides)


def _executor(provider, **overrides):
    module_name, class_name = {
        "claude": ("cli_executor", "CLIExecutor"),
        "codex": ("codex_executor", "CodexExecutor"),
    }[provider]
    module = importlib.import_module(f"src.api.services.executors.{module_name}")
    return getattr(module, class_name)(_settings(**overrides))


class _Process:
    """Small asynchronous process double with observable termination/reaping."""

    def __init__(self, provider, *, hanging=False):
        self.returncode = None if hanging else 0
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self._finished = asyncio.Event()
        event = (
            {"type": "item.completed", "item": {"type": "agent_message", "text": "working"}}
            if provider == "codex"
            else {"type": "assistant", "message": {"content": [{"type": "text", "text": "working"}]}}
        )
        self.stdout.feed_data((json.dumps(event) + "\n").encode())
        if not hanging:
            self.stdout.feed_eof()
            self._finished.set()
        self.kill = MagicMock(side_effect=self._terminate)
        self.terminate = MagicMock(side_effect=self._terminate)
        self.wait = AsyncMock(side_effect=self._wait)

    def _terminate(self):
        self.returncode = -9
        if not self.stdout.at_eof():
            self.stdout.feed_eof()
        self._finished.set()

    async def _wait(self):
        await self._finished.wait()
        return self.returncode


async def _drain(stream):
    return [event async for event in stream]


async def _until_child_output(stream):
    async for event in stream:
        if "working" in event.content:
            return event
    pytest.fail("the running child must expose its output")


def test_factory_defaults_to_claude_and_codex_parser_preserves_failure():
    from src.api.services.executors import get_executor
    from src.api.services.executors.cli_executor import CLIExecutor
    from src.api.services.executors.codex_executor import CodexExecutor, parse_codex_event

    default = _settings()
    assert default.GAME_AGENT_PROVIDER == "claude"
    assert isinstance(get_executor(default), CLIExecutor)
    assert isinstance(get_executor(_settings(GAME_AGENT_PROVIDER="codex")), CodexExecutor)

    thinking = parse_codex_event({
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "plan the level"},
    })
    assert any(e.type == "thinking" and "plan the level" in e.content for e in thinking)
    command = parse_codex_event({
        "type": "item.completed",
        "item": {
            "type": "command_execution", "command": "cargo check",
            "aggregated_output": "checked successfully", "exit_code": 0,
            "status": "completed",
        },
    })
    assert any(e.type == "tool_result" and "checked successfully" in e.content for e in command)
    assert "cargo check" in repr([(e.content, e.metadata) for e in command])
    complete = parse_codex_event({
        "type": "turn.completed", "usage": {"input_tokens": 19, "output_tokens": 7},
    })
    assert any(e.type == "complete" for e in complete)
    assert "19" in repr([e.metadata for e in complete])
    assert "7" in repr([e.metadata for e in complete])
    for payload in (
        {"type": "turn.failed", "error": {"message": "authentication rejected"}},
        {"type": "item.completed", "item": {
            "type": "command_execution", "command": "cargo check",
            "aggregated_output": "compiler failed", "exit_code": 1, "status": "failed",
        }},
    ):
        failed = parse_codex_event(payload)
        assert all(e.type != "complete" for e in failed)
        if payload["type"] == "turn.failed":
            assert any(e.type == "error" and "authentication rejected" in e.content for e in failed)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_subprocess_environment_excludes_app_secrets_and_never_reads_dotenv(
    monkeypatch, tmp_path, provider,
):
    executor = _executor(provider)
    forbidden = {
        "SECRET_KEY", "DATABASE_URL", "RESEND_API_KEY", "LAUNCHER_TOKEN",
        "FAL_KEY", "GOOGLE_API_KEY", "XAI_API_KEY",
    }
    for key in forbidden:
        monkeypatch.setenv(key, f"private-{key}")
    (tmp_path / ".env").write_text("DOTENV_ONLY_SECRET=must-not-load\n")
    process = _Process(provider)
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    def guard(original):
        def guarded(file, *args, **kwargs):
            if isinstance(file, (str, bytes, Path)) and Path(file).name == ".env":
                pytest.fail("executor must not read a .env file")
            return original(file, *args, **kwargs)
        return guarded

    monkeypatch.setattr(builtins, "open", guard(builtins.open))
    monkeypatch.setattr(io, "open", guard(io.open))
    await _drain(executor.run_stage("skill body", "make a game", tmp_path, engine="bevy"))
    assert spawn.await_count == 1
    environment = spawn.call_args.kwargs["env"]
    assert forbidden.isdisjoint(environment)
    assert "DOTENV_ONLY_SECRET" not in environment
    assert environment.get("PATH"), "the child needs a usable toolchain PATH"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("mode", ["create", "modify"])
async def test_bevy_runs_in_game_directory_with_bevy_instructions(
    monkeypatch, tmp_path, provider, mode,
):
    executor = _executor(provider)
    spawn = AsyncMock(return_value=_Process(provider))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    await _drain(executor.run_stage(
        "Bevy skill body", "add a hopping fox", tmp_path, mode=mode, engine="bevy",
    ))
    assert spawn.await_count == 1
    assert Path(spawn.call_args.kwargs["cwd"]).resolve() == tmp_path.resolve()
    supplied = "\n".join(str(value) for value in spawn.call_args.args).lower()
    for guide in tmp_path.rglob("*.md"):
        supplied += "\n" + guide.read_text().lower()
    assert "bevy.md" in supplied
    assert "generate a godot game" not in supplied
    assert "godot/stage" not in supplied


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["godot", "bevy"])
@pytest.mark.parametrize("budget_cents", [0, 12345])
async def test_creation_agents_forward_zero_and_nonzero_budgets(
    tmp_path, engine, budget_cents,
):
    module = importlib.import_module(f"src.api.services.{engine}_creation_agent")
    prefix = "Godot" if engine == "godot" else "Bevy"
    request = getattr(module, f"{prefix}CreationRequest")(
        intent="make a hopping fox", budget_cents=budget_cents,
    )
    assert request.budget_cents == budget_cents
    calls = []
    executor = MagicMock()

    async def stage(*args, **kwargs):
        calls.append(kwargs)
        if False:
            yield

    executor.run_stage = stage
    service = MagicMock()
    service.read_skill.return_value = "skill body"
    service.export_html5 = AsyncMock(return_value=tmp_path / "dist")
    service.build_wasm.return_value = tmp_path / "dist"
    agent = getattr(module, f"{prefix}CreationAgent")(executor, service)
    await _drain(agent.create_game(request, tmp_path))
    assert calls, "creation must invoke its executor"
    assert all(call.get("engine") == engine for call in calls)
    assert all(call.get("budget_cents") == budget_cents for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("stop", ["timeout", "close", "cancel"])
async def test_deadline_and_interrupted_streams_kill_and_reap_child(
    monkeypatch, tmp_path, provider, stop,
):
    executor = _executor(provider, GAME_AGENT_TIMEOUT_SECONDS=1)
    process = _Process(provider, hanging=True)
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    stream = executor.run_stage("skill body", "make a game", tmp_path)
    if stop == "timeout":
        pending = asyncio.create_task(_drain(stream))
        done, _ = await asyncio.wait({pending}, timeout=2)
        if not done:
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass
            pytest.fail("the configured 1-second deadline was not enforced within 2 seconds")
        try:
            await pending
        except TimeoutError:
            pass
        assert process.kill.called, "the configured deadline must kill the child"
    elif stop == "close":
        await asyncio.wait_for(_until_child_output(stream), timeout=1)
        await asyncio.wait_for(stream.aclose(), timeout=1)
        assert process.kill.called, "closing an active stream must kill its child"
    else:
        await asyncio.wait_for(_until_child_output(stream), timeout=1)
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert process.kill.called, "cancelling an active stream must kill its child"
    assert process.wait.await_count > 0, "terminated children must be reaped"
    assert process.returncode is not None
