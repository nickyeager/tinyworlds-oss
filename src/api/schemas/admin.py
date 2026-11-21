"""Admin-only schemas for the user management panel."""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AdminUserResponse(BaseModel):
    """User row as shown in the admin Users tab."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    username: str
    full_name: Optional[str] = None
    is_active: bool
    is_admin: bool
    is_anonymous: bool
    scheduled_deletion_at: Optional[datetime] = None
    created_at: datetime
    last_seen_at: Optional[datetime] = None
    active_session_count: int = 0
    game_count: int = 0


class AdminUserListResponse(BaseModel):
    users: list[AdminUserResponse]
    next_cursor: Optional[str] = None
    total: int


class AdminUserUpdate(BaseModel):
    """Patch payload for the row-level toggles."""

    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None


class AdminPasswordResetRequest(BaseModel):
    send_email: bool = True


class AdminPasswordResetResponse(BaseModel):
    expires_at: datetime
    email_sent: bool
    # Only set when send_email=False — gives the admin a copy-able link.
    reset_url: Optional[str] = None


class AdminSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_name: Optional[str] = None
    device_type: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    is_active: bool
    last_active_at: datetime
    created_at: datetime
    revoked_at: Optional[datetime] = None


class AdminSessionListResponse(BaseModel):
    sessions: list[AdminSessionResponse]


class AdminAuditLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    admin_user_id: UUID
    action: str
    target_user_id: Optional[UUID] = None
    target_email: Optional[str] = None
    detail: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime


AuditAction = Literal[
    "create_invitation",
    "resend_invitation",
    "delete_invitation",
    "issue_password_reset",
    "set_user_active",
    "set_user_admin",
    "delete_user",
    "revoke_session",
    "revoke_all_sessions",
]
