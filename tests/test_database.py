"""Database layer: migrations, schema, indexes, constraints, pgvector, CRUD."""
from __future__ import annotations

import pathlib
import uuid as uuid_mod

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database.models import PropertyStatus, PropertyType
from app.properties import repository as repo

EXPECTED_TABLES = {
    "properties", "projects", "documents", "document_chunks", "users",
    "user_preferences", "conversations", "messages", "ai_events",
    "favorites", "saved_searches", "leads", "appointments", "alembic_version",
}

EXPECTED_INDEXES = {
    "ix_properties_price", "ix_properties_city", "ix_properties_type",
    "ix_properties_operation", "ix_properties_bedrooms", "ix_properties_status",
}


async def test_migration_head_is_applied(session):
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = pathlib.Path(__file__).resolve().parent.parent
    head = ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_current_head()
    current = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    assert current == head


async def test_all_expected_tables_exist(session):
    rows = (
        await session.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
    ).scalars().all()
    assert EXPECTED_TABLES.issubset(set(rows))


async def test_performance_indexes_exist(session):
    rows = (
        await session.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))
    ).scalars().all()
    assert EXPECTED_INDEXES.issubset(set(rows))


async def test_pgvector_extension_and_column(session):
    version = (
        await session.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
    ).scalar()
    assert version, "pgvector must be installed"
    col_type = (
        await session.execute(
            text(
                "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "WHERE c.relname = 'properties' AND a.attname = 'title_embedding'"
            )
        )
    ).scalar()
    assert col_type and col_type.startswith(("vector", "halfvec"))


async def test_pgvector_similarity_operator_works(session):
    import math

    identical = (
        await session.execute(text("SELECT '[1,2,3]'::vector <=> '[1,2,3]'::vector"))
    ).scalar()
    assert float(identical) == pytest.approx(0.0, abs=1e-9)

    distance = (
        await session.execute(text("SELECT '[1,2,3]'::vector <=> '[1,2,4]'::vector"))
    ).scalar()
    expected = 1 - 17 / (math.sqrt(14) * math.sqrt(21))
    assert float(distance) == pytest.approx(expected, abs=1e-6)
    assert 0.0 <= float(distance) <= 1.0


async def test_search_vector_is_generated_and_filled(session):
    matched = (
        await session.execute(
            text(
                "SELECT search_vector @@ to_tsquery('spanish','carepa') "
                "FROM properties WHERE code = 'PROP-0001'"
            )
        )
    ).scalar()
    assert matched is True


async def test_create_update_delete_property_roundtrip(session):
    created = await repo.create_property(
        session,
        {
            "title": "Casa de prueba unitaria",
            "property_type": "casa",
            "operation": "SALE",
            "price": 199_000_000,
            "city": "Apartado",
            "neighborhood": "Centro",
            "bedrooms": 3,
            "bathrooms": 2,
            "parking_spaces": 1,
            "features": ["garaje"],
        },
    )
    assert created.id is not None
    assert created.title_embedding is not None, "embedding must be synced on create"

    updated = await repo.update_property(
        session, created.id, {"price": 210_000_000, "status": "RESERVED"}
    )
    assert float(updated.price) == 210_000_000
    assert updated.status is PropertyStatus.RESERVED

    fetched = await repo.get_property(session, str(created.id))
    assert fetched.code == created.code

    assert await repo.delete_property(session, created.id) is True
    assert await repo.get_property(session, created.id) is None
    await session.rollback()


async def test_create_property_requires_valid_enums(session):
    with pytest.raises(ValueError):
        await repo.create_property(session, {"title": "X", "property_type": "castillo", "price": 1})
    await session.rollback()
    with pytest.raises(ValueError):
        await repo.create_property(
            session, {"title": "X", "property_type": "casa", "price": 1, "operation": "BARTER"}
        )
    await session.rollback()
    with pytest.raises(ValueError):
        await repo.create_property(
            session, {"title": "X", "property_type": "casa", "price": 1, "status": "PENDING"}
        )
    await session.rollback()


async def test_duplicate_property_code_is_rejected(session):
    await repo.create_property(
        session, {"code": "PROP-DUP-1", "title": "A", "property_type": "casa", "price": 1}
    )
    with pytest.raises(IntegrityError):
        await repo.create_property(
            session, {"code": "PROP-DUP-1", "title": "B", "property_type": "casa", "price": 2}
        )
    await session.rollback()


async def test_favorite_unique_constraint(session):
    from app.crm import service as crm
    from app.memory import service as memory_service

    prop = await repo.get_property_by_code(session, "PROP-0001")
    user = await memory_service.get_or_create_user(session, 1_000_000_500)
    assert await crm.add_favorite(session, user.id, prop.id) is True
    assert await crm.add_favorite(session, user.id, prop.id) is False  # idempotent
    await session.rollback()


async def test_count_by_status_matches_seed(session):
    counts = await repo.count_by_status(session)
    assert counts.get("AVAILABLE", 0) >= 13
    assert counts.get("SOLD", 0) >= 1
    assert counts.get("RESERVED", 0) >= 1
    assert counts.get("INACTIVE", 0) >= 1


async def test_list_locations_returns_cities_and_neighborhoods(session):
    locations = await repo.list_locations(session)
    assert "carepa" in locations
    assert locations["carepa"] == "Carepa"
    assert any(v == "El Centro" for v in locations.values())


async def test_property_to_dict_contract(session):
    prop = await repo.get_property_by_code(session, "PROP-0001")
    data = prop.to_dict()
    for key in (
        "id", "code", "title", "property_type", "operation", "price", "currency",
        "city", "neighborhood", "address", "area_m2",
    ):
        assert key in data, f"to_dict must expose {key}"
    assert uuid_mod.UUID(data["id"])


async def test_inventory_covers_required_property_types(session):
    rows = (
        await session.execute(text("SELECT DISTINCT property_type FROM properties"))
    ).scalars().all()
    for expected in ("casa", "apartamento", "lote", "local", "oficina", "finca"):
        assert expected in set(rows), f"seed must cover {expected}"
    assert {t.value for t in PropertyType} >= {
        "casa", "apartamento", "lote", "local", "oficina", "finca", "proyecto",
    }


async def test_inventory_covers_sale_and_rent(session):
    rows = (
        await session.execute(text("SELECT DISTINCT operation FROM properties"))
    ).scalars().all()
    assert {"SALE", "RENT"}.issubset(set(rows))

