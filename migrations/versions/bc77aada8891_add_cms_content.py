"""add_cms_content

Revision ID: bc77aada8891
Revises: 5ba4013e9193
Create Date: 2026-09-17 23:56:22.144554

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'bc77aada8891'
down_revision: Union[str, None] = '5ba4013e9193'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cms_content',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('type', sa.Enum('text', 'html', 'json', 'image', 'number', 'boolean', name='cmscontenttype', native_enum=False, length=32), nullable=False),
        sa.Column('value', sa.Text(), nullable=False, default=''),
        sa.Column('label', sa.String(length=200), nullable=False, default=''),
        sa.Column('description', sa.Text(), nullable=False, default=''),
        sa.Column('group', sa.String(length=50), nullable=False, default='general'),
        sa.Column('is_public', sa.Boolean(), nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_index(op.f('ix_cms_content_key'), 'cms_content', ['key'], unique=True)
    op.create_index(op.f('ix_cms_content_group'), 'cms_content', ['group'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_cms_content_group'), table_name='cms_content')
    op.drop_index(op.f('ix_cms_content_key'), table_name='cms_content')
    op.drop_table('cms_content')