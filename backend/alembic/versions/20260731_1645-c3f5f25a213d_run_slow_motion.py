"""run slow motion

Revision ID: c3f5f25a213d
Revises: 7c00bb2016ea
Create Date: 2026-07-31 16:45:30.278441
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = 'c3f5f25a213d'
down_revision: str | None = '7c00bb2016ea'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column('test_cases', 'category',
               existing_type=postgresql.ENUM('recorded', 'positive', 'negative', 'edge', 'security', name='case_category'),
               server_default=None,
               existing_nullable=False)
    op.alter_column('test_cases', 'priority',
               existing_type=postgresql.ENUM('critical', 'high', 'medium', 'low', name='case_priority'),
               server_default=None,
               existing_nullable=False)
    op.alter_column('test_cases', 'generated_by',
               existing_type=sa.VARCHAR(length=64),
               server_default=None,
               existing_nullable=False)
    op.add_column(
        'test_runs',
        # server_default because the table already has rows; existing runs were
        # not slowed down, so 0 is the truthful backfill.
        sa.Column('slow_mo_ms', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('test_runs', 'slow_mo_ms')
    op.alter_column('test_cases', 'generated_by',
               existing_type=sa.VARCHAR(length=64),
               server_default=sa.text("'recording'::character varying"),
               existing_nullable=False)
    op.alter_column('test_cases', 'priority',
               existing_type=postgresql.ENUM('critical', 'high', 'medium', 'low', name='case_priority'),
               server_default=sa.text("'medium'::case_priority"),
               existing_nullable=False)
    op.alter_column('test_cases', 'category',
               existing_type=postgresql.ENUM('recorded', 'positive', 'negative', 'edge', 'security', name='case_category'),
               server_default=sa.text("'recorded'::case_category"),
               existing_nullable=False)
