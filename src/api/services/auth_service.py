"""Authentication service for user management and login."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.config import get_settings
from src.api.core.security import verify_password, get_password_hash
from src.api.models.user import User
from src.api.models.password_reset_token import PasswordResetToken
from src.api.repositories.user_repository import UserRepository
from src.api.schemas.user import UserCreate

settings = get_settings()


class AuthService:
    """Service for authentication and user management."""

    def __init__(self):
        """Initialize auth service."""
        self.repository = UserRepository()

    async def create_user(
        self,
        db: AsyncSession,
        user_in: UserCreate,
        is_anonymous: bool = False
    ) -> User:
        """
        Create new user with hashed password.

        Args:
            db: Database session
            user_in: User creation data
            is_anonymous: Whether this is an anonymous user

        Returns:
            Created user

        Raises:
            ValueError: If email already exists
        """
        # Check if email already exists
        existing_user = await self.repository.get_by_email(db, user_in.email)
        if existing_user:
            raise ValueError("Email already registered")

        # Check if username already exists
        existing_username = await self.repository.get_by_username(db, user_in.username)
        if existing_username:
            raise ValueError("Username already taken")

        # Hash password and create user
        user_dict = user_in.model_dump()
        user_dict["hashed_password"] = get_password_hash(user_dict.pop("password"))

        # Calculate scheduled deletion for anonymous users
        scheduled_deletion = None
        if is_anonymous:
            scheduled_deletion = datetime.now(timezone.utc) + timedelta(days=settings.ANONYMOUS_USER_TTL_DAYS)

        # Bootstrap admin: anyone whose email is in ADMIN_EMAILS gets is_admin on creation.
        is_admin = (
            not is_anonymous
            and user_dict["email"].lower() in settings.admin_emails_set
        )

        db_user = User(
            email=user_dict["email"],
            username=user_dict["username"],
            full_name=user_dict.get("full_name"),
            hashed_password=user_dict["hashed_password"],
            is_anonymous=is_anonymous,
            is_admin=is_admin,
            scheduled_deletion_at=scheduled_deletion
        )

        db.add(db_user)
        await db.flush()
        await db.refresh(db_user)

        return db_user

    async def create_anonymous_user(self, db: AsyncSession) -> User:
        """
        Create an anonymous user with random credentials.

        Args:
            db: Database session

        Returns:
            Created anonymous user
        """
        anonymous_id = str(uuid4())[:8]
        anonymous_email = f"anon_{anonymous_id}@anonymous.tinyworlds.dev"
        anonymous_password = str(uuid4())

        user_data = UserCreate(
            email=anonymous_email,
            password=anonymous_password,
            username=f"anonymous_{anonymous_id}"
        )

        return await self.create_user(db, user_data, is_anonymous=True)

    async def upgrade_anonymous_account(
        self,
        db: AsyncSession,
        user: User,
        email: str,
        username: str,
        password: str
    ) -> User:
        """
        Upgrade an anonymous account to a registered account.

        Args:
            db: Database session
            user: The anonymous user to upgrade
            email: New email address
            username: New username
            password: New password

        Returns:
            Updated user

        Raises:
            ValueError: If user is not anonymous or email/username taken
        """
        if not user.is_anonymous:
            raise ValueError("Account is already registered")

        # Check if email already exists
        existing_email = await self.repository.get_by_email(db, email)
        if existing_email and existing_email.id != user.id:
            raise ValueError("Email already registered")

        # Check if username already exists
        existing_username = await self.repository.get_by_username(db, username)
        if existing_username and existing_username.id != user.id:
            raise ValueError("Username already taken")

        # Update user
        user.email = email
        user.username = username
        user.hashed_password = get_password_hash(password)
        user.is_anonymous = False
        user.scheduled_deletion_at = None
        user.updated_at = datetime.now(timezone.utc)

        await db.flush()
        await db.refresh(user)

        return user

    async def authenticate(
        self,
        db: AsyncSession,
        email: str,
        password: str
    ) -> Optional[User]:
        """
        Authenticate user with email and password.

        Args:
            db: Database session
            email: User email
            password: Plain text password

        Returns:
            User if authentication successful, None otherwise
        """
        user = await self.repository.get_by_email(db, email)
        if not user:
            return None

        if not verify_password(password, user.hashed_password):
            return None

        if not user.is_active:
            return None

        # Bootstrap admin on login: keeps ADMIN_EMAILS as the source of truth so
        # an existing account picks up the flag without manual DB edits.
        if not user.is_admin and user.email.lower() in settings.admin_emails_set:
            user.is_admin = True
            await db.flush()

        return user

    async def create_password_reset_token(
        self,
        db: AsyncSession,
        user: User
    ) -> str:
        """
        Create a password reset token for a user.

        Args:
            db: Database session
            user: User requesting password reset

        Returns:
            The raw reset token (to be sent via email)
        """
        # Invalidate any existing tokens for this user
        await db.execute(
            delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        )

        # Generate new token
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES)

        reset_token = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at
        )

        db.add(reset_token)
        await db.flush()

        return raw_token

    async def validate_password_reset_token(
        self,
        db: AsyncSession,
        raw_token: str
    ) -> Optional[PasswordResetToken]:
        """
        Validate a password reset token.

        Args:
            db: Database session
            raw_token: The raw token from the email link

        Returns:
            The token record if valid, None otherwise
        """
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > datetime.now(timezone.utc)
            )
        )
        return result.scalar_one_or_none()

    async def reset_password(
        self,
        db: AsyncSession,
        raw_token: str,
        new_password: str
    ) -> bool:
        """
        Reset a user's password using a reset token.

        Args:
            db: Database session
            raw_token: The raw token from the email link
            new_password: The new password

        Returns:
            True if password was reset, False if token invalid
        """
        reset_token = await self.validate_password_reset_token(db, raw_token)
        if not reset_token:
            return False

        # Get the user
        user = await db.get(User, reset_token.user_id)
        if not user:
            return False

        # Update password
        user.hashed_password = get_password_hash(new_password)
        user.updated_at = datetime.now(timezone.utc)

        # Mark token as used
        reset_token.used_at = datetime.now(timezone.utc)

        await db.flush()
        return True

    async def cleanup_expired_anonymous_users(self, db: AsyncSession) -> int:
        """
        Delete anonymous users past their scheduled deletion date.

        Args:
            db: Database session

        Returns:
            Number of users deleted
        """
        result = await db.execute(
            delete(User).where(
                User.is_anonymous == True,
                User.scheduled_deletion_at < datetime.now(timezone.utc)
            )
        )
        return result.rowcount
