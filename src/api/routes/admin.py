"""Admin routes — invitations + user management."""
import json
import logging
import secrets
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.config import get_settings
from src.api.core.database import get_db
from src.api.dependencies import require_admin
from src.api.models.invitation import Invitation
from src.api.models.user import User
from src.api.repositories.admin_audit_log_repository import AdminAuditLogRepository
from src.api.repositories.invitation_repository import InvitationRepository
from src.api.repositories.user_repository import UserRepository
from src.api.schemas.admin import (
    AdminPasswordResetRequest,
    AdminPasswordResetResponse,
    AdminSessionListResponse,
    AdminSessionResponse,
    AdminUserListResponse,
    AdminUserResponse,
    AdminUserUpdate,
)
from src.api.schemas.invitation import (
    InvitationCreate,
    InvitationListResponse,
    InvitationResponse,
)
from src.api.services.auth_service import AuthService
from src.api.services.email_service import email_service
from src.api.services.session_service import SessionService

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

invitation_repo = InvitationRepository()
user_repo = UserRepository()
audit_log_repo = AdminAuditLogRepository()
auth_service = AuthService()
session_service = SessionService()


def _get_ip(request: Request) -> Optional[str]:
    if request.client:
        return request.client.host
    return None


def _to_invitation_response(
    invitation: Invitation,
    *,
    email_sent: Optional[bool] = None,
) -> InvitationResponse:
    accept_url = f"{settings.FRONTEND_URL.rstrip('/')}/register?invite={invitation.token}"
    return InvitationResponse(
        id=invitation.id,
        email=invitation.email,
        token=invitation.token,
        accept_url=accept_url,
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        accepted_by_user_id=invitation.accepted_by_user_id,
        email_sent=email_sent,
    )


async def _send_invite_email(invitation: Invitation, inviter: User) -> bool:
    accept_url = f"{settings.FRONTEND_URL.rstrip('/')}/register?invite={invitation.token}"
    inviter_name = inviter.full_name or inviter.username
    try:
        return await email_service.send_invitation_email(
            invitation.email, accept_url, inviter_name=inviter_name
        )
    except Exception as exc:
        # Don't fail the API call just because Resend hiccuped — the admin
        # still gets the URL back to copy/paste.
        logger.error("send_invitation_email failed for %s: %s", invitation.email, exc)
        return False


# ---------- Invitations ----------


@router.post(
    "/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    payload: InvitationCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Issue an invite token for a given email. Optionally emails it."""
    email_lc = payload.email.lower().strip()

    existing_user = await user_repo.get_by_email(db, email_lc)
    if existing_user and not existing_user.is_anonymous:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A registered account with that email already exists",
        )

    pending = await invitation_repo.get_pending_by_email(db, email_lc)
    if pending is not None:
        invitation = pending
        action = "resend_invitation"
    else:
        token = secrets.token_urlsafe(32)
        invitation = await invitation_repo.create(
            db,
            email=email_lc,
            token=token,
            created_by=admin.id,
            ttl_days=settings.INVITATION_TTL_DAYS,
        )
        action = "create_invitation"

    email_sent = False
    if payload.send_email:
        email_sent = await _send_invite_email(invitation, admin)

    await audit_log_repo.write(
        db,
        admin_user_id=admin.id,
        action=action,
        target_email=email_lc,
        detail=f"send_email={payload.send_email} email_sent={email_sent}",
        ip_address=_get_ip(request),
    )
    await db.commit()
    return _to_invitation_response(invitation, email_sent=email_sent if payload.send_email else None)


@router.get("/invitations", response_model=InvitationListResponse)
async def list_invitations(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    invitations = await invitation_repo.list_all(db)
    return InvitationListResponse(
        invitations=[_to_invitation_response(i) for i in invitations],
        total=len(invitations),
    )


@router.post(
    "/invitations/{invitation_id}/resend",
    response_model=InvitationResponse,
)
async def resend_invitation(
    invitation_id: UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    invitation = await invitation_repo.get(db, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.accepted_at is not None:
        raise HTTPException(status_code=400, detail="Invite already accepted")

    email_sent = await _send_invite_email(invitation, admin)
    await audit_log_repo.write(
        db,
        admin_user_id=admin.id,
        action="resend_invitation",
        target_email=invitation.email,
        detail=f"email_sent={email_sent}",
        ip_address=_get_ip(request),
    )
    await db.commit()
    return _to_invitation_response(invitation, email_sent=email_sent)


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invitation(
    invitation_id: UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    invitation = await invitation_repo.get(db, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")

    target_email = invitation.email
    await invitation_repo.delete(db, invitation)
    await audit_log_repo.write(
        db,
        admin_user_id=admin.id,
        action="delete_invitation",
        target_email=target_email,
        ip_address=_get_ip(request),
    )
    await db.commit()
    return None


# ---------- Users ----------


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    q: Optional[str] = Query(None),
    include_anonymous: bool = Query(False),
    is_admin_filter: Optional[bool] = Query(None, alias="is_admin"),
    is_active_filter: Optional[bool] = Query(None, alias="is_active"),
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows, next_cursor, total = await user_repo.list_for_admin(
        db,
        q=q,
        include_anonymous=include_anonymous,
        is_admin=is_admin_filter,
        is_active=is_active_filter,
        cursor=cursor,
        limit=limit,
    )
    return AdminUserListResponse(
        users=[AdminUserResponse(**r) for r in rows],
        next_cursor=next_cursor,
        total=total,
    )


@router.get("/users/{user_id}", response_model=AdminUserResponse)
async def get_user_detail(
    user_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows, _, _ = await user_repo.list_for_admin(db, q=None, include_anonymous=True, limit=200)
    for r in rows:
        if r["id"] == user_id:
            return AdminUserResponse(**r)
    raise HTTPException(status_code=404, detail="User not found")


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: UUID,
    payload: AdminUserUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle is_active and/or is_admin. Self-edits to is_admin are rejected
    so an admin can't accidentally lock themselves out as the only admin."""
    user = await user_repo.get(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.is_admin is not None and user.id == admin.id and payload.is_admin is False:
        raise HTTPException(
            status_code=400,
            detail="Refusing to demote yourself; ask another admin",
        )

    changes: list[str] = []
    if payload.is_active is not None and payload.is_active != user.is_active:
        user.is_active = payload.is_active
        changes.append(f"is_active={payload.is_active}")
        await audit_log_repo.write(
            db,
            admin_user_id=admin.id,
            action="set_user_active",
            target_user_id=user.id,
            target_email=user.email,
            detail=f"is_active={payload.is_active}",
            ip_address=_get_ip(request),
        )
        if payload.is_active is False:
            # Deactivating? Revoke all sessions so they're booted now.
            await session_service.revoke_all_sessions(db, str(user.id))

    if payload.is_admin is not None and payload.is_admin != user.is_admin:
        user.is_admin = payload.is_admin
        changes.append(f"is_admin={payload.is_admin}")
        await audit_log_repo.write(
            db,
            admin_user_id=admin.id,
            action="set_user_admin",
            target_user_id=user.id,
            target_email=user.email,
            detail=f"is_admin={payload.is_admin}",
            ip_address=_get_ip(request),
        )

    await db.flush()
    await db.commit()

    # Re-read with aggregates for the response.
    rows, _, _ = await user_repo.list_for_admin(db, q=None, include_anonymous=True, limit=200)
    for r in rows:
        if r["id"] == user.id:
            return AdminUserResponse(**r)
    raise HTTPException(status_code=500, detail="User vanished mid-update")


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Hard delete. Cascades to sessions, refresh tokens, password resets, and
    games (per existing FK ON DELETE CASCADE rules)."""
    user = await user_repo.get(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Refusing to delete yourself")

    target_email = user.email
    await audit_log_repo.write(
        db,
        admin_user_id=admin.id,
        action="delete_user",
        target_user_id=user.id,
        target_email=target_email,
        ip_address=_get_ip(request),
    )
    await db.delete(user)
    await db.commit()
    return None


@router.post(
    "/users/{user_id}/password-reset",
    response_model=AdminPasswordResetResponse,
)
async def trigger_password_reset(
    user_id: UUID,
    payload: AdminPasswordResetRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await user_repo.get(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_anonymous:
        raise HTTPException(status_code=400, detail="Cannot reset password for an anonymous user")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="User is inactive")

    raw_token = await auth_service.create_password_reset_token(db, user)
    reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={raw_token}"

    email_sent = False
    if payload.send_email:
        try:
            email_sent = await email_service.send_password_reset_email(user.email, raw_token)
        except Exception as exc:
            logger.error("password reset send failed for %s: %s", user.email, exc)
            email_sent = False

    await audit_log_repo.write(
        db,
        admin_user_id=admin.id,
        action="issue_password_reset",
        target_user_id=user.id,
        target_email=user.email,
        detail=f"send_email={payload.send_email} email_sent={email_sent}",
        ip_address=_get_ip(request),
    )
    await db.commit()

    # Look up the freshly-created token row to return its expires_at.
    from datetime import datetime, timedelta, timezone
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES
    )

    return AdminPasswordResetResponse(
        expires_at=expires_at,
        email_sent=email_sent,
        reset_url=None if payload.send_email else reset_url,
    )


# ---------- Sessions ----------


@router.get(
    "/users/{user_id}/sessions",
    response_model=AdminSessionListResponse,
)
async def list_user_sessions(
    user_id: UUID,
    active_only: bool = Query(True),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await user_repo.get(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    sessions = await session_service.get_user_sessions(
        db, str(user.id), active_only=active_only
    )
    return AdminSessionListResponse(
        sessions=[AdminSessionResponse.model_validate(s) for s in sessions]
    )


@router.delete(
    "/users/{user_id}/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_user_session(
    user_id: UUID,
    session_id: UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ok = await session_service.revoke_session(db, str(session_id), str(user_id))
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")

    await audit_log_repo.write(
        db,
        admin_user_id=admin.id,
        action="revoke_session",
        target_user_id=user_id,
        detail=f"session_id={session_id}",
        ip_address=_get_ip(request),
    )
    await db.commit()
    return None


@router.post(
    "/users/{user_id}/sessions/revoke-all",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_all_user_sessions(
    user_id: UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await user_repo.get(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    count = await session_service.revoke_all_sessions(db, str(user.id))
    await audit_log_repo.write(
        db,
        admin_user_id=admin.id,
        action="revoke_all_sessions",
        target_user_id=user.id,
        target_email=user.email,
        detail=f"count={count}",
        ip_address=_get_ip(request),
    )
    await db.commit()
    return None


# ---------------------------------------------------------------------
# Failures corpus search — gives the agent and us a searchable view of
# data/godogen_failures.jsonl without grep-and-jq.
# ---------------------------------------------------------------------

@router.get("/failures")
async def list_failures(
    rule: Optional[str] = Query(None, description="Exact match against the rule field"),
    engine: Optional[str] = Query(None, description="godot | bevy"),
    game_id: Optional[str] = Query(None, description="Exact game id"),
    stage: Optional[str] = Query(None, description="Exact stage field"),
    since: Optional[str] = Query(None, description="ISO timestamp lower bound (inclusive)"),
    limit: int = Query(100, ge=1, le=2000),
    admin: User = Depends(require_admin),
):
    """Search the append-only failure corpus, newest first.

    Always returns the histogram of matched rules in ``rule_counts`` so
    callers can spot whether one rule dominates without scanning all rows.
    """
    from src.api.services.failure_log import _LOG_PATH
    if not _LOG_PATH.is_file():
        return {"total_scanned": 0, "matched_count": 0, "matched": [], "rule_counts": {}}

    matched: list[dict] = []
    rule_counts: dict[str, int] = {}
    total = 0
    with _LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rule and rec.get("rule") != rule:
                continue
            if engine and rec.get("engine") != engine:
                continue
            if game_id and rec.get("game_id") != game_id:
                continue
            if stage and rec.get("stage") != stage:
                continue
            if since and (rec.get("ts") or "") < since:
                continue
            matched.append(rec)
            r = rec.get("rule") or "<missing>"
            rule_counts[r] = rule_counts.get(r, 0) + 1

    matched.sort(key=lambda r: r.get("ts") or "", reverse=True)
    return {
        "total_scanned": total,
        "matched_count": len(matched),
        "matched": matched[:limit],
        "rule_counts": dict(sorted(rule_counts.items(), key=lambda kv: -kv[1])),
    }
