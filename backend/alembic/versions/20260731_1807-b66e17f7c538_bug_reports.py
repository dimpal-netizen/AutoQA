"""bug reports

Revision ID: b66e17f7c538
Revises: 9e6e42a43789
Create Date: 2026-07-31 18:07:32.684201
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = 'b66e17f7c538'
down_revision: str | None = '9e6e42a43789'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('bug_reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('result_id', sa.Integer(), nullable=True),
    sa.Column('analysis_id', sa.Integer(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('steps_to_reproduce', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('expected', sa.Text(), nullable=False),
    sa.Column('actual', sa.Text(), nullable=False),
    sa.Column('environment', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('severity', postgresql.ENUM(name='severity', create_type=False), nullable=False),
    sa.Column('priority', postgresql.ENUM(name='severity', create_type=False), nullable=False),
    sa.Column('status', sa.Enum('draft', 'open', 'resolved', 'wont_fix', name='bug_status'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['analysis_id'], ['ai_analyses.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['result_id'], ['test_results.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bug_reports_project_id'), 'bug_reports', ['project_id'], unique=False)
    op.create_index(op.f('ix_bug_reports_result_id'), 'bug_reports', ['result_id'], unique=False)
    op.create_index(op.f('ix_bug_reports_severity'), 'bug_reports', ['severity'], unique=False)
    op.create_index(op.f('ix_bug_reports_status'), 'bug_reports', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_bug_reports_status'), table_name='bug_reports')
    op.drop_index(op.f('ix_bug_reports_severity'), table_name='bug_reports')
    op.drop_index(op.f('ix_bug_reports_result_id'), table_name='bug_reports')
    op.drop_index(op.f('ix_bug_reports_project_id'), table_name='bug_reports')
    op.drop_table('bug_reports')

    # bug_status is this migration's own type; severity belongs to the
    # analyses table and must survive this being rolled back.
    postgresql.ENUM(name='bug_status').drop(op.get_bind(), checkfirst=True)
