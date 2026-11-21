"""Trusted access records for the filesystem-backed game projects.

Access records are deliberately outside the agent's writable project mount.
Legacy projects remain publicly playable, but have no implicit owner.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import HTTPException

from src.api.core.config import get_settings


Visibility = Literal["public", "private", "unlisted"]
_GAME_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z")


def game_path(game_id: str) -> Path:
    if not _GAME_ID.fullmatch(game_id):
        raise HTTPException(404, "Game not found")
    root = Path(get_settings().GODOT_GAMES_DIR).resolve()
    path = root / game_id
    if path.is_symlink() or path.resolve().parent != root:
        raise HTTPException(404, "Game not found")
    return path


def metadata_path(game_id: str) -> Path:
    project = game_path(game_id)
    # A separate volume in production; never mounted into an agent container.
    root = project.parent.parent / "data" / "game-metadata"
    return root / f"{game_id}.json"


def ensure_no_symlinks(project: Path) -> None:
    """Agent files must not redirect trusted readers/writers outside a project."""
    if project.is_symlink():
        raise HTTPException(404, "Game not found")
    for root, directories, files in os.walk(project, followlinks=False):
        if any((Path(root) / name).is_symlink() for name in directories + files):
            raise HTTPException(409, "Game contains an unsafe symbolic link")


def isolated_play_redirect(request):
    """Active generated HTML must only execute on the dedicated playback origin."""
    from starlette.responses import RedirectResponse
    from urllib.parse import urlsplit

    origin = get_settings().GAME_PLAY_ORIGIN.rstrip("/")
    if not origin:
        return None
    target = urlsplit(origin)
    if (
        target.scheme not in {"http", "https"}
        or not target.netloc
        or target.path
        or target.query
        or target.fragment
        or target.username
        or target.password
    ):
        raise RuntimeError("GAME_PLAY_ORIGIN must be an HTTP origin without a path")
    if request.url.netloc != target.netloc:
        suffix = request.url.path
        if request.url.query:
            suffix += "?" + request.url.query
        return RedirectResponse(origin + suffix, headers={"Cache-Control": "no-store"})
    return None


@dataclass(frozen=True)
class GameAccess:
    owner_user_id: str | None
    visibility: Visibility


def read_access(game_id: str) -> GameAccess:
    path = metadata_path(game_id)
    if path.is_symlink():
        raise HTTPException(404, "Game not found")
    try:
        data = json.loads(path.read_text())
        owner = data["owner_user_id"]
        visibility = data["visibility"]
        if (
            not isinstance(owner, str)
            or not owner
            or visibility not in {"public", "private", "unlisted"}
        ):
            raise ValueError("Invalid access record")
        return GameAccess(owner, visibility)
    except FileNotFoundError:
        return GameAccess(None, "public")
    except (OSError, ValueError, KeyError, TypeError):
        # Corrupt records must never turn private games into legacy public games.
        raise HTTPException(404, "Game not found") from None


def create_access(
    game_id: str, owner_user_id: str, visibility: Visibility = "public"
) -> None:
    if not owner_user_id or visibility not in {"public", "private", "unlisted"}:
        raise ValueError("Invalid game access record")
    path = metadata_path(game_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"owner_user_id": str(owner_user_id), "visibility": visibility}
    )
    # Creation never changes an existing owner's record.
    with path.open("x", encoding="utf-8") as output:
        output.write(payload)
    os.chmod(path, 0o600)


def is_owner(access: GameAccess, user) -> bool:
    return user is not None and (
        bool(getattr(user, "is_admin", False))
        or (access.owner_user_id is not None and access.owner_user_id == str(user.id))
    )


def can_view(game_id: str, user=None, *, listing: bool = False) -> bool:
    access = read_access(game_id)
    return (
        is_owner(access, user)
        or access.visibility == "public"
        or (access.visibility == "unlisted" and not listing)
    )
