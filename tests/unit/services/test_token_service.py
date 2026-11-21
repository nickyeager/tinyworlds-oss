"""Tests for TokenService."""
import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.services.token_service import TokenService
from src.api.models.user import User
from src.api.models.user_session import UserSession
from src.api.core.security import get_password_hash


@pytest.mark.asyncio
async def test_create_token_pair(db_session: AsyncSession):
    """Test creating access and refresh token pair."""
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
    session = UserSession(user_id=user.id, device_name="Test Device")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    # Create token pair
    service = TokenService()
    token_pair = await service.create_token_pair(
        db=db_session,
        user_id=str(user.id),
        session_id=str(session.id),
    )

    assert token_pair.access_token is not None
    assert token_pair.refresh_token is not None
    assert token_pair.token_type == "bearer"
    assert token_pair.expires_in == 1800  # 30 minutes

    # Verify access token is valid
    payload = service.validate_access_token(token_pair.access_token)
    assert payload is not None
    assert payload["sub"] == str(user.id)


@pytest.mark.asyncio
async def test_refresh_token_rotation(db_session: AsyncSession):
    """Test refresh token rotation creates new pair and revokes old."""
    # Setup user and session
    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password=get_password_hash("testpass123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    session = UserSession(user_id=user.id, device_name="Test Device")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    # Create initial token pair
    service = TokenService()
    initial_pair = await service.create_token_pair(
        db=db_session,
        user_id=str(user.id),
        session_id=str(session.id),
    )
    await db_session.commit()

    # Refresh the token
    new_pair = await service.refresh_access_token(
        db=db_session,
        refresh_token=initial_pair.refresh_token,
    )
    await db_session.commit()

    # New tokens should be different
    assert new_pair.access_token != initial_pair.access_token
    assert new_pair.refresh_token != initial_pair.refresh_token

    # Old refresh token should be revoked
    old_token = await service.get_refresh_token(db_session, initial_pair.refresh_token)
    assert old_token.is_revoked is True
    assert old_token.revoke_reason == "rotated"


@pytest.mark.asyncio
async def test_token_reuse_detection(db_session: AsyncSession):
    """Test that reusing a revoked token revokes entire family."""
    # Setup user and session
    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password=get_password_hash("testpass123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    session = UserSession(user_id=user.id, device_name="Test Device")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    service = TokenService()

    # Create initial token
    token1 = await service.create_token_pair(
        db=db_session,
        user_id=str(user.id),
        session_id=str(session.id),
    )
    await db_session.commit()

    # Refresh once (token1 is now revoked)
    token2 = await service.refresh_access_token(
        db=db_session,
        refresh_token=token1.refresh_token,
    )
    await db_session.commit()

    # Try to reuse token1 (should detect reuse and raise)
    with pytest.raises(ValueError, match="Token reuse detected"):
        await service.refresh_access_token(
            db=db_session,
            refresh_token=token1.refresh_token,
        )

    # token2 should also be revoked now (entire family revoked)
    token2_record = await service.get_refresh_token(db_session, token2.refresh_token)
    assert token2_record.is_revoked is True


@pytest.mark.asyncio
async def test_revoke_all_user_tokens(db_session: AsyncSession):
    """Test revoking all tokens for a user."""
    # Setup user and session
    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password=get_password_hash("testpass123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    session = UserSession(user_id=user.id, device_name="Test Device")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    service = TokenService()

    # Create multiple token pairs
    token1 = await service.create_token_pair(db_session, str(user.id), str(session.id))
    token2 = await service.create_token_pair(db_session, str(user.id), str(session.id))
    await db_session.commit()

    # Revoke all
    count = await service.revoke_all_user_tokens(db_session, str(user.id))
    await db_session.commit()

    assert count == 2

    # Both tokens should be revoked
    t1 = await service.get_refresh_token(db_session, token1.refresh_token)
    t2 = await service.get_refresh_token(db_session, token2.refresh_token)
    assert t1.is_revoked is True
    assert t2.is_revoked is True


def test_expired_access_token_returns_none():
    """validate_access_token must return None (not raise) for expired JWTs."""
    service = TokenService()
    token = service._create_access_token(
        "user-1", "sess-1", expires_delta=timedelta(minutes=-5)
    )
    assert service.validate_access_token(token) is None


def test_garbage_access_token_returns_none():
    assert TokenService().validate_access_token("not-a-jwt") is None


@pytest.mark.asyncio
async def test_refresh_with_unknown_token_rejected(db_session: AsyncSession):
    service = TokenService()
    with pytest.raises(ValueError, match="Invalid refresh token"):
        await service.refresh_access_token(db_session, "garbage-token-value")
