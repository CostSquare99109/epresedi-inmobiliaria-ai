"""lead_assignment_and_app_settings

Revision ID: c4f8a2d6b0e2
Revises: 5ba4013e9193
Create Date: 2026-09-18 00:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'c4f8a2d6b0e2'
down_revision: str | None = '5ba4013e9193'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Asignación de asesores a leads (FK real, no campo improvisado)
    op.add_column('leads', sa.Column('assigned_admin_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_leads_assigned_admin', 'leads', 'admin_users',
        ['assigned_admin_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_leads_assigned_admin', 'leads', ['assigned_admin_id'], unique=False)

    # Configuración de negocio administrable (key-value con valor JSONB)
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(length=80), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('description', sa.String(length=240), nullable=False, server_default=sa.text("''")),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    op.drop_table('app_settings')
    op.drop_index('ix_leads_assigned_admin', table_name='leads')
    op.drop_constraint('fk_leads_assigned_admin', 'leads', type_='foreignkey')
    op.drop_column('leads', 'assigned_admin_id')
