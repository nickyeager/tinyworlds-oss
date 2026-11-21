"""Invitation repository for invite-token operations."""
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.models.invitation import Invitation


class InvitationRepository:
    """Direct DB ops for invitations (small surface — no BaseRepository needed)."""

    async def create(
        self,
        db: AsyncSession,
        email: str,
        token: str,
        created_by: UUID,
        ttl_days: int = 7,
    ) -> Invitation:
        invitation = Invitation(
            id=uuid4(),
            email=email.lower().strip(),
            token=token,
            created_by=created_by,
            expires_at=datetime.now(timezone.utc) + timedelta(days=ttl_days),
        )
        db.add(invitation)
        await db.flush()
        await db.refresh(invitation)
        return invitation

    async def list_all(self, db: AsyncSession) -> list[Invitation]:
        result = await db.execute(
            select(Invitation).order_by(Invitation.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_token(self, db: AsyncSession, token: str) -> Optional[Invitation]:
        result = await db.execute(select(Invitation).where(Invitation.token == token))
        return result.scalars().first()

    async def get(self, db: AsyncSession, invitation_id: UUID) -> Optional[Invitation]:
        result = await db.execute(select(Invitation).where(Invitation.id == invitation_id))
        return result.scalars().first()

    async def get_pending_by_email(self, db: AsyncSession, email: str) -> Optional[Invitation]:
        """Return any unexpired, unaccepted invite for this email."""
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(Invitation)
            .where(Invitation.email == email.lower().strip())
            .where(Invitation.accepted_at.is_(None))
            .where(Invitation.expires_at > now)
        )
        return result.scalars().first()

    async def mark_accepted(
        self, db: AsyncSession, invitation: Invitation, user_id: UUID
    ) -> Invitation:
        invitation.accepted_at = datetime.now(timezone.utc)
        invitation.accepted_by_user_id = user_id
        await db.flush()
        return invitation

    async def delete(self, db: AsyncSession, invitation: Invitation) -> None:
        await db.delete(invitation)
        await db.flush()
