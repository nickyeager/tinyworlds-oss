"""Invitation model — admin-issued invite tokens for new account creation."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship

from src.api.core.database import Base
from src.api.core.db_types import UUID


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(UUID(), primary_key=True, default=uuid4, index=True)
    email = Column(String(255), nullable=False, index=True)
    token = Column(String(64), nullable=False, unique=True, index=True)
    created_by = Column(UUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    accepted_by_user_id = Column(UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    creator = relationship("User", foreign_keys=[created_by])
    accepted_by = relationship("User", foreign_keys=[accepted_by_user_id])
