"""Add authentication schema for proper user management

Revision ID: 004
Revises: 003
Create Date: 2026-01-16

This migration:
1. Adds is_anonymous, scheduled_deletion_at to users table
2. Creates password_reset_tokens table
"""
from typing import Sequence, Union
from datetime import datetime, timedelta

from alembic import op
import sqlalchemy as sa

revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add authentication schema."""
    conn = op.get_bind()

    # SQLite requires table recreation to add columns
    # Step 1: Create new users table with additional columns
    op.create_table(
        'users_new',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('username', sa.String(100), nullable=False, unique=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='1'),
        sa.Column('is_anonymous', sa.Boolean, nullable=False, server_default='0'),
        sa.Column('scheduled_deletion_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )

    # Step 2: Copy existing data, marking anonymous users
    conn.execute(sa.text("""
        INSERT INTO users_new (
            id, email, username, hashed_password, full_name,
            is_active, is_anonymous, scheduled_deletion_at, created_at, updated_at
        )
        SELECT
            id, email, username, hashed_password, full_name,
            is_active,
            CASE WHEN email LIKE 'anon_%@tinyworlds.app' THEN 1 ELSE 0 END as is_anonymous,
            CASE WHEN email LIKE 'anon_%@tinyworlds.app'
                THEN datetime('now', '+30 days')
                ELSE NULL
            END as scheduled_deletion_at,
            created_at, updated_at
        FROM users
    """))

    # Step 3: Drop old table and rename new one
    op.drop_table('users')
    op.rename_table('users_new', 'users')

    # Step 4: Recreate indexes
    op.create_index('ix_users_id', 'users', ['id'])
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
    op.create_index('ix_users_is_anonymous', 'users', ['is_anonymous'])
    op.create_index('ix_users_scheduled_deletion', 'users', ['scheduled_deletion_at'])

    # Step 5: Create password_reset_tokens table
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime, nullable=False),
        sa.Column('used_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_password_reset_tokens_user_id', 'password_reset_tokens', ['user_id'])
    op.create_index('ix_password_reset_tokens_token_hash', 'password_reset_tokens', ['token_hash'], unique=True)


def downgrade() -> None:
    """Remove authentication schema."""
    conn = op.get_bind()

    # Drop password_reset_tokens table
    op.drop_table('password_reset_tokens')

    # Recreate users table without new columns
    op.create_table(
        'users_old',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('username', sa.String(100), nullable=False, unique=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )

    conn.execute(sa.text("""
        INSERT INTO users_old (id, email, username, hashed_password, full_name, is_active, created_at, updated_at)
        SELECT id, email, username, hashed_password, full_name, is_active, created_at, updated_at
        FROM users
    """))

    op.drop_table('users')
    op.rename_table('users_old', 'users')

    # Recreate indexes
    op.create_index('ix_users_id', 'users', ['id'])
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
