"""Migrate users to UUID and add game persistence schema

Revision ID: 003
Revises:
Create Date: 2025-12-11

This migration:
1. Migrates existing users table from INTEGER to UUID (String-based)
2. Adds username field to users
3. Creates complete game persistence schema (SQLite compatible)
"""
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Migrate to UUID and create game schema."""

    # Step 1: Create new users table with UUID
    op.create_table(
        'users_new',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('username', sa.String(100), nullable=False, unique=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )

    # Step 2: Migrate existing users with UUID generation
    # We'll use Python to generate UUIDs for existing users
    conn = op.get_bind()

    # Get existing users
    result = conn.execute(sa.text("SELECT id, email, hashed_password, full_name, is_active, created_at, updated_at FROM users"))
    users = result.fetchall()

    # Insert into new table with UUIDs
    username_counter = {}
    for user in users:
        new_uuid = str(uuid4())
        # Generate username from email (before @)
        base_username = user[1].split('@')[0]

        # Handle duplicate usernames by adding a counter
        if base_username in username_counter:
            username_counter[base_username] += 1
            username = f"{base_username}{username_counter[base_username]}"
        else:
            username_counter[base_username] = 0
            username = base_username

        conn.execute(
            sa.text("""
                INSERT INTO users_new (id, email, username, hashed_password, full_name, is_active, created_at, updated_at)
                VALUES (:id, :email, :username, :hashed_password, :full_name, :is_active, :created_at, :updated_at)
            """),
            {
                'id': new_uuid,
                'email': user[1],
                'username': username,
                'hashed_password': user[2],
                'full_name': user[3],
                'is_active': user[4],
                'created_at': user[5],
                'updated_at': user[6],
            }
        )

    # Step 3: Drop old table and rename new one
    op.drop_table('users')
    op.rename_table('users_new', 'users')

    # Step 4: Recreate indexes
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
    op.create_index('ix_users_id', 'users', ['id'])

    # Step 5: Create games table
    op.create_table(
        'games',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('owner_id', sa.String(36), nullable=False),
        sa.Column('visibility', sa.String(20), nullable=False, server_default='private'),
        sa.Column('project_path', sa.Text, nullable=False),
        sa.Column('template_repo_url', sa.Text, nullable=True),
        sa.Column('template_commit_hash', sa.String(40), nullable=True),
        sa.Column('current_version_id', sa.String(36), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.CheckConstraint("visibility IN ('private', 'public', 'unlisted')", name='games_visibility_check'),
    )
    op.create_index('ix_games_owner_id', 'games', ['owner_id'])
    op.create_index('ix_games_visibility', 'games', ['visibility'])
    op.create_index('ix_games_created_at', 'games', ['created_at'])

    # Step 6: Create game_collaborators table
    op.create_table(
        'game_collaborators',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('game_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default='editor'),
        sa.Column('invited_at', sa.DateTime, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('invited_by', sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invited_by'], ['users.id']),
        sa.UniqueConstraint('game_id', 'user_id', name='uq_game_collaborators_game_user'),
        sa.CheckConstraint("role IN ('viewer', 'editor', 'admin')", name='game_collaborators_role_check'),
    )
    op.create_index('ix_game_collaborators_game_id', 'game_collaborators', ['game_id'])
    op.create_index('ix_game_collaborators_user_id', 'game_collaborators', ['user_id'])

    # Step 7: Create game_versions table
    op.create_table(
        'game_versions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('game_id', sa.String(36), nullable=False),
        sa.Column('version_number', sa.Integer, nullable=False),
        sa.Column('snapshot', sa.Text, nullable=False),  # JSON as TEXT
        sa.Column('intent', sa.Text, nullable=False),
        sa.Column('change_summary', sa.Text, nullable=True),
        sa.Column('created_by', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.UniqueConstraint('game_id', 'version_number', name='uq_game_versions_game_version'),
    )
    op.create_index('ix_game_versions_game_id', 'game_versions', ['game_id'])
    op.create_index('ix_game_versions_created_at', 'game_versions', ['created_at'])
    op.create_index('ix_game_versions_game_version', 'game_versions', ['game_id', 'version_number'])

    # Step 8: Create game_assets table
    op.create_table(
        'game_assets',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('game_id', sa.String(36), nullable=False),
        sa.Column('version_id', sa.String(36), nullable=True),
        sa.Column('asset_type', sa.String(50), nullable=False),
        sa.Column('asset_name', sa.String(255), nullable=False),
        sa.Column('file_path', sa.Text, nullable=False),
        sa.Column('file_size_bytes', sa.BigInteger, nullable=True),
        sa.Column('mime_type', sa.String(100), nullable=True),
        sa.Column('generation_prompt', sa.Text, nullable=True),
        sa.Column('pixel_art_applied', sa.Boolean, server_default='0'),
        sa.Column('godot_resource_path', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['version_id'], ['game_versions.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_game_assets_game_id', 'game_assets', ['game_id'])
    op.create_index('ix_game_assets_version_id', 'game_assets', ['version_id'])
    op.create_index('ix_game_assets_asset_type', 'game_assets', ['asset_type'])

    # Step 9: Create modified_files table
    op.create_table(
        'modified_files',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('version_id', sa.String(36), nullable=False),
        sa.Column('file_path', sa.Text, nullable=False),
        sa.Column('modification_type', sa.String(20), nullable=False),
        sa.Column('diff', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['version_id'], ['game_versions.id'], ondelete='CASCADE'),
        sa.CheckConstraint("modification_type IN ('created', 'updated', 'deleted')", name='modified_files_type_check'),
    )
    op.create_index('ix_modified_files_version_id', 'modified_files', ['version_id'])


def downgrade() -> None:
    """Revert to INTEGER user IDs and drop game tables."""

    # Drop game tables
    op.drop_table('modified_files')
    op.drop_table('game_assets')
    op.drop_table('game_versions')
    op.drop_table('game_collaborators')
    op.drop_table('games')

    # Recreate old users table with INTEGER
    op.create_table(
        'users_old',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=False),
    )

    # Migrate users back (lose UUIDs, get new sequential IDs)
    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT email, hashed_password, full_name, is_active, created_at, updated_at FROM users"))
    users = result.fetchall()

    for user in users:
        conn.execute(
            sa.text("""
                INSERT INTO users_old (email, hashed_password, full_name, is_active, created_at, updated_at)
                VALUES (:email, :hashed_password, :full_name, :is_active, :created_at, :updated_at)
            """),
            {
                'email': user[0],
                'hashed_password': user[1],
                'full_name': user[2],
                'is_active': user[3],
                'created_at': user[4],
                'updated_at': user[5],
            }
        )

    op.drop_table('users')
    op.rename_table('users_old', 'users')

    # Recreate old indexes
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_id', 'users', ['id'])
