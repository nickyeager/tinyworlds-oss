"""Append-only audit log for privileged admin actions."""
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.models.admin_audit_log import AdminAuditLog


class AdminAuditLogRepository:
    async def write(
        self,
        db: AsyncSession,
        *,
        admin_user_id: UUID,
        action: str,
        target_user_id: Optional[UUID] = None,
        target_email: Optional[str] = None,
        detail: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> AdminAuditLog:
        entry = AdminAuditLog(
            id=uuid4(),
            admin_user_id=admin_user_id,
            action=action,
            target_user_id=target_user_id,
            target_email=target_email,
            detail=detail,
            ip_address=ip_address,
        )
        db.add(entry)
        await db.flush()
        return entry
