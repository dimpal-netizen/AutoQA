"""ai failure analysis

Revision ID: 9e6e42a43789
Revises: f174f401b704
Create Date: 2026-07-31 17:19:58.904381
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = '9e6e42a43789'
down_revision: str | None = 'f174f401b704'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ai_analyses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('result_id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('root_cause', sa.Text(), nullable=False),
    sa.Column('suggested_fix', sa.Text(), nullable=False),
    sa.Column('category', sa.Enum('application_bug', 'test_bug', 'selector_broken', 'timing', 'environment', 'test_data', 'flaky', name='failure_category'), nullable=False),
    sa.Column('severity', sa.Enum('critical', 'high', 'medium', 'low', name='severity'), nullable=False),
    sa.Column('priority', sa.Enum('critical', 'high', 'medium', 'low', name='severity'), nullable=False),
    sa.Column('is_product_bug', sa.Boolean(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Float(), nullable=False),
    sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['result_id'], ['test_results.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['test_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ai_analyses_category'), 'ai_analyses', ['category'], unique=False)
    op.create_index(op.f('ix_ai_analyses_result_id'), 'ai_analyses', ['result_id'], unique=False)
    op.create_index(op.f('ix_ai_analyses_run_id'), 'ai_analyses', ['run_id'], unique=False)
    op.create_index(op.f('ix_ai_analyses_severity'), 'ai_analyses', ['severity'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ai_analyses_severity'), table_name='ai_analyses')
    op.drop_index(op.f('ix_ai_analyses_run_id'), table_name='ai_analyses')
    op.drop_index(op.f('ix_ai_analyses_result_id'), table_name='ai_analyses')
    op.drop_index(op.f('ix_ai_analyses_category'), table_name='ai_analyses')
    op.drop_table('ai_analyses')

    # Dropping the table leaves its enum types behind, and the next upgrade
    # from a clean base then fails with "type already exists".
    for enum_name in ('failure_category', 'severity'):
        postgresql.ENUM(name=enum_name).drop(op.get_bind(), checkfirst=True)
