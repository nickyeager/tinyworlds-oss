"""Shared dependencies for API routes."""

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.database import get_db
from src.api.core.security import decode_access_token
from src.api.core.config import get_settings
from src.api.models.user import User
from src.api.repositories.user_repository import UserRepository

settings = get_settings()

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")
optional_oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login",
    auto_error=False,
)


async def get_user_from_token(
    token: str, db: AsyncSession, *, allow_media: bool = False
) -> User:
    """
    Get user from a JWT token string. Used for WebSocket authentication
    where FastAPI Depends() is not available.

    Args:
        token: JWT token string
        db: Database session

    Returns:
        User object

    Raises:
        HTTPException: If token is invalid or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Decode token
    payload = decode_access_token(token)
    if payload is None or (
        payload.get("purpose")
        and not (allow_media and payload.get("purpose") == "game-media")
    ):
        raise credentials_exception

    user_id_str: str = payload.get("sub")
    if user_id_str is None:
        raise credentials_exception

    try:
        from uuid import UUID

        user_id = UUID(user_id_str)
    except (ValueError, TypeError):
        raise credentials_exception

    # Get user from database
    repository = UserRepository()
    user = await repository.get(db, user_id)

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )

    return user


async def get_current_user(
    db: AsyncSession = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> User:
    """
    Dependency to get the current authenticated user.

    Args:
        db: Database session
        token: JWT token from Authorization header

    Returns:
        Current user

    Raises:
        HTTPException: If token is invalid or user not found
    """
    payload = decode_access_token(token)
    if payload and payload.get("purpose"):
        raise HTTPException(401, "Session token required")
    return await get_user_from_token(token, db)


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require the current user to have is_admin=True."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def get_optional_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    header_token: str | None = Depends(optional_oauth2_scheme),
    token: str | None = Query(
        None, description="Authentication for private game media"
    ),
) -> User | None:
    chosen = header_token or token
    if not chosen:
        game_id = request.path_params.get("game_id")
        cookie = request.cookies.get("tw_game_media")
        payload = decode_access_token(cookie) if cookie else None
        if (
            payload
            and payload.get("purpose") == "game-media"
            and payload.get("game_id") == game_id
        ):
            chosen = cookie
    if chosen:
        payload = decode_access_token(chosen)
        if (
            payload
            and payload.get("purpose")
            and (
                payload.get("purpose") != "game-media"
                or payload.get("game_id") != request.path_params.get("game_id")
            )
        ):
            raise HTTPException(401, "Invalid media scope")
        return await get_user_from_token(chosen, db, allow_media=True)
    return None


async def require_game_owner(
    game_id: str,
    current_user: User = Depends(get_current_user),
) -> User:
    from src.api.services.game_access import (
        game_path,
        read_access,
        is_owner,
        ensure_no_symlinks,
    )

    if not game_path(game_id).is_dir() or not is_owner(
        read_access(game_id), current_user
    ):
        raise HTTPException(404, "Game not found")
    ensure_no_symlinks(game_path(game_id))
    return current_user


async def require_game_viewer(
    game_id: str,
    current_user: User | None = Depends(get_optional_current_user),
) -> None:
    from src.api.services.game_access import game_path, can_view, ensure_no_symlinks

    if not game_path(game_id).is_dir() or not can_view(game_id, current_user):
        raise HTTPException(404, "Game not found")
    ensure_no_symlinks(game_path(game_id))


async def require_game_asset_owner(
    game_id: str,
    current_user: User | None = Depends(get_optional_current_user),
) -> User:
    """Native asset tags use URL authentication; source access still requires ownership."""
    from src.api.services.game_access import (
        game_path,
        is_owner,
        read_access,
        ensure_no_symlinks,
    )

    if current_user is None:
        raise HTTPException(401, "Authentication required")
    if not game_path(game_id).is_dir() or not is_owner(
        read_access(game_id), current_user
    ):
        raise HTTPException(404, "Game not found")
    ensure_no_symlinks(game_path(game_id))
    return current_user


async def get_current_user_for_asset(
    db: AsyncSession = Depends(get_db),
    header_token: str = Depends(
        OAuth2PasswordBearer(
            tokenUrl=f"{settings.API_V1_PREFIX}/auth/login",
            auto_error=False,
        )
    ),
    token: str | None = Query(
        None, description="JWT fallback for asset URLs in <audio>/<model-viewer> tags"
    ),
) -> User:
    """Auth for asset endpoints — accepts either ``Authorization: Bearer …``
    header (server-to-server) OR a ``?token=<jwt>`` query parameter.

    Native browser tags like ``<audio src>`` and ``<model-viewer src>`` issue
    a plain GET and can't attach a custom header — they need the query-param
    fallback. JWT lifetime is the same 7-day session so the exposure window
    is unchanged; the trade-off is the token may land in browser history /
    server access logs, which is acceptable for short-lived session tokens
    and not acceptable for long-lived API keys (none are involved here).
    """
    chosen = header_token or token
    if not chosen:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required (Authorization header or ?token=)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await get_user_from_token(chosen, db)
