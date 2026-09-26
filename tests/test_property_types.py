"""Regla definitiva de tipos de propiedad: solo casa y apartamento.

Verifica la eliminación integral de lote/local/oficina/finca(/proyecto)
en modelo, repositorio, API, búsqueda determinista, intents y estado del
agente (Fase 10 de la limpieza de tipos).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.agents.intents import Intent, detect_intent
from app.agents.state import PROPERTY_TYPES, merge_state_update
from app.api.routes import _validate_enum_value
from app.database.models import PropertyType
from app.properties import repository as repo
from app.properties.search import SearchFilters, extract_filters, search_properties

REMOVED = ("lote", "local", "oficina", "finca", "proyecto")


def test_property_type_enum_only_casa_apartamento():
    assert {t.value for t in PropertyType} == {"casa", "apartamento"}
    assert PropertyType("casa") is PropertyType.HOUSE
    assert PropertyType("apartamento") is PropertyType.APARTMENT


@pytest.mark.parametrize("dead", REMOVED)
def test_removed_types_are_not_valid_enum_members(dead):
    with pytest.raises(ValueError):
        PropertyType(dead)


def test_state_property_types_only_casa_apartamento():
    assert set(PROPERTY_TYPES) == {"casa", "apartamento"}


@pytest.mark.parametrize("dead", REMOVED)
def test_state_rejects_removed_types(dead):
    state: dict = {}
    applied, rejected = merge_state_update(state, {"property_type": dead})
    assert applied == {}
    assert rejected, f"{dead} debe ser rechazado por el estado"
    assert "property_type" not in state


def test_state_accepts_casa_and_apartamento():
    for valid in ("casa", "apartamento"):
        state: dict = {}
        applied, rejected = merge_state_update(state, {"property_type": valid})
        assert not rejected
        assert applied["property_type"] == valid


@pytest.mark.parametrize("dead", REMOVED)
async def test_repository_rejects_removed_types_on_create(session, dead):
    with pytest.raises(ValueError, match="property_type inválido"):
        await repo.create_property(
            session, {"title": "X", "property_type": dead, "price": 1}
        )
    await session.rollback()


async def test_repository_creates_casa_and_apartamento(session):
    casa = await repo.create_property(
        session,
        {"title": "Casa regla", "property_type": "casa", "operation": "SALE",
         "price": 100_000_000, "city": "Carepa"},
    )
    assert casa.property_type is PropertyType.HOUSE
    apto = await repo.create_property(
        session,
        {"title": "Apto regla", "property_type": "apartamento", "operation": "RENT",
         "price": 1_000_000, "city": "Carepa"},
    )
    assert apto.property_type is PropertyType.APARTMENT

    updated = await repo.update_property(session, casa.id, {"property_type": "apartamento"})
    assert updated.property_type is PropertyType.APARTMENT
    updated = await repo.update_property(session, apto.id, {"property_type": "casa"})
    assert updated.property_type is PropertyType.HOUSE
    await session.rollback()


@pytest.mark.parametrize("dead", REMOVED)
def test_api_enum_validation_rejects_removed_types(dead):
    with pytest.raises(HTTPException) as exc:
        _validate_enum_value(dead, PropertyType, "property_type")
    assert exc.value.status_code == 422


def test_api_enum_validation_accepts_casa_apartamento():
    assert _validate_enum_value("casa", PropertyType, "property_type") == "casa"
    assert _validate_enum_value("apartamento", PropertyType, "property_type") == "apartamento"


@pytest.mark.parametrize(
    "text", ["busco un lote en Carepa", "quiero ver oficinas", "fincas en venta", "local comercial"],
)
def test_extract_filters_never_returns_removed_types(text):
    filters, _ = extract_filters(text)
    assert filters.property_type in (None, "casa", "apartamento"), text


def test_extract_filters_still_detects_casa_and_apartamento():
    assert extract_filters("busco una casa en Carepa")[0].property_type == "casa"
    assert extract_filters("apartamento en arriendo")[0].property_type == "apartamento"


@pytest.mark.parametrize("dead", REMOVED)
async def test_search_with_removed_type_returns_nothing(session, dead):
    hits = await search_properties(session, SearchFilters(property_type=dead, limit=20), "")
    assert hits == []


async def test_search_still_finds_casa_and_apartamento(session):
    hits = await search_properties(session, SearchFilters(property_type="casa", limit=20), "")
    assert hits
    hits = await search_properties(session, SearchFilters(property_type="apartamento", limit=20), "")
    assert hits


def test_tool_spec_enums_only_casa_apartamento():
    from app.agents.tool_specs import TOOL_SPECS

    by_name = {s["function"]["name"]: s["function"] for s in TOOL_SPECS}
    for name in ("update_conversation_state", "search_properties", "create_alert"):
        params = by_name[name]["parameters"]["properties"]
        carrier = params.get("property_type")
        if carrier is None:  # search_properties / create_alert anidan el enum en filters
            carrier = params["filters"]["properties"]["property_type"]
        assert carrier["enum"] == ["casa", "apartamento"], name


def test_removed_type_words_do_not_trigger_search_intent_alone():
    # Sin criterios de búsqueda reales, un tipo eliminado solo no debe
    # clasificarse como búsqueda de propiedad válida.
    assert detect_intent("lote") is not Intent.SEARCH_PROPERTY
    assert detect_intent("finca") is not Intent.SEARCH_PROPERTY
