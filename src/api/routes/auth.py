"""Authentication routes."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.config import get_settings
from src.api.core.database import get_db
from src.api.core.security import create_access_token
from src.api.dependencies import get_current_user
from src.api.models.user import User
from src.api.schemas.auth import (
    Token,
    TokenWithUser,
    LoginRequest,
    PasswordResetRequest,
    PasswordResetConfirm,
    MessageResponse,
    RefreshTokenRequest,
    SessionInfo,
    SessionListResponse,
)
from src.api.schemas.user import User as UserSchema, UserCreate, UpgradeAccountRequest
from src.api.repositories.invitation_repository import InvitationRepository
from src.api.services.auth_service import AuthService
from src.api.services.token_service import TokenService
from src.api.services.session_service import SessionService
from src.api.services.email_service import email_service

from datetime import datetime, timezone
from src.api.middleware.rate_limit import (
    check_login_rate_limit,
    check_register_rate_limit,
    check_password_reset_rate_limit,
)

settings = get_settings()
router = APIRouter()
auth_service = AuthService()
token_service = TokenService()
session_service = SessionService()
invitation_repo = InvitationRepository()


def _get_device_info(request: Request) -> dict:
    """Extract device info from request."""
    user_agent = request.headers.get("user-agent", "")
    # Simple device type detection
    device_type = "desktop"
    if "Mobile" in user_agent or "Android" in user_agent:
        device_type = "mobile"
    elif "Tablet" in user_agent or "iPad" in user_agent:
        device_type = "tablet"

    # Get client IP (handle proxies)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip_address = forwarded.split(",")[0].strip()
    else:
        ip_address = request.client.host if request.client else None

    return {
        "user_agent": user_agent[:500] if user_agent else None,
        "device_type": device_type,
        "ip_address": ip_address,
    }


@router.post("/register", response_model=TokenWithUser, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(check_register_rate_limit),
):
    """
    Register a new user.

    Returns access token and refresh token with session tracking.
    """
    invitation = None
    if user_in.invite_token:
        invitation = await invitation_repo.get_by_token(db, user_in.invite_token)
        if invitation is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid invite token",
            )
        if invitation.accepted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invite has already been used",
            )
        if invitation.expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invite has expired",
            )
        if invitation.email != user_in.email.lower().strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invite was issued to a different email address",
            )

    try:
        user = await auth_service.create_user(db, user_in, is_anonymous=False)

        if invitation is not None:
            await invitation_repo.mark_accepted(db, invitation, user.id)

        # Create session
        device_info = _get_device_info(request)
        session = await session_service.create_session(
            db=db,
            user_id=str(user.id),
            device_name=f"{device_info['device_type'].title()} Browser",
            **device_info,
        )

        # Create token pair
        token_pair = await token_service.create_token_pair(
            db=db,
            user_id=str(user.id),
            session_id=str(session.id),
        )

        await db.commit()

        return {
            "access_token": token_pair.access_token,
            "refresh_token": token_pair.refresh_token,
            "token_type": "bearer",
            "expires_in": token_pair.expires_in,
            "user_id": user.id,
            "is_anonymous": user.is_anonymous,
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/invitation/{token}")
async def lookup_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public lookup of an invite token — used by /register to prefill email."""
    invitation = await invitation_repo.get_by_token(db, token)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    if invitation.accepted_at is not None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invite already used")
    if invitation.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invite expired")
    return {"email": invitation.email, "expires_at": invitation.expires_at}


@router.post("/login", response_model=TokenWithUser)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(check_login_rate_limit),
):
    """
    Login with email and password to get JWT token.

    Returns access token and refresh token with session tracking.
    """
    user = await auth_service.authenticate(
        db,
        email=form_data.username,  # OAuth2 spec uses 'username' field
        password=form_data.password
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Reject anonymous users from regular login
    if user.is_anonymous:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please use a registered account to login",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create session
    device_info = _get_device_info(request)
    session = await session_service.create_session(
        db=db,
        user_id=str(user.id),
        device_name=f"{device_info['device_type'].title()} Browser",
        **device_info,
    )

    # Create token pair
    token_pair = await token_service.create_token_pair(
        db=db,
        user_id=str(user.id),
        session_id=str(session.id),
    )

    await db.commit()

    return {
        "access_token": token_pair.access_token,
        "refresh_token": token_pair.refresh_token,
        "token_type": "bearer",
        "expires_in": token_pair.expires_in,
        "user_id": user.id,
        "is_anonymous": user.is_anonymous,
    }


@router.post("/login/json", response_model=TokenWithUser)
async def login_json(
    credentials: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(check_login_rate_limit),
):
    """
    Login with JSON body (alternative to OAuth2 form).

    Returns access token and refresh token with session tracking.
    """
    user = await auth_service.authenticate(
        db,
        email=credentials.email,
        password=credentials.password
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if user.is_anonymous:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please use a registered account to login",
        )

    # Create session
    device_info = _get_device_info(request)
    session = await session_service.create_session(
        db=db,
        user_id=str(user.id),
        device_name=f"{device_info['device_type'].title()} Browser",
        **device_info,
    )

    # Create token pair
    token_pair = await token_service.create_token_pair(
        db=db,
        user_id=str(user.id),
        session_id=str(session.id),
    )

    await db.commit()

    return {
        "access_token": token_pair.access_token,
        "refresh_token": token_pair.refresh_token,
        "token_type": "bearer",
        "expires_in": token_pair.expires_in,
        "user_id": user.id,
        "is_anonymous": user.is_anonymous,
    }


@router.post("/anonymous", response_model=TokenWithUser)
async def get_anonymous_token(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Get an anonymous token for unauthenticated game creation.

    Creates a temporary anonymous user and returns a JWT token.
    This allows users to create games without registering first.
    Anonymous users are automatically cleaned up after 30 days.

    Returns:
        JWT access token for anonymous user with refresh token
    """
    try:
        user = await auth_service.create_anonymous_user(db)

        # Create session
        device_info = _get_device_info(request)
        session = await session_service.create_session(
            db=db,
            user_id=str(user.id),
            device_name="Anonymous Session",
            **device_info,
        )

        # Create token pair
        token_pair = await token_service.create_token_pair(
            db=db,
            user_id=str(user.id),
            session_id=str(session.id),
        )

        await db.commit()

        return {
            "access_token": token_pair.access_token,
            "refresh_token": token_pair.refresh_token,
            "token_type": "bearer",
            "expires_in": token_pair.expires_in,
            "user_id": user.id,
            "is_anonymous": True,
        }
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create anonymous session"
        )


@router.post("/refresh", response_model=Token)
async def refresh_token(
    refresh_request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Exchange refresh token for new access token.

    This implements token rotation - the old refresh token is revoked
    and a new token pair is returned.

    Args:
        refresh_request: Contains the refresh token

    Returns:
        New access token and refresh token

    Raises:
        HTTPException: If refresh token is invalid, expired, or reused
    """
    try:
        token_pair = await token_service.refresh_access_token(
            db=db,
            refresh_token=refresh_request.refresh_token,
        )
        await db.commit()

        return {
            "access_token": token_pair.access_token,
            "refresh_token": token_pair.refresh_token,
            "token_type": "bearer",
            "expires_in": token_pair.expires_in,
        }
    except ValueError as e:
        error_msg = str(e)
        if "reuse" in error_msg.lower():
            # Token reuse is a security event - commit the family revocation
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session compromised. Please login again.",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )


@router.post("/upgrade", response_model=TokenWithUser)
async def upgrade_account(
    upgrade_data: UpgradeAccountRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Upgrade an anonymous account to a registered account.

    This preserves all games and data created while anonymous.
    """
    try:
        user = await auth_service.upgrade_anonymous_account(
            db,
            user=current_user,
            email=upgrade_data.email,
            username=upgrade_data.username,
            password=upgrade_data.password
        )

        # Create new session for upgraded account
        device_info = _get_device_info(request)
        session = await session_service.create_session(
            db=db,
            user_id=str(user.id),
            device_name=f"{device_info['device_type'].title()} Browser",
            **device_info,
        )

        # Create new token pair
        token_pair = await token_service.create_token_pair(
            db=db,
            user_id=str(user.id),
            session_id=str(session.id),
        )

        await db.commit()

        return {
            "access_token": token_pair.access_token,
            "refresh_token": token_pair.refresh_token,
            "token_type": "bearer",
            "expires_in": token_pair.expires_in,
            "user_id": user.id,
            "is_anonymous": False,
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Logout the current user.

    Revokes all refresh tokens for the current user.
    Client should also clear stored tokens.

    Returns:
        Success message
    """
    await token_service.revoke_all_user_tokens(db, str(current_user.id), reason="logout")
    await db.commit()
    return {"message": "Successfully logged out"}


@router.post("/logout/all", response_model=MessageResponse)
async def logout_all_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Logout from all devices.

    Revokes all sessions and refresh tokens for the current user.

    Returns:
        Success message with count of revoked sessions
    """
    count = await session_service.revoke_all_sessions(db, str(current_user.id))
    await db.commit()
    return {"message": f"Successfully logged out from {count} device(s)"}


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all active sessions for the current user.

    Returns:
        List of active sessions with device info
    """
    sessions = await session_service.get_user_sessions(db, str(current_user.id))

    session_list = [
        SessionInfo(
            id=s.id,
            device_name=s.device_name,
            device_type=s.device_type,
            ip_address=s.ip_address,
            last_active_at=s.last_active_at,
            created_at=s.created_at,
            is_current=False,  # Could be determined from token if needed
        )
        for s in sessions
    ]

    return SessionListResponse(sessions=session_list, total=len(session_list))


@router.delete("/sessions/{session_id}", response_model=MessageResponse)
async def revoke_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Revoke a specific session.

    Args:
        session_id: ID of the session to revoke

    Returns:
        Success message

    Raises:
        HTTPException: If session not found or not owned by user
    """
    success = await session_service.revoke_session(db, session_id, str(current_user.id))
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    await db.commit()
    return {"message": "Session revoked successfully"}


@router.get("/me", response_model=UserSchema)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """
    Get current user information.
    """
    return current_user


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    request: PasswordResetRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(check_password_reset_rate_limit),
):
    """
    Request a password reset email.

    Always returns success to prevent email enumeration attacks.
    """
    user = await auth_service.repository.get_by_email(db, request.email)

    if user and not user.is_anonymous:
        # Generate reset token
        reset_token = await auth_service.create_password_reset_token(db, user)
        await db.commit()

        # Send email
        await email_service.send_password_reset_email(user.email, reset_token)

    # Always return success to prevent email enumeration
    return {"message": "If an account exists with that email, a password reset link has been sent"}


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    request: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db)
):
    """
    Reset password using a reset token.

    Also revokes all existing sessions for security.
    """
    success = await auth_service.reset_password(db, request.token, request.password)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )

    # Revoke all sessions after password reset for security
    # Get user from token to revoke sessions
    token_record = await auth_service.validate_password_reset_token(db, request.token)
    if token_record:
        await session_service.revoke_all_sessions(db, str(token_record.user_id))

    await db.commit()
    return {"message": "Password has been reset successfully"}
