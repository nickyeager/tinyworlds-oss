"""API routes for Godot game management and voice-controlled modification."""
import asyncio
import json
import logging
import subprocess
import time
import uuid
from pathlib import Path
from typing import AsyncIterator, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from starlette.datastructures import UploadFile as StarletteUploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.api.services.visual_reference import VisualReference, decode_reference, save_reference, reference_instruction
from src.api.core.config import get_settings
from src.api.dependencies import (get_current_user, get_optional_current_user, require_game_owner, require_game_viewer)
from src.api.services.game_access import game_path as safe_game_path, create_access, can_view, read_access, is_owner
from src.api.models.user import User
from src.api.services.executors import get_executor
from src.api.services.email_service import email_service
from src.api.services.failure_log import record_failure as _record_failure
from src.api.services.game_jobs import start_job
from src.api.services.game_event_log import GameEventLog
from src.api.services.browser_verification import verify_browser, verified_screenshot
from src.api.services.game_access import isolated_play_redirect
from src.api.dependencies import require_game_asset_owner
from src.api.services.godot_game_service import GodotGameService
from src.api.services.godot_creation_agent import GodotCreationAgent, GodotCreationRequest
from src.api.services.godot_modification_service import (
    GodotModificationService,
    GodotModificationRequest,
)
from src.api.services.modification_run_log import (
    build_modification_summary,
    list_modification_runs,
    read_modification_run,
    reference_attachments,
    screenshot_names_since,
    utc_now_iso,
)
from src.api.services.play_cache import (
    asset_version,
    dist_asset_versions,
    inject_play_asset_cache_buster,
    versioned_play_asset_headers,
)
from src.api.services.mobile_support import inject_mobile_play_shim
from src.api.services.suggestions_generator import generate_suggestions
from src.api.services.upload_validator import (
    MAX_BYTES as UPLOAD_MAX_BYTES,
    UploadError,
    save_upload,
    validate_image,
)
from src.api.middleware.rate_limit import check_game_creation_rate_limit


logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()


def _should_notify_on_success(user: User) -> bool:
    """Return whether successful generation/modification should email user."""
    return bool(getattr(user, "is_registered", not getattr(user, "is_anonymous", False)))


# In-memory modification rate limiter
_active_modifications: dict[str, float] = {}  # game_id -> start timestamp
_modification_lock = asyncio.Lock()
_MAX_CONCURRENT_MODIFICATIONS = 3


# -------------------------------------------------------------------
# Request/Response Models
# -------------------------------------------------------------------



class CreateGameRequest(BaseModel):
    """Request to create a new Godot game."""
    description: str = Field(..., description="Natural language game description")
    budget_cents: Optional[int] = Field(None, ge=0, le=10000, description="Asset generation budget in cents")
    visibility: Literal["public", "private", "unlisted"] = "public"
    reference_image: VisualReference | None = None


class ModifyGameRequest(BaseModel):
    """Request to modify a Godot game with voice or text."""
    instruction: str = Field(..., description="Natural language modification instruction")


class ModifyGameResponse(BaseModel):
    """Response from game modification."""
    success: bool
    changes: list[str] = []
    explanation: str = ""
    error: Optional[str] = None


class GameInfoResponse(BaseModel):
    """Game info response."""
    game_id: str
    name: Optional[str] = None
    game_path: str
    has_plan: bool
    has_structure: bool
    has_video: bool
    has_export: bool
    engine: str = "godot"
    can_edit: bool = False
    visibility: str = "public"


class RenameGameRequest(BaseModel):
    """Body for PATCH /games/{id}: rename a game's display name."""
    name: str = Field(..., min_length=1, max_length=80)


# -------------------------------------------------------------------
# Helper Functions
# -------------------------------------------------------------------

def get_game_path(game_id: str) -> Path:
    """Get the path to a Godot game by ID."""
    return safe_game_path(game_id)


def game_exists(game_id: str) -> bool:
    """Check if a Godot game directory exists.

    Requires `project.godot` so a `bevy-<id>` directory under the same
    generated_games/ root cannot 200 on this router. Symmetric with the
    bevy router's `Cargo.toml` discriminator.
    """
    path = get_game_path(game_id)
    return path.is_dir() and (path / "project.godot").exists()


# -------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------

@router.post("/games", dependencies=[Depends(check_game_creation_rate_limit)])
async def create_game(request: CreateGameRequest, current_user: User = Depends(get_current_user)):
    """Create a new Godot game from a natural language description (SSE streaming).

    Streams Server-Sent Events for the full godogen pipeline:
    visual-target → decompose → scaffold → assets → task loop → video.
    """
    reference_data = decode_reference(request.reference_image)
    original_description = request.description
    executor = get_executor(settings)
    game_id = f"godot-{uuid.uuid4().hex[:8]}"
    game_service = GodotGameService(settings)
    game_path = game_service.create_game(game_id, Path(settings.GODOT_GAMES_DIR))
    create_access(game_id, str(current_user.id), request.visibility)
    if reference_data is not None and request.reference_image is not None:
        path = save_reference(game_path, request.reference_image, reference_data)
        request = request.model_copy(update={"description": reference_instruction(request.description, path)})

    agent = GodotCreationAgent(executor, game_service)

    # Build the init event and write it synchronously to events.jsonl BEFORE
    # spawning the background pipeline task. This guarantees the SSE tail
    # always has at least one event to replay even if the user reconnects
    # immediately, and keeps a deterministic "the game exists" marker on
    # disk that game_exists() and friends can rely on.
    # The description is persisted in the init event so the
    # frontend can rebuild a "Restart with same prompt" button without
    # storing anything itself — it just reads the original request back
    # from the events.jsonl after a failure.
    init_payload: dict = {
        "event_type": "init",
        "provider": executor.provider,
        "game_id": game_id,
        "engine": "godot",
        "description": original_description,
        "budget_cents": request.budget_cents,
    }
    if reference_data is not None:
        init_payload["attachments"] = reference_attachments(game_path, request.description)

    event_log = GameEventLog(game_path)
    event_log.events_file.parent.mkdir(parents=True, exist_ok=True)
    with event_log.events_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(init_payload) + "\n")

    # Generation runs as a background task — detached from this HTTP request.
    # The SSE response is just a *view* onto the persistent event log. If the
    # client disconnects (refresh, network blip, deploy), the pipeline keeps
    # running and writing to disk; a new SSE connection via the resume
    # endpoint picks up where it left off.
    start_job(game_id,
        _run_pipeline_to_log(
            game_id=game_id,
            game_path=game_path,
            request=request,
            agent=agent,
            game_service=game_service,
            executor=executor,
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
    request: CreateGameRequest,
    agent: GodotCreationAgent,
    game_service: GodotGameService,
    executor,
    notification_email: Optional[str],
    notify_on_success: bool,
) -> None:
    """Run the full godogen pipeline, writing every event to events.jsonl.

    Decoupled from the SSE connection — survives client disconnects,
    refreshes, mobile sleep. Does NOT survive backend container restart
    (the Claude subprocess is a child of this process).
    """
    event_log = GameEventLog(game_path)

    def _write(event_dict: dict) -> None:
        """Append one event to events.jsonl. Synchronous; the file is
        local disk and writes are small (<4 KB) so this stays fast."""
        try:
            with event_log.events_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event_dict) + "\n")
        except Exception:
            logger.exception("failed to persist event for game=%s", game_id)

    try:
        # Main generation. agent.create_game persists each event via
        # its internal _CreationLog; we just need to drive the
        # iterator and collect provider errors.
        pipeline_errors = []
        async for event in agent.create_game(
            GodotCreationRequest(
                intent=request.description,
                budget_cents=request.budget_cents,
            ),
            game_path,
        ):
            payload = event.to_sse_dict()
            if payload.get("event_type") == "ErrorEvent" or payload.get("stream_type") == "error":
                pipeline_errors.append(payload.get("error_message") or payload.get("content") or "Provider failed")
        if pipeline_errors:
            _write({"event_type": "failed", "game_id": game_id, "failures": pipeline_errors})
            return

        failures = await verify_browser(game_path, "godot", game_service.verify_playable(game_path), require_pip=True)

        if failures:
            retry_status = {
                "event_type": "StatusEvent",
                "service": "godot_creation_agent",
                "message": f"Verification found {len(failures)} issue(s) — attempting one self-correction pass",
                "step": "retry",
                "status": "started",
                "failures": failures,
            }
            _write(retry_status)
            async for event in agent.attempt_fix(game_path, failures, budget_cents=request.budget_cents):
                payload = event.to_sse_dict()
                if payload.get("event_type") == "ErrorEvent" or payload.get("stream_type") == "error":
                    pipeline_errors.append(payload.get("error_message") or payload.get("content") or "Provider failed")
            if pipeline_errors:
                _write({"event_type": "failed", "game_id": game_id, "failures": pipeline_errors})
                return
            failures = await verify_browser(game_path, "godot", game_service.verify_playable(game_path), require_pip=True)

        if failures:
            for failure in failures:
                _record_failure(
                    game_id=game_id,
                    engine="godot",
                    stage="verify",
                    rule="verify_playable",
                    detail=str(failure),
                    file=None,
                )
            _write({"event_type": "failed", "game_id": game_id, "failures": failures})
        else:
            # Fire-and-forget suggestions sidecar. Same placement as
            # the legacy inline version — only fires on real success.
            asyncio.create_task(  # noqa: RUF006
                generate_suggestions(game_path, "godot", executor=executor)
            )
            _write({"event_type": "done", "game_id": game_id})
            if notify_on_success and notification_email:
                await _send_game_created_notification(
                    notification_email,
                    game_id,
                    "godot",
                    game_service.read_name(game_path),
                )
    except Exception as e:
        logger.exception("pipeline task crashed for game=%s", game_id)
        _write({
            "event_type": "crashed",
            "game_id": game_id,
            "error": f"{type(e).__name__}: {e}",
        })


async def _send_game_created_notification(
    email: str,
    game_id: str,
    engine: str,
    game_name: Optional[str],
) -> None:
    try:
        await email_service.send_game_created_email(email, game_id, engine, game_name)
    except Exception:
        logger.exception("failed to send game-created email for game=%s", game_id)


async def _send_game_modified_notification(
    email: str,
    game_id: str,
    engine: str,
    game_name: Optional[str],
) -> None:
    try:
        await email_service.send_game_modified_email(email, game_id, engine, game_name)
    except Exception:
        logger.exception("failed to send game-modified email for game=%s", game_id)


async def _replay_and_tail_sse(
    event_log: GameEventLog, *, since_seq: int = -1
) -> AsyncIterator[str]:
    """Stream the persistent event log as SSE.

    Replays from ``since_seq + 1``, then tails new appends until a
    terminal event lands or the pipeline finalizes. Stamps each event
    with its sequence number so the client can pass ``?since=N`` on
    reconnect and pick up exactly where it left off.
    """
    async for seq, event in event_log.tail(since_seq=since_seq, stop_on_summary=False):
        event_with_seq = {**event, "seq": seq}
        yield f"data: {json.dumps(event_with_seq)}\n\n"


@router.get("/games/{game_id}/events/stream", dependencies=[Depends(require_game_owner)])
async def stream_game_events(game_id: str, since: int = -1):
    """SSE replay + tail of a game's creation log.

    The same shape POST /games returns, but reattachable. Pass
    ``?since=N`` to resume after a disconnect (N is the highest ``seq``
    the client has already seen). Returns 404 if no events.jsonl exists
    for this id.

    Deliberately does NOT require ``game_exists()`` (which checks for
    project.godot) — a build that's only seconds in won't have written
    that file yet, and we still want the reattach to work.
    """
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


@router.get("/games/{game_id}/modifications/{run_id}/events/stream", dependencies=[Depends(require_game_owner)])
async def stream_modification_events(
    game_id: str, run_id: str, since: int = -1,
):
    """SSE replay + tail of one modification run's event log.

    Modifications take 30s-10min and can drop their HTTP connection at
    any point (refresh, mobile sleep, deploy bounce). The persistent log
    lives at ``<game_path>/.modifications/<run_id>/events.jsonl`` —
    this endpoint reattaches the client to that log so the modify panel
    can survive disconnects the same way the create page does.

    Validates ``run_id`` is alphanumeric (uuid4().hex[:10] in practice)
    to prevent path-traversal via the run_id segment.
    """
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


@router.get("/games/{game_id}/modifications", dependencies=[Depends(require_game_owner)])
async def list_game_modifications(game_id: str):
    """List persisted modification runs for a Godot game."""
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")
    game_path = get_game_path(game_id)
    return {
        "game_id": game_id,
        "engine": "godot",
        "runs": list_modification_runs(game_path, game_id=game_id, engine="godot"),
    }


@router.get("/games/{game_id}/modifications/{run_id}/events", dependencies=[Depends(require_game_owner)])
async def get_modification_events(game_id: str, run_id: str):
    """Return summary plus parsed events for one finished Godot modification run."""
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
        engine="godot",
        run_id=run_id,
    )


@router.get("/games", response_model=list[GameInfoResponse])
async def list_games(current_user: User | None = Depends(get_optional_current_user)):
    """List all Godot games."""
    game_service = GodotGameService(settings)
    base = Path(settings.GODOT_GAMES_DIR)
    game_ids = [gid for gid in game_service.list_games(base) if can_view(gid, current_user, listing=True)]
    results = []
    for gid in game_ids:
        gp = base / gid
        plan = game_service.read_artifact(gp, "PLAN.md")
        results.append(GameInfoResponse(
            game_id=gid,
            name=game_service.read_name(gp),
            game_path=str(gp),
            has_plan=bool(plan),
            has_structure=bool(game_service.read_artifact(gp, "STRUCTURE.md")),
            has_video=(gp / "screenshots" / "presentation" / "gameplay.mp4").exists(),
            has_export=(gp / "dist" / "index.html").exists(),
            engine="godot",
            can_edit=is_owner(read_access(gid), current_user), visibility=read_access(gid).visibility,
        ))
    return results


@router.get("/games/{game_id}", response_model=GameInfoResponse, dependencies=[Depends(require_game_viewer)])
async def get_game_info(game_id: str, current_user: User | None = Depends(get_optional_current_user)):
    """Get information about a Godot game."""
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )

    game_path = get_game_path(game_id)
    game_service = GodotGameService(settings)

    return GameInfoResponse(
        game_id=game_id,
        name=game_service.read_name(game_path),
        game_path=str(game_path),
        has_plan=bool(game_service.read_artifact(game_path, "PLAN.md")),
        has_structure=bool(game_service.read_artifact(game_path, "STRUCTURE.md")),
        has_video=(game_path / "screenshots" / "presentation" / "gameplay.mp4").exists(),
        has_export=(game_path / "dist" / "index.html").exists(),
        engine="godot",
        can_edit=is_owner(read_access(game_id), current_user), visibility=read_access(game_id).visibility,
    )


# ---------------------------------------------------------------------------
# Runtime telemetry from the WASM game itself
# ---------------------------------------------------------------------------


class PlaythroughEvent(BaseModel):
    """One event POSTed from the running WASM game.

    Frontend / GDScript autoload composes these with whatever fields are
    relevant per kind — we don't enforce a schema beyond a kind string.
    Common kinds godogen-generated games emit:

      session_start    — game loaded, player ready; data: {build_id, scene}
      player_pos       — sampled every N seconds; data: {x,y,z, ts_session}
      pickup           — player picked something up; data: {kind, object_id}
      interact         — interact key pressed against a target; data: {target}
      error            — caught script error; data: {type, message}
      session_end      — beforeunload; data: {duration_s, fps_avg}
    """
    kind: str = Field(..., max_length=64)
    data: dict = Field(default_factory=dict)
    session_id: Optional[str] = Field(default=None, max_length=64)


@router.post("/games/{game_id}/playthrough", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_game_viewer)])
async def post_playthrough_event(
    game_id: str,
    event: PlaythroughEvent,
):
    """Accept one runtime event from a generated game's WASM build.

    Intentionally unauthenticated: the game runs in the user's own
    browser; a forged event harms no one but the forger's own ledger
    slice. The route exists for telemetry / debugging, not for any
    privileged action.

    Per-game rate cap (300 events / 60s) is enforced in
    :class:`GameRuntimeLog`; over the cap returns 429 and the GDScript
    autoload backs off (or silently drops).
    """
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"game '{game_id}' not found")

    from src.api.services.game_runtime_log import (
        RateLimitedError,
        default_runtime_log,
    )

    try:
        default_runtime_log.append(
            game_id,
            event.kind,
            event.data,
            session_id=event.session_id,
        )
    except RateLimitedError as e:
        raise HTTPException(status_code=429, detail=str(e),
                            headers={"Retry-After": "60"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/games/{game_id}/playthrough", dependencies=[Depends(require_game_owner)])
async def get_playthrough(
    game_id: str,
    limit: int = 200,
    kind: Optional[str] = None,
):
    """Return recent runtime events for a game.

    Public read for now (matches the public POST). Frontend uses this to
    render an "in-game activity" panel on the game detail page and on the
    spend-badge Operations tab.
    """
    from src.api.services.game_runtime_log import default_runtime_log

    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"game '{game_id}' not found")

    kinds = {k.strip() for k in kind.split(",")} if kind else None
    events = default_runtime_log.events_for_game(
        game_id, limit=min(limit, 1000), kinds=kinds
    )
    summary = default_runtime_log.summary_for_game(game_id)
    return {"summary": summary, "events": events}


@router.delete("/games/{game_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_game_owner)])
async def delete_game(
    game_id: str,
    current_user: User = Depends(get_current_user),
):
    """Hard-delete a Godot game: removes the on-disk directory tree.

    Irreversible. The frontend gates this behind a two-step confirm so a
    misclick can't trigger it. There is no DB row for godot games today —
    `generated_games/<id>/` is the source of truth — so we just rm -rf and
    return 204.
    """
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )
    import shutil
    game_path = get_game_path(game_id)
    shutil.rmtree(game_path)
    return None


@router.patch("/games/{game_id}", response_model=GameInfoResponse, dependencies=[Depends(require_game_owner)])
async def rename_game(
    game_id: str,
    request: RenameGameRequest,
    current_user: User = Depends(get_current_user),
):
    """Rename a Godot game (updates `config/name` in project.godot)."""
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )
    game_path = get_game_path(game_id)
    game_service = GodotGameService(settings)
    try:
        game_service.write_name(game_path, request.name)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return GameInfoResponse(
        game_id=game_id,
        name=game_service.read_name(game_path),
        game_path=str(game_path),
        has_plan=bool(game_service.read_artifact(game_path, "PLAN.md")),
        has_structure=bool(game_service.read_artifact(game_path, "STRUCTURE.md")),
        has_video=(game_path / "screenshots" / "presentation" / "gameplay.mp4").exists(),
        has_export=(game_path / "dist" / "index.html").exists(),
        engine="godot",
        can_edit=True, visibility=read_access(game_id).visibility,
    )


@router.get("/games/{game_id}/progress", dependencies=[Depends(require_game_owner)])
async def get_progress(game_id: str):
    """Get live build progress by inspecting game directory.

    Useful for polling during sub-agent execution when SSE goes quiet.
    """
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")

    game_path = get_game_path(game_id)
    game_service = GodotGameService(settings)

    # Count files
    scripts = list((game_path / "scripts").glob("*.cs")) if (game_path / "scripts").exists() else []
    scenes = list((game_path / "scenes").glob("*.tscn")) if (game_path / "scenes").exists() else []
    screenshots = list(game_path.rglob("screenshots/**/*.png"))
    assets = list(game_path.rglob("assets/**/*")) if (game_path / "assets").exists() else []

    # Parse PLAN.md task statuses
    plan_content = game_service.read_artifact(game_path, "PLAN.md")
    tasks = []
    if plan_content:
        import re
        for match in re.finditer(r'## (\d+)\. (.+?)$.*?\*\*Status:\*\*\s*(\S+(?:\s*\([^)]*\))?)', plan_content, re.MULTILINE | re.DOTALL):
            tasks.append({
                "number": int(match.group(1)),
                "name": match.group(2).strip(),
                "status": match.group(3).strip(),
            })

    return {
        "game_id": game_id,
        "scripts": len(scripts),
        "scenes": len(scenes),
        "screenshots": len(screenshots),
        "assets": len([a for a in assets if a.is_file()]),
        "has_plan": plan_content is not None,
        "has_structure": game_service.read_artifact(game_path, "STRUCTURE.md") is not None,
        "has_video": (game_path / "screenshots" / "presentation" / "gameplay.mp4").exists(),
        "has_export": (game_path / "dist" / "index.html").exists(),
        "tasks": tasks,
    }


@router.get("/games/{game_id}/log", dependencies=[Depends(require_game_owner)])
async def get_creation_log(game_id: str, tail: int = 0):
    """Return the persisted creation log for a game.

    The pipeline writes every event to .creation/events.jsonl during creation
    and a summary.json on exit (success, partial, failed, or crashed). This
    endpoint surfaces both so failures can be diagnosed after the SSE stream
    has closed.

    Args:
        tail: If > 0, only the last N events are returned.
    """
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")

    game_path = get_game_path(game_id)
    creation_dir = game_path / ".creation"

    if not creation_dir.exists():
        return {
            "game_id": game_id,
            "summary": None,
            "events": [],
            "note": "No creation log — game predates the logging feature or was created outside the pipeline.",
        }

    summary = None
    summary_file = creation_dir / "summary.json"
    if summary_file.exists():
        try:
            summary = json.loads(summary_file.read_text())
        except Exception as e:
            summary = {"error": f"Failed to parse summary.json: {e}"}

    events: list[dict] = []
    events_file = creation_dir / "events.jsonl"
    if events_file.exists():
        for line in events_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue

    if tail > 0:
        events = events[-tail:]

    return {
        "game_id": game_id,
        "summary": summary,
        "events": events,
    }


@router.post("/games/{game_id}/modify", response_model=ModifyGameResponse, dependencies=[Depends(require_game_owner)])
async def modify_game(game_id: str, request: ModifyGameRequest, current_user: User = Depends(get_current_user)):
    """Modify a Godot game with natural language instruction.

    First tries fast @export var modification. Falls back to full agent
    for complex changes.
    """
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )

    game_path = get_game_path(game_id)
    game_service = GodotGameService(settings)
    executor = get_executor(settings)
    service = GodotModificationService(executor, game_service)

    mod_request = GodotModificationRequest(
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

    failures = await verify_browser(game_path, "godot", game_service.verify_playable(game_path), require_pip=True)
    if failures:
        final_success = False
        last_error = "; ".join(failures)
    return ModifyGameResponse(
        success=final_success and not last_error,
        changes=last_changes,
        explanation=last_content,
        error=last_error,
    )


@router.post("/games/{game_id}/modify/stream", dependencies=[Depends(require_game_owner)])
async def modify_game_stream(
    game_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Modify a Godot game with streaming progress updates (SSE).

    Accepts either ``application/json`` (``{"instruction": "..."}``) or
    ``multipart/form-data`` with an ``instruction`` form field and an optional
    ``image`` upload. When an image is present it is saved under
    ``<game>/_user_uploads/`` and the instruction is augmented with a
    reference-image directive for the modify skill.
    """
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )

    content_type = (request.headers.get("content-type") or "").lower()
    game_path = get_game_path(game_id)
    image_path: Optional[Path] = None

    if "multipart/form-data" in content_type:
        # Fast reject: bail before parsing if Content-Length already exceeds limit.
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > UPLOAD_MAX_BYTES + 64 * 1024:
            raise HTTPException(status_code=400, detail="request body too large")

        form = await request.form()
        instruction = (form.get("instruction") or "").strip()
        if not instruction:
            raise HTTPException(status_code=400, detail="instruction required")

        upload = form.get("image")
        if isinstance(upload, StarletteUploadFile):
            data = await upload.read()
            try:
                validate_image(upload.content_type, len(data), data)
            except UploadError as e:
                raise HTTPException(status_code=400, detail=str(e))
            image_path = save_upload(game_path, upload.filename or "upload", data)
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON body")
        instruction = (body.get("instruction") or "").strip()
        if not instruction:
            raise HTTPException(status_code=400, detail="instruction required")
        if body.get("reference_image") is not None:
            try:
                reference = VisualReference.model_validate(body["reference_image"])
            except ValueError as error:
                raise HTTPException(400, "Invalid reference image") from error
            data = decode_reference(reference)
            image_path = save_reference(game_path, reference, data)

    if image_path is not None:
        instruction = reference_instruction(instruction, image_path)

    # Rate limit: one modification at a time per game, max N concurrent globally
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

    game_service = GodotGameService(settings)
    executor = get_executor(settings)
    service = GodotModificationService(executor, game_service)

    mod_request = GodotModificationRequest(
        instruction=instruction,
        game_path=game_path,
    )
    run_id = uuid.uuid4().hex[:10]
    event_log = GameEventLog(game_path, log_dir=f".modifications/{run_id}")
    event_log.append({
        "event_type": "init",
        "type": "status",
        "content": "Modification queued",
        "timestamp": utc_now_iso(),
        # `instruction` is persisted so the modify panel can offer a
        # "Retry with same instruction" button after a failed run without
        # the user retyping. Also helps debugging — every event log shows
        # what was asked for at the top.
        "metadata": {
            "game_id": game_id,
            "run_id": run_id,
            "engine": "godot",
            "instruction": instruction,
            "has_image": image_path is not None,
            "attachments": reference_attachments(game_path, instruction),
        },
    })

    start_job(game_id,
        _run_modification_to_log(
            game_id=game_id,
            game_path=game_path,
            run_id=run_id,
            instruction=instruction,
            engine="godot",
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
    engine: str,
    service,
    mod_request,
    event_log: GameEventLog,
    game_service,
    notification_email: Optional[str],
    notify_on_success: bool,
) -> None:
    last_content = ""
    last_changes: list[str] = []
    last_error: Optional[str] = None
    final_success = False
    export_status: Optional[str] = None
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
            if isinstance(metadata, dict) and metadata.get("export_status"):
                export_status = str(metadata["export_status"])

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
        verification_failures = await verify_browser(game_path, "godot", game_service.verify_playable(game_path), require_pip=True)
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
        terminal = {
            "timestamp": utc_now_iso(),
            "event_type": "done" if terminal_success else "failed",
            "type": "complete" if terminal_success else "error",
            "content": final_message,
            "metadata": {
                "game_id": game_id,
                "run_id": run_id,
                "engine": engine,
                "changes": last_changes,
                "explanation": last_content,
                "success": terminal_success,
                "status": status_value,
                "has_export": has_export,
                "has_playable_build": has_playable_build,
                "export_status": export_status,
                "verification_failures": verification_failures,
                "new_screenshots": screenshot_names_since(game_path, start_wall_time),
            },
        }
        event_log.append(terminal)
        event_log.write_summary(build_modification_summary(
            game_id=game_id,
            engine=engine,
            run_id=run_id,
            instruction=instruction,
            status=status_value,
            started_at=started_at,
            finished_at=utc_now_iso(),
            duration_seconds=time.perf_counter() - start_time,
            event_count=len(persisted_events) + 2,  # init + streamed events + terminal
            final_message=final_message,
            explanation=last_content,
            changes=last_changes,
            error=None if terminal_success else last_error,
            has_export=has_export,
            has_playable_build=has_playable_build,
            verification_failures=verification_failures,
            events=persisted_events,
            new_screenshots=screenshot_names_since(game_path, start_wall_time),
            export_status=export_status,
        ))
        if terminal_success and notify_on_success and notification_email:
            await _send_game_modified_notification(
                notification_email,
                game_id,
                engine,
                game_service.read_name(game_path),
            )
    except Exception as exc:
        logger.exception("modification task crashed for game=%s", game_id)
        event_log.append({
            "event_type": "crashed",
            "type": "error",
            "content": f"{type(exc).__name__}: {exc}",
            "metadata": {"game_id": game_id, "run_id": run_id, "engine": engine},
        })
        try:
            event_log.write_summary(build_modification_summary(
                game_id=game_id,
                engine=engine,
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
                export_status=export_status,
            ))
        except Exception:
            logger.exception("failed to write modification summary for game=%s", game_id)
    finally:
        _active_modifications.pop(game_id, None)


@router.get("/games/{game_id}/screenshot", dependencies=[Depends(require_game_viewer)])
async def get_screenshot(game_id: str):
    """Get the most representative image for a Godot game.

    Lookup order (most → least preferred):
      1. Latest PNG in `screenshots/` — what godogen-capture writes.
      2. Frame extracted from `screenshots/presentation/gameplay.mp4`.
      3. Latest PNG anywhere under `assets/` — surfaces in-progress
         sprites, backgrounds, or asset-tool outputs during the
         ~5-minute window before the first real screenshot exists.
      4. 204 No Content with the canonical "no image yet" signal.

    Deliberately does NOT require `project.godot` — a fresh build needs
    a polling-friendly endpoint *before* scaffold completes (the
    frontend's preview tile starts polling at the init event). The
    `<game_id>/.creation/events.jsonl` is a sufficient existence
    proof; project.godot only matters for `/play`.
    """
    game_path = get_game_path(game_id)
    # Existence via either project.godot OR the creation event log —
    # the second covers builds that are still in scaffold phase.
    creation_log = game_path / ".creation" / "events.jsonl"
    if not (game_path.is_dir() and (
        (game_path / "project.godot").exists() or creation_log.is_file()
    )):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )

    trusted_capture = await verified_screenshot(game_path)
    if trusted_capture is not None:
        return FileResponse(trusted_capture, media_type="image/png", headers={"Cache-Control": "private, no-store"})

    screenshots_dir = game_path / "screenshots"

    # 1. Real screenshots from godogen-capture (preferred).
    if screenshots_dir.exists():
        png_files = sorted(
            screenshots_dir.glob("*.png"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if png_files:
            return FileResponse(
                png_files[0],
                media_type="image/png",
                headers={"Cache-Control": "no-store"},
            )

    # 2. Presentation video frame extraction.
    video_path = screenshots_dir / "presentation" / "gameplay.mp4"
    if video_path.exists():
        thumb_path = screenshots_dir / "thumbnail.png"
        if not thumb_path.exists():
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(video_path), "-ss", "3", "-frames:v", "1", str(thumb_path)],
                    capture_output=True, timeout=10,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        if thumb_path.exists():
            return FileResponse(thumb_path, media_type="image/png")

    # 3. In-progress asset fallback. During the first ~5 minutes of a
    #    build, godogen is generating sprites/backgrounds/etc. under
    #    assets/. Surfacing the newest one gives the user a real
    #    "your build is making things" preview instead of a broken
    #    image icon. Scoped to a few well-known subdirs so we don't
    #    accidentally serve a .png from inside a node_modules-style
    #    tree (godot doesn't have one, but defense in depth).
    asset_candidates: list[Path] = []
    for sub in ("assets/img", "assets/sprites", "assets/bg", "assets/tmp/qa"):
        d = game_path / sub
        if d.is_dir():
            asset_candidates.extend(p for p in d.rglob("*.png") if p.is_file())
    if asset_candidates:
        latest = max(asset_candidates, key=lambda p: p.stat().st_mtime)
        return FileResponse(
            latest,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    # 4. Nothing yet — serve a 1×1 transparent PNG with 200 so the
    # frontend's <img> renders quietly (no broken-icon, no log spam,
    # no 404). Browsers treat 204 on <img> as "load failed" and show
    # the broken-image placeholder, defeating the point. A literal
    # 67-byte transparent PNG is the minimum that lets the image load
    # cleanly and means "we'll have something real soon — keep polling."
    # `Cache-Control: no-store` so a real screenshot replaces it
    # immediately on the next poll.
    _TRANSPARENT_1x1_PNG = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f"
        b"\x00\x01\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return Response(
        content=_TRANSPARENT_1x1_PNG,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Tinyworlds-Placeholder": "1"},
    )


@router.get("/games/{game_id}/events", dependencies=[Depends(require_game_owner)])
async def get_game_events(game_id: str):
    """Return the creation-time event log for a game so the UI can replay
    the build.

    The godot creation agent persists every SSE event to
    ``<game_path>/.creation/events.jsonl``. This endpoint serves that file
    parsed as JSON so the frontend can render it with the same components
    used in the live stream view.

    Returns ``{"events": [...], "summary": {...} | null}`` — summary is
    the contents of ``.creation/summary.json`` when present (status,
    duration, has_export, etc.).
    """
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")

    game_path = get_game_path(game_id)
    events_path = game_path / ".creation" / "events.jsonl"
    summary_path = game_path / ".creation" / "summary.json"

    events: list[dict] = []
    if events_path.is_file():
        for line in events_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip malformed lines rather than 500ing — the JSONL is
                # append-only and a partial flush could leave a half line.
                continue

    summary: Optional[dict] = None
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text())
        except json.JSONDecodeError:
            summary = None

    return {"events": events, "summary": summary, "game_id": game_id}


@router.get("/games/{game_id}/history", dependencies=[Depends(require_game_owner)])
async def get_game_history(game_id: str):
    """Get modification history from MEMORY.md."""
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")

    game_path = get_game_path(game_id)
    game_service = GodotGameService(settings)
    memory = game_service.read_artifact(game_path, "MEMORY.md")
    if not memory:
        return {"game_id": game_id, "history": []}

    import re
    entries: list[dict] = []
    # Parse ## Modification: ... sections
    sections = re.split(r'^## ', memory, flags=re.MULTILINE)
    for section in sections:
        if not section.startswith("Modification:"):
            continue
        lines = section.strip().split("\n")
        title = lines[0].replace("Modification:", "").strip()
        details = []
        for line in lines[1:]:
            line = line.strip()
            if line.startswith("- ") and not line.startswith("- **Status:**"):
                details.append(line[2:])
        entries.append({"instruction": title, "changes": details})

    return {"game_id": game_id, "history": entries}


@router.get("/games/{game_id}/media", dependencies=[Depends(require_game_owner)])
async def list_game_media(game_id: str):
    """List all screenshots and videos for a game."""
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")

    game_path = get_game_path(game_id)
    screenshots_dir = game_path / "screenshots"

    screenshots: list[dict] = []
    videos: list[dict] = []

    # Trusted browser captures live outside the agent-writable game directory.
    # New runtime builds may have only this capture, with no legacy screenshots.
    # Serve it through the existing authenticated endpoint, never as an asset path.
    if await verified_screenshot(game_path) is not None:
        screenshots.append({
            "path": "verification/canvas.png",
            "name": "Game preview",
            "url": f"/api/v1/godot/games/{game_id}/screenshot",
        })

    if screenshots_dir.exists():
        # Collect screenshots from all subdirectories
        for png in sorted(screenshots_dir.rglob("*.png")):
            rel = str(png.relative_to(game_path))
            screenshots.append({
                "path": rel,
                "name": png.name,
                "url": f"/api/v1/godot/games/{game_id}/assets/{rel}",
            })

        # Collect videos
        for ext in ("*.mp4", "*.webm", "*.avi"):
            for vid in sorted(screenshots_dir.rglob(ext)):
                rel = str(vid.relative_to(game_path))
                videos.append({
                    "path": rel,
                    "name": vid.name,
                    "url": f"/api/v1/godot/games/{game_id}/assets/{rel}",
                })

    return {"game_id": game_id, "screenshots": screenshots, "videos": videos}


@router.get("/games/{game_id}/video", dependencies=[Depends(require_game_viewer)])
async def get_video(game_id: str):
    """Get the presentation video for a Godot game."""
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )

    video_path = get_game_path(game_id) / "screenshots" / "presentation" / "gameplay.mp4"

    if not video_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Presentation video not yet available for this game",
        )

    return FileResponse(video_path, media_type="video/mp4")


@router.get("/games/{game_id}/suggestions", dependencies=[Depends(require_game_owner)])
async def get_suggestions(game_id: str):
    """Return cached modification suggestions or ``{pending: true}``.

    Suggestions are generated best-effort after creation/modify via a
    one-shot CLI call and persisted to ``suggestions.json`` in the game
    directory. Absent file == still pending (or generator failed).
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


@router.get("/games/{game_id}/plan", dependencies=[Depends(require_game_owner)])
async def get_plan(game_id: str):
    """Get the PLAN.md content for a Godot game."""
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )

    game_path = get_game_path(game_id)
    game_service = GodotGameService(settings)
    plan = game_service.read_artifact(game_path, "PLAN.md")

    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PLAN.md not yet generated for this game",
        )

    return {"game_id": game_id, "content": plan}


@router.get("/games/{game_id}/structure", dependencies=[Depends(require_game_owner)])
async def get_structure(game_id: str):
    """Get the STRUCTURE.md content for a Godot game."""
    if not game_exists(game_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found",
        )

    game_path = get_game_path(game_id)
    game_service = GodotGameService(settings)
    structure = game_service.read_artifact(game_path, "STRUCTURE.md")

    if structure is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="STRUCTURE.md not yet generated for this game",
        )

    return {"game_id": game_id, "content": structure}


# -------------------------------------------------------------------
# Game Play (HTML5 Web Export)
# -------------------------------------------------------------------

ASSET_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".glb": "model/gltf-binary",
    ".tres": "application/octet-stream",
    ".tscn": "application/octet-stream",
}


@router.get("/games/{game_id}/assets/{file_path:path}", dependencies=[Depends(require_game_asset_owner)])
async def serve_game_asset(game_id: str, file_path: str):
    """Serve raw asset files from a game directory (images, videos, etc.)."""
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")

    game_path = get_game_path(game_id)
    asset_file = game_path / file_path

    # Security: reject path traversal
    try:
        asset_file.resolve().relative_to(game_path.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if not asset_file.exists() or not asset_file.is_file():
        raise HTTPException(status_code=404, detail=f"Asset not found: {file_path}")

    ext = Path(file_path).suffix.lower()
    content_type = ASSET_CONTENT_TYPES.get(ext, "application/octet-stream")
    return FileResponse(asset_file, media_type=content_type)


WASM_CONTENT_TYPES = {
    ".html": "text/html",
    ".js": "application/javascript",
    ".wasm": "application/wasm",
    ".pck": "application/octet-stream",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


# Injected into every served Godot index.html. Captures errors, console
# warn/error, JS heap samples, WebGL context-loss, and Godot heartbeat
# (window.__godotState if the game writes one), and ships them via
# sendBeacon on visibilitychange/pagehide so we get data even when the
# tab dies. ~5s rolling buffer is enough to diagnose tab crashes.
_TELEMETRY_SHIM = """
<script>
(function() {
  var GAME_ID = "__GAME_ID__";
  var SESSION = (crypto.randomUUID && crypto.randomUUID()) || (Date.now() + "-" + Math.random().toString(36).slice(2));
  var ENDPOINT = "/api/v1/godot/games/" + GAME_ID + "/telemetry";
  var BUFFER_MAX = 500;
  var buf = [];
  function push(kind, payload) {
    buf.push({t: Date.now(), kind: kind, ...payload});
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
  // Capture uncaught errors
  window.addEventListener("error", function(e) {
    push("error", {message: String(e.message), source: e.filename, line: e.lineno, col: e.colno, stack: e.error && e.error.stack});
  });
  window.addEventListener("unhandledrejection", function(e) {
    push("unhandledrejection", {message: String(e.reason && e.reason.message || e.reason), stack: e.reason && e.reason.stack});
  });
  // Wrap console.warn/error (keep originals running so DevTools still shows them)
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
  // Heap + Godot state sampler. Also acts as a freeze watchdog: if the
  // interval fires noticeably late, the JS thread was blocked (typically
  // by the WASM main loop hanging) and we record a "frozen" event so we
  // can distinguish slow-stall failures from clean JS-error crashes.
  // We have to be careful about backgrounded tabs — browsers clamp
  // setInterval to >=1s and pause RAF when document.hidden, so the next
  // tick after unhide sees a huge drift even though the WASM thread is
  // perfectly healthy. Skip the drift check while hidden, and reset the
  // baseline whenever visibility flips back to visible.
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
    if (window.__godotState) sample.godot = window.__godotState;
    push("sample", sample);
    if (drift > 3000) {
      push("frozen", {drift: drift});
      flush("frozen");
    }
  }, 1000);
  // Expose push/flush so the server-side HTML rewrite can wire them into
  // `engine.startGame({onPrint, onPrintError})`. We can't patch Engine from
  // here because it's declared `const Engine = ...` at script top level —
  // not on window — so `typeof Engine` resolves to undefined from this
  // separate <script> block. The serve_game_file route handles the wiring.
  window.__tw_push = push;
  window.__tw_flush = flush;
  // WebGL context loss
  function attachCanvasListeners() {
    var c = document.getElementById("canvas");
    if (!c) return setTimeout(attachCanvasListeners, 250);
    c.addEventListener("webglcontextlost", function(e) {
      push("webglcontextlost", {});
      flush("webglcontextlost");
    });
    c.addEventListener("webglcontextrestored", function() {
      push("webglcontextrestored", {});
    });
  }
  attachCanvasListeners();
  // Periodic flush so we don't lose data on a hard crash that skips pagehide
  setInterval(function() { flush("interval"); }, 5000);
  document.addEventListener("visibilitychange", function() {
    if (document.visibilityState === "hidden") flush("visibilitychange");
  });
  window.addEventListener("pagehide", function() { flush("pagehide"); });
  window.__telemetryFlush = flush;
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
    response = RedirectResponse(f"/api/v1/godot/games/{game_id}/play/index.html{embedded}")
    if current_user is not None:
        from datetime import timedelta
        from src.api.core.security import create_access_token
        media_token = create_access_token({"sub": str(current_user.id), "purpose": "game-media", "game_id": game_id}, expires_delta=timedelta(minutes=5))
        response.set_cookie("tw_game_media", media_token, max_age=300, httponly=True, secure=request.url.scheme == "https" or settings.GAME_PLAY_ORIGIN.startswith("https://"), samesite="lax", path=f"/api/v1/godot/games/{game_id}/")
    return response


@router.get("/games/{game_id}/play/{file_path:path}", dependencies=[Depends(require_game_viewer)])
async def serve_game_file(game_id: str, file_path: str, request: Request):
    """Serve HTML5 exported game files with COEP/COOP headers for SharedArrayBuffer."""
    isolated = isolated_play_redirect(request)
    if isolated is not None:
        return isolated
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")

    dist_file = get_game_path(game_id) / "dist" / file_path
    if not dist_file.exists() or not dist_file.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    # Security: reject path traversal
    try:
        dist_file.resolve().relative_to((get_game_path(game_id) / "dist").resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    cache_headers = versioned_play_asset_headers(dist_file, request)
    if read_access(game_id).visibility != "public":
        cache_headers.update({key: "private, no-store" for key in ("Cache-Control", "CDN-Cache-Control", "Cloudflare-CDN-Cache-Control")})
    etag = cache_headers["ETag"]
    inm = request.headers.get("if-none-match", "")
    # Caddy rewrites ETag to `"<orig>-zstd"` when it compresses; strip any
    # such suffix from the client's reported ETag before matching ours.
    inm_clean = inm.strip()
    if inm_clean.endswith('-zstd"') or inm_clean.endswith('-gzip"') or inm_clean.endswith('-br"'):
        inm_clean = inm_clean.rsplit("-", 1)[0] + '"'
    if inm_clean and inm_clean == etag:
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": cache_headers["Cache-Control"],
                "CDN-Cache-Control": cache_headers["CDN-Cache-Control"],
                "Cloudflare-CDN-Cache-Control": cache_headers["Cloudflare-CDN-Cache-Control"],
                "Cross-Origin-Embedder-Policy": "require-corp",
                "Cross-Origin-Opener-Policy": "same-origin",
            },
        )

    ext = Path(file_path).suffix.lower()
    content_type = WASM_CONTENT_TYPES.get(ext, "application/octet-stream")

    coop_coep = {
        "Cross-Origin-Embedder-Policy": "require-corp",
        "Cross-Origin-Opener-Policy": "same-origin",
    }
    if ext == ".html":
        coop_coep["Cache-Control"] = "no-store"
        coop_coep["CDN-Cache-Control"] = "no-store"
        coop_coep["Cloudflare-CDN-Cache-Control"] = "no-store"
    else:
        coop_coep.update(cache_headers)

    if ext == ".html":
        html = dist_file.read_text(encoding="utf-8")
        html = inject_play_asset_cache_buster(
            html,
            dist_asset_versions(dist_file.parent),
        )
        html = inject_mobile_play_shim(html)
        from src.api.services.pip_bridge import inject_pip_bridge
        html = inject_pip_bridge(html, settings.FRONTEND_URL)
        if request.query_params.get("embedded") == "1":
            from src.api.services.mobile_support import inject_embedded_play_focus
            html = inject_embedded_play_focus(html)
        # Inject onPrint/onPrintError callbacks into the engine.startGame
        # config object before injecting the shim (the shim's comment also
        # contains "engine.startGame(" so it must run after this rewrite).
        # Godot 4's HTML template calls `engine.startGame({'onProgress':...})`
        # and doesn't expose these hooks any other way, so this is the only
        # path to capture engine stderr (renderer feature mismatches, shader
        # errors, missing resources) into our telemetry stream.
        html = html.replace(
            "engine.startGame({",
            "engine.startGame({"
            "'onPrint':function(m){if(window.__tw_push)window.__tw_push('godot.print',{msg:String(m).slice(0,500)});},"
            "'onPrintError':function(m){if(window.__tw_push){window.__tw_push('godot.printErr',{msg:String(m).slice(0,500)});window.__tw_flush('printErr');}},",
            1,
        )
        if request.query_params.get("embedded") == "1":
            from src.api.services.preview_lifecycle import inject_preview_lifecycle
            html = inject_preview_lifecycle(html)
        shim = _TELEMETRY_SHIM.replace("__GAME_ID__", game_id)
        if "</head>" in html:
            html = html.replace("</head>", shim + "</head>", 1)
        else:
            html = shim + html
        return HTMLResponse(content=html, headers=coop_coep)

    response = FileResponse(dist_file, media_type=content_type)
    for k, v in coop_coep.items():
        response.headers[k] = v
    response.headers["ETag"] = f'"{asset_version(dist_file)}"'
    return response


@router.post("/games/{game_id}/telemetry", dependencies=[Depends(require_game_viewer)])
async def post_telemetry(game_id: str, request: Request):
    """Append browser telemetry events (errors, console, heap, WebGL) as NDJSON.

    Stored at generated_games/{game_id}/telemetry/{session}.ndjson. Used to
    diagnose tab crashes that kill the page before stderr can be inspected.
    """
    if not game_exists(game_id):
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    session = str(body.get("session", "unknown"))[:64]
    # Sanitize session id — allow only safe filename chars.
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
            # Mirror runtime failure signals into the cross-game failure log
            # so passive learning sees them. Only log the "interesting" events
            # — frozen frames, JS errors, godot stderr — not heap samples.
            kind = ev.get("kind")
            if kind == "frozen":
                _record_failure(
                    game_id=game_id, engine="godot", stage="telemetry",
                    rule="frozen_thread",
                    detail=f"drift={ev.get('drift')}ms session={safe_session}",
                )
            elif kind == "godot.printErr":
                # Godot's HTML5 export routes benign bootstrap status through
                # printErr (loader progress, dependency-wait noise). Skip the
                # known-noise lines so the corpus only captures real errors.
                # See playthrough.md.
                msg = str(ev.get("msg", ""))
                msg_stripped = msg.strip()
                if (
                    msg_stripped.startswith("still waiting on run dependencies")
                    or msg_stripped.startswith("dependency: ")
                    or msg_stripped == "(end of list)"
                ):
                    continue
                _record_failure(
                    game_id=game_id, engine="godot", stage="telemetry",
                    rule="godot_print_err",
                    detail=msg[:400],
                )
            elif kind == "error":
                _record_failure(
                    game_id=game_id, engine="godot", stage="telemetry",
                    rule="js_error",
                    detail=str(ev.get("message", ""))[:400],
                )
    return {"ok": True, "received": len(events)}
