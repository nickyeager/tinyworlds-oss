"""User model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.orm import relationship

from src.api.core.database import Base
from src.api.core.db_types import UUID


class User(Base):
    """User account model."""

    __tablename__ = "users"

    id = Column(UUID(), primary_key=True, default=uuid4, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_anonymous = Column(Boolean, default=False, nullable=False, index=True)
    is_admin = Column(Boolean, default=False, nullable=False)
    scheduled_deletion_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    owned_games = relationship("Game", back_populates="owner", foreign_keys="Game.owner_id")
    game_collaborations = relationship("GameCollaborator", back_populates="user", foreign_keys="GameCollaborator.user_id", cascade="all, delete-orphan")
    created_versions = relationship("GameVersion", back_populates="creator", foreign_keys="GameVersion.created_by")
    password_reset_tokens = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")

    @property
    def is_registered(self) -> bool:
        """Check if user is a registered (non-anonymous) user."""
        return not self.is_anonymous
