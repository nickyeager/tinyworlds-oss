"""Game models for persistence layer."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from src.api.core.database import Base
from src.api.core.db_types import JSON, UUID


class Game(Base):
    """Core game project table."""

    __tablename__ = "games"

    id = Column(UUID(), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(UUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    visibility = Column(String(20), nullable=False, default="private", index=True)
    engine = Column(
        String(20), nullable=False, default="godot",
        server_default="godot", index=True,
    )
    project_path = Column(Text, nullable=False)
    template_repo_url = Column(Text, nullable=True)
    template_commit_hash = Column(String(40), nullable=True)
    current_version_id = Column(UUID(), ForeignKey("game_versions.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Constraints
    __table_args__ = (
        CheckConstraint("visibility IN ('private', 'public', 'unlisted')", name="games_visibility_check"),
        CheckConstraint("engine IN ('godot', 'bevy')", name="games_engine_check"),
    )

    # Relationships
    owner = relationship("User", back_populates="owned_games", foreign_keys=[owner_id])
    collaborators = relationship("GameCollaborator", back_populates="game", cascade="all, delete-orphan")
    versions = relationship("GameVersion", back_populates="game", foreign_keys="GameVersion.game_id", cascade="all, delete-orphan")
    current_version = relationship("GameVersion", foreign_keys=[current_version_id], post_update=True)
    assets = relationship("GameAsset", back_populates="game", cascade="all, delete-orphan")


class GameCollaborator(Base):
    """Game collaboration junction table with role-based access."""

    __tablename__ = "game_collaborators"

    id = Column(UUID(), primary_key=True, default=uuid4)
    game_id = Column(UUID(), ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False, default="editor")
    invited_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    invited_by = Column(UUID(), ForeignKey("users.id"), nullable=True)

    # Constraints
    __table_args__ = (
        UniqueConstraint("game_id", "user_id", name="uq_game_collaborators_game_user"),
        CheckConstraint("role IN ('viewer', 'editor', 'admin')", name="game_collaborators_role_check"),
    )

    # Relationships
    game = relationship("Game", back_populates="collaborators")
    user = relationship("User", back_populates="game_collaborations", foreign_keys=[user_id])
    inviter = relationship("User", foreign_keys=[invited_by])


class GameVersion(Base):
    """Version history using snapshot-based storage."""

    __tablename__ = "game_versions"

    id = Column(UUID(), primary_key=True, default=uuid4)
    game_id = Column(UUID(), ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    snapshot = Column(JSON(), nullable=False)
    intent = Column(Text, nullable=False)
    change_summary = Column(Text, nullable=True)
    created_by = Column(UUID(), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Constraints
    __table_args__ = (
        UniqueConstraint("game_id", "version_number", name="uq_game_versions_game_version"),
    )

    # Relationships
    game = relationship("Game", back_populates="versions", foreign_keys=[game_id])
    creator = relationship("User", back_populates="created_versions", foreign_keys=[created_by])
    assets = relationship("GameAsset", back_populates="version")
    modified_files = relationship("ModifiedFile", back_populates="version", cascade="all, delete-orphan")


class GameAsset(Base):
    """Generated assets with metadata and file system paths."""

    __tablename__ = "game_assets"

    id = Column(UUID(), primary_key=True, default=uuid4)
    game_id = Column(UUID(), ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id = Column(UUID(), ForeignKey("game_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    asset_type = Column(String(50), nullable=False, index=True)
    asset_name = Column(String(255), nullable=False)
    file_path = Column(Text, nullable=False)
    file_size_bytes = Column(BigInteger, nullable=True)
    mime_type = Column(String(100), nullable=True)
    generation_prompt = Column(Text, nullable=True)
    pixel_art_applied = Column(Boolean, default=False)
    godot_resource_path = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    game = relationship("Game", back_populates="assets")
    version = relationship("GameVersion", back_populates="assets")


class ModifiedFile(Base):
    """Code modifications per version."""

    __tablename__ = "modified_files"

    id = Column(UUID(), primary_key=True, default=uuid4)
    version_id = Column(UUID(), ForeignKey("game_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = Column(Text, nullable=False)
    modification_type = Column(String(20), nullable=False)
    diff = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Constraints
    __table_args__ = (
        CheckConstraint("modification_type IN ('created', 'updated', 'deleted')", name="modified_files_type_check"),
    )

    # Relationships
    version = relationship("GameVersion", back_populates="modified_files")
