"""Repository layer for game persistence."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from src.api.models import (
    Game,
    GameAsset,
    GameCollaborator,
    GameVersion,
    ModifiedFile,
    User,
)


class GameRepository:
    """Repository for game CRUD operations."""

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session."""
        self.session = session

    async def create_game(
        self,
        name: str,
        owner_id: UUID,
        project_path: Path,
        template_repo_url: Optional[str] = None,
        template_commit_hash: Optional[str] = None,
        description: Optional[str] = None,
        visibility: str = "private",
    ) -> Game:
        """Create a new game."""
        game = Game(
            name=name,
            owner_id=owner_id,
            project_path=str(project_path),
            template_repo_url=template_repo_url,
            template_commit_hash=template_commit_hash,
            description=description,
            visibility=visibility,
        )
        self.session.add(game)
        await self.session.flush()
        return game

    async def get_game(self, game_id: UUID) -> Optional[Game]:
        """Get a game by ID with all relationships loaded."""
        stmt = (
            select(Game)
            .options(
                selectinload(Game.owner),
                selectinload(Game.collaborators).selectinload(GameCollaborator.user),
                selectinload(Game.current_version),
            )
            .where(Game.id == game_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_games_by_user(
        self,
        user_id: UUID,
        include_collaborations: bool = True,
        visibility_filter: Optional[List[str]] = None,
    ) -> List[Game]:
        """Get all games owned by or accessible to a user."""
        conditions = [Game.owner_id == user_id]

        if include_collaborations:
            # Include games where user is a collaborator
            collab_subquery = (
                select(GameCollaborator.game_id)
                .where(GameCollaborator.user_id == user_id)
                .scalar_subquery()
            )
            conditions.append(Game.id.in_(collab_subquery))

        stmt = (
            select(Game)
            .options(
                selectinload(Game.owner),
                selectinload(Game.current_version),
            )
            .where(or_(*conditions))
        )

        if visibility_filter:
            stmt = stmt.where(Game.visibility.in_(visibility_filter))

        stmt = stmt.order_by(desc(Game.updated_at))

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_game(
        self,
        game_id: UUID,
        **updates,
    ) -> Optional[Game]:
        """Update game fields."""
        game = await self.get_game(game_id)
        if not game:
            return None

        for key, value in updates.items():
            if hasattr(game, key):
                setattr(game, key, value)

        await self.session.flush()
        return game

    async def delete_game(self, game_id: UUID) -> bool:
        """Delete a game (soft delete via cascade)."""
        game = await self.get_game(game_id)
        if not game:
            return False

        await self.session.delete(game)
        await self.session.flush()
        return True

    async def check_user_access(
        self,
        game_id: UUID,
        user_id: UUID,
        required_role: Optional[str] = None,
    ) -> bool:
        """Check if user has access to a game."""
        game = await self.get_game(game_id)
        if not game:
            return False

        # Owner has all access
        if game.owner_id == user_id:
            return True

        # Check collaborator access
        stmt = select(GameCollaborator).where(
            and_(
                GameCollaborator.game_id == game_id,
                GameCollaborator.user_id == user_id,
            )
        )
        result = await self.session.execute(stmt)
        collaborator = result.scalar_one_or_none()

        if not collaborator:
            return False

        if required_role:
            # Check role hierarchy: admin > editor > viewer
            role_hierarchy = {"viewer": 0, "editor": 1, "admin": 2}
            return role_hierarchy.get(collaborator.role, 0) >= role_hierarchy.get(required_role, 0)

        return True


class GameVersionRepository:
    """Repository for game version operations."""

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session."""
        self.session = session

    async def create_version(
        self,
        game_id: UUID,
        version_number: int,
        snapshot: Dict,
        intent: str,
        created_by: UUID,
        change_summary: Optional[str] = None,
    ) -> GameVersion:
        """Create a new game version."""
        version = GameVersion(
            game_id=game_id,
            version_number=version_number,
            snapshot=snapshot,
            intent=intent,
            created_by=created_by,
            change_summary=change_summary,
        )
        self.session.add(version)
        await self.session.flush()
        return version

    async def get_version(self, version_id: UUID) -> Optional[GameVersion]:
        """Get a version by ID."""
        stmt = (
            select(GameVersion)
            .options(
                selectinload(GameVersion.creator),
                selectinload(GameVersion.assets),
                selectinload(GameVersion.modified_files),
            )
            .where(GameVersion.id == version_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_versions_by_game(
        self,
        game_id: UUID,
        limit: Optional[int] = None,
    ) -> List[GameVersion]:
        """Get all versions for a game."""
        stmt = (
            select(GameVersion)
            .options(selectinload(GameVersion.creator))
            .where(GameVersion.game_id == game_id)
            .order_by(desc(GameVersion.version_number))
        )

        if limit:
            stmt = stmt.limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_version(self, game_id: UUID) -> Optional[GameVersion]:
        """Get the latest version for a game."""
        versions = await self.get_versions_by_game(game_id, limit=1)
        return versions[0] if versions else None

    async def get_next_version_number(self, game_id: UUID) -> int:
        """Get the next version number for a game."""
        latest = await self.get_latest_version(game_id)
        return (latest.version_number + 1) if latest else 1


class GameAssetRepository:
    """Repository for game asset operations."""

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session."""
        self.session = session

    async def create_asset(
        self,
        game_id: UUID,
        asset_type: str,
        asset_name: str,
        file_path: Path,
        version_id: Optional[UUID] = None,
        file_size_bytes: Optional[int] = None,
        mime_type: Optional[str] = None,
        generation_prompt: Optional[str] = None,
        pixel_art_applied: bool = False,
        godot_resource_path: Optional[str] = None,
    ) -> GameAsset:
        """Create a new game asset."""
        asset = GameAsset(
            game_id=game_id,
            version_id=version_id,
            asset_type=asset_type,
            asset_name=asset_name,
            file_path=str(file_path),
            file_size_bytes=file_size_bytes,
            mime_type=mime_type,
            generation_prompt=generation_prompt,
            pixel_art_applied=pixel_art_applied,
            godot_resource_path=godot_resource_path,
        )
        self.session.add(asset)
        await self.session.flush()
        return asset

    async def get_assets_by_game(
        self,
        game_id: UUID,
        asset_type: Optional[str] = None,
    ) -> List[GameAsset]:
        """Get all assets for a game."""
        stmt = select(GameAsset).where(GameAsset.game_id == game_id)

        if asset_type:
            stmt = stmt.where(GameAsset.asset_type == asset_type)

        stmt = stmt.order_by(desc(GameAsset.created_at))

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_assets_by_version(self, version_id: UUID) -> List[GameAsset]:
        """Get all assets for a specific version."""
        stmt = (
            select(GameAsset)
            .where(GameAsset.version_id == version_id)
            .order_by(GameAsset.asset_type, GameAsset.asset_name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class ModifiedFileRepository:
    """Repository for modified file tracking."""

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session."""
        self.session = session

    async def create_modified_file(
        self,
        version_id: UUID,
        file_path: str,
        modification_type: str,
        diff: Optional[str] = None,
    ) -> ModifiedFile:
        """Record a modified file."""
        modified_file = ModifiedFile(
            version_id=version_id,
            file_path=file_path,
            modification_type=modification_type,
            diff=diff,
        )
        self.session.add(modified_file)
        await self.session.flush()
        return modified_file

    async def get_modified_files_by_version(self, version_id: UUID) -> List[ModifiedFile]:
        """Get all modified files for a version."""
        stmt = (
            select(ModifiedFile)
            .where(ModifiedFile.version_id == version_id)
            .order_by(ModifiedFile.file_path)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class GameCollaboratorRepository:
    """Repository for game collaborator operations."""

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session."""
        self.session = session

    async def add_collaborator(
        self,
        game_id: UUID,
        user_id: UUID,
        role: str = "editor",
        invited_by: Optional[UUID] = None,
    ) -> GameCollaborator:
        """Add a collaborator to a game."""
        collaborator = GameCollaborator(
            game_id=game_id,
            user_id=user_id,
            role=role,
            invited_by=invited_by,
        )
        self.session.add(collaborator)
        await self.session.flush()
        return collaborator

    async def get_collaborators(self, game_id: UUID) -> List[GameCollaborator]:
        """Get all collaborators for a game."""
        stmt = (
            select(GameCollaborator)
            .options(selectinload(GameCollaborator.user))
            .where(GameCollaborator.game_id == game_id)
            .order_by(GameCollaborator.invited_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_collaborator_role(
        self,
        game_id: UUID,
        user_id: UUID,
        role: str,
    ) -> Optional[GameCollaborator]:
        """Update a collaborator's role."""
        stmt = select(GameCollaborator).where(
            and_(
                GameCollaborator.game_id == game_id,
                GameCollaborator.user_id == user_id,
            )
        )
        result = await self.session.execute(stmt)
        collaborator = result.scalar_one_or_none()

        if collaborator:
            collaborator.role = role
            await self.session.flush()

        return collaborator

    async def remove_collaborator(
        self,
        game_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Remove a collaborator from a game."""
        stmt = select(GameCollaborator).where(
            and_(
                GameCollaborator.game_id == game_id,
                GameCollaborator.user_id == user_id,
            )
        )
        result = await self.session.execute(stmt)
        collaborator = result.scalar_one_or_none()

        if collaborator:
            await self.session.delete(collaborator)
            await self.session.flush()
            return True

        return False
