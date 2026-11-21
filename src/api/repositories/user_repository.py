"""User repository for database operations."""
import base64
import json
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.models.game import Game
from src.api.models.user import User
from src.api.models.user_session import UserSession
from src.api.repositories.base_repository import BaseRepository
from src.api.schemas.user import UserCreate, UserUpdate


def _encode_cursor(created_at: datetime, user_id: UUID) -> str:
    payload = {"c": created_at.isoformat(), "i": str(user_id)}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    return datetime.fromisoformat(payload["c"]), UUID(payload["i"])


class UserRepository(BaseRepository[User, UserCreate, UserUpdate]):
    """Repository for user-specific database operations."""

    def __init__(self):
        """Initialize user repository."""
        super().__init__(User)

    async def get_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        """Get user by email address."""
        result = await db.execute(
            select(User).where(User.email == email)
        )
        return result.scalars().first()

    async def get_by_username(self, db: AsyncSession, username: str) -> Optional[User]:
        """Get user by username."""
        result = await db.execute(
            select(User).where(User.username == username)
        )
        return result.scalars().first()

    async def is_active(self, db: AsyncSession, user_id: int) -> bool:
        """Check if user is active."""
        user = await self.get(db, user_id)
        return user.is_active if user else False

    async def list_for_admin(
        self,
        db: AsyncSession,
        *,
        q: Optional[str] = None,
        include_anonymous: bool = False,
        is_admin: Optional[bool] = None,
        is_active: Optional[bool] = None,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> tuple[list[dict], Optional[str], int]:
        """Paginated user list for the admin panel.

        Returns (rows, next_cursor, total_matching). Each row is a dict shaped
        for AdminUserResponse — User columns plus derived last_seen_at /
        active_session_count / game_count aggregates.
        """
        limit = max(1, min(limit, 200))

        last_seen_sub = (
            select(
                UserSession.user_id.label("user_id"),
                func.max(UserSession.last_active_at).label("last_seen_at"),
                func.sum(
                    case((UserSession.is_active.is_(True), 1), else_=0)
                ).label("active_session_count"),
            )
            .group_by(UserSession.user_id)
            .subquery()
        )

        game_count_sub = (
            select(
                Game.owner_id.label("owner_id"),
                func.count(Game.id).label("game_count"),
            )
            .group_by(Game.owner_id)
            .subquery()
        )

        filters = []
        if not include_anonymous:
            filters.append(User.is_anonymous.is_(False))
        if is_admin is not None:
            filters.append(User.is_admin.is_(is_admin))
        if is_active is not None:
            filters.append(User.is_active.is_(is_active))
        if q:
            like = f"%{q.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(User.email).like(like),
                    func.lower(User.username).like(like),
                    func.lower(func.coalesce(User.full_name, "")).like(like),
                )
            )

        where_clause = and_(*filters) if filters else None

        if cursor:
            cur_created_at, cur_id = _decode_cursor(cursor)
            cursor_clause = or_(
                User.created_at < cur_created_at,
                and_(User.created_at == cur_created_at, User.id < cur_id),
            )
            where_clause = and_(where_clause, cursor_clause) if where_clause is not None else cursor_clause

        count_q = select(func.count()).select_from(User)
        if filters:
            count_q = count_q.where(and_(*filters))
        total = (await db.execute(count_q)).scalar() or 0

        stmt = (
            select(
                User,
                last_seen_sub.c.last_seen_at,
                last_seen_sub.c.active_session_count,
                game_count_sub.c.game_count,
            )
            .outerjoin(last_seen_sub, last_seen_sub.c.user_id == User.id)
            .outerjoin(game_count_sub, game_count_sub.c.owner_id == User.id)
            .order_by(User.created_at.desc(), User.id.desc())
            .limit(limit + 1)
        )
        if where_clause is not None:
            stmt = stmt.where(where_clause)

        result = await db.execute(stmt)
        all_rows = result.all()

        rows: list[dict] = []
        for user, last_seen_at, active_session_count, game_count in all_rows[:limit]:
            rows.append(
                {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "full_name": user.full_name,
                    "is_active": user.is_active,
                    "is_admin": user.is_admin,
                    "is_anonymous": user.is_anonymous,
                    "scheduled_deletion_at": user.scheduled_deletion_at,
                    "created_at": user.created_at,
                    "last_seen_at": last_seen_at,
                    "active_session_count": int(active_session_count or 0),
                    "game_count": int(game_count or 0),
                }
            )

        next_cursor: Optional[str] = None
        if len(all_rows) > limit:
            last = rows[-1]
            next_cursor = _encode_cursor(last["created_at"], last["id"])

        return rows, next_cursor, total
