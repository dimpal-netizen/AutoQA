"""what the test expected, and what was on screen instead

An analysis said what went wrong and what to do, but never stated the two facts
the reader wants first: what should have happened, and what actually did. Those
were left to be inferred from `root_cause`, which is a sentence about the cause
rather than about either side of the mismatch.

Null for every existing row, which is correct rather than a gap. Those analyses
were written before the model was asked the question, and deriving the answer
from prose we already have would be a guess wearing the clothes of a finding.
The UI shows the pair when it is there and omits it when it is not.

Revision ID: d3b71c904e18
Revises: a41d7c8e3b62
Create Date: 2026-08-06 11:30:12.407918
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd3b71c904e18'
down_revision: str | None = 'a41d7c8e3b62'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('ai_analyses', sa.Column('expected', sa.Text(), nullable=True))
    op.add_column('ai_analyses', sa.Column('actual', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('ai_analyses', 'actual')
    op.drop_column('ai_analyses', 'expected')
