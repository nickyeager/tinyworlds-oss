"""Shared test fixtures for API tests."""
import os
from typing import AsyncGenerator
# Set required environment variables before imports
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "test-key")
os.environ.setdefault("USE_AZURE", "false")  # Disable Azure to avoid client init issues

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.api.core.config import Settings
from src.api.core.database import Base, get_db
from src.api.main import app


# Test database URL (in-memory SQLite)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Create a fresh database session for each test.
    Uses in-memory SQLite for fast, isolated tests.
    """
    # Create async engine
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
    )

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session
    AsyncSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with AsyncSessionLocal() as session:
        yield session

    # Drop tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Create test client with overridden database dependency.
    """

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    # Use transport parameter with ASGITransport for newer httpx versions
    from httpx import ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def test_settings() -> Settings:
    """Test settings with overrides."""
    return Settings(
        SECRET_KEY="test-secret-key-for-testing-only",
        DATABASE_URL=TEST_DATABASE_URL,
        DEBUG=True,
    )


@pytest.fixture
async def auth_user(db_session: AsyncSession):
    """Create and return an authenticated test user."""
    from src.api.models.user import User
    from src.api.core.security import get_password_hash

    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password=get_password_hash("testpass123"),
        full_name="Test User"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def auth_token(client: AsyncClient, auth_user) -> str:
    """Get authentication token for test user."""
    response = await client.post(
        "/api/v1/auth/login",
        data={
            "username": auth_user.email,
            "password": "testpass123"
        }
    )
    return response.json()["access_token"]


@pytest.fixture
async def auth_client(client: AsyncClient, auth_user) -> AsyncClient:
    """Create authenticated client with token in headers."""
    # Login to get token
    response = await client.post(
        "/api/v1/auth/login",
        data={
            "username": auth_user.email,
            "password": "testpass123"
        }
    )
    token = response.json()["access_token"]

    # Add token to client headers
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """Reset rate limiters before each test to avoid interference."""
    from src.api.middleware.rate_limit import (
        login_limiter,
        register_limiter,
        password_reset_limiter,
    )
    # Clear all buckets
    login_limiter._buckets.clear()
    register_limiter._buckets.clear()
    password_reset_limiter._buckets.clear()
    yield


@pytest.fixture(autouse=True)
async def reap_api_background_jobs():
    # ASGITransport does not run application lifespan shutdown. Jobs outliving
    # their response must be reaped before the test's event loop/database closes.
    yield
    from src.api.services.game_jobs import stop_jobs
    await stop_jobs()
