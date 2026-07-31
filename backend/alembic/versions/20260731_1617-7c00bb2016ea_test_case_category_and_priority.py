"""test case category and priority

Revision ID: 7c00bb2016ea
Revises: 794389a0df50
Create Date: 2026-07-31 16:17:39.233448
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '7c00bb2016ea'
down_revision: str | None = '794389a0df50'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # The enum types must exist before the ALTER that uses them. `add_column`
    # with a sa.Enum does not create them the way `create_table` does, and with
    # a server_default Postgres has to resolve the type immediately - so
    # without this the migration fails with `type "case_category" does not
    # exist`. create_type=False below then stops SQLAlchemy trying again.
    category = postgresql.ENUM(
        'recorded', 'positive', 'negative', 'edge', 'security', name='case_category'
    )
    priority = postgresql.ENUM('critical', 'high', 'medium', 'low', name='case_priority')
    category.create(bind, checkfirst=True)
    priority.create(bind, checkfirst=True)

    # server_default matters too: these are NOT NULL and the table already has
    # rows. Without it the ALTER fails on any database that has ever generated
    # a suite. Existing cases came from a recording, so `recorded` is the
    # honest backfill.
    op.add_column(
        'test_cases',
        sa.Column(
            'category',
            postgresql.ENUM(name='case_category', create_type=False),
            nullable=False,
            server_default='recorded',
        ),
    )
    op.add_column(
        'test_cases',
        sa.Column(
            'priority',
            postgresql.ENUM(name='case_priority', create_type=False),
            nullable=False,
            server_default='medium',
        ),
    )
    op.add_column(
        'test_cases',
        sa.Column('generated_by', sa.String(length=64), nullable=False,
                  server_default='recording'),
    )
    op.create_index(op.f('ix_test_cases_category'), 'test_cases', ['category'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_test_cases_category'), table_name='test_cases')
    op.drop_column('test_cases', 'generated_by')
    op.drop_column('test_cases', 'priority')
    op.drop_column('test_cases', 'category')

    # Dropping a column leaves its enum type behind, and the next upgrade from
    # a clean base then fails with "type already exists".
    for enum_name in ('case_priority', 'case_category'):
        postgresql.ENUM(name=enum_name).drop(op.get_bind(), checkfirst=True)
