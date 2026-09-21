"""add_system_settings

Revision ID: 1988f6b5fe93
Revises: bc77aada8891
Create Date: 2026-09-18 00:03:01.130198

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '1988f6b5fe93'
down_revision: str | None = 'bc77aada8891'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'system_settings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('type', sa.Enum('text', 'html', 'json', 'number', 'boolean', name='systemsettingtype', native_enum=False, length=32), nullable=False),
        sa.Column('value', sa.Text(), nullable=False, default=''),
        sa.Column('label', sa.String(length=200), nullable=False, default=''),
        sa.Column('description', sa.Text(), nullable=False, default=''),
        sa.Column('category', sa.String(length=50), nullable=False, default='general'),
        sa.Column('is_editable', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_index(op.f('ix_system_settings_key'), 'system_settings', ['key'], unique=True)
    op.create_index(op.f('ix_system_settings_category'), 'system_settings', ['category'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_system_settings_category'), table_name='system_settings')
    op.drop_index(op.f('ix_system_settings_key'), table_name='system_settings')
    op.drop_table('system_settings')