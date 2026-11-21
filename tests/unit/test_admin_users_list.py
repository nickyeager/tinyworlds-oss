"""Unit tests for UserRepository.list_for_admin — search, filters, cursor pagination."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.models.game import Game
from src.api.models.user import User
from src.api.models.user_session import UserSession
from src.api.repositories.user_repository import UserRepository


def _make_user(
    *,
    email: str,
    username: str,
    full_name: str | None = None,
    is_anonymous: bool = False,
    is_admin: bool = False,
    is_active: bool = True,
    created_at: datetime | None = None,
) -> User:
    return User(
        id=uuid4(),
        email=email,
        username=username,
        hashed_password="x",
        full_name=full_name,
        is_anonymous=is_anonymous,
        is_admin=is_admin,
        is_active=is_active,
        created_at=created_at or datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_list_excludes_anonymous_by_default(db_session: AsyncSession):
    repo = UserRepository()
    db_session.add(_make_user(email="real@x.com", username="real"))
    db_session.add(_make_user(email="anon@x.com", username="anon", is_anonymous=True))
    await db_session.commit()

    rows, _, total = await repo.list_for_admin(db_session)

    assert total == 1
    assert [r["email"] for r in rows] == ["real@x.com"]


@pytest.mark.asyncio
async def test_list_include_anonymous(db_session: AsyncSession):
    repo = UserRepository()
    db_session.add(_make_user(email="real@x.com", username="real"))
    db_session.add(_make_user(email="anon@x.com", username="anon", is_anonymous=True))
    await db_session.commit()

    rows, _, total = await repo.list_for_admin(db_session, include_anonymous=True)

    assert total == 2
    assert {r["email"] for r in rows} == {"real@x.com", "anon@x.com"}


@pytest.mark.asyncio
async def test_list_filter_is_admin(db_session: AsyncSession):
    repo = UserRepository()
    db_session.add(_make_user(email="a@x.com", username="a", is_admin=True))
    db_session.add(_make_user(email="b@x.com", username="b", is_admin=False))
    await db_session.commit()

    rows, _, _ = await repo.list_for_admin(db_session, is_admin=True)
    assert [r["email"] for r in rows] == ["a@x.com"]

    rows, _, _ = await repo.list_for_admin(db_session, is_admin=False)
    assert [r["email"] for r in rows] == ["b@x.com"]


@pytest.mark.asyncio
async def test_list_filter_is_active(db_session: AsyncSession):
    repo = UserRepository()
    db_session.add(_make_user(email="on@x.com", username="on", is_active=True))
    db_session.add(_make_user(email="off@x.com", username="off", is_active=False))
    await db_session.commit()

    rows, _, _ = await repo.list_for_admin(db_session, is_active=False)
    assert [r["email"] for r in rows] == ["off@x.com"]


@pytest.mark.asyncio
async def test_list_search_matches_email_username_fullname(db_session: AsyncSession):
    repo = UserRepository()
    db_session.add(_make_user(email="alice@x.com", username="alice", full_name="Alice Adams"))
    db_session.add(_make_user(email="bob@y.com", username="bobby", full_name="Bob Jones"))
    db_session.add(_make_user(email="carol@x.com", username="c", full_name="Carol Smith"))
    await db_session.commit()

    # Email substring
    rows, _, _ = await repo.list_for_admin(db_session, q="alice")
    assert {r["email"] for r in rows} == {"alice@x.com"}

    # Username substring
    rows, _, _ = await repo.list_for_admin(db_session, q="BOB")
    assert {r["email"] for r in rows} == {"bob@y.com"}

    # full_name substring, case-insensitive
    rows, _, _ = await repo.list_for_admin(db_session, q="smith")
    assert {r["email"] for r in rows} == {"carol@x.com"}


@pytest.mark.asyncio
async def test_list_cursor_pagination_no_duplicates_or_gaps(db_session: AsyncSession):
    repo = UserRepository()
    base = datetime.now(timezone.utc)
    for i in range(7):
        db_session.add(
            _make_user(
                email=f"u{i}@x.com",
                username=f"u{i}",
                # Make created_at distinct + descending so order is stable.
                created_at=base - timedelta(seconds=i),
            )
        )
    await db_session.commit()

    page1, cursor1, total = await repo.list_for_admin(db_session, limit=3)
    assert total == 7
    assert len(page1) == 3
    assert cursor1 is not None

    page2, cursor2, _ = await repo.list_for_admin(db_session, limit=3, cursor=cursor1)
    assert len(page2) == 3
    assert cursor2 is not None

    page3, cursor3, _ = await repo.list_for_admin(db_session, limit=3, cursor=cursor2)
    assert len(page3) == 1
    assert cursor3 is None  # No more pages

    seen = [r["email"] for r in page1 + page2 + page3]
    assert len(seen) == len(set(seen)) == 7


@pytest.mark.asyncio
async def test_list_includes_session_and_game_aggregates(db_session: AsyncSession):
    repo = UserRepository()
    user = _make_user(email="a@x.com", username="a")
    db_session.add(user)
    await db_session.flush()

    # One active session
    session = UserSession(
        id=uuid4(),
        user_id=user.id,
        is_active=True,
        last_active_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(session)

    # Two owned games
    for i in range(2):
        db_session.add(
            Game(
                id=uuid4(),
                owner_id=user.id,
                name=f"g{i}",
                description="",
                project_path=f"/tmp/g{i}",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    await db_session.commit()

    rows, _, _ = await repo.list_for_admin(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert row["active_session_count"] == 1
    assert row["game_count"] == 2
    assert row["last_seen_at"] is not None
