"""Add admin_audit_log table

Revision ID: 007
Revises: 006
Create Date: 2026-05-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'admin_audit_log',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('admin_user_id', sa.String(36), nullable=False, index=True),
        sa.Column('action', sa.String(64), nullable=False, index=True),
        sa.Column('target_user_id', sa.String(36), nullable=True, index=True),
        sa.Column('target_email', sa.String(255), nullable=True),
        sa.Column('detail', sa.Text, nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), index=True),
        sa.ForeignKeyConstraint(['admin_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_user_id'], ['users.id'], ondelete='SET NULL'),
    )


def downgrade() -> None:
    op.drop_table('admin_audit_log')
