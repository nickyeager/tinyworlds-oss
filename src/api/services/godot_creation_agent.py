"""Godot game creation agent — orchestrates the full godogen pipeline."""
import asyncio
import json
import logging
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional, Dict, List

from src.api.observability.events import (
    BaseEvent, StatusEvent, CompletionEvent, ErrorEvent, EventLevel, CLIStreamEvent
)
from src.api.services.game_access import ensure_no_symlinks
from src.api.services.mobile_support import append_mobile_controls_requirement

logger = logging.getLogger(__name__)


_LESSONS_PREAMBLE = """

--- Project Lessons ---
Before starting each godogen stage, read the matching lessons file from
`.claude/skills/local/godogen-lessons/` (relative to the repo root) and apply
any guidance present. Files may be empty (just a placeholder comment) — that's
fine, proceed normally. If a lesson contradicts the upstream skill, the lesson
wins (it was written from a real failure on this project).

| Stage | Lessons file |
|-------|--------------|
| decomposer / scaffold / asset-planner | godogen-lessons/scaffold.md |
| task-execution (writing scripts) | godogen-lessons/scripts.md |
| scene-generation | godogen-lessons/scenes.md |
| asset-gen / rembg | godogen-lessons/assets.md |
| capture / final result bundle | godogen-lessons/capture.md |
| any stage (cross-cutting build/export/quirks) | godogen-lessons/general.md |
| runtime / play-time issues (telemetry, freeze, no-input) | godogen-lessons/playthrough.md |
"""


class _CreationLog:
    """Append-only per-game creation log written to {game_path}/.creation/.

    Captures every event emitted during creation so failures can be diagnosed
    after the SSE stream has closed. Always writes a summary.json on close,
    even if the pipeline raised.
    """

    def __init__(self, game_path: Path):
        self.dir = game_path / ".creation"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.dir / "events.jsonl"
        self.summary_file = self.dir / "summary.json"
        self.started_at = datetime.now(timezone.utc)
        self._start_perf = time.perf_counter()
        self._fp = self.events_file.open("a", encoding="utf-8")
        self._has_error = False
        self._last_message: Optional[str] = None
        self._total_cost_usd: float = 0.0
        self._event_count = 0

    def write(self, event: BaseEvent) -> None:
        try:
            data = event.to_sse_dict()
        except Exception:
            return
        try:
            self._fp.write(json.dumps(data, default=str) + "\n")
            self._fp.flush()
        except Exception as e:
            logger.warning("Failed to write creation event: %s", e)
            return
        self._event_count += 1
        if data.get("event_type") == "ErrorEvent" or (data.get("event_type") == "CLIStreamEvent" and data.get("stream_type") == "error"):
            self._has_error = True
        msg = data.get("message") or data.get("content")
        if msg:
            self._last_message = msg
        cost = data.get("cost_usd")
        if isinstance(cost, (int, float)):
            self._total_cost_usd += float(cost)

    def close(self, *, has_export: bool, has_video: bool, exception: Optional[BaseException] = None) -> None:
        try:
            self._fp.close()
        except Exception:
            pass

        ended_at = datetime.now(timezone.utc)
        duration = time.perf_counter() - self._start_perf

        if exception is not None:
            status = "crashed"
            error = f"{type(exception).__name__}: {exception}"
        elif self._has_error:
            status = "failed"
            error = self._last_message
        elif has_export or has_video:
            status = "success"
            error = None
        else:
            status = "partial"
            error = "Pipeline finished without producing an export or presentation video"

        summary = {
            "started_at": self.started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_seconds": round(duration, 2),
            "status": status,
            "error": error,
            "final_message": self._last_message,
            "event_count": self._event_count,
            "total_cost_usd": round(self._total_cost_usd, 4),
            "has_export": has_export,
            "has_video": has_video,
        }
        try:
            self.summary_file.write_text(json.dumps(summary, indent=2))
        except Exception as e:
            logger.warning("Failed to write creation summary: %s", e)


@dataclass
class GodotCreationRequest:
    intent: str
    budget_cents: Optional[int] = None


@dataclass
class TaskInfo:
    number: int
    name: str
    status: str
    depends_on: List[int]
    block: str  # Full markdown block


class GodotCreationAgent:
    """Orchestrates the godogen pipeline: visual-target → decompose → scaffold → tasks."""

    SERVICE_NAME = "godot_creation_agent"

    def __init__(self, executor, game_service):
        """
        Args:
            executor: GodotExecutor (CLI or SDK)
            game_service: GodotGameService
        """
        self.executor = executor
        self.game_service = game_service

    @staticmethod
    def _promote_capture_artifacts(game_path: Path) -> None:
        """Copy the latest ``screenshots/result/{N}/`` proof artifacts up to
        ``screenshots/presentation/``.

        The godogen capture skill writes frames + ``video.mp4`` (and sometimes
        ``gameplay.mp4`` / ``gameplay.png``) into numbered ``screenshots/result/{N}/``
        run directories. The TinyWorlds API and creation summary check a single
        canonical ``screenshots/presentation/gameplay.mp4`` location — this
        helper bridges the gap so successful captures aren't reported as
        ``status=partial`` just because the artifacts weren't promoted.

        For the still thumbnail we also fall back to the newest ``frame*.png``
        in the latest result dir if no ``gameplay.png`` was emitted.

        Best-effort: if no result directories exist, no-ops. Failures are
        logged and swallowed — promotion must never crash creation.
        """
        try:
            result_root = game_path / "screenshots" / "result"
            if not result_root.exists() or not result_root.is_dir():
                logger.info(
                    "No screenshots/result/ directory at %s — skipping capture promotion",
                    game_path,
                )
                return

            numbered = [
                (int(entry.name), entry)
                for entry in result_root.iterdir()
                if entry.is_dir() and entry.name.isdigit()
            ]
            if not numbered:
                logger.info(
                    "screenshots/result/ at %s has no numbered subdirectories — skipping",
                    game_path,
                )
                return

            numbered.sort(key=lambda t: t[0])
            _, latest = numbered[-1]

            presentation = game_path / "screenshots" / "presentation"

            video_src = latest / "gameplay.mp4"
            if not video_src.exists():
                # godogen capture also emits the encoded video as video.mp4
                alt = latest / "video.mp4"
                if alt.exists():
                    video_src = alt
            if video_src.exists():
                presentation.mkdir(parents=True, exist_ok=True)
                shutil.copy2(video_src, presentation / "gameplay.mp4")
                logger.info("Promoted %s -> %s/gameplay.mp4", video_src, presentation)

            png_src = latest / "gameplay.png"
            if not png_src.exists():
                frames = sorted(latest.glob("frame*.png"))
                if frames:
                    png_src = frames[-1]
            if png_src.exists():
                presentation.mkdir(parents=True, exist_ok=True)
                shutil.copy2(png_src, presentation / "gameplay.png")
                logger.info("Promoted %s -> %s/gameplay.png", png_src, presentation)
        except Exception as e:  # noqa: BLE001 — best-effort, never raise
            logger.warning("Capture artifact promotion failed: %s", e)

    # Auto-retry thresholds for "zero-cost partial" — the signature of an
    # Anthropic-side early-stop where the agent emits a `result` event without
    # running the pipeline. See docs/debug or /debug-prod-game runbook.
    _RETRY_MAX_COST_USD = 0.05
    _RETRY_MAX_DURATION_S = 120.0

    async def create_game(
        self,
        request: GodotCreationRequest,
        game_path: Path,
    ) -> AsyncIterator[BaseEvent]:
        """Run the godogen pipeline, with one auto-retry on zero-cost partial.

        First attempt runs the full pipeline. If it ends with no export, no
        video, no error, ~$0 cost, and < 2 min duration, that's the signature
        of an Anthropic-side early-stop (agent emitted `result` without doing
        the work). We retry once inline before giving up.
        """
        async for event in self._run_creation_attempt(request, game_path):
            yield event

        if not self._should_auto_retry(game_path):
            return

        summary = self._read_summary(game_path) or {}
        logger.warning(
            "Auto-retrying %s after zero-cost partial (cost=$%.4f duration=%.1fs)",
            game_path.name,
            summary.get("total_cost_usd", 0.0),
            summary.get("duration_seconds", 0.0),
        )
        yield CLIStreamEvent(
            service=self.SERVICE_NAME,
            stream_type="status",
            content=(
                f"First attempt ended early "
                f"(cost=${summary.get('total_cost_usd', 0.0):.2f}, "
                f"{summary.get('duration_seconds', 0.0):.0f}s, no artifacts). "
                "Auto-retrying once."
            ),
        )
        async for event in self._run_creation_attempt(request, game_path):
            yield event

    def _read_summary(self, game_path: Path) -> Optional[dict]:
        try:
            return json.loads((game_path / ".creation" / "summary.json").read_text())
        except Exception:
            return None

    def _should_auto_retry(self, game_path: Path) -> bool:
        summary = self._read_summary(game_path)
        if not summary:
            return False
        if summary.get("status") != "partial":
            return False
        if summary.get("has_export") or summary.get("has_video"):
            return False
        cost = summary.get("total_cost_usd")
        duration = summary.get("duration_seconds")
        if not isinstance(cost, (int, float)) or not isinstance(duration, (int, float)):
            return False
        return cost <= self._RETRY_MAX_COST_USD and duration <= self._RETRY_MAX_DURATION_S

    async def _run_creation_attempt(
        self,
        request: GodotCreationRequest,
        game_path: Path,
    ) -> AsyncIterator[BaseEvent]:
        """One pass of the godogen pipeline via a single Claude Code invocation.

        Every event is also persisted to {game_path}/.creation/events.jsonl
        and a summary.json is written on exit, so failures remain diagnosable
        after the SSE stream closes. On retry, events.jsonl appends and
        summary.json overwrites with the latest attempt's outcome.
        """
        creation_log = _CreationLog(game_path)
        dist_path: Optional[Path] = None
        crash: Optional[BaseException] = None

        def _emit(event: BaseEvent) -> BaseEvent:
            creation_log.write(event)
            return event

        try:
            yield _emit(StatusEvent(
                service=self.SERVICE_NAME,
                message="Starting game generation...",
                step="pipeline",
                status="started",
            ))

            skill_content = self.game_service.read_skill("SKILL.md")
            skill_content += _LESSONS_PREAMBLE

            user_prompt = append_mobile_controls_requirement(request.intent)

            # Pre-create .capture/run_godot + .capture/env so the capture skill
            # never silently no-ops on a missing wrapper (lesson:
            # godogen-lessons/capture.md — ~50% skip rate when Setup was deferred).
            self.game_service.ensure_capture_wrapper(game_path)

            async for event in self.executor.run_stage(
                skill_content,
                user_prompt,
                game_path,
                engine="godot",
                budget_cents=request.budget_cents,
            ):
                if event.type == "thinking":
                    yield _emit(CLIStreamEvent(
                        service=self.SERVICE_NAME,
                        stream_type="thinking",
                        content=event.content,
                    ))
                elif event.type == "tool_use":
                    yield _emit(CLIStreamEvent(
                        service=self.SERVICE_NAME,
                        stream_type="tool_use",
                        tool_name=event.content,
                        tool_input=event.metadata.get("input", {}) if event.metadata else {},
                    ))
                elif event.type == "tool_result":
                    yield _emit(CLIStreamEvent(
                        service=self.SERVICE_NAME,
                        stream_type="tool_result",
                        content=event.content,
                        tool_input={"tool_use_id": event.metadata.get("tool_use_id", "")} if event.metadata else {},
                    ))
                elif event.type == "error":
                    yield _emit(CLIStreamEvent(
                        service=self.SERVICE_NAME,
                        stream_type="error",
                        content=event.content,
                    ))
                elif event.type == "complete":
                    yield _emit(CLIStreamEvent(
                        service=self.SERVICE_NAME,
                        stream_type="complete",
                        content=event.content,
                        cost_usd=event.metadata.get("cost_usd") if event.metadata else None,
                    ))
                elif event.type == "status":
                    yield _emit(CLIStreamEvent(
                        service=self.SERVICE_NAME,
                        stream_type="status",
                        content=event.content,
                    ))

            ensure_no_symlinks(game_path)
            yield _emit(StatusEvent(
                service=self.SERVICE_NAME,
                message="Exporting to browser...",
                step="export",
                status="started",
            ))
            dist_path = await self.game_service.export_html5(game_path)
            if dist_path:
                yield _emit(StatusEvent(
                    service=self.SERVICE_NAME,
                    message="Browser export complete!",
                    step="export",
                    status="completed",
                ))
            else:
                yield _emit(StatusEvent(
                    service=self.SERVICE_NAME,
                    message="Browser export failed — video fallback available",
                    step="export",
                    status="completed",
                ))

            # Promote any screenshots/result/{N}/ artifacts to the canonical
            # presentation/ location before checking has_video.
            self._promote_capture_artifacts(game_path)

            has_export = dist_path is not None
            video_path = game_path / "screenshots" / "presentation" / "gameplay.mp4"
            has_video = video_path.exists()

            if has_export:
                yield _emit(CompletionEvent(
                    service=self.SERVICE_NAME,
                    message="Game ready to play in browser!",
                    result_path=str(dist_path / "index.html"),
                ))
            elif has_video:
                yield _emit(CompletionEvent(
                    service=self.SERVICE_NAME,
                    message="Game complete with presentation video!",
                    result_path=str(video_path),
                ))
            else:
                yield _emit(CompletionEvent(
                    service=self.SERVICE_NAME,
                    message="Game generation complete!",
                    result_path=str(game_path),
                ))

        except Exception as e:
            crash = e
            logger.exception("Game creation failed")
            yield _emit(ErrorEvent(
                service=self.SERVICE_NAME,
                error_message=str(e),
                suggestion="Check .creation/events.jsonl for details",
            ))
        finally:
            self._promote_capture_artifacts(game_path)
            video_path = game_path / "screenshots" / "presentation" / "gameplay.mp4"
            creation_log.close(
                has_export=dist_path is not None,
                has_video=video_path.exists(),
                exception=crash,
            )

    async def attempt_fix(
        self,
        game_path: Path,
        failures: List[str],
        *,
        budget_cents: Optional[int] = None,
    ) -> AsyncIterator[BaseEvent]:
        """Run a single self-correction pass after verify_playable rejects.

        Sends Claude back to the same project with the failure list as the
        instruction. Re-exports HTML5 at the end. Caller is expected to
        re-run verify_playable after consuming this generator.

        Mirrors the upstream "rembg --preview QA" pattern (htdt/godogen
        915e7ad): give the agent an artifact it can self-check against.
        Here the artifact is the failure list from verify_playable.

        Events stream into the SAME .creation/ log directory (events.jsonl
        appends, summary.json overwrites with the final outcome).
        """
        creation_log = _CreationLog(game_path)
        crash: Optional[BaseException] = None
        dist_path: Optional[Path] = None

        def _emit(event: BaseEvent) -> BaseEvent:
            creation_log.write(event)
            return event

        failures_block = "\n".join(f"- {f}" for f in failures)
        fix_instruction = (
            "The previous generation pass produced a project that failed playability "
            "verification with these specific issues:\n\n"
            f"{failures_block}\n\n"
            "Fix all of them in this same project directory. Edit existing files in "
            "place — do NOT delete the project and start over. After fixes, re-run "
            "`godot --headless --import` if assets/scripts changed. Only declare "
            "complete when these specific issues are resolved on disk: the next "
            "verify_playable check will repeat the same assertions."
        )
        fix_instruction = append_mobile_controls_requirement(fix_instruction)

        try:
            yield _emit(StatusEvent(
                service=self.SERVICE_NAME,
                message=f"Retrying after {len(failures)} verification failure(s)...",
                step="retry",
                status="started",
            ))

            skill_content = self.game_service.read_skill("SKILL.md")
            skill_content += _LESSONS_PREAMBLE

            self.game_service.ensure_capture_wrapper(game_path)

            async for event in self.executor.run_stage(
                skill_content,
                fix_instruction,
                game_path,
                engine="godot",
                budget_cents=budget_cents,
            ):
                if event.type == "thinking":
                    yield _emit(CLIStreamEvent(
                        service=self.SERVICE_NAME,
                        stream_type="thinking",
                        content=event.content,
                    ))
                elif event.type == "tool_use":
                    yield _emit(CLIStreamEvent(
                        service=self.SERVICE_NAME,
                        stream_type="tool_use",
                        tool_name=event.content,
                        tool_input=event.metadata.get("input", {}) if event.metadata else {},
                    ))
                elif event.type == "tool_result":
                    yield _emit(CLIStreamEvent(
                        service=self.SERVICE_NAME,
                        stream_type="tool_result",
                        content=event.content,
                        tool_input={"tool_use_id": event.metadata.get("tool_use_id", "")} if event.metadata else {},
                    ))
                elif event.type == "error":
                    yield _emit(CLIStreamEvent(
                        service=self.SERVICE_NAME,
                        stream_type="error",
                        content=event.content,
                    ))
                elif event.type == "complete":
                    yield _emit(CLIStreamEvent(
                        service=self.SERVICE_NAME,
                        stream_type="complete",
                        content=event.content,
                        cost_usd=event.metadata.get("cost_usd") if event.metadata else None,
                    ))
                elif event.type == "status":
                    yield _emit(CLIStreamEvent(
                        service=self.SERVICE_NAME,
                        stream_type="status",
                        content=event.content,
                    ))

            # Re-export — the fix likely changed scenes/scripts
            yield _emit(StatusEvent(
                service=self.SERVICE_NAME,
                message="Re-exporting to browser after fix...",
                step="export",
                status="started",
            ))
            try:
                dist_path = await self.game_service.export_html5(game_path)
                yield _emit(StatusEvent(
                    service=self.SERVICE_NAME,
                    message="Re-export complete" if dist_path else "Re-export failed",
                    step="export",
                    status="completed",
                ))
            except Exception as exc:  # noqa: BLE001 — log and continue; route will re-verify
                logger.exception("Re-export failed during fix attempt")
                yield _emit(ErrorEvent(
                    service=self.SERVICE_NAME,
                    error_message=f"Re-export failed: {exc}",
                    suggestion="Check .creation/events.jsonl",
                ))
        except Exception as e:
            crash = e
            logger.exception("Fix attempt failed")
            yield _emit(ErrorEvent(
                service=self.SERVICE_NAME,
                error_message=str(e),
                suggestion="Check .creation/events.jsonl for details",
            ))
        finally:
            self._promote_capture_artifacts(game_path)
            video_path = game_path / "screenshots" / "presentation" / "gameplay.mp4"
            creation_log.close(
                has_export=dist_path is not None,
                has_video=video_path.exists(),
                exception=crash,
            )

    def _parse_tasks(self, plan_md: str) -> List[TaskInfo]:
        """Parse PLAN.md into task list."""
        tasks = []
        # Split on ## N. pattern
        task_pattern = re.compile(r'^## (\d+)\. (.+)$', re.MULTILINE)
        matches = list(task_pattern.finditer(plan_md))

        for i, match in enumerate(matches):
            number = int(match.group(1))
            name = match.group(2).strip()

            # Extract block (from this header to next header or end)
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(plan_md)
            block = plan_md[start:end].strip()

            # Parse status — handle "done (partial)" as a single value
            status_match = re.search(r'\*\*Status:\*\*\s*(\S+(?:\s*\([^)]*\))?)', block)
            status = status_match.group(1) if status_match else "pending"

            # Parse depends
            deps_match = re.search(r'\*\*Depends on:\*\*\s*(.+)', block)
            depends_on = []
            if deps_match:
                deps_str = deps_match.group(1).strip()
                if deps_str != "(none)":
                    depends_on = [int(d.strip()) for d in deps_str.split(",") if d.strip().isdigit()]

            tasks.append(TaskInfo(
                number=number,
                name=name,
                status=status,
                depends_on=depends_on,
                block=block,
            ))

        return tasks

    def _deps_met(self, task: TaskInfo, all_tasks: List[TaskInfo]) -> bool:
        """Check if all dependencies are done."""
        for dep_num in task.depends_on:
            dep_task = next((t for t in all_tasks if t.number == dep_num), None)
            if dep_task and dep_task.status not in ("done", "done (partial)", "skipped"):
                return False
        return True

    def _update_task_status(self, game_path: Path, task_number: int, new_status: str):
        """Update a task's status in PLAN.md. Inserts Status line if missing."""
        plan_path = game_path / "PLAN.md"
        if not plan_path.exists():
            return
        content = plan_path.read_text()

        # Try to update existing Status field
        update_pattern = re.compile(
            rf'(## {task_number}\..+?\n-\s*\*\*Status:\*\*\s*)(\S+(?:\s*\([^)]*\))?)',
            re.DOTALL
        )
        updated, count = update_pattern.subn(rf'\g<1>{new_status}', content)

        if count > 0:
            plan_path.write_text(updated)
            return

        # No Status field found — insert one after the task header
        insert_pattern = re.compile(
            rf'(## {task_number}\.[^\n]*\n)',
        )
        match = insert_pattern.search(content)
        if match:
            insert_pos = match.end()
            content = content[:insert_pos] + f"- **Status:** {new_status}\n" + content[insert_pos:]
            plan_path.write_text(content)
