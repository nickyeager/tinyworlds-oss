"""Password reset token model."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship

from src.api.core.database import Base
from src.api.core.db_types import UUID


class PasswordResetToken(Base):
    """Single-use token for password reset flow."""

    __tablename__ = "password_reset_tokens"

    id = Column(UUID(), primary_key=True, default=uuid4)
    user_id = Column(UUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    user = relationship("User", back_populates="password_reset_tokens")

    @property
    def is_valid(self) -> bool:
        """Check if token is valid (not used and not expired)."""
        return self.used_at is None and self.expires_at > datetime.now(timezone.utc)
