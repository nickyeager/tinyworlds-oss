"""Command lines for Claude Code and Codex, local and in the worker."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.api import sidecar_launcher as launcher
from src.api.core.config import Settings
from src.api.services.agent_commands import agent_model, claude_flags, codex_flags
from src.api.services.executors.cli_executor import CLIExecutor
from src.api.services.executors.codex_executor import CodexExecutor


def _worker_argv(provider: str, model: str = "") -> list[str]:
    request = launcher.AgentRunRequest(
        provider=provider, prompt="make a game", game_path="/games/godot-abc", model=model
    )
    argv = launcher.agent_run_argv(request, Path("/games/godot-abc"), "job", "token")
    return argv[argv.index(launcher.AGENT_WORKER_IMAGE) + 1 :]


def test_blank_model_adds_no_model_flag():
    assert "--model" not in claude_flags()
    assert "--model" not in codex_flags()


@pytest.mark.parametrize(
    "model", ["opus", "claude-fable-5-2", "claude-opus-5-5[1m]", "gpt-5.5-codex", "o4-mini"]
)
def test_any_model_name_is_passed_through(model):
    assert claude_flags(model)[-2:] == ["--model", model]
    assert codex_flags(model)[-2:] == ["--model", model]
    assert _worker_argv("claude", model)[-4:] == ["--model", model, "--", "make a game"]
    assert _worker_argv("codex", model)[-4:] == ["--model", model, "--", "make a game"]


@pytest.mark.parametrize("model", ["--yolo", "a b", "x;rm", "-m", "a" * 101])
def test_worker_rejects_model_names_that_look_like_flags(model):
    with pytest.raises(ValidationError):
        launcher.AgentRunRequest(
            provider="claude", prompt="p", game_path="/games/godot-abc", model=model
        )


def test_each_provider_reads_its_own_model_setting():
    settings = Settings(CLAUDE_CLI_MODEL="claude-fable-5-2", CODEX_CLI_MODEL="gpt-5.5-codex")
    assert agent_model(settings, "claude") == "claude-fable-5-2"
    assert agent_model(settings, "codex") == "gpt-5.5-codex"
    assert CLIExecutor(settings)._command("p")[-2:] == ["--model", "claude-fable-5-2"]
    assert CodexExecutor(settings)._command("p")[-3:] == ["--model", "gpt-5.5-codex", "p"]


def test_local_and_worker_use_the_same_flags():
    settings = Settings(CLAUDE_CLI_MODEL="", CODEX_CLI_MODEL="")
    assert CodexExecutor(settings)._command("p")[1:-1] == _worker_argv("codex")[1:-2]
    local = CLIExecutor(settings)._command("p")[3:]
    worker = [flag for flag in _worker_argv("claude")[2:-2] if flag != "--dangerously-skip-permissions"]
    assert local == worker
