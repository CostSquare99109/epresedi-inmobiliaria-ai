"""Add detailed property fields for complete property management

Revision ID: 0002_add_property_detail_fields
Revises: 0001_add_real_estate_core
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0002_add_property_detail_fields'
down_revision: str = '0001_add_real_estate_core'
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Add new columns to properties table as nullable first
    op.add_column('properties', sa.Column('bedrooms_description', sa.Text(), nullable=True))
    op.add_column('properties', sa.Column('bathrooms_description', sa.Text(), nullable=True))
    op.add_column('properties', sa.Column('living_room_description', sa.Text(), nullable=True))
    op.add_column('properties', sa.Column('laundry_area_description', sa.Text(), nullable=True))
    op.add_column('properties', sa.Column('has_parking', sa.Boolean(), nullable=True))
    op.add_column('properties', sa.Column('parking_description', sa.Text(), nullable=True))
    op.add_column('properties', sa.Column('rent_price', sa.Numeric(14, 2), nullable=True))
    op.add_column('properties', sa.Column('services_included', sa.String(20), nullable=True))
    op.add_column('properties', sa.Column('nomenclatura', sa.String(240), nullable=True))
    op.add_column('properties', sa.Column('visiting_hours', postgresql.JSONB(), nullable=True))

    # Update existing rows with defaults
    op.execute("UPDATE properties SET bedrooms_description = '' WHERE bedrooms_description IS NULL")
    op.execute("UPDATE properties SET bathrooms_description = '' WHERE bathrooms_description IS NULL")
    op.execute("UPDATE properties SET living_room_description = '' WHERE living_room_description IS NULL")
    op.execute("UPDATE properties SET laundry_area_description = '' WHERE laundry_area_description IS NULL")
    op.execute("UPDATE properties SET has_parking = FALSE WHERE has_parking IS NULL")
    op.execute("UPDATE properties SET parking_description = '' WHERE parking_description IS NULL")
    op.execute("UPDATE properties SET services_included = 'no_incluye' WHERE services_included IS NULL")
    op.execute("UPDATE properties SET nomenclatura = '' WHERE nomenclatura IS NULL")
    op.execute("UPDATE properties SET visiting_hours = '[]'::jsonb WHERE visiting_hours IS NULL")

    # Now make columns NOT NULL with defaults
    op.alter_column('properties', 'bedrooms_description', nullable=False, server_default='')
    op.alter_column('properties', 'bathrooms_description', nullable=False, server_default='')
    op.alter_column('properties', 'living_room_description', nullable=False, server_default='')
    op.alter_column('properties', 'laundry_area_description', nullable=False, server_default='')
    op.alter_column('properties', 'has_parking', nullable=False, server_default=sa.false())
    op.alter_column('properties', 'parking_description', nullable=False, server_default='')
    op.alter_column('properties', 'services_included', nullable=False, server_default='no_incluye')
    op.alter_column('properties', 'nomenclatura', nullable=False, server_default='')
    op.alter_column('properties', 'visiting_hours', nullable=False, server_default=sa.text("'[]'::jsonb"))

    # Add check constraints for new numeric field
    op.create_check_constraint('ck_properties_rent_price_nonneg', 'properties', 'rent_price >= 0')
    op.create_check_constraint('ck_properties_services_included', 'properties', "services_included IN ('incluye', 'no_incluye')")

    # Add new columns to property_images table for metadata
    op.add_column('property_images', sa.Column('name', sa.String(200), nullable=True))
    op.add_column('property_images', sa.Column('description', sa.Text(), nullable=True))

    # Update existing rows
    op.execute("UPDATE property_images SET name = '' WHERE name IS NULL")
    op.execute("UPDATE property_images SET description = '' WHERE description IS NULL")

    # Now make columns NOT NULL with defaults
    op.alter_column('property_images', 'name', nullable=False, server_default='')
    op.alter_column('property_images', 'description', nullable=False, server_default='')

    # Create index for visiting_hours
    op.create_index('ix_properties_visiting_hours', 'properties', ['visiting_hours'], postgresql_using='gin')


def downgrade() -> None:
    # Drop index
    op.drop_index('ix_properties_visiting_hours', 'properties')

    # Drop columns from property_images
    op.drop_column('property_images', 'description')
    op.drop_column('property_images', 'name')

    # Drop constraints
    op.drop_constraint('ck_properties_services_included', 'properties', type_='check')
    op.drop_constraint('ck_properties_rent_price_nonneg', 'properties', type_='check')

    # Drop columns from properties
    op.drop_column('properties', 'visiting_hours')
    op.drop_column('properties', 'nomenclatura')
    op.drop_column('properties', 'services_included')
    op.drop_column('properties', 'rent_price')
    op.drop_column('properties', 'parking_description')
    op.drop_column('properties', 'has_parking')
    op.drop_column('properties', 'laundry_area_description')
    op.drop_column('properties', 'living_room_description')
    op.drop_column('properties', 'bathrooms_description')
    op.drop_column('properties', 'bedrooms_description')