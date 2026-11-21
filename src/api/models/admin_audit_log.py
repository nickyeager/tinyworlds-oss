"""Admin audit log — append-only record of every privileged action."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text

from src.api.core.database import Base
from src.api.core.db_types import UUID


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"

    id = Column(UUID(), primary_key=True, default=uuid4)
    admin_user_id = Column(UUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(64), nullable=False, index=True)
    target_user_id = Column(UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    target_email = Column(String(255), nullable=True)
    detail = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
