"""Invitation schemas."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr


class InvitationCreate(BaseModel):
    email: EmailStr
    send_email: bool = True


class InvitationResponse(BaseModel):
    """Invite returned to admins. `accept_url` is built server-side from FRONTEND_URL."""

    id: UUID
    email: str
    token: str
    accept_url: str
    created_at: datetime
    expires_at: datetime
    accepted_at: Optional[datetime] = None
    accepted_by_user_id: Optional[UUID] = None
    # Only meaningful on the response from create/resend.
    email_sent: Optional[bool] = None

    class Config:
        from_attributes = True


class InvitationListResponse(BaseModel):
    invitations: list[InvitationResponse]
    total: int
