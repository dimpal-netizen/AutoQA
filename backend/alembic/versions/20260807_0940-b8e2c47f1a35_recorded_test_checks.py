"""checks added to the recorded test

The recorded test is the baseline every other case is written around, and it
asserts nothing. Twenty-eight steps of clicking and typing, then it ends — so it
passes as long as every click found something to click. Add a backpack to a cart
that stays empty and it still reports green.

Checks live on the suite rather than on the case they end up in, because that
case is rebuilt from the recording every time the suite is regenerated. A check
written onto it would last until the next press of a button; held here, it is
re-applied on every rebuild.

The recording is deliberately not touched. It is a record of what somebody did,
and they did not do these.

Empty for every existing suite, which is correct rather than a gap: nobody has
been asked yet.

Revision ID: b8e2c47f1a35
Revises: d3b71c904e18
Create Date: 2026-08-07 09:40:18.552104
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'b8e2c47f1a35'
down_revision: str | None = 'd3b71c904e18'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'test_suites',
        sa.Column(
            'checks',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default='[]',
        ),
    )


def downgrade() -> None:
    op.drop_column('test_suites', 'checks')
