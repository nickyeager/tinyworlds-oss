"""Shared fixtures for e2e tests.

Provides common utilities for:
- HTTP client setup
- API key validation
- Game cleanup
- SSE parsing
- Config value extraction
"""
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.api.main import app
from src.api.core.config import get_settings
from src.api.core.database import Base, get_db

settings = get_settings()

# Test database URL (in-memory SQLite)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


# =============================================================================
# API Key Fixtures
# =============================================================================

@pytest.fixture
def require_anthropic_key():
    """Require ANTHROPIC_API_KEY for agent tests."""
    key = os.getenv("ANTHROPIC_API_KEY")
    assert key, "ANTHROPIC_API_KEY environment variable required for this test"
    return key


@pytest.fixture
def require_google_key():
    """Require GOOGLE_API_KEY for sprite generation tests."""
    key = os.getenv("GOOGLE_API_KEY")
    assert key, "GOOGLE_API_KEY environment variable required for this test"
    return key


@pytest.fixture
def require_azure_keys():
    """Require Azure Speech keys for voice tests."""
    key = os.getenv("AZURE_SPEECH_KEY")
    region = os.getenv("AZURE_SPEECH_REGION")
    assert key, "AZURE_SPEECH_KEY environment variable required for this test"
    assert region, "AZURE_SPEECH_REGION environment variable required for this test"
    return {"key": key, "region": region}


# =============================================================================
# Rate Limiter Reset Fixture
# =============================================================================

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


# =============================================================================
# HTTP Client Fixtures
# =============================================================================

@pytest.fixture
async def client():
    """Async HTTP client for FastAPI app with isolated test database."""
    # Create async engine with in-memory database
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
    )

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session factory
    AsyncSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db():
        async with AsyncSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()

    # Drop tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def auth_token(client):
    """Get authentication token for test user."""
    # Try anonymous auth first (simpler)
    response = await client.post(f"{settings.API_V1_PREFIX}/auth/anonymous")
    if response.status_code == 200:
        return response.json()["access_token"]

    # Fall back to register/login
    await client.post(
        f"{settings.API_V1_PREFIX}/auth/register",
        json={
            "email": "e2e-test@example.com",
            "username": "e2e_test",
            "password": "testpass123"
        }
    )
    response = await client.post(
        f"{settings.API_V1_PREFIX}/auth/login",
        data={"username": "e2e-test@example.com", "password": "testpass123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["access_token"]


# =============================================================================
# Cleanup Fixtures
# =============================================================================

@pytest.fixture
def cleanup_games():
    """Track and cleanup created game directories after test."""
    paths: list[Path] = []
    yield paths
    for path in paths:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def unique_game_id():
    """Generate a unique game ID for tests."""
    return f"e2e-test-{int(time.time())}-{os.getpid()}"


# =============================================================================
# SSE Parsing Helpers
# =============================================================================

def parse_sse_stream(response_text: str) -> list[dict[str, Any]]:
    """Parse SSE response text into list of event dictionaries.

    Args:
        response_text: Raw SSE response text with "data: {json}" lines

    Returns:
        List of parsed event dictionaries
    """
    events = []
    for line in response_text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                event_data = json.loads(line[6:])
                events.append(event_data)
            except json.JSONDecodeError:
                # Skip malformed JSON lines
                pass
    return events


def get_events_by_type(events: list[dict], event_type: str) -> list[dict]:
    """Filter events by type field.

    Args:
        events: List of parsed event dictionaries
        event_type: Event type to filter for (e.g., "complete", "ThinkingEvent")

    Returns:
        List of events matching the type
    """
    # Check both 'type' and 'event_type' fields for compatibility
    return [e for e in events if e.get("type") == event_type or e.get("event_type") == event_type]


def get_first_event_by_type(events: list[dict], event_type: str) -> dict | None:
    """Get first event matching the type.

    Args:
        events: List of parsed event dictionaries
        event_type: Event type to find

    Returns:
        First matching event or None
    """
    matching = get_events_by_type(events, event_type)
    return matching[0] if matching else None


# =============================================================================
# Config Value Extraction
# =============================================================================

def extract_config_value(config_text: str, key: str) -> int | None:
    """Extract numeric value from TypeScript config file.

    Args:
        config_text: Contents of config.ts file
        key: Config key to extract (e.g., "PLAYER_SPEED")

    Returns:
        Integer value or None if not found
    """
    # Match patterns like: PLAYER_SPEED: 200 or PLAYER_SPEED = 200
    match = re.search(rf"{key}\s*[:=]\s*(\d+)", config_text)
    return int(match.group(1)) if match else None


def extract_config_color(config_text: str, key: str) -> list[int] | None:
    """Extract RGB color array from TypeScript config file.

    Args:
        config_text: Contents of config.ts file
        key: Config key to extract (e.g., "PLAYER_COLOR")

    Returns:
        List of [R, G, B] values or None if not found
    """
    # Match patterns like: PLAYER_COLOR: [255, 0, 0]
    match = re.search(rf"{key}\s*[:=]\s*\[(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\]", config_text)
    if match:
        return [int(match.group(1)), int(match.group(2)), int(match.group(3))]
    return None


# =============================================================================
# Audio Fixtures
# =============================================================================

@pytest.fixture
def fixtures_path():
    """Path to test fixtures directory."""
    return Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def sample_audio_path(fixtures_path):
    """Path to sample audio file for voice tests."""
    audio_path = fixtures_path / "audio" / "make_space_shooter.wav"
    if not audio_path.exists():
        pytest.fail(
            f"Audio fixture not found at {audio_path}. "
            "Create a .wav file with the spoken words 'make a space shooter'."
        )
    return audio_path


@pytest.fixture
def sample_modify_audio_path(fixtures_path):
    """Path to sample audio for modification command."""
    audio_path = fixtures_path / "audio" / "jump_higher.wav"
    if not audio_path.exists():
        pytest.fail(
            f"Audio fixture not found at {audio_path}. "
            "Create a .wav file with the spoken words 'make jumps higher'."
        )
    return audio_path
