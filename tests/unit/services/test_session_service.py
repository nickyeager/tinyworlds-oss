"""Tests for SessionService."""
import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.services.session_service import SessionService
from src.api.models.user import User
from src.api.core.security import get_password_hash


@pytest.mark.asyncio
async def test_create_session(db_session: AsyncSession):
    """Test creating a new user session."""
    # Create test user
    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password=get_password_hash("testpass123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Create session
    service = SessionService()
    session = await service.create_session(
        db=db_session,
        user_id=str(user.id),
        device_name="Chrome on MacOS",
        user_agent="Mozilla/5.0...",
        ip_address="192.168.1.1",
    )
    await db_session.commit()

    assert session is not None
    assert session.user_id == user.id
    assert session.device_name == "Chrome on MacOS"
    assert session.is_active is True


@pytest.mark.asyncio
async def test_get_user_sessions(db_session: AsyncSession):
    """Test listing active sessions for a user."""
    # Create test user
    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password=get_password_hash("testpass123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    service = SessionService()

    # Create multiple sessions
    await service.create_session(db_session, str(user.id), device_name="Desktop")
    await service.create_session(db_session, str(user.id), device_name="Mobile")
    await db_session.commit()

    # Get all sessions
    sessions = await service.get_user_sessions(db_session, str(user.id))

    assert len(sessions) == 2
    device_names = {s.device_name for s in sessions}
    assert "Desktop" in device_names
    assert "Mobile" in device_names


@pytest.mark.asyncio
async def test_revoke_session(db_session: AsyncSession):
    """Test revoking a specific session."""
    # Create test user
    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password=get_password_hash("testpass123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    service = SessionService()
    session = await service.create_session(db_session, str(user.id), device_name="Test")
    await db_session.commit()

    # Revoke the session
    success = await service.revoke_session(db_session, str(session.id), str(user.id))
    await db_session.commit()

    assert success is True

    # Session should no longer be active
    sessions = await service.get_user_sessions(db_session, str(user.id))
    assert len(sessions) == 0


@pytest.mark.asyncio
async def test_revoke_all_sessions(db_session: AsyncSession):
    """Test revoking all sessions for a user."""
    # Create test user
    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password=get_password_hash("testpass123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    service = SessionService()

    # Create multiple sessions
    await service.create_session(db_session, str(user.id), device_name="Session 1")
    await service.create_session(db_session, str(user.id), device_name="Session 2")
    await service.create_session(db_session, str(user.id), device_name="Session 3")
    await db_session.commit()

    # Revoke all
    count = await service.revoke_all_sessions(db_session, str(user.id))
    await db_session.commit()

    assert count == 3

    # No active sessions
    sessions = await service.get_user_sessions(db_session, str(user.id))
    assert len(sessions) == 0


@pytest.mark.asyncio
async def test_update_session_activity(db_session: AsyncSession):
    """Test updating session's last active time."""
    # Create test user
    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password=get_password_hash("testpass123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    service = SessionService()
    session = await service.create_session(db_session, str(user.id), device_name="Test")
    await db_session.commit()

    # Backdate the session an hour, then read the stored value back so both
    # sides of the comparison share the DB's timezone handling. A strict >
    # then proves update_session_activity actually advanced the timestamp
    # (no sleep needed, can't pass vacuously).
    session.last_active_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.commit()
    await db_session.refresh(session)
    backdated = session.last_active_at

    await service.update_session_activity(db_session, str(session.id))
    await db_session.commit()
    await db_session.refresh(session)

    assert session.last_active_at > backdated


@pytest.mark.asyncio
async def test_revoke_session_wrong_user_denied(db_session: AsyncSession):
    """user_id is the authorization check: another user's id must not be able
    to revoke the session, and it must remain active."""
    owner = User(
        email="owner@example.com",
        username="owner",
        hashed_password=get_password_hash("testpass123"),
    )
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)

    service = SessionService()
    session = await service.create_session(db_session, str(owner.id), device_name="Test")
    await db_session.commit()

    revoked = await service.revoke_session(
        db_session, str(session.id), "someone-else-entirely"
    )
    await db_session.commit()

    assert revoked is False
    still_active = await service.get_user_sessions(db_session, str(owner.id))
    assert len(still_active) == 1
