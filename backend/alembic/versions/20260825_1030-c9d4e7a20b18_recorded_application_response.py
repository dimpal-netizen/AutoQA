"""What the application said back to each recorded action.

A recording of what somebody did is only half of what happened. The other half
is the application's answer - it navigated, or it put a message on the screen -
and without it every recorded value looks equally permanent: an address that
must be new on every run is indistinguishable from one that must already exist,
because from a list of clicks and keystrokes the two are identical.

That is what makes a recorded test fail the second time it runs. It replays the
data it captured, the application refuses it for the entirely correct reason
that the data is already there, and the run goes red against software that is
working. The answer is what tells the two kinds of value apart, and it is only
knowable while the page is still in front of the recorder.

Nullable, and null on every recording made before today. Nothing downstream may
require it - see `codegen/dataroles.py`, which treats it as corroboration for a
decision it can already make structurally.

Revision ID: c9d4e7a20b18
Revises: e7c3a91f5d24
Create Date: 2026-08-25 10:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'c9d4e7a20b18'
down_revision: str | None = 'e7c3a91f5d24'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recorded_actions",
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recorded_actions", "response")
