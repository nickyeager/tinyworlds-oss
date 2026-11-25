"""Godot game modification service — handles voice/text modifications."""
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional, List

from src.api.services.failure_log import record_failure
from src.api.services.mobile_support import append_mobile_controls_requirement
from src.api.services.runtime_diagnostics import build_runtime_diagnostics
from src.api.services.suggestions_generator import generate_suggestions
from src.api.services.touch_input_lint import lint_touch_handlers

logger = logging.getLogger(__name__)


@dataclass
class GodotModificationRequest:
    instruction: str
    game_path: Path


@dataclass
class GodotModificationResult:
    success: bool
    changes: List[str]
    explanation: str
    error: Optional[str] = None


@dataclass
class GodotModificationProgress:
    type: str  # thinking, tool_use, tool_result, text, complete, error
    content: str
    metadata: Optional[dict] = None


class GodotModificationService:
    """Handle iterative modifications to Godot games via CLI agent."""

    def __init__(self, executor, game_service):
        self.executor = executor
        self.game_service = game_service

    async def modify_game(
        self, request: GodotModificationRequest
    ) -> AsyncIterator[GodotModificationProgress]:
        """Run modification via CLI agent with full context."""
        yield GodotModificationProgress(type="thinking", content="Using agent for modification...")

        context = {}
        for name in ["STRUCTURE.md", "MEMORY.md", "PLAN.md"]:
            content = self.game_service.read_artifact(request.game_path, name)
            if content:
                context[name] = content
        runtime_diagnostics = build_runtime_diagnostics(
            request.game_path,
            game_id=request.game_path.name,
            engine="godot",
        )
        if runtime_diagnostics:
            context["RUNTIME_DIAGNOSTICS.md"] = runtime_diagnostics

        # Track the latest screenshot before modification starts
        screenshots_dir = request.game_path / "screenshots"
        pre_screenshots = set()
        if screenshots_dir.exists():
            pre_screenshots = set(screenshots_dir.glob("*.png"))

        self.game_service.ensure_capture_wrapper(request.game_path)

        async for event in self.executor.run_stage(
            "",  # Edit constraints live in the runtime manifest.
            append_mobile_controls_requirement(request.instruction),
            request.game_path,
            context_files=context,
            mode="modify",
            engine="godot",
            budget_cents=getattr(request, "budget_cents", None),
        ):
            yield GodotModificationProgress(
                type=event.type,
                content=event.content,
                metadata=event.metadata,
            )

        # Re-export to HTML5 so the browser embed reflects the changes
        yield GodotModificationProgress(
            type="status",
            content="Re-exporting to browser...",
        )
        # Advisory touch-input lint after modify. The user may have explicitly
        # asked for desktop-only changes, so we record + warn rather than block.
        touch_failures = lint_touch_handlers(request.game_path, "godot")
        for f in touch_failures:
            logger.warning("post-modify lint: %s", f.as_message())
            record_failure(
                game_id=request.game_path.name,
                engine="godot",
                stage="modify",
                rule=f.rule,
                detail=f.detail,
                file=f.file,
            )
            yield GodotModificationProgress(
                type="status",
                content=f"Warning: {f.detail}",
                metadata={"lint_rule": f.rule},
            )

        dist_path = await self.game_service.export_html5(request.game_path)
        if dist_path:
            yield GodotModificationProgress(
                type="status",
                content="Browser export complete — game updated",
                metadata={"export_status": "success", "dist_path": str(dist_path)},
            )
            # Fire-and-forget: refresh suggestions sidecar after a successful modify.
            asyncio.create_task(  # noqa: RUF006 — intentional fire-and-forget
                generate_suggestions(request.game_path, "godot", executor=self.executor)
            )
        else:
            yield GodotModificationProgress(
                type="status",
                content="Browser export failed — source files were still modified",
                metadata={"export_status": "failed"},
            )

        # After modification, check for new screenshots and emit them
        if screenshots_dir.exists():
            post_screenshots = sorted(
                screenshots_dir.glob("*.png"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            new_screenshots = [s for s in post_screenshots if s not in pre_screenshots]
            if new_screenshots:
                for ss in new_screenshots[:3]:
                    yield GodotModificationProgress(
                        type="tool_result",
                        content=f"Screenshot captured: {ss.name}",
                        metadata={"screenshot": str(ss)},
                    )
            elif post_screenshots:
                # No new screenshots but existing ones — emit the latest
                yield GodotModificationProgress(
                    type="tool_result",
                    content=f"Screenshot available: {post_screenshots[0].name}",
                    metadata={"screenshot": str(post_screenshots[0])},
                )
