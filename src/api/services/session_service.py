"""Session service for managing user login sessions."""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.models.user_session import UserSession
from src.api.models.refresh_token import RefreshToken


class SessionService:
    """Service for managing user sessions across devices."""

    async def create_session(
        self,
        db: AsyncSession,
        user_id: str,
        device_name: Optional[str] = None,
        device_type: Optional[str] = None,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> UserSession:
        """
        Create a new session for a user.

        Args:
            db: Database session
            user_id: User ID
            device_name: Human-readable device name
            device_type: Device type (desktop, mobile, tablet)
            user_agent: Browser user agent string
            ip_address: Client IP address

        Returns:
            Created UserSession
        """
        session = UserSession(
            user_id=user_id,
            device_name=device_name,
            device_type=device_type,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        db.add(session)
        await db.flush()
        await db.refresh(session)
        return session

    async def get_session(
        self,
        db: AsyncSession,
        session_id: str,
    ) -> Optional[UserSession]:
        """Get a session by ID."""
        result = await db.execute(
            select(UserSession).where(UserSession.id == session_id)
        )
        return result.scalars().first()

    async def get_user_sessions(
        self,
        db: AsyncSession,
        user_id: str,
        active_only: bool = True,
    ) -> list[UserSession]:
        """
        Get all sessions for a user.

        Args:
            db: Database session
            user_id: User ID
            active_only: Whether to return only active sessions

        Returns:
            List of UserSession objects
        """
        query = select(UserSession).where(UserSession.user_id == user_id)
        if active_only:
            query = query.where(UserSession.is_active == True)
        query = query.order_by(UserSession.last_active_at.desc())

        result = await db.execute(query)
        return list(result.scalars().all())

    async def revoke_session(
        self,
        db: AsyncSession,
        session_id: str,
        user_id: str,
    ) -> bool:
        """
        Revoke a specific session.

        Args:
            db: Database session
            session_id: Session ID to revoke
            user_id: User ID (for authorization check)

        Returns:
            True if session was revoked, False if not found
        """
        result = await db.execute(
            select(UserSession).where(
                UserSession.id == session_id,
                UserSession.user_id == user_id,
                UserSession.is_active == True,
            )
        )
        session = result.scalars().first()

        if session is None:
            return False

        session.is_active = False
        session.revoked_at = datetime.now(timezone.utc)

        # Also revoke all refresh tokens for this session
        token_result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.session_id == session_id,
                RefreshToken.is_revoked == False,
            )
        )
        for token in token_result.scalars().all():
            token.is_revoked = True
            token.revoked_at = datetime.now(timezone.utc)
            token.revoke_reason = "session_revoked"

        await db.flush()
        return True

    async def revoke_all_sessions(
        self,
        db: AsyncSession,
        user_id: str,
        except_session_id: Optional[str] = None,
    ) -> int:
        """
        Revoke all sessions for a user.

        Args:
            db: Database session
            user_id: User ID
            except_session_id: Optional session ID to keep active

        Returns:
            Number of sessions revoked
        """
        query = select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.is_active == True,
        )
        if except_session_id:
            query = query.where(UserSession.id != except_session_id)

        result = await db.execute(query)
        sessions = result.scalars().all()

        count = 0
        for session in sessions:
            session.is_active = False
            session.revoked_at = datetime.now(timezone.utc)
            count += 1

        # Revoke all refresh tokens for revoked sessions
        if count > 0:
            token_query = select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked == False,
            )
            if except_session_id:
                token_query = token_query.where(RefreshToken.session_id != except_session_id)

            token_result = await db.execute(token_query)
            for token in token_result.scalars().all():
                token.is_revoked = True
                token.revoked_at = datetime.now(timezone.utc)
                token.revoke_reason = "all_sessions_revoked"

        await db.flush()
        return count

    async def update_session_activity(
        self,
        db: AsyncSession,
        session_id: str,
    ) -> bool:
        """
        Update the last active time for a session.

        Args:
            db: Database session
            session_id: Session ID

        Returns:
            True if session was updated, False if not found
        """
        result = await db.execute(
            select(UserSession).where(
                UserSession.id == session_id,
                UserSession.is_active == True,
            )
        )
        session = result.scalars().first()

        if session is None:
            return False

        session.last_active_at = datetime.now(timezone.utc)
        await db.flush()
        return True
