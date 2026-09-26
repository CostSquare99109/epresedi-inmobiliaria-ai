"""Unique active appointment slot (anti double-booking race)

Revision ID: 0007_unique_active_slot
Revises: 0006_restrict_property_types
Create Date: 2026-09-26 00:00:00.000000

Garantía a nivel de base de datos contra la condición de carrera
TOCTOU en POST /appointments: dos reservas simultáneas del mismo
(property_id, scheduled_at) pasaban el SELECT de choque y se insertaban
las dos. El índice único parcial solo cubre citas activas
(REQUESTED/CONFIRMED): cancelar libera el slot (las CANCELLED/COMPLETED
quedan fuera del índice).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0007_unique_active_slot'
down_revision: str | None = '0006_restrict_property_types'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        'uq_appointments_active_slot',
        'appointments',
        ['property_id', 'scheduled_at'],
        unique=True,
        postgresql_where=sa.text("status IN ('REQUESTED', 'CONFIRMED')"),
    )


def downgrade() -> None:
    op.drop_index('uq_appointments_active_slot', table_name='appointments')
