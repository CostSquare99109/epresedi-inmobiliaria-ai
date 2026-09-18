"""add_admin_users_and_audit_log

Revision ID: 5ba4013e9193
Revises: b976e4404b71
Create Date: 2026-09-17 22:48:46.212663

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '5ba4013e9193'
down_revision: Union[str, None] = 'b976e4404b71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Admin users table
    op.create_table(
        'admin_users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.Enum('superadmin', 'admin', 'editor', 'asesor', name='adminrole', native_enum=False, length=32), nullable=False, default='asesor'),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )
    op.create_index(op.f('ix_admin_users_email'), 'admin_users', ['email'], unique=True)
    op.create_index(op.f('ix_admin_users_role'), 'admin_users', ['role'], unique=False)

    # Admin audit log table
    op.create_table(
        'admin_audit_log',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('admin_user_id', sa.UUID(), nullable=True),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('entity', sa.String(length=64), nullable=False),
        sa.Column('entity_id', sa.String(length=64), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False, default={}),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('result', sa.String(length=16), nullable=False, default='success'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['admin_user_id'], ['admin_users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_admin_audit_log_admin_user_id'), 'admin_audit_log', ['admin_user_id'], unique=False)
    op.create_index(op.f('ix_admin_audit_log_entity'), 'admin_audit_log', ['entity'], unique=False)
    op.create_index(op.f('ix_admin_audit_log_action'), 'admin_audit_log', ['action'], unique=False)
    op.create_index(op.f('ix_admin_audit_log_created_at'), 'admin_audit_log', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_admin_audit_log_created_at'), table_name='admin_audit_log')
    op.drop_index(op.f('ix_admin_audit_log_action'), table_name='admin_audit_log')
    op.drop_index(op.f('ix_admin_audit_log_entity'), table_name='admin_audit_log')
    op.drop_index(op.f('ix_admin_audit_log_admin_user_id'), table_name='admin_audit_log')
    op.drop_table('admin_audit_log')
    op.drop_index(op.f('ix_admin_users_role'), table_name='admin_users')
    op.drop_index(op.f('ix_admin_users_email'), table_name='admin_users')
    op.drop_table('admin_users')