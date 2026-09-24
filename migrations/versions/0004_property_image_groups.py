"""Group property images by characteristic (portada/piso/bano/cocina/...).

Revision ID: 0004_property_image_groups
Revises: 0003_remove_projects
Create Date: 2026-09-24

Adds `group` (característica: portada, piso, bano, cocina, lavadero,
parqueadero, extra, general) and `extra_name` (nombre del extra
personalizado, p. ej. "Piscina") to property_images.

Existing rows keep working: cover images are backfilled as 'portada',
everything else as 'general'. Reversible.
"""
from alembic import op
import sqlalchemy as sa

revision: str = '0004_property_image_groups'
down_revision: str = '0003_remove_projects'
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column('property_images', sa.Column('group', sa.String(40), nullable=True))
    op.add_column('property_images', sa.Column('extra_name', sa.String(200), nullable=True))

    # Backfill: la portada existente pertenece al grupo 'portada',
    # el resto queda como 'general' (legado, sin grupo).
    op.execute("UPDATE property_images SET \"group\" = 'portada' WHERE is_cover = TRUE")
    op.execute("UPDATE property_images SET \"group\" = 'general' WHERE \"group\" IS NULL")
    op.execute("UPDATE property_images SET extra_name = '' WHERE extra_name IS NULL")

    op.alter_column('property_images', 'group', nullable=False, server_default='general')
    op.alter_column('property_images', 'extra_name', nullable=False, server_default='')

    op.create_index(
        'ix_property_images_property_group', 'property_images', ['property_id', 'group'],
    )


def downgrade() -> None:
    op.drop_index('ix_property_images_property_group', 'property_images')
    op.drop_column('property_images', 'extra_name')
    op.drop_column('property_images', 'group')
