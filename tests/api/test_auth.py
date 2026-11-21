"""Tests for authentication endpoints."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.models.user import User
from src.api.core.security import get_password_hash


@pytest.mark.auth
class TestUserRegistration:
    """Test user registration endpoint."""

    @pytest.mark.asyncio
    async def test_register_new_user(self, client: AsyncClient):
        """Test successful user registration returns token."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "test@example.com",
                "username": "testuser",
                "password": "testpass123",
                "full_name": "Test User"
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["is_anonymous"] is False
        assert "user_id" in data

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient, db_session: AsyncSession):
        """Test registration with existing email fails."""
        # Create existing user
        existing_user = User(
            email="existing@example.com",
            username="existinguser",
            hashed_password=get_password_hash("password123"),
            full_name="Existing User"
        )
        db_session.add(existing_user)
        await db_session.commit()

        # Attempt to register with same email
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "existing@example.com",
                "username": "newuser",
                "password": "newpassword123",
                "full_name": "New User"
            }
        )

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, client: AsyncClient):
        """Test registration with invalid email format."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "not-an-email",
                "username": "testuser",
                "password": "testpass123",
                "full_name": "Test User"
            }
        )

        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_register_short_password(self, client: AsyncClient):
        """Test registration with password too short."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "test@example.com",
                "username": "testuser",
                "password": "short",
                "full_name": "Test User"
            }
        )

        assert response.status_code == 422  # Validation error


@pytest.mark.auth
class TestUserLogin:
    """Test user login endpoint."""

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, db_session: AsyncSession):
        """Test successful login returns token."""
        # Create test user
        user = User(
            email="test@example.com",
            username="testuser",
            hashed_password=get_password_hash("testpass123"),
            full_name="Test User"
        )
        db_session.add(user)
        await db_session.commit()

        # Login
        response = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "test@example.com",  # OAuth2 uses 'username' field
                "password": "testpass123"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient, db_session: AsyncSession):
        """Test login with wrong password fails."""
        # Create test user
        user = User(
            email="test@example.com",
            username="testuser",
            hashed_password=get_password_hash("correctpassword"),
            full_name="Test User"
        )
        db_session.add(user)
        await db_session.commit()

        # Login with wrong password
        response = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "test@example.com",
                "password": "wrongpassword"
            }
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Test login with non-existent user fails."""
        response = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "nonexistent@example.com",
                "password": "somepassword"
            }
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_inactive_user(self, client: AsyncClient, db_session: AsyncSession):
        """Test login with inactive user fails."""
        # Create inactive user
        user = User(
            email="test@example.com",
            username="testuser",
            hashed_password=get_password_hash("testpass123"),
            full_name="Test User",
            is_active=False
        )
        db_session.add(user)
        await db_session.commit()

        # Attempt login
        response = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "test@example.com",
                "password": "testpass123"
            }
        )

        assert response.status_code == 401


@pytest.mark.auth
class TestGetCurrentUser:
    """Test get current user endpoint."""

    @pytest.mark.asyncio
    async def test_get_current_user_success(self, client: AsyncClient, db_session: AsyncSession):
        """Test getting current user info with valid token."""
        # Create and login user
        user = User(
            email="test@example.com",
            username="testuser",
            hashed_password=get_password_hash("testpass123"),
            full_name="Test User"
        )
        db_session.add(user)
        await db_session.commit()

        # Login to get token
        login_response = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "test@example.com",
                "password": "testpass123"
            }
        )
        token = login_response.json()["access_token"]

        # Get current user
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["username"] == "testuser"
        assert data["full_name"] == "Test User"

    @pytest.mark.asyncio
    async def test_get_current_user_no_token(self, client: AsyncClient):
        """Test getting current user without token fails."""
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_invalid_token(self, client: AsyncClient):
        """Test getting current user with invalid token fails."""
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401
