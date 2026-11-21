"""User schemas for request/response validation."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    """Base user schema with common fields."""

    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100, description="Unique username")
    full_name: Optional[str] = None


class UserCreate(UserBase):
    """Schema for user creation."""

    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")
    invite_token: Optional[str] = Field(None, description="Optional admin-issued invite token")


class UserUpdate(BaseModel):
    """Schema for user updates."""

    full_name: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8)


class User(UserBase):
    """Schema for user responses (excludes password)."""

    id: UUID
    is_active: bool
    is_anonymous: bool = False
    is_admin: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UpgradeAccountRequest(BaseModel):
    """Schema for upgrading anonymous account to registered."""

    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8)
