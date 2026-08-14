"""A team's manual test-case spreadsheets, kept per project.

Uploading one is a way into a project alongside recording a session, and the
two answer different halves of the same question: a recording is the only thing
that can say what is on the page, a sheet the only thing that says what your
team cares about testing. Neither produces a test alone.

So a sheet uploaded before anything has been recorded is kept rather than
refused, and turns into cases the moment a recording exists.

The parsed rows are stored rather than the original file - already capped at
two hundred rows, and what every reader downstream actually wants.

Revision ID: e7c3a91f5d24
Revises: ca45b0942860
Create Date: 2026-08-13 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'e7c3a91f5d24'
down_revision: str | None = 'ca45b0942860'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'excel_sheets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('rows', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('row_count', sa.Integer(), nullable=False),
        sa.Column('uploaded_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        # Deleting a project takes its sheets with it; deleting the person who
        # uploaded one does not - the sheet is the team's, not theirs.
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_excel_sheets_project_id'), 'excel_sheets',
                    ['project_id'], unique=False)
    op.create_index(op.f('ix_excel_sheets_uploaded_by_id'), 'excel_sheets',
                    ['uploaded_by_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_excel_sheets_uploaded_by_id'), table_name='excel_sheets')
    op.drop_index(op.f('ix_excel_sheets_project_id'), table_name='excel_sheets')
    op.drop_table('excel_sheets')
