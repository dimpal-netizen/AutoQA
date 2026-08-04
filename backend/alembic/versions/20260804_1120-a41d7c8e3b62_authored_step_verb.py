"""which vocabulary word a step was authored with

Needed so a test case can be opened in the editor and saved again unchanged.
`action` is too coarse to round-trip: expect_visible, expect_hidden,
expect_text, expect_url, expect_not_url, expect_masked and expect_not_masked
are seven different things that all store as ActionType.ASSERT, so a step read
back would come out as whichever of them was listed first.

Null for every existing row, which is correct rather than a gap: those steps
were generated before the editor existed. The service infers the verb where the
action is unambiguous and refuses the edit where it is not, instead of guessing.

Revision ID: a41d7c8e3b62
Revises: b66e17f7c538
Create Date: 2026-08-04 11:20:04.118293
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a41d7c8e3b62'
down_revision: str | None = 'b66e17f7c538'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('test_steps', sa.Column('verb', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('test_steps', 'verb')
