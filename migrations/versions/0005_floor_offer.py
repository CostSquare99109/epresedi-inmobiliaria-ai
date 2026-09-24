"""Floor offer model: which part of the property is offered.

Revision ID: 0005_floor_offer
Revises: 0004_property_image_groups
Create Date: 2026-09-24

Adds to properties:
- `floor_offer_type` (VARCHAR 20, NOT NULL, default 'full_property'):
  full_property | single_floor | multiple_floors | partial
- `offered_floors` (JSONB, NOT NULL, default '[]'): offered floor numbers.

Existing rows keep working: they are backfilled as 'full_property' + '[]',
which preserves the old meaning of `floors` (total floors of the whole
property). Reversible.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0005_floor_offer'
down_revision: str = '0004_property_image_groups'
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column('properties', sa.Column('floor_offer_type', sa.String(20), nullable=True))
    op.add_column('properties', sa.Column('offered_floors', postgresql.JSONB(), nullable=True))

    # Backfill: old rows offered the whole property (legacy `floors` = total).
    op.execute("UPDATE properties SET floor_offer_type = 'full_property' WHERE floor_offer_type IS NULL")
    op.execute("UPDATE properties SET offered_floors = '[]'::jsonb WHERE offered_floors IS NULL")

    op.alter_column('properties', 'floor_offer_type', nullable=False, server_default='full_property')
    op.alter_column('properties', 'offered_floors', nullable=False, server_default=sa.text("'[]'::jsonb"))

    op.create_check_constraint(
        'ck_properties_floor_offer_type', 'properties',
        "floor_offer_type IN ('full_property', 'single_floor', 'multiple_floors', 'partial')",
    )
    op.create_index(
        'ix_properties_offered_floors', 'properties', ['offered_floors'], postgresql_using='gin'
    )


def downgrade() -> None:
    op.drop_index('ix_properties_offered_floors', 'properties')
    op.drop_constraint('ck_properties_floor_offer_type', 'properties', type_='check')
    op.drop_column('properties', 'offered_floors')
    op.drop_column('properties', 'floor_offer_type')
