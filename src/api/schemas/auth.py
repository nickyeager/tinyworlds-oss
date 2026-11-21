"""Authentication schemas."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class Token(BaseModel):
    """JWT token response."""

    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int = 1800  # 30 minutes in seconds (short-lived access tokens)


class TokenWithUser(Token):
    """JWT token response with user info."""

    user_id: UUID
    is_anonymous: bool = False


class RefreshTokenRequest(BaseModel):
    """Request to refresh access token."""

    refresh_token: str


class SessionInfo(BaseModel):
    """User session information."""

    id: UUID
    device_name: Optional[str] = None
    device_type: Optional[str] = None
    ip_address: Optional[str] = None
    last_active_at: datetime
    created_at: datetime
    is_current: bool = False

    class Config:
        from_attributes = True


class SessionListResponse(BaseModel):
    """List of user sessions."""

    sessions: list[SessionInfo]
    total: int


class TokenData(BaseModel):
    """Data encoded in JWT token."""

    user_id: Optional[str] = None


class LoginRequest(BaseModel):
    """Login request with email and password."""

    email: EmailStr
    password: str


class PasswordResetRequest(BaseModel):
    """Request password reset email."""

    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Confirm password reset with token."""

    token: str
    password: str = Field(..., min_length=8)


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str
