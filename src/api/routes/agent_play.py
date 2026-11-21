"""Account-scoped reference game sessions, separate from source-editing jobs."""
from typing import Literal

from fastapi import APIRouter, Depends, Response, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api.dependencies import get_current_user, require_game_viewer
from src.api.models.user import User
from src.api.services.agent_play import arena
from src.api.services.game_companion import companions, GameSync, GameAction

router = APIRouter(prefix="/agent-play", tags=["agent-play"])


class NewSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["coop", "versus"] = "coop"
    controller: Literal["builtin", "external"] = "builtin"


class PlayAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    player: Literal["human", "agent"]
    action: Literal["up", "down", "left", "right", "wait"]
    expected_revision: int = Field(ge=0, strict=True)


class ConnectSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["coop", "versus"] | None = None
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    new_round: bool = False



@router.post("/games/{game_id}/sync", dependencies=[Depends(require_game_viewer)])
async def sync_game(game_id: str, body: GameSync, response: Response, user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return companions.sync(str(user.id), game_id, body)


@router.post("/games/join")
async def join_game(response: Response, user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return companions.read(str(user.id), join=True)


@router.get("/games/current")
async def current_game(response: Response, user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return companions.read(str(user.id))


@router.get("/games/sessions/{session_id}")
async def read_game(session_id: str, response: Response, user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return companions.read(str(user.id), session_id)


@router.post("/games/sessions/{session_id}/actions")
async def game_action(session_id: str, body: GameAction, user: User = Depends(get_current_user)):
    return companions.action(str(user.id), session_id, body)


def _generated_or_arena(owner: str, session_id: str | None = None, join: bool = False):
    try:
        return companions.read(owner, session_id, join=join)
    except HTTPException as error:
        if error.status_code != 404:
            raise
        if session_id:
            return arena.read(session_id, owner)
        return arena.connect(owner, join=True) if join else arena.current(owner)


@router.post("/auto/join")
async def auto_join(user: User = Depends(get_current_user)):
    return _generated_or_arena(str(user.id), join=True)


@router.get("/auto/state")
async def auto_state(response: Response, session_id: str | None = None, user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return _generated_or_arena(str(user.id), session_id)


@router.post("/auto/{session_id}/actions")
async def auto_action(session_id: str, body: GameAction, user: User = Depends(get_current_user)):
    owner = str(user.id)
    state = _generated_or_arena(owner, session_id)
    if state["game"] == "dot-arena-v1":
        return arena.action(session_id, owner, "agent", body.action, body.expected_revision)
    return companions.action(owner, session_id, body)


@router.delete("/auto/{session_id}", status_code=204)
async def auto_close(session_id: str, user: User = Depends(get_current_user)):
    owner = str(user.id)
    state = _generated_or_arena(owner, session_id)
    if state["game"] == "dot-arena-v1":
        arena.close(session_id, owner)
    else:
        companions.close(owner, session_id)


@router.post("/connect")
async def connect(body: ConnectSession, user: User = Depends(get_current_user)):
    return arena.connect(str(user.id), **body.model_dump())


@router.post("/join")
async def join(body: ConnectSession, user: User = Depends(get_current_user)):
    return arena.connect(str(user.id), join=True, **body.model_dump())


@router.get("/current")
async def current(response: Response, user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return arena.current(str(user.id))


@router.post("", status_code=201)
async def create_session(body: NewSession, user: User = Depends(get_current_user)):
    return arena.create(str(user.id), body.mode, body.controller)


@router.get("/{session_id}")
async def get_session(session_id: str, response: Response, user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return arena.read(session_id, str(user.id))


@router.post("/{session_id}/actions")
async def act(session_id: str, body: PlayAction, user: User = Depends(get_current_user)):
    return arena.action(session_id, str(user.id), body.player, body.action, body.expected_revision)


@router.delete("/{session_id}", status_code=204)
async def close(session_id: str, user: User = Depends(get_current_user)):
    arena.close(session_id, str(user.id))
