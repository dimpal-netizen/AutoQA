"""What a test had to change to get through.

A recorded test replays the data it captured, and the second time it runs the
application is often right to refuse it - the account exists now, the item is
taken, the slot is booked. A test that notices that, substitutes a value the
application will accept and carries on is testing the workflow it was written
to test, which is the whole point.

But a pass reached that way is not the same news as a pass, and must never look
like one. Somebody deciding whether to ship needs to see that step 11 ran on
different data; and a test quietly adapting on every run for a month is an
application changing underneath it, not a test doing its job. Neither is
visible unless the substitutions are kept.

Empty on almost every result. Never nullable: "nothing was changed" is an
answer, and a column that cannot distinguish it from "nobody looked" would make
every old result ambiguous.

Revision ID: d2f6b81c4a37
Revises: c9d4e7a20b18
Create Date: 2026-08-25 11:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'd2f6b81c4a37'
down_revision: str | None = 'c9d4e7a20b18'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "test_results",
        sa.Column(
            "adaptations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("test_results", "adaptations")
