"""Abstract base class for Godot pipeline stage executors.

Defines the common interface used by both CLI and SDK execution modes.
The executor handles *how* the LLM runs; the service handles *what* to ask.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional


@dataclass
class ExecutorResult:
    """Result from a completed pipeline stage execution.

    Attributes:
        success: Whether the stage completed without errors
        output_files: Files created or modified during the stage
        stdout: Combined stdout output from the execution
        errors: List of error messages encountered
        cost_usd: Estimated API cost in USD (None for CLI mode)
    """

    success: bool
    output_files: List[str] = field(default_factory=list)
    stdout: str = ""
    errors: List[str] = field(default_factory=list)
    cost_usd: Optional[float] = None


@dataclass
class ExecutorEvent:
    """A streaming event emitted during pipeline stage execution.

    Attributes:
        type: Event type — one of "status", "file_changed", "thinking",
              "tool_use", "error", "complete"
        content: Human-readable event content or data
        metadata: Optional structured metadata (e.g., exit_code, file_path)
    """

    type: str
    content: str = ""
    metadata: Optional[Dict] = None


class GodotExecutor(ABC):
    """Abstract base class for running a Godot pipeline stage with an LLM.

    Both CLIExecutor (subprocess) and SDKExecutor (direct API) implement
    this interface so the GodotCreationAgent can be executor-agnostic.
    """

    @abstractmethod
    async def run_stage(
        self,
        skill_content: str,
        user_prompt: str,
        game_path: Path,
        image_paths: Optional[List[str]] = None,
        context_files: Optional[Dict[str, str]] = None,
        mode: str = "create",
        *,
        engine: str = "godot",
        budget_cents: Optional[int] = None,
    ) -> AsyncIterator[ExecutorEvent]:
        """Run a pipeline stage, yielding events as they occur.

        Args:
            skill_content: The skill .md file content used as the system prompt.
            user_prompt: The user-facing instruction for this stage.
            game_path: Working directory for the game project.
            image_paths: Optional list of image filenames relative to game_path
                         (e.g., ["reference.png"]).
            context_files: Optional mapping of filename → content for extra
                           context injected into the prompt (e.g., PLAN.md).
            mode: "create" for new games, "modify" for modifying existing games.

        Yields:
            ExecutorEvent instances. The final event always has type="complete".
        """

    @abstractmethod
    async def run_stage_sync(
        self,
        skill_content: str,
        user_prompt: str,
        game_path: Path,
        image_paths: Optional[List[str]] = None,
        context_files: Optional[Dict[str, str]] = None,
        mode: str = "create",
        *,
        engine: str = "godot",
        budget_cents: Optional[int] = None,
    ) -> ExecutorResult:
        """Run a pipeline stage synchronously, collecting all events.

        Convenience wrapper over run_stage() for callers that do not need
        streaming progress updates.

        Args:
            skill_content: The skill .md file content used as the system prompt.
            user_prompt: The user-facing instruction for this stage.
            game_path: Working directory for the game project.
            image_paths: Optional list of image filenames relative to game_path.
            context_files: Optional mapping of filename → content for context.

        Returns:
            ExecutorResult summarising the completed stage.
        """
