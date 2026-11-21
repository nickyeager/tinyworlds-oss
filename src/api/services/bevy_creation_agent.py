"""Bevy game creation agent — orchestrates the full godogen pipeline for Bevy.

Structural mirror of :mod:`src.api.services.godot_creation_agent`. The May 6
Bevy support plan (Workstream 4) explicitly accepts the duplication for v1
rather than introducing a base class — engines diverge in too many small
ways for a premature abstraction to pay off. Differences vs the Godot agent:

- No project-lessons preamble (Bevy has no lessons file in v1).
- Skill loading reads ``SKILL.md`` directly (no ``../godogen/SKILL.md``
  fallback — that was Godot-historical).
- Build step delegates to the synchronous ``BevyGameService.build_wasm``
  via ``asyncio.to_thread`` so the SSE loop stays free.
- Adds ``_promote_capture_artifacts`` to copy
  ``screenshots/result/{N}/gameplay.{mp4,png}`` (where Bevy's upstream
  capture skill writes proof artifacts) into ``screenshots/presentation/``,
  satisfying the contract documented on
  :meth:`BevyGameService.screenshot_path` / ``video_path``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional, List

from src.api.observability.events import (
    BaseEvent, StatusEvent, CompletionEvent, ErrorEvent, CLIStreamEvent
)
from src.api.services.mobile_support import append_mobile_controls_requirement

logger = logging.getLogger(__name__)


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
        if data.get("event_type") == "ErrorEvent":
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
class BevyCreationRequest:
    intent: str
    budget_cents: Optional[int] = None


@dataclass
class TaskInfo:
    number: int
    name: str
    status: str
    depends_on: List[int]
    block: str  # Full markdown block


class BevyCreationAgent:
    """Orchestrates the godogen pipeline for Bevy: skill → executor → wasm build."""

    SERVICE_NAME = "bevy_creation_agent"

    def __init__(self, executor, game_service):
        """
        Args:
            executor: BevyExecutor (CLI or SDK)
            game_service: BevyGameService
        """
        self.executor = executor
        self.game_service = game_service

    @staticmethod
    def _promote_capture_artifacts(game_path: Path) -> None:
        """Copy the latest ``screenshots/result/{N}/`` proof artifacts up to
        ``screenshots/presentation/``.

        Bevy's upstream ``capture.md`` skill writes ``gameplay.mp4`` and
        ``gameplay.png`` into ``screenshots/result/{N}/`` (numbered run
        directories). The TinyWorlds API serves proof artifacts from a
        single canonical ``screenshots/presentation/`` location — this
        helper bridges the gap.

        Best-effort: if no result directories exist, no-ops. If a copy
        fails, logs and returns without raising — never let promotion
        failure crash creation.
        """
        try:
            result_root = game_path / "screenshots" / "result"
            if not result_root.exists() or not result_root.is_dir():
                logger.info(
                    "No screenshots/result/ directory at %s — skipping capture promotion",
                    game_path,
                )
                return

            numbered = []
            for entry in result_root.iterdir():
                if entry.is_dir() and entry.name.isdigit():
                    numbered.append((int(entry.name), entry))
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
            if video_src.exists():
                presentation.mkdir(parents=True, exist_ok=True)
                shutil.copy2(video_src, presentation / "gameplay.mp4")
                logger.info(
                    "Promoted %s -> %s/gameplay.mp4", video_src, presentation
                )

            png_src = latest / "gameplay.png"
            if png_src.exists():
                presentation.mkdir(parents=True, exist_ok=True)
                shutil.copy2(png_src, presentation / "gameplay.png")
                logger.info(
                    "Promoted %s -> %s/gameplay.png", png_src, presentation
                )
        except Exception as e:  # noqa: BLE001 — best-effort, never raise
            logger.warning("Capture artifact promotion failed: %s", e)

    # Auto-retry thresholds for "zero-cost partial" — see the Godot agent's
    # matching constants and /debug-prod-game runbook.
    _RETRY_MAX_COST_USD = 0.05
    _RETRY_MAX_DURATION_S = 120.0

    async def create_game(
        self,
        request: BevyCreationRequest,
        game_path: Path,
    ) -> AsyncIterator[BaseEvent]:
        """Run the godogen pipeline, with one auto-retry on zero-cost partial."""
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
        request: BevyCreationRequest,
        game_path: Path,
    ) -> AsyncIterator[BaseEvent]:
        """One pass of the godogen pipeline via a single Claude Code invocation.

        Every event is persisted to ``{game_path}/.creation/events.jsonl`` and a
        summary.json is written on exit. On retry, events.jsonl appends and
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

            async for event in self.executor.run_stage(
                skill_content,
                append_mobile_controls_requirement(request.intent),
                game_path,
                engine="bevy",
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

            yield _emit(StatusEvent(
                service=self.SERVICE_NAME,
                message="Building WebAssembly bundle...",
                step="export",
                status="started",
            ))
            try:
                dist_path = await asyncio.to_thread(
                    self.game_service.build_wasm, game_path
                )
            except Exception as exc:  # noqa: BLE001 — degraded path, not fatal
                logger.exception("build_wasm failed during create_game")
                dist_path = None
                yield _emit(StatusEvent(
                    service=self.SERVICE_NAME,
                    message="Browser export failed — video fallback available",
                    step="export",
                    status="completed",
                ))
            else:
                yield _emit(StatusEvent(
                    service=self.SERVICE_NAME,
                    message="Browser export complete!",
                    step="export",
                    status="completed",
                ))

            # Promote upstream capture artifacts (result/{N}/) into the
            # canonical presentation/ location before checking has_video.
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
        instruction. Re-runs the wasm build at the end. Caller is expected
        to re-run verify_playable after consuming this generator.

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
            "the wasm build if assets/scripts changed. Only declare complete when "
            "these specific issues are resolved on disk: the next verify_playable "
            "check will repeat the same assertions."
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

            async for event in self.executor.run_stage(
                skill_content,
                fix_instruction,
                game_path,
                engine="bevy",
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

            # Re-build — the fix likely changed sources
            yield _emit(StatusEvent(
                service=self.SERVICE_NAME,
                message="Re-building WebAssembly bundle after fix...",
                step="export",
                status="started",
            ))
            try:
                dist_path = await asyncio.to_thread(
                    self.game_service.build_wasm, game_path
                )
                yield _emit(StatusEvent(
                    service=self.SERVICE_NAME,
                    message="Re-export complete" if dist_path else "Re-export failed",
                    step="export",
                    status="completed",
                ))
            except Exception as exc:  # noqa: BLE001 — log and continue; route will re-verify
                logger.exception("Re-build failed during fix attempt")
                dist_path = None
                yield _emit(ErrorEvent(
                    service=self.SERVICE_NAME,
                    error_message=f"Re-export failed: {exc}",
                    suggestion="Check .creation/events.jsonl",
                ))

            # Promote any new capture artifacts after the fix attempt.
            self._promote_capture_artifacts(game_path)
        except Exception as e:
            crash = e
            logger.exception("Fix attempt failed")
            yield _emit(ErrorEvent(
                service=self.SERVICE_NAME,
                error_message=str(e),
                suggestion="Check .creation/events.jsonl for details",
            ))
        finally:
            video_path = game_path / "screenshots" / "presentation" / "gameplay.mp4"
            creation_log.close(
                has_export=dist_path is not None,
                has_video=video_path.exists(),
                exception=crash,
            )
