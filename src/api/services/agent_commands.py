"""The one place that builds Claude Code and Codex command lines.

The local executors and the Docker launcher both use these, so their flags
cannot drift apart. Model names are passed through untouched: a new model
works as soon as the installed CLI knows it, with no change here.
"""

from __future__ import annotations

# Blank means "use the CLI's default model". Brackets allow context-window
# suffixes such as "name[1m]". The value is passed as one argv item, never
# through a shell.
MODEL_PATTERN = r"^(?:[A-Za-z0-9][A-Za-z0-9_.:/\[\]-]*)?$"
MODEL_MAX_LENGTH = 100


def agent_model(settings, provider: str) -> str:
    """Model override for a provider; blank uses that CLI's default."""
    name = "CODEX_CLI_MODEL" if provider == "codex" else "CLAUDE_CLI_MODEL"
    return getattr(settings, name, "") or ""


def claude_flags(
    model: str = "",
    *,
    settings_path: str | None = None,
    skip_permissions: bool = False,
) -> list[str]:
    """Flags for `claude -p`. The caller adds the binary and the prompt."""
    flags = ["--output-format", "stream-json", "--verbose"]
    if skip_permissions:
        # Only for the disposable worker container, which is the sandbox.
        flags.append("--dangerously-skip-permissions")
    flags += [
        "--max-turns",
        "100",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
    ]
    if settings_path:
        flags += ["--settings", settings_path]
    if model:
        flags += ["--model", model]
    return flags


def codex_flags(model: str = "") -> list[str]:
    """Arguments after the codex binary, up to but not including the prompt."""
    flags = [
        "exec",
        "--json",
        "--sandbox",
        "workspace-write",
        "--ignore-user-config",
        "--disable",
        "hooks",
        "--ignore-rules",
        "--ephemeral",
        "--skip-git-repo-check",
    ]
    if model:
        flags += ["--model", model]
    return flags
