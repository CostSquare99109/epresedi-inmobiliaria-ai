"""widen prompt_version to 64 chars

Revision ID: dbd22e5c5ba6
Revises: 5935871c4e4b
Create Date: 2026-09-19 16:16:12.984315

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'dbd22e5c5ba6'
down_revision: str | None = '5935871c4e4b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column('ai_events', 'prompt_version',
               existing_type=sa.VARCHAR(length=20),
               type_=sa.String(length=64),
               existing_nullable=False)


def downgrade() -> None:
    op.alter_column('ai_events', 'prompt_version',
               existing_type=sa.String(length=64),
               type_=sa.VARCHAR(length=20),
               existing_nullable=False)
