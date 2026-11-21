"""Refresh token model for token rotation."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import relationship

from src.api.core.database import Base
from src.api.core.db_types import UUID


class RefreshToken(Base):
    """Refresh token for secure token rotation flow."""

    __tablename__ = "refresh_tokens"

    id = Column(UUID(), primary_key=True, default=uuid4)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(UUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(UUID(), ForeignKey("user_sessions.id", ondelete="CASCADE"), nullable=False)
    family_id = Column(UUID(), nullable=False, index=True)
    is_revoked = Column(Boolean, default=False, nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoke_reason = Column(String(50), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    user = relationship("User", back_populates="refresh_tokens")
    session = relationship("UserSession", back_populates="refresh_tokens")

    __table_args__ = (
        Index("ix_refresh_tokens_user_active", user_id, is_revoked),
        Index("ix_refresh_tokens_family", family_id, is_revoked),
    )
