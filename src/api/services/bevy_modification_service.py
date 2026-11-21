"""Bevy game modification service — handles voice/text modifications.

Structural mirror of :mod:`src.api.services.godot_modification_service`. The
key difference: rebuild goes through :class:`BevyBuilder` (docker), not Godot's
in-process headless export. A failed rebuild surfaces as a status message but
does not raise — the source files are still modified, matching the Godot
service's behaviour.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, List, Optional

from src.api.services.failure_log import record_failure
from src.api.services.mobile_support import append_mobile_controls_requirement
from src.api.services.runtime_diagnostics import build_runtime_diagnostics
from src.api.services.touch_input_lint import lint_touch_handlers

logger = logging.getLogger(__name__)


@dataclass
class BevyModificationRequest:
    instruction: str
    game_path: Path


@dataclass
class BevyModificationResult:
    success: bool
    changes: List[str]
    explanation: str
    error: Optional[str] = None


@dataclass
class BevyModificationProgress:
    type: str  # thinking, tool_use, tool_result, text, complete, error, status
    content: str
    metadata: Optional[dict] = None


class BevyModificationService:
    """Handle iterative modifications to Bevy games via the CLI agent."""

    def __init__(self, executor, game_service):
        self.executor = executor
        self.game_service = game_service

    async def modify_game(
        self, request: BevyModificationRequest
    ) -> AsyncIterator[BevyModificationProgress]:
        """Run modification via CLI agent with full context."""
        yield BevyModificationProgress(
            type="thinking", content="Using agent for modification..."
        )

        context: dict[str, str] = {}
        for name in ["STRUCTURE.md", "MEMORY.md", "PLAN.md"]:
            content = self.game_service.read_artifact(request.game_path, name)
            if content:
                context[name] = content
        runtime_diagnostics = build_runtime_diagnostics(
            request.game_path,
            game_id=request.game_path.name,
            engine="bevy",
        )
        if runtime_diagnostics:
            context["RUNTIME_DIAGNOSTICS.md"] = runtime_diagnostics

        # bevy-modify is a TinyWorlds-only skill, not part of the synced
        # godogen subtree.
        modify_skill_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / ".claude" / "skills" / "local" / "bevy-modify" / "SKILL.md"
        )
        try:
            skill = modify_skill_path.read_text()
        except FileNotFoundError:
            skill = ""

        screenshots_dir = request.game_path / "screenshots"
        pre_screenshots = set()
        if screenshots_dir.exists():
            pre_screenshots = set(screenshots_dir.glob("*.png"))

        async for event in self.executor.run_stage(
            skill,
            append_mobile_controls_requirement(request.instruction),
            request.game_path,
            context_files=context,
            mode="modify",
            engine="bevy",
            budget_cents=getattr(request, "budget_cents", None),
        ):
            yield BevyModificationProgress(
                type=event.type,
                content=event.content,
                metadata=event.metadata,
            )

        # Advisory touch-input lint after modify.
        touch_failures = lint_touch_handlers(request.game_path, "bevy")
        for f in touch_failures:
            logger.warning("post-modify lint: %s", f.as_message())
            record_failure(
                game_id=request.game_path.name,
                engine="bevy",
                stage="modify",
                rule=f.rule,
                detail=f.detail,
                file=f.file,
            )
            yield BevyModificationProgress(
                type="status",
                content=f"Warning: {f.detail}",
                metadata={"lint_rule": f.rule},
            )

        # Rebuild WASM so /play reflects the changes. The host has no rust
        # toolchain — this goes through the bevy-builder docker image.
        yield BevyModificationProgress(
            type="status",
            content="Rebuilding WebAssembly bundle...",
        )
        try:
            build = asyncio.create_task(asyncio.to_thread(self.game_service.build_wasm, request.game_path))
            try:
                await asyncio.shield(build)
            except asyncio.CancelledError:
                # The launcher call runs in a thread and cannot be cancelled by
                # cancelling this task. Drain it before releasing the per-game
                # lock so a later edit cannot race its writes.
                try:
                    await build
                except Exception:
                    logger.exception("Bevy build failed while stopping %s", request.game_path)
                raise
            yield BevyModificationProgress(
                type="status",
                content="WASM rebuild complete — game updated",
                metadata={"rebuild_status": "success"},
            )
        except Exception as exc:  # builder errors surface as RuntimeError, etc.
            logger.exception("Bevy rebuild failed for %s", request.game_path)
            yield BevyModificationProgress(
                type="status",
                content=f"WASM rebuild failed — source files were still modified ({exc})",
                metadata={"rebuild_status": "failed", "error": str(exc)},
            )

        if screenshots_dir.exists():
            post_screenshots = sorted(
                screenshots_dir.glob("*.png"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            new_screenshots = [s for s in post_screenshots if s not in pre_screenshots]
            if new_screenshots:
                for ss in new_screenshots[:3]:
                    yield BevyModificationProgress(
                        type="tool_result",
                        content=f"Screenshot captured: {ss.name}",
                        metadata={"screenshot": str(ss)},
                    )
            elif post_screenshots:
                yield BevyModificationProgress(
                    type="tool_result",
                    content=f"Screenshot available: {post_screenshots[0].name}",
                    metadata={"screenshot": str(post_screenshots[0])},
                )
