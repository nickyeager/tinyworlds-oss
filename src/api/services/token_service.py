"""Token service for JWT access and refresh token management."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.config import get_settings
from src.api.models.refresh_token import RefreshToken

settings = get_settings()


class TokenPair(BaseModel):
    """Access and refresh token pair."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 1800  # 30 minutes in seconds


class TokenPayload(BaseModel):
    """Decoded token payload."""
    sub: str  # user_id
    exp: datetime
    iat: datetime
    jti: str  # unique token ID
    session_id: Optional[str] = None


class TokenService:
    """Service for managing JWT tokens with rotation."""

    ACCESS_TOKEN_EXPIRE_MINUTES = 30
    REFRESH_TOKEN_EXPIRE_DAYS = 30

    def _hash_token(self, token: str) -> str:
        """Create SHA-256 hash of token for storage."""
        return hashlib.sha256(token.encode()).hexdigest()

    def _create_access_token(
        self,
        user_id: str,
        session_id: str,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """Create a JWT access token."""
        if expires_delta is None:
            expires_delta = timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)

        now = datetime.now(timezone.utc)
        expire = now + expires_delta
        jti = str(uuid4())

        to_encode = {
            "sub": user_id,
            "exp": expire,
            "iat": now,
            "jti": jti,
            "session_id": session_id,
            "type": "access",
        }

        return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    def _create_refresh_token_value(self) -> str:
        """Create a cryptographically secure refresh token value."""
        return secrets.token_urlsafe(32)

    async def create_token_pair(
        self,
        db: AsyncSession,
        user_id: str,
        session_id: str,
        family_id: Optional[str] = None,
    ) -> TokenPair:
        """
        Create access and refresh token pair.

        Args:
            db: Database session
            user_id: User ID
            session_id: Session ID
            family_id: Optional family ID for token rotation (new family if None)

        Returns:
            TokenPair with access and refresh tokens
        """
        # Create access token
        access_token = self._create_access_token(user_id, session_id)

        # Create refresh token
        refresh_token_value = self._create_refresh_token_value()
        token_hash = self._hash_token(refresh_token_value)

        # Use provided family_id or create new one
        if family_id is None:
            family_id = str(uuid4())

        # Store refresh token in database
        expires_at = datetime.now(timezone.utc) + timedelta(days=self.REFRESH_TOKEN_EXPIRE_DAYS)
        db_token = RefreshToken(
            token_hash=token_hash,
            user_id=user_id,
            session_id=session_id,
            family_id=family_id,
            expires_at=expires_at,
        )
        db.add(db_token)
        await db.flush()

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token_value,
            expires_in=self.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    def validate_access_token(self, token: str) -> Optional[dict]:
        """
        Validate and decode an access token.

        Args:
            token: JWT access token

        Returns:
            Token payload if valid, None otherwise
        """
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
            )
            if payload.get("type") != "access":
                return None
            return payload
        except JWTError:
            return None

    async def get_refresh_token(
        self,
        db: AsyncSession,
        token_value: str,
    ) -> Optional[RefreshToken]:
        """Get refresh token record by token value."""
        token_hash = self._hash_token(token_value)
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalars().first()

    async def refresh_access_token(
        self,
        db: AsyncSession,
        refresh_token: str,
    ) -> TokenPair:
        """
        Exchange refresh token for new token pair (rotation).

        Args:
            db: Database session
            refresh_token: Current refresh token

        Returns:
            New TokenPair

        Raises:
            ValueError: If token is invalid, expired, or reused
        """
        # Find token in database
        token_record = await self.get_refresh_token(db, refresh_token)

        if token_record is None:
            raise ValueError("Invalid refresh token")

        # Check if token is revoked (potential reuse attack)
        if token_record.is_revoked:
            # Revoke entire token family for security
            await self.revoke_token_family(db, str(token_record.family_id))
            raise ValueError("Token reuse detected. All sessions revoked for security.")

        # Check expiration (handle both naive and aware datetimes from SQLite)
        expires_at = token_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise ValueError("Refresh token has expired")

        # Mark old token as revoked (single-use)
        token_record.is_revoked = True
        token_record.revoked_at = datetime.now(timezone.utc)
        token_record.revoke_reason = "rotated"

        # Create new token pair with same family
        new_pair = await self.create_token_pair(
            db=db,
            user_id=str(token_record.user_id),
            session_id=str(token_record.session_id),
            family_id=str(token_record.family_id),
        )

        await db.flush()
        return new_pair

    async def revoke_refresh_token(
        self,
        db: AsyncSession,
        token_value: str,
        reason: str = "logout",
    ) -> bool:
        """Revoke a single refresh token."""
        token_record = await self.get_refresh_token(db, token_value)
        if token_record is None:
            return False

        token_record.is_revoked = True
        token_record.revoked_at = datetime.now(timezone.utc)
        token_record.revoke_reason = reason
        await db.flush()
        return True

    async def revoke_token_family(
        self,
        db: AsyncSession,
        family_id: str,
    ) -> int:
        """Revoke all tokens in a family (security event)."""
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.family_id == family_id,
                RefreshToken.is_revoked == False,
            )
        )
        tokens = result.scalars().all()

        count = 0
        for token in tokens:
            token.is_revoked = True
            token.revoked_at = datetime.now(timezone.utc)
            token.revoke_reason = "family_revoked"
            count += 1

        await db.flush()
        return count

    async def revoke_all_user_tokens(
        self,
        db: AsyncSession,
        user_id: str,
        reason: str = "logout_all",
    ) -> int:
        """Revoke all refresh tokens for a user."""
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked == False,
            )
        )
        tokens = result.scalars().all()

        count = 0
        for token in tokens:
            token.is_revoked = True
            token.revoked_at = datetime.now(timezone.utc)
            token.revoke_reason = reason
            count += 1

        await db.flush()
        return count
