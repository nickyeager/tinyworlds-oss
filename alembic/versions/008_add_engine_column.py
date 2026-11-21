"""Add engine column to games

Revision ID: 008
Revises: 007
Create Date: 2026-05-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('games') as batch_op:
        batch_op.add_column(
            sa.Column(
                'engine',
                sa.String(20),
                nullable=False,
                server_default='godot',
            )
        )
        batch_op.create_check_constraint(
            'games_engine_check',
            "engine IN ('godot', 'bevy')",
        )
        batch_op.create_index('ix_games_engine', ['engine'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('games') as batch_op:
        batch_op.drop_index('ix_games_engine')
        batch_op.drop_constraint('games_engine_check', type_='check')
        batch_op.drop_column('engine')
