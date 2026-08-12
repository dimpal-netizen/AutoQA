"""Sample files a test can upload.

A browser never tells a page where a chosen file lives, so a recording of
somebody adding a property holds the name of their photograph and nothing else.
AutoQA builds a plain 800x600 image in its place, which uploads correctly - but
it is a grey rectangle, and a site that resizes, checks or later displays the
photograph deserves a photograph.

Shared rather than per project: a photograph is a photograph, and the same
handful serves every listing form anybody records.

The bytes live on disk under the storage directory; this table is the index.

Revision ID: ca45b0942860
Revises: b8e2c47f1a35
Create Date: 2026-08-11 17:24:11.984202
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
revision: str = 'ca45b0942860'
down_revision: str | None = 'b8e2c47f1a35'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('sample_files',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=128), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('file_path', sa.String(length=512), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('sample_files')
