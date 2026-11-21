"""Short-lived, authenticated job requests for the TinyWorlds MCP gateway."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from src.api.dependencies import get_current_user, require_game_owner
from src.api.middleware.rate_limit import check_game_creation_rate_limit
from src.api.models.user import User
from src.api.routes import games, godot_games, bevy_games
from src.api.services.game_access import game_path
from src.api.services.browser_verification import verified_screenshot
from src.api.services.game_event_log import GameEventLog, TERMINAL_EVENT_TYPES

router = APIRouter()


class CreatePluginGame(games.UnifiedCreateGameRequest):
    description: str = Field(min_length=1, max_length=8000)
    budget_cents: int = Field(default=0, ge=0, le=10000)
    visibility: str = Field(default="private", pattern="^(public|private|unlisted)$")


async def _queued(response) -> dict:
    """Read only the persisted init frame; the background task owns execution."""
    iterator = response.body_iterator
    try:
        chunk = await anext(iterator)
        if isinstance(chunk, bytes):
            chunk = chunk.decode()
        for line in chunk.splitlines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                if event.get("event_type") == "init":
                    meta = event.get("metadata") or event
                    return {
                        "game_id": meta["game_id"],
                        "engine": meta["engine"],
                        "run_id": meta.get("run_id"),
                        "status": "queued",
                    }
        raise HTTPException(
            500, "Job started but receipt unavailable; inspect games before retrying"
        )
    finally:
        await iterator.aclose()


@router.post("/jobs", dependencies=[Depends(check_game_creation_rate_limit)])
async def create_job(payload: CreatePluginGame, user: User = Depends(get_current_user)):
    return await _queued(await games.create_game(payload, user))


@router.post("/games/{game_id}/modify", dependencies=[Depends(require_game_owner)])
async def modify_job(
    game_id: str, request: Request, user: User = Depends(get_current_user)
):
    body = await request.json()
    instruction = body.get("instruction")
    if (
        not isinstance(instruction, str)
        or not instruction.strip()
        or len(instruction) > 8000
    ):
        raise HTTPException(422, "Provide an instruction between 1 and 8000 characters")
    engine = games._resolve_engine(game_id)
    if engine == "godot":
        response = await godot_games.modify_game_stream(game_id, request, user)
    elif engine == "bevy":
        response = await bevy_games.modify_game_stream(
            game_id, bevy_games.BevyModifyGameRequest(instruction=instruction), user
        )
    else:
        raise HTTPException(404, "Game not found")
    return await _queued(response)


@router.get("/games/{game_id}/job", dependencies=[Depends(require_game_owner)])
async def job_status(game_id: str, run_id: str | None = None):
    if run_id is not None and not re.fullmatch(r"[a-zA-Z0-9]{1,32}", run_id):
        raise HTTPException(422, "Invalid modification run ID")
    project = game_path(game_id)
    directory = f".modifications/{run_id}" if run_id else ".creation"
    log = GameEventLog(project, log_dir=directory)
    if any(
        path.is_symlink()
        for path in (
            project / ".creation",
            project / ".modifications",
            log.events_file.parent,
            log.events_file,
        )
    ):
        raise HTTPException(409, "Job contains an unsafe symbolic link")
    if not log.exists():
        raise HTTPException(404, "Job not found")
    events = log.read_all()
    terminal = next(
        (e for e in reversed(events) if e.get("event_type") in TERMINAL_EVENT_TYPES),
        None,
    )
    initial = next((e for e in events if e.get("event_type") == "init"), {})
    engine = initial.get("engine") or initial.get("metadata", {}).get("engine")
    status = terminal["event_type"] if terminal else "running"
    verified = (
        await verified_screenshot(project) is not None if status == "done" else False
    )
    if status == "done" and not verified:
        status = "verification_missing"
    return {
        "game_id": game_id,
        "run_id": run_id,
        "engine": engine,
        "status": status,
        "browser_verified": verified,
        "event_count": len(events),
        # Include only application terminal evidence, never raw agent output.
        "failures": (terminal or {}).get("failures", []),
        "reason": (terminal or {}).get("reason"),
    }
