"""Engine-agnostic umbrella router for game create + list.

Mounted at ``/api/v1/games``. Two endpoints:

* ``POST /games`` — reads ``settings.DEFAULT_GAME_ENGINE`` and dispatches
  to the godot or bevy creation pipeline. The first SSE event is an
  ``init`` payload that carries both ``game_id`` and ``engine`` so the
  frontend knows which engine-specific routes to hit afterwards for
  play/info/video/screenshot/rename.
* ``GET /games`` — merges both engines' game lists into a unified
  response, each item tagged with ``engine``. If one side raises, log a
  warning and continue with the other.

The engine-specific routes (``/api/v1/godot/...``, ``/api/v1/bevy/...``)
remain the right surface for everything else (play/info/video/etc.) —
this umbrella only owns create + list.

The ``UnifiedGameInfoResponse`` shape is duplicated locally (rather than
imported from either engine module) to keep this router decoupled from
the engine-specific routers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.services.visual_reference import VisualReference
from src.api.core.config import get_settings
from src.api.dependencies import (
    get_current_user,
    get_optional_current_user,
    require_game_owner,
)
from src.api.services.game_access import can_view, game_path, read_access, is_owner
from src.api.middleware.rate_limit import check_game_creation_rate_limit
from src.api.models.user import User
from src.api.services.bevy_game_service import BevyGameService
from src.api.services.godot_game_service import GodotGameService
from src.api.routes import bevy_games as _bevy_routes
from src.api.routes import godot_games as _godot_routes

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()


# -------------------------------------------------------------------
# Models
# -------------------------------------------------------------------




class UnifiedCreateGameRequest(BaseModel):
    """Request body for the umbrella create endpoint.

    Mirrors the per-engine request bodies — they're identical today.
    """

    description: str = Field(..., description="Natural language game description")
    budget_cents: Optional[int] = Field(
        None, ge=0, le=10000, description="Asset generation budget in cents"
    )
    engine: Literal["godot", "bevy"] | None = None
    visibility: Literal["public", "private", "unlisted"] = "public"
    reference_image: VisualReference | None = None


class UnifiedGameInfoResponse(BaseModel):
    """Unified game-info response carrying the engine discriminator."""

    game_id: str
    name: Optional[str] = None
    game_path: str
    has_plan: bool
    has_structure: bool
    has_video: bool
    has_export: bool
    engine: str
    can_edit: bool = False
    visibility: str = "public"


# -------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------


@router.get("/capabilities")
async def capabilities():
    from src.api.services.executors.runtime import UPSTREAM_COMMIT
    from src.api.services.personal_provider import read_connection
    connection = read_connection(settings) if settings.PERSONAL_MODE else None

    return {
        "provider": connection.provider if connection else settings.GAME_AGENT_PROVIDER,
        "personal_mode": settings.PERSONAL_MODE,
        "requires_provider_connection": settings.PERSONAL_MODE and connection is None,
        "execution_mode": settings.AGENT_EXECUTION_MODE,
        "engines": ["godot", "bevy"],
        "asset_budget_required": True,
        "upstream_revision": UPSTREAM_COMMIT,
    }


@router.post("", dependencies=[Depends(check_game_creation_rate_limit)])
async def create_game(
    request: UnifiedCreateGameRequest,
    current_user: User = Depends(get_current_user),
):
    """Create a new game using the engine selected by ``DEFAULT_GAME_ENGINE``.

    Streams SSE events from the underlying creation pipeline. The first
    event is ``{"event_type": "init", "game_id": ..., "engine": ...}``
    so the frontend can route subsequent calls (play/info/etc.) to the
    correct engine-specific endpoints.
    """
    engine = request.engine or settings.DEFAULT_GAME_ENGINE
    payload = request.model_dump(exclude={"engine"}, exclude_none=True)
    if engine == "bevy":
        return await _bevy_routes.create_game(
            _bevy_routes.BevyCreateGameRequest.model_validate(payload),
            current_user,
        )
    return await _godot_routes.create_game(
        _godot_routes.CreateGameRequest.model_validate(payload),
        current_user,
    )


def _godot_info(
    game_id: str, base: Path, svc: GodotGameService, current_user=None
) -> UnifiedGameInfoResponse:
    gp = game_path(game_id)
    return UnifiedGameInfoResponse(
        game_id=game_id,
        name=svc.read_name(gp),
        game_path=str(gp),
        has_plan=bool(svc.read_artifact(gp, "PLAN.md")),
        has_structure=bool(svc.read_artifact(gp, "STRUCTURE.md")),
        has_video=(gp / "screenshots" / "presentation" / "gameplay.mp4").exists(),
        has_export=(gp / "dist" / "index.html").exists(),
        engine="godot",
        can_edit=is_owner(read_access(game_id), current_user),
        visibility=read_access(game_id).visibility,
    )


def _bevy_info(
    game_id: str, base: Path, svc: BevyGameService, current_user=None
) -> UnifiedGameInfoResponse:
    gp = game_path(game_id)
    return UnifiedGameInfoResponse(
        game_id=game_id,
        name=svc.read_name(gp),
        game_path=str(gp),
        has_plan=bool(svc.read_artifact(gp, "PLAN.md")),
        has_structure=bool(svc.read_artifact(gp, "STRUCTURE.md")),
        has_video=(gp / "screenshots" / "presentation" / "gameplay.mp4").exists(),
        has_export=(gp / "dist" / "index.html").exists(),
        engine="bevy",
        can_edit=is_owner(read_access(game_id), current_user),
        visibility=read_access(game_id).visibility,
    )


def _resolve_engine(game_id: str) -> Optional[str]:
    """Disk-based engine discriminator for an existing game id.

    Mirrors the per-engine ``game_exists`` helpers: ``project.godot``
    means godot, ``Cargo.toml`` means bevy. Returns ``None`` if the
    directory doesn't exist or has neither marker.
    """
    gp = game_path(game_id)
    if not gp.is_dir():
        return None
    if (gp / "project.godot").exists():
        return "godot"
    if (gp / "Cargo.toml").exists():
        return "bevy"
    return None


@router.get("/{game_id}/suggestions", dependencies=[Depends(require_game_owner)])
async def get_suggestions(game_id: str):
    """Return cached modification suggestions for a game, dispatching by engine."""
    engine = _resolve_engine(game_id)
    if engine == "godot":
        return await _godot_routes.get_suggestions(game_id)
    if engine == "bevy":
        return await _bevy_routes.get_suggestions(game_id)
    raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")


@router.get("", response_model=list[UnifiedGameInfoResponse])
async def list_games(current_user: User | None = Depends(get_optional_current_user)):
    """List games from both engines, merged into one response.

    A failure on one side is logged and swallowed so the other side's
    games still surface.
    """
    base = Path(settings.GODOT_GAMES_DIR)
    results: list[UnifiedGameInfoResponse] = []

    try:
        godot_svc = GodotGameService(settings)
        godot_ids = [
            gid
            for gid in godot_svc.list_games(base)
            if can_view(gid, current_user, listing=True)
        ]
        results.extend(
            _godot_info(gid, base, godot_svc, current_user) for gid in godot_ids
        )
    except Exception:  # pragma: no cover — defensive
        logger.warning(
            "Failed to list godot games for umbrella endpoint", exc_info=True
        )

    try:
        bevy_svc = BevyGameService(settings)
        bevy_ids = [
            gid
            for gid in bevy_svc.list_games(base)
            if can_view(gid, current_user, listing=True)
        ]
        results.extend(
            _bevy_info(gid, base, bevy_svc, current_user) for gid in bevy_ids
        )
    except Exception:  # pragma: no cover — defensive
        logger.warning("Failed to list bevy games for umbrella endpoint", exc_info=True)

    return results


@router.post("/{game_id}/cancel", dependencies=[Depends(require_game_owner)])
async def cancel_generation(game_id: str):
    from src.api.services.game_jobs import cancel_job

    return {"cancelled": await cancel_job(game_id)}
