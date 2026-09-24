"""Add real estate core tables: property_images, branches, business_hours, and extend properties

Revision ID: 0001_add_real_estate_core
Revises: 55d8459dd9e7
Create Date: 2026-09-22

"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001_add_real_estate_core'
down_revision: str | None = '55d8459dd9e7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create branches (sedes) table
    op.create_table(
        'branches',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(160), nullable=False),
        sa.Column('city', sa.String(80), nullable=False),
        sa.Column('neighborhood', sa.String(120), default=''),
        sa.Column('street', sa.String(160), default=''),
        sa.Column('street_number', sa.String(60), default=''),
        sa.Column('descriptive_location', sa.Text(), default=''),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index('ix_branches_city', 'branches', ['city'])
    op.create_index('ix_branches_is_active', 'branches', ['is_active'])

    # 2. Create property_images table
    op.create_table(
        'property_images',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('property_id', sa.UUID(), nullable=False),
        sa.Column('filename', sa.String(300), nullable=False),
        sa.Column('is_cover', sa.Boolean(), default=False),
        sa.Column('sort_order', sa.Integer(), default=0),
        sa.Column('alt_text', sa.String(200), default=''),
        sa.Column('file_size', sa.BigInteger(), default=0),
        sa.Column('mime_type', sa.String(100), default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_property_images_property_id', 'property_images', ['property_id'])
    op.create_index('ix_property_images_property_cover', 'property_images', ['property_id', 'is_cover'])
    op.create_index('ix_property_images_property_order', 'property_images', ['property_id', 'sort_order'])

    # 3. Create business_hours table (per branch, supports multiple intervals per day)
    op.create_table(
        'business_hours',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('branch_id', sa.UUID(), nullable=True),  # NULL = global/default hours
        sa.Column('weekday', sa.Integer(), nullable=False),  # 0=Monday .. 6=Sunday
        sa.Column('is_closed', sa.Boolean(), default=False),
        sa.Column('open_time', sa.Time(), nullable=True),
        sa.Column('close_time', sa.Time(), nullable=True),
        sa.Column('interval_order', sa.Integer(), default=0),  # for multiple intervals per day
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('weekday >= 0 AND weekday <= 6', name='ck_business_hours_weekday'),
        sa.CheckConstraint(
            '(is_closed = true AND open_time IS NULL AND close_time IS NULL) OR '
            '(is_closed = false AND open_time IS NOT NULL AND close_time IS NOT NULL AND open_time < close_time)',
            name='ck_business_hours_times'
        ),
    )
    op.create_index('ix_business_hours_branch_weekday', 'business_hours', ['branch_id', 'weekday', 'interval_order'])
    op.create_index('ix_business_hours_branch_id', 'business_hours', ['branch_id'])

    # 4. Add new columns to properties table
    op.add_column('properties', sa.Column('branch_id', sa.UUID(), nullable=True))
    op.add_column('properties', sa.Column('street', sa.String(160), default=''))
    op.add_column('properties', sa.Column('street_number', sa.String(60), default=''))
    op.add_column('properties', sa.Column('descriptive_location', sa.Text(), default=''))
    op.add_column('properties', sa.Column('floors', sa.Integer(), nullable=True))
    op.add_column('properties', sa.Column('has_kitchen', sa.Boolean(), default=True))
    op.add_column('properties', sa.Column('has_living_room', sa.Boolean(), default=True))
    op.add_column('properties', sa.Column('has_laundry_area', sa.Boolean(), default=False))
    op.add_column('properties', sa.Column('price_period', sa.String(20), default=''))  # e.g., 'month' for rent

    # Add FK for branch_id
    op.create_foreign_key('fk_properties_branch', 'properties', 'branches', ['branch_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_properties_branch_id', 'properties', ['branch_id'])
    op.create_index('ix_properties_floors', 'properties', ['floors'])

    # Add check constraints for numeric fields
    op.create_check_constraint('ck_properties_price_nonneg', 'properties', 'price >= 0')
    op.create_check_constraint('ck_properties_floors_nonneg', 'properties', 'floors >= 0')
    op.create_check_constraint('ck_properties_bedrooms_nonneg', 'properties', 'bedrooms >= 0')
    op.create_check_constraint('ck_properties_bathrooms_nonneg', 'properties', 'bathrooms >= 0')
    op.create_check_constraint('ck_properties_parking_nonneg', 'properties', 'parking_spaces >= 0')

    # 5. Add display labels to enums (handled in Python, but document here)
    # Operation: SALE -> 'Compra', RENT -> 'Arriendo'
    # PropertyStatus: AVAILABLE -> 'Disponible', others -> 'No disponible'

    # 6. Migrate existing filesystem images to property_images table
    # This will be done in a data migration step after the schema is created

    # 7. Create default branch and migrate existing properties
    # Insert a default branch for existing properties
    op.execute("""
        INSERT INTO branches (id, name, city, neighborhood, street, street_number, is_active, created_at, updated_at)
        VALUES (
            '00000000-0000-0000-0000-000000000001'::uuid,
            'Sede Principal',
            'Carepa',
            'El Centro',
            'Calle 70',
            '# 68A - 11',
            true,
            now(),
            now()
        )
        ON CONFLICT (name) DO NOTHING;
    """)

    # 8. Create default business hours (global, no branch_id)
    op.execute("""
        INSERT INTO business_hours (id, branch_id, weekday, is_closed, open_time, close_time, interval_order, created_at, updated_at)
        VALUES 
        (gen_random_uuid(), NULL, 0, false, '08:00', '18:00', 0, now(), now()),  -- Monday
        (gen_random_uuid(), NULL, 1, false, '08:00', '18:00', 0, now(), now()),  -- Tuesday
        (gen_random_uuid(), NULL, 2, false, '08:00', '18:00', 0, now(), now()),  -- Wednesday
        (gen_random_uuid(), NULL, 3, false, '08:00', '18:00', 0, now(), now()),  -- Thursday
        (gen_random_uuid(), NULL, 4, false, '08:00', '18:00', 0, now(), now()),  -- Friday
        (gen_random_uuid(), NULL, 5, false, '09:00', '15:00', 0, now(), now()),  -- Saturday
        (gen_random_uuid(), NULL, 6, true, NULL, NULL, 0, now(), now())          -- Sunday (closed)
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    # Drop constraints first
    op.drop_constraint('ck_properties_parking_nonneg', 'properties', type_='check')
    op.drop_constraint('ck_properties_bathrooms_nonneg', 'properties', type_='check')
    op.drop_constraint('ck_properties_bedrooms_nonneg', 'properties', type_='check')
    op.drop_constraint('ck_properties_floors_nonneg', 'properties', type_='check')
    op.drop_constraint('ck_properties_price_nonneg', 'properties', type_='check')

    # Drop indexes
    op.drop_index('ix_properties_floors', 'properties')
    op.drop_index('ix_properties_branch_id', 'properties')
    op.drop_constraint('fk_properties_branch', 'properties', type_='foreignkey')

    # Drop columns
    op.drop_column('properties', 'price_period')
    op.drop_column('properties', 'has_laundry_area')
    op.drop_column('properties', 'has_living_room')
    op.drop_column('properties', 'has_kitchen')
    op.drop_column('properties', 'floors')
    op.drop_column('properties', 'descriptive_location')
    op.drop_column('properties', 'street_number')
    op.drop_column('properties', 'street')
    op.drop_column('properties', 'branch_id')

    # Drop tables
    op.drop_index('ix_business_hours_branch_id', 'business_hours')
    op.drop_index('ix_business_hours_branch_weekday', 'business_hours')
    op.drop_table('business_hours')

    op.drop_index('ix_property_images_property_order', 'property_images')
    op.drop_index('ix_property_images_property_cover', 'property_images')
    op.drop_index('ix_property_images_property_id', 'property_images')
    op.drop_table('property_images')

    op.drop_index('ix_branches_is_active', 'branches')
    op.drop_index('ix_branches_city', 'branches')
    op.drop_table('branches')
