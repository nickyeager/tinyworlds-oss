"""Public provider factory for independent engine selection."""

from src.api.core.config import Settings
from src.api.services.godot_executor import GodotExecutor
from src.api.services.executors.cli_executor import CLIExecutor
from src.api.services.executors.codex_executor import CodexExecutor


def get_executor(settings: Settings) -> GodotExecutor:
    """Select Claude by default or Codex using GAME_AGENT_PROVIDER."""
    from src.api.services.personal_provider import resolve_personal_settings
    settings = resolve_personal_settings(settings)
    provider = getattr(settings, "GAME_AGENT_PROVIDER", "claude")
    if provider == "codex":
        return CodexExecutor(settings)
    if provider == "claude":
        return CLIExecutor(settings)
    raise ValueError(f"Unsupported game agent provider: {provider}")


__all__ = ["get_executor", "CLIExecutor", "CodexExecutor"]
