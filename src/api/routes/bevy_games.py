"""API routes for Bevy game management (v1 core surface).

Structural mirror of :mod:`src.api.routes.godot_games` — but only the v1 core
endpoints. The deferred surfaces (modify, progress/log, history, structure,
plan, media, asset serving, telemetry) will land in a follow-up; this file
intentionally stays small.

Game IDs are prefixed ``bevy-<hex8>`` so Bevy and Godot games can coexist
under the same ``generated_games/`` root. The engine discriminator on disk
is the presence of ``Cargo.toml`` (Bevy) vs ``project.godot`` (Godot).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.api.core.config import get_settings
from src.api.dependencies import (get_current_user, get_optional_current_user, require_game_owner, require_game_viewer, require_game_asset_owner)
from src.api.services.game_access import game_path as safe_game_path, create_access, can_view, read_access, is_owner
from src.api.middleware.rate_limit import check_game_creation_rate_limit
from src.api.models.user import User
from src.api.services.bevy_creation_agent import BevyCreationAgent, BevyCreationRequest
from src.api.services.bevy_game_service import BevyGameService
from src.api.services.bevy_modification_service import (
    BevyModificationRequest,
    BevyModificationService,
)
from src.api.services.email_service import email_service
from src.api.services.executors import get_executor
from src.api.services.failure_log import record_failure as _record_failure
from src.api.services.game_jobs import start_job
from src.api.services.game_event_log import GameEventLog
from src.api.services.browser_verification import verify_browser, verified_screenshot
from src.api.services.game_access import isolated_play_redirect
from src.api.services.mobile_support import inject_mobile_play_shim
from src.api.services.modification_run_log import (
    build_modification_summary,
    list_modification_runs,
    read_modification_run,
    screenshot_names_since,
    utc_now_iso,
)
from src.api.services.play_cache import (
    asset_version,
    dist_asset_versions,
    inject_play_asset_cache_buster,
    versioned_play_asset_headers,
)
from src.api.services.suggestions_generator import generate_suggestions

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()


def _should_notify_on_success(user: User) -> bool:
    """Return whether successful generation/modification should email user."""
    return bool(getattr(user, "is_registered", not getattr(user, "is_anonymous", False)))


# In-flight modification tracking — same shape as godot_games to keep behaviour
# parity. One modification at a time per game; cap globally.
_active_modifications: dict[str, float] = {}
_modification_lock = asyncio.Lock()
_MAX_CONCURRENT_MODIFICATIONS = 3


# -------------------------------------------------------------------
# Request/Response Models
# -------------------------------------------------------------------

from src.api.services.visual_reference import VisualReference, decode_reference, save_reference, reference_instruction
from src.api.services.modification_run_log import reference_attachments


class BevyCreateGameRequest(BaseModel):
    """Request to create a new Bevy game."""
    description: str = Field(..., description="Natural language game description")
    budget_cents: Optional[int] = Field(None, ge=0, le=10000, description="Asset generation budget in cents")
    visibility: Literal["public", "private", "unlisted"] = "public"
    reference_image: VisualReference | None = None


class BevyGameInfoResponse(BaseModel):
    """Game info response (Bevy)."""
    game_id: str
    name: Optional[str] = None
    game_path: str
    has_plan: bool
    has_structure: bool
    has_video: bool
    has_export: bool
    engine: str = "bevy"
    can_edit: bool = False
    visibility: str = "public"


class BevyRenameGameRequest(BaseModel):
    """Body for PATCH /games/{id}: rename a game's display name."""
    name: str = Field(..., min_length=1, max_length=80)


class BevyModifyGameRequest(BaseModel):
    """Request to modify a Bevy game with natural-language instruction."""
    instruction: str = Field(..., min_length=1)
    reference_image: VisualReference | None = None


class BevyModifyGameResponse(BaseModel):
    success: bool
    changes: list[str]
    explanation: str
    error: Optional[str] = None


# -------------------------------------------------------------------
# Helper Functions
# -------------------------------------------------------------------

def get_game_path(game_id: str) -> Path:
    """Get the path to a Bevy game by ID."""
    return safe_game_path(game_id)


def game_exists(game_id: str) -> bool:
    """Check if a Bevy game directory exists.

    Requires ``Cargo.toml`` to be present so a Godot game with a
    coincidentally-matching directory name does not 200 here.
    """
    path = get_game_path(game_id)
    return path.exists() and path.is_dir() and (path / "Cargo.toml").exists()


def _build_info(game_id: str, game_path: Path, game_service: BevyGameService, current_user=None) -> BevyGameInfoResponse:
    return BevyGameInfoResponse(
        game_id=game_id,
        name=game_service.read_name(game_path),
        game_path=str(game_path),
        has_plan=bool(game_service.read_artifact(game_path, "PLAN.md")),
        has_structure=bool(game_service.read_artifact(game_path, "STRUCTURE.md")),
        has_video=(game_path / "screenshots" / "presentation" / "gameplay.mp4").exists(),
        has_export=(game_path / "dist" / "index.html").exists(),
        engine="bevy",
        can_edit=is_owner(read_access(game_id), current_user), visibility=read_access(game_id).visibility,
    )


# -------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------

@router.post("/games", dependencies=[Depends(check_game_creation_rate_limit)])
async def create_game(request: BevyCreateGameRequest, current_user: User = Depends(get_current_user)):
    """Create a new Bevy game from a natural language description (SSE streaming)."""
    reference_data = decode_reference(request.reference_image)
    original_description = request.description
    executor = get_executor(settings)
    game_id = f"bevy-{uuid.uuid4().hex[:8]}"
    game_service = BevyGameService(settings)
    game_path = game_service.create_game(game_id, Path(settings.GODOT_GAMES_DIR))
    create_access(game_id, str(current_user.id), request.visibility)
    if reference_data is not None and request.reference_image is not None:
        path = save_reference(game_path, request.reference_image, reference_data)
        request = request.model_copy(update={"description": reference_instruction(request.description, path)})

    agent = BevyCreationAgent(executor, game_service)
    event_log = GameEventLog(game_path)
    event_log.append({
        "event_type": "init",
        "game_id": game_id,
        "engine": "bevy",
        "provider": executor.provider,
        "description": original_description,
        "attachments": reference_attachments(game_path, request.description),
        "budget_cents": request.budget_cents,
    })

    start_job(game_id,
        _run_pipeline_to_log(
            game_id=game_id,
            game_path=game_path,
            request=request,
            agent=agent,
            game_service=game_service,
            executor=executor,
            event_log=event_log,
            notification_email=current_user.email,
            notify_on_success=_should_notify_on_success(current_user),
        )
        , event_log
    )

    return StreamingResponse(
        _replay_and_tail_sse(event_log, since_seq=-1),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _run_pipeline_to_log(
    *,
    game_id: str,
    game_path: Path,
    request: BevyCreateGameRequest,
    agent: BevyCreationAgent,
    game_service: BevyGameService,
    executor,
    event_log: GameEventLog,
    notification_email: Optional[str],
    notify_on_success: bool,
) -> None:
    def _write(event_dict: dict) -> None:
        try:
            event_log.append(event_dict)
        except Exception:
            logger.exception("failed to persist bevy event for game=%s", game_id)

    try:
        pipeline_errors = []
        async for _event in agent.create_game(
            BevyCreationRequest(
                intent=request.description,
                budget_cents=request.budget_cents,
            ),
            game_path,
        ):
            # BevyCreationAgent already writes its own .creation log. Appending
            # here keeps the stream path consistent with the explicit init/done
            # events owned by this router.
            payload = _event.to_sse_dict()
            if payload.get("event_type") == "ErrorEvent" or payload.get("stream_type") == "error":
                pipeline_errors.append(payload.get("error_message") or payload.get("content") or "Provider failed")
        if pipeline_errors:
            _write({"event_type": "failed", "game_id": game_id, "engine": "bevy", "failures": pipeline_errors})
            return

        failures = await verify_browser(game_path, "bevy", game_service.verify_playable(game_path), require_pip=True)

        if failures:
            retry_status = {
                "event_type": "StatusEvent",
                "service": "bevy_creation_agent",
                "message": (
                    f"Verification found {len(failures)} issue(s) — "
                    "attempting one self-correction pass"
                ),
                "step": "retry",
                "status": "started",
                "failures": failures,
            }
            _write(retry_status)
            async for _event in agent.attempt_fix(game_path, failures, budget_cents=request.budget_cents):
                payload = _event.to_sse_dict()
                if payload.get("event_type") == "ErrorEvent" or payload.get("stream_type") == "error":
                    pipeline_errors.append(payload.get("error_message") or payload.get("content") or "Provider failed")
            if pipeline_errors:
                _write({"event_type": "failed", "game_id": game_id, "engine": "bevy", "failures": pipeline_errors})
                return
            failures = await verify_browser(game_path, "bevy", game_service.verify_playable(game_path), require_pip=True)

        if failures:
            for failure in failures:
                _record_failure(
                    game_id=game_id,
                    engine="bevy",
                    stage="verify",
                    rule="verify_playable",
                    detail=str(failure),
                    file=None,
                )
            _write({"event_type": "failed", "game_id": game_id, "engine": "bevy", "failures": failures})
        else:
            asyncio.create_task(  # noqa: RUF006 — intentional fire-and-forget
                generate_suggestions(game_path, "bevy", executor=executor)
            )
            _write({"event_type": "done", "game_id": game_id, "engine": "bevy"})
            if notify_on_success and notification_email:
                await _send_game_created_notification(
                    notification_email,
                    game_id,
                    game_service.read_name(game_path),
                )
    except Exception as e:
        logger.exception("bevy pipeline task crashed for game=%s", game_id)
        _write({
            "event_type": "crashed",
            "game_id": game_id,
            "engine": "bevy",
            "error": f"{type(e).__name__}: {e}",
        })


async def _replay_and_tail_sse(
    event_log: GameEventLog, *, since_seq: int = -1
):
    async for seq, event in event_log.tail(since_seq=since_seq, stop_on_summary=False):
        yield f"data: {json.dumps({**event, 'seq': seq})}\n\n"


async def _send_game_created_notification(
    email: str,
    game_id: str,
    game_name: Optional[str],
) -> None:
    try:
        await email_service.send_game_created_email(email, game_id, "bevy", game_name)
    except Exception:
        logger.exception("failed to send bevy game-created email for game=%s", game_id)


async def _send_game_modified_notification(
    email: str,
    game_id: str,
    game_name: Optional[str],
) -> None:
    try:
        await email_service.send_game_modified_email(email, game_id, "bevy", game_name)
    except Exception:
        logger.exception("failed to send bevy game-modified email for game=%s", game_id)


@router.get("/games/{game_id}/events/stream", dependencies=[Depends(require_game_owner)])
async def stream_game_events(game_id: str, since: int = -1):
    """SSE replay + tail of a Bevy game's creation log."""
    game_path = get_game_path(game_id)
    event_log = GameEventLog(game_path)
    if not game_path.is_dir() or not event_log.exists():
        raise HTTPException(
            status_code=404,
            detail=f"no creation log for game '{game_id}'",
        )
    return StreamingResponse(
        _replay_and_tail_sse(event_log, since_seq=since),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/games/{game_id}/modifications", dependencies=[Depends(require_game_owner)])
async def list_game_modifications(game_id: str):
    """List persisted modification runs for a Bevy game."""
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")
    game_path = get_game_path(game_id)
    return {
        "game_id": game_id,
        "engine": "bevy",
        "runs": list_modification_runs(game_path, game_id=game_id, engine="bevy"),
    }


@router.get("/games/{game_id}/modifications/{run_id}/events", dependencies=[Depends(require_game_owner)])
async def get_modification_events(game_id: str, run_id: str):
    """Return summary plus parsed events for one Bevy modification run."""
    if not run_id.isalnum() or len(run_id) > 32:
        raise HTTPException(status_code=400, detail="invalid run_id")
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")
    game_path = get_game_path(game_id)
    event_log = GameEventLog(game_path, log_dir=f".modifications/{run_id}")
    if not event_log.exists():
        raise HTTPException(
            status_code=404,
            detail=f"no modification log for game='{game_id}' run='{run_id}'",
        )
    return read_modification_run(
        game_path,
        game_id=game_id,
        engine="bevy",
        run_id=run_id,
    )


@router.get("/games/{game_id}/modifications/{run_id}/events/stream", dependencies=[Depends(require_game_owner)])
async def stream_modification_events(
    game_id: str, run_id: str, since: int = -1,
):
    """SSE replay + tail of one Bevy modification run's event log."""
    if not run_id.isalnum() or len(run_id) > 32:
        raise HTTPException(status_code=400, detail="invalid run_id")
    game_path = get_game_path(game_id)
    event_log = GameEventLog(game_path, log_dir=f".modifications/{run_id}")
    if not game_path.is_dir() or not event_log.exists():
        raise HTTPException(
            status_code=404,
            detail=f"no modification log for game='{game_id}' run='{run_id}'",
        )
    return StreamingResponse(
        _replay_and_tail_sse(event_log, since_seq=since),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/games", response_model=list[BevyGameInfoResponse])
async def list_games(current_user: User | None = Depends(get_optional_current_user)):
    """List all Bevy games (filtered by Cargo.toml presence)."""
    game_service = BevyGameService(settings)
    base = Path(settings.GODOT_GAMES_DIR)
    game_ids = [gid for gid in game_service.list_games(base) if can_view(gid, current_user, listing=True)]
    return [_build_info(gid, base / gid, game_service, current_user) for gid in game_ids]


@router.get("/games/{game_id}", response_model=BevyGameInfoResponse, dependencies=[Depends(require_game_viewer)])
async def get_game_info(game_id: str, current_user: User | None = Depends(get_optional_current_user)):
    """Get information about a Bevy game."""
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )
    game_path = get_game_path(game_id)
    game_service = BevyGameService(settings)
    return _build_info(game_id, game_path, game_service, current_user)


@router.delete("/games/{game_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_game_owner)])
async def delete_game(
    game_id: str,
    current_user: User = Depends(get_current_user),
):
    """Hard-delete a Bevy game: removes the on-disk directory tree.

    Includes `target/` and `dist/` which can be hundreds of MB. Frontend
    two-step confirm gates this. No DB row to clean up — `generated_games/
    <id>/` is the source of truth.
    """
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )
    import shutil
    game_path = get_game_path(game_id)
    shutil.rmtree(game_path)
    logger.info("deleted bevy game: %s (by %s)", game_id, current_user.email)
    return None


@router.patch("/games/{game_id}", response_model=BevyGameInfoResponse, dependencies=[Depends(require_game_owner)])
async def rename_game(
    game_id: str,
    request: BevyRenameGameRequest,
    current_user: User = Depends(get_current_user),
):
    """Rename a Bevy game (writes display_name into Cargo.toml metadata)."""
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )
    game_path = get_game_path(game_id)
    game_service = BevyGameService(settings)
    try:
        game_service.write_name(game_path, request.name)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _build_info(game_id, game_path, game_service, current_user)


# -------------------------------------------------------------------
# Modify
# -------------------------------------------------------------------

@router.post("/games/{game_id}/modify", response_model=BevyModifyGameResponse, dependencies=[Depends(require_game_owner)])
async def modify_game(
    game_id: str,
    request: BevyModifyGameRequest,
    current_user: User = Depends(get_current_user),
):
    """Modify a Bevy game with a natural-language instruction (non-streaming)."""
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )

    game_path = get_game_path(game_id)
    image_data = decode_reference(request.reference_image)
    if request.reference_image is not None:
        image_path = save_reference(game_path, request.reference_image, image_data)
        request = request.model_copy(update={"instruction": reference_instruction(request.instruction, image_path)})
    game_service = BevyGameService(settings)
    executor = get_executor(settings)
    service = BevyModificationService(executor, game_service)

    mod_request = BevyModificationRequest(
        instruction=request.instruction,
        game_path=game_path,
    )

    last_content = ""
    last_changes: list[str] = []
    last_error: Optional[str] = None
    final_success = False

    async for progress in service.modify_game(mod_request):
        if (progress.metadata or {}).get("rebuild_status") == "failed" or (progress.metadata or {}).get("export_status") == "failed":
            last_error = progress.content
            final_success = False
        if progress.type == "complete":
            final_success = True
            last_content = progress.content
            last_changes = (progress.metadata or {}).get("changes", [])
        elif progress.type == "error":
            last_error = progress.content

    failures = await verify_browser(game_path, "bevy", game_service.verify_playable(game_path), require_pip=True)
    if failures:
        final_success = False
        last_error = "; ".join(failures)
    return BevyModifyGameResponse(
        success=final_success and not last_error,
        changes=last_changes,
        explanation=last_content,
        error=last_error,
    )


@router.post("/games/{game_id}/modify/stream", dependencies=[Depends(require_game_owner)])
async def modify_game_stream(
    game_id: str,
    request: BevyModifyGameRequest,
    current_user: User = Depends(get_current_user),
):
    """Modify a Bevy game with streaming progress updates (SSE)."""
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )

    if request.reference_image is not None:
        reference_data = decode_reference(request.reference_image)
        reference_path = save_reference(get_game_path(game_id), request.reference_image, reference_data)
        request = request.model_copy(update={"instruction": reference_instruction(request.instruction, reference_path)})

    async with _modification_lock:
        if game_id in _active_modifications:
            raise HTTPException(
                status_code=429,
                detail="A modification is already in progress for this game",
            )
        if len(_active_modifications) >= _MAX_CONCURRENT_MODIFICATIONS:
            raise HTTPException(
                status_code=429,
                detail="Too many concurrent modifications — try again shortly",
            )
        _active_modifications[game_id] = time.time()

    game_path = get_game_path(game_id)
    game_service = BevyGameService(settings)
    executor = get_executor(settings)
    service = BevyModificationService(executor, game_service)

    mod_request = BevyModificationRequest(
        instruction=request.instruction,
        game_path=game_path,
    )
    run_id = uuid.uuid4().hex[:10]
    event_log = GameEventLog(game_path, log_dir=f".modifications/{run_id}")
    event_log.append({
        "event_type": "init",
        "type": "status",
        "content": "Modification queued",
        "timestamp": utc_now_iso(),
        "metadata": {
            "game_id": game_id,
            "run_id": run_id,
            "engine": "bevy",
            "instruction": request.instruction,
            "has_image": request.reference_image is not None,
            "attachments": reference_attachments(game_path, request.instruction),
        },
    })

    start_job(game_id,
        _run_modification_to_log(
            game_id=game_id,
            game_path=game_path,
            run_id=run_id,
            instruction=request.instruction,
            service=service,
            mod_request=mod_request,
            event_log=event_log,
            game_service=game_service,
            notification_email=current_user.email,
            notify_on_success=_should_notify_on_success(current_user),
        )
        , event_log
    )

    return StreamingResponse(
        _replay_and_tail_sse(event_log, since_seq=-1),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _run_modification_to_log(
    *,
    game_id: str,
    game_path: Path,
    run_id: str,
    instruction: str,
    service: BevyModificationService,
    mod_request: BevyModificationRequest,
    event_log: GameEventLog,
    game_service: BevyGameService,
    notification_email: Optional[str],
    notify_on_success: bool,
) -> None:
    last_content = ""
    last_changes: list[str] = []
    last_error: Optional[str] = None
    final_success = False
    rebuild_status: Optional[str] = None
    start_time = time.perf_counter()
    start_wall_time = time.time()
    started_at = utc_now_iso()
    persisted_events: list[dict] = []

    try:
        async for progress in service.modify_game(mod_request):
            if (progress.metadata or {}).get("rebuild_status") == "failed" or (progress.metadata or {}).get("export_status") == "failed":
                last_error = progress.content
                final_success = False
            if progress.type in {"thinking", "text"} and progress.content:
                last_content = progress.content
            if progress.type == "complete":
                final_success = True
                last_content = progress.content or last_content
                last_changes = (progress.metadata or {}).get("changes", [])
            elif progress.type == "error":
                last_error = progress.content
            metadata = progress.metadata or {}
            if isinstance(metadata, dict) and metadata.get("rebuild_status"):
                rebuild_status = str(metadata["rebuild_status"])
            event = {
                "timestamp": utc_now_iso(),
                "type": progress.type,
                "content": progress.content,
                "metadata": progress.metadata,
            }
            persisted_events.append(event)
            event_log.append(event)

        verification_event = {
            "timestamp": utc_now_iso(),
            "type": "status",
            "content": "Checking the updated game in the browser…",
            "metadata": {"phase": "verification"},
        }
        persisted_events.append(verification_event)
        event_log.append(verification_event)
        verification_failures = await verify_browser(game_path, "bevy", game_service.verify_playable(game_path), require_pip=True)
        has_export = (game_path / "dist" / "index.html").exists()
        has_playable_build = not verification_failures
        status_value = (
            "success"
            if final_success and has_playable_build and not last_error
            else "partial"
            if final_success or has_export
            else "failed"
        )
        terminal_success = status_value == "success"
        if verification_failures and not last_error:
            last_error = "; ".join(verification_failures)
        final_message = (
            "Modification complete"
            if terminal_success
            else last_error or "Modification finished without a playable browser build"
        )
        event_log.append({
            "timestamp": utc_now_iso(),
            "event_type": "done" if terminal_success else "failed",
            "type": "complete" if terminal_success else "error",
            "content": final_message,
            "metadata": {
                "game_id": game_id,
                "run_id": run_id,
                "engine": "bevy",
                "changes": last_changes,
                "explanation": last_content,
                "success": terminal_success,
                "status": status_value,
                "has_export": has_export,
                "has_playable_build": has_playable_build,
                "rebuild_status": rebuild_status,
                "verification_failures": verification_failures,
            },
        })
        event_log.write_summary(build_modification_summary(
            game_id=game_id,
            engine="bevy",
            run_id=run_id,
            instruction=instruction,
            status=status_value,
            started_at=started_at,
            finished_at=utc_now_iso(),
            duration_seconds=time.perf_counter() - start_time,
            event_count=len(persisted_events) + 2,
            final_message=final_message,
            explanation=last_content,
            changes=last_changes,
            error=None if terminal_success else last_error,
            has_export=has_export,
            has_playable_build=has_playable_build,
            verification_failures=verification_failures,
            events=persisted_events,
            new_screenshots=screenshot_names_since(game_path, start_wall_time),
            rebuild_status=rebuild_status,
        ))
        if terminal_success and notify_on_success and notification_email:
            await _send_game_modified_notification(
                notification_email,
                game_id,
                game_service.read_name(game_path),
            )
    except Exception as exc:
        logger.exception("bevy modification task crashed for game=%s", game_id)
        event_log.append({
            "event_type": "crashed",
            "type": "error",
            "content": f"{type(exc).__name__}: {exc}",
            "metadata": {"game_id": game_id, "run_id": run_id, "engine": "bevy"},
        })
        try:
            event_log.write_summary(build_modification_summary(
                game_id=game_id,
                engine="bevy",
                run_id=run_id,
                instruction=instruction,
                status="crashed",
                started_at=started_at,
                finished_at=utc_now_iso(),
                duration_seconds=time.perf_counter() - start_time,
                event_count=len(persisted_events) + 2,
                final_message=f"{type(exc).__name__}: {exc}",
                error=f"{type(exc).__name__}: {exc}",
                has_export=(game_path / "dist" / "index.html").exists(),
                has_playable_build=False,
                verification_failures=[],
                events=persisted_events,
                new_screenshots=screenshot_names_since(game_path, start_wall_time),
                rebuild_status=rebuild_status,
            ))
        except Exception:
            logger.exception("failed to write bevy modification summary for game=%s", game_id)
    finally:
        _active_modifications.pop(game_id, None)


# -------------------------------------------------------------------
# Game Play (WebAssembly served from dist/)
# -------------------------------------------------------------------

WASM_CONTENT_TYPES = {
    ".html": "text/html",
    ".js": "application/javascript",
    ".wasm": "application/wasm",
    ".css": "text/css",
    ".json": "application/json",
    ".map": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


# Injected into every served Bevy index.html. Bevy's wasm-bindgen output is
# bare (no engine framework to hook), so we capture failures at the JS layer:
#  - WASM instantiate errors (the bevy-4b86463c 0x6B failure 2026-05-11 was
#    invisible until we made this — manual `import init()` was the only way
#    to surface the message)
#  - JS errors / unhandledrejections (including the wasm-bindgen init promise)
#  - console.error / console.warn
#  - Heap sampler + drift watchdog (mirrors Godot)
#  - **Canvas-never-created watchdog**: Bevy creates its <canvas> element
#    inside the WASM main loop. If init() throws before the loop starts, the
#    page stays empty. We flush a "canvas_missing" event after 5s without a
#    canvas appearing — the most reliable "silent black screen" signal.
_BEVY_TELEMETRY_SHIM = """
<script>
(function() {
  var GAME_ID = "__GAME_ID__";
  var SESSION = (crypto.randomUUID && crypto.randomUUID()) || (Date.now() + "-" + Math.random().toString(36).slice(2));
  var ENDPOINT = "/api/v1/bevy/games/" + GAME_ID + "/telemetry";
  var BUFFER_MAX = 500;
  var buf = [];
  function push(kind, payload) {
    buf.push(Object.assign({t: Date.now(), kind: kind}, payload));
    if (buf.length > BUFFER_MAX) buf.splice(0, buf.length - BUFFER_MAX);
  }
  function flush(reason) {
    if (!buf.length) return;
    try {
      var body = JSON.stringify({session: SESSION, reason: reason, events: buf});
      var blob = new Blob([body], {type: "application/json"});
      if (navigator.sendBeacon) navigator.sendBeacon(ENDPOINT, blob);
      else fetch(ENDPOINT, {method: "POST", body: body, headers: {"content-type": "application/json"}, keepalive: true}).catch(function(){});
      buf = [];
    } catch(e) {}
  }
  window.__tw_bevy_push = push;
  window.__tw_bevy_flush = flush;

  window.addEventListener("error", function(e) {
    push("error", {message: String(e.message), source: e.filename, line: e.lineno, col: e.colno, stack: e.error && e.error.stack});
  });
  window.addEventListener("unhandledrejection", function(e) {
    var msg = String(e.reason && e.reason.message || e.reason);
    push("unhandledrejection", {message: msg, stack: e.reason && e.reason.stack});
    // Likely the wasm-bindgen init() promise rejecting. Flush immediately so
    // the failure is in the corpus even if the page errors out hard right after.
    flush("unhandledrejection");
  });
  ["warn", "error"].forEach(function(level) {
    var orig = console[level].bind(console);
    console[level] = function() {
      var args = Array.prototype.slice.call(arguments).map(function(a) {
        try { return typeof a === "string" ? a : JSON.stringify(a); } catch(e) { return String(a); }
      });
      push("console." + level, {msg: args.join(" ").slice(0, 500)});
      orig.apply(null, arguments);
    };
  });

  // Heap + drift sampler. Mirrors Godot: drift>3s = frozen WASM thread.
  // Backgrounded tabs trip setInterval clamping → huge fake drift on the
  // first tick after unhide. Skip while hidden; reset baseline on unhide.
  var lastTick = Date.now();
  document.addEventListener("visibilitychange", function() {
    if (document.visibilityState === "visible") lastTick = Date.now();
  });
  setInterval(function() {
    var now = Date.now();
    var drift = now - lastTick - 1000;
    lastTick = now;
    if (document.hidden) return;  // tab throttling is not a freeze.
    var sample = {};
    if (drift > 0) sample.drift = drift;
    if (performance && performance.memory) {
      sample.heap = performance.memory.usedJSHeapSize;
      sample.heapLimit = performance.memory.jsHeapSizeLimit;
    }
    push("sample", sample);
    if (drift > 3000) { push("frozen", {drift: drift}); flush("frozen"); }
  }, 1000);

  // Canvas-never-created watchdog. Fires once at 5s if no <canvas> exists.
  setTimeout(function() {
    if (!document.querySelector("canvas")) {
      push("canvas_missing", {bodyChildren: [].map.call(document.body.children, function(e){return e.tagName;}).join(",")});
      flush("canvas_missing");
    }
  }, 5000);

  setInterval(function() { flush("interval"); }, 5000);
  document.addEventListener("visibilitychange", function() {
    if (document.visibilityState === "hidden") flush("visibilitychange");
  });
  window.addEventListener("pagehide", function() { flush("pagehide"); });
})();
</script>
"""


@router.get("/games/{game_id}/play", dependencies=[Depends(require_game_viewer)])
async def play_game_redirect(game_id: str, request: Request, current_user: User | None = Depends(get_optional_current_user)):
    """Redirect to the game's index.html."""
    isolated = isolated_play_redirect(request)
    if isolated is not None:
        return isolated
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")
    index = get_game_path(game_id) / "dist" / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Game not exported to web yet")
    embedded = "?embedded=1" if request.query_params.get("embedded") == "1" else ""
    response = RedirectResponse(f"/api/v1/bevy/games/{game_id}/play/index.html{embedded}")
    if current_user is not None:
        from datetime import timedelta
        from src.api.core.security import create_access_token
        media_token = create_access_token({"sub": str(current_user.id), "purpose": "game-media", "game_id": game_id}, expires_delta=timedelta(minutes=5))
        response.set_cookie("tw_game_media", media_token, max_age=300, httponly=True, secure=request.url.scheme == "https" or settings.GAME_PLAY_ORIGIN.startswith("https://"), samesite="lax", path=f"/api/v1/bevy/games/{game_id}/")
    return response


@router.get("/games/{game_id}/play/{file_path:path}", dependencies=[Depends(require_game_viewer)])
async def serve_game_file(game_id: str, file_path: str, request: Request):
    """Serve WebAssembly bundle files from the game's dist/ directory."""
    isolated = isolated_play_redirect(request)
    if isolated is not None:
        return isolated
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")

    dist_dir = (get_game_path(game_id) / "dist").resolve()
    candidate = (dist_dir / file_path).resolve()

    # Security: reject path traversal — resolved file must live under dist/.
    try:
        candidate.relative_to(dist_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    ext = Path(file_path).suffix.lower()
    content_type = WASM_CONTENT_TYPES.get(ext, "application/octet-stream")
    # Inject the telemetry shim into the served HTML so JS errors, WASM
    # instantiate failures, and silent canvas-missing failures land in the
    # cross-engine failure corpus instead of being invisible black screens.
    if ext == ".html":
        html = candidate.read_text(encoding="utf-8")
        html = inject_play_asset_cache_buster(html, dist_asset_versions(candidate.parent))
        html = inject_mobile_play_shim(html)
        from src.api.services.pip_bridge import inject_pip_bridge
        html = inject_pip_bridge(html, settings.FRONTEND_URL)
        if request.query_params.get("embedded") == "1":
            from src.api.services.mobile_support import inject_embedded_play_focus
            html = inject_embedded_play_focus(html)
        shim = _BEVY_TELEMETRY_SHIM.replace("__GAME_ID__", game_id)
        if "</head>" in html:
            html = html.replace("</head>", shim + "</head>", 1)
        else:
            html = shim + html
        return HTMLResponse(
            content=html,
            headers={
                "Cache-Control": "no-store",
                "CDN-Cache-Control": "no-store",
                "Cloudflare-CDN-Cache-Control": "no-store",
            },
        )

    cache_headers = versioned_play_asset_headers(candidate, request)
    if read_access(game_id).visibility != "public":
        cache_headers.update({key: "private, no-store" for key in ("Cache-Control", "CDN-Cache-Control", "Cloudflare-CDN-Cache-Control")})
    inm = request.headers.get("if-none-match", "").strip()
    if inm == cache_headers["ETag"]:
        return Response(status_code=304, headers=cache_headers)

    response = FileResponse(candidate, media_type=content_type, headers=cache_headers)
    response.headers["ETag"] = f'"{asset_version(candidate)}"'
    return response


@router.post("/games/{game_id}/telemetry", dependencies=[Depends(require_game_viewer)])
async def post_telemetry(game_id: str, request: Request):
    """Append browser telemetry events (errors, drift, canvas-missing) as NDJSON.

    Stored at `generated_games/{id}/telemetry/{session}.ndjson` and the
    interesting events (errors, frozen, canvas_missing) are mirrored into
    `data/godogen_failures.jsonl` so the passive learning loop sees them.
    """
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    session = str(body.get("session", "unknown"))[:64]
    safe_session = "".join(c for c in session if c.isalnum() or c in "-_") or "unknown"
    reason = body.get("reason", "")
    events = body.get("events", [])
    if not isinstance(events, list):
        raise HTTPException(status_code=400, detail="events must be a list")

    tdir = get_game_path(game_id) / "telemetry"
    tdir.mkdir(parents=True, exist_ok=True)
    out = tdir / f"{safe_session}.ndjson"

    server_t = int(time.time() * 1000)
    with out.open("a", encoding="utf-8") as f:
        for ev in events:
            if not isinstance(ev, dict):
                continue
            ev["_server_t"] = server_t
            ev["_reason"] = reason
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            kind = ev.get("kind")
            if kind == "frozen":
                _record_failure(
                    game_id=game_id, engine="bevy", stage="telemetry",
                    rule="frozen_thread",
                    detail=f"drift={ev.get('drift')}ms session={safe_session}",
                )
            elif kind == "canvas_missing":
                _record_failure(
                    game_id=game_id, engine="bevy", stage="telemetry",
                    rule="canvas_missing",
                    detail=f"no <canvas> after 5s — body children: {ev.get('bodyChildren', '')}",
                )
            elif kind in ("error", "unhandledrejection"):
                _record_failure(
                    game_id=game_id, engine="bevy", stage="telemetry",
                    rule="js_error",
                    detail=str(ev.get("message", ""))[:400],
                )
    return {"ok": True, "received": len(events)}


@router.get("/games/{game_id}/assets/{file_path:path}", dependencies=[Depends(require_game_asset_owner)])
async def serve_editor_image(game_id: str, file_path: str):
    """Serve owner-only image previews through the same contract as Godot."""
    root = get_game_path(game_id).resolve()
    candidate = (root / file_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(403, "Access denied")
    media_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(candidate.suffix.lower())
    if not media_type or not candidate.is_file():
        raise HTTPException(404, "Image not found")
    return FileResponse(candidate, media_type=media_type, headers={"Cache-Control": "private, no-store"})


@router.get("/games/{game_id}/screenshot", dependencies=[Depends(require_game_viewer)])
async def get_screenshot(game_id: str):
    """Serve the canonical presentation screenshot for a Bevy game."""
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )
    game_service = BevyGameService(settings)
    trusted_capture = await verified_screenshot(get_game_path(game_id))
    if trusted_capture is not None:
        return FileResponse(trusted_capture, media_type="image/png", headers={"Cache-Control": "private, no-store"})
    path = game_service.screenshot_path(get_game_path(game_id))
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No screenshot available for this game",
        )
    return FileResponse(path, media_type="image/png")


@router.get("/games/{game_id}/video", dependencies=[Depends(require_game_viewer)])
async def get_video(game_id: str):
    """Serve the canonical presentation video for a Bevy game."""
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )
    game_service = BevyGameService(settings)
    path = game_service.video_path(get_game_path(game_id))
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Presentation video not yet available for this game",
        )
    return FileResponse(path, media_type="video/mp4")


@router.get("/games/{game_id}/suggestions", dependencies=[Depends(require_game_owner)])
async def get_suggestions(game_id: str):
    """Return cached modification suggestions or ``{pending: true}``.

    Mirror of the godot router's suggestions endpoint. Suggestions are
    generated best-effort after creation via a one-shot CLI call and
    persisted to ``suggestions.json`` in the game directory.
    """
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )
    sidecar = get_game_path(game_id) / "suggestions.json"
    if not sidecar.exists():
        return {"suggestions": [], "pending": True}
    try:
        return json.loads(sidecar.read_text())
    except Exception as e:
        logger.warning("Malformed suggestions.json for %s: %s", game_id, e)
        return {"suggestions": [], "pending": True}


@router.get("/games/{game_id}/media", dependencies=[Depends(require_game_owner)])
async def list_game_media(game_id: str):
    """Owner-only screenshots for reviewing and marking game changes."""
    project = get_game_path(game_id)
    screenshots = []
    if await verified_screenshot(project) is not None:
        screenshots.append({"path": "verification/canvas.png", "name": "Game preview", "url": f"/api/v1/bevy/games/{game_id}/screenshot"})
    directory = project / "screenshots"
    if directory.is_dir():
        for png in sorted(directory.rglob("*.png")):
            relative = png.relative_to(project).as_posix()
            screenshots.append({"path": relative, "name": png.name, "url": f"/api/v1/bevy/games/{game_id}/assets/{relative}"})
    return {"game_id": game_id, "screenshots": screenshots, "videos": []}


@router.get("/games/{game_id}/screenshot", dependencies=[Depends(require_game_owner)])
async def get_editor_screenshot(game_id: str):
    project = get_game_path(game_id)
    capture = await verified_screenshot(project)
    if capture is not None:
        return FileResponse(capture, media_type="image/png", headers={"Cache-Control": "private, no-store"})
    return Response(status_code=204)
