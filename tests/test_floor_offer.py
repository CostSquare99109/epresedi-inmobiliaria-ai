"""Floor offer model: total floors vs. which part is offered.

Criterio de aceptación del flujo de pisos en "Nueva Propiedad":
- Venta + 2 pisos + propiedad completa
- Arriendo + 2 pisos + propiedad completa
- Arriendo + 2 pisos + piso 1 / piso 2
- Arriendo + 3 pisos + pisos 1 y 2
- 2 pisos + piso 3 se rechaza (422)
- Compatibilidad: propiedades antiguas siguen cargando/editándose.
"""
from __future__ import annotations

import httpx
import pytest

from app.api import routes
from app.properties import repository as repo
from app.properties.flooring import (
    floors_display,
    prune_offered_floors,
    validate_floor_offer,
)
from app.properties.search import SearchFilters, extract_filters, search_properties


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=routes.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _base_payload(**over):
    payload = {
        "title": "Casa pisos", "property_type": "casa", "operation": "SALE",
        "price": 250_000_000, "city": "Carepa", "neighborhood": "El Centro",
    }
    payload.update(over)
    return payload


# ---------------------------------------------------------- unit validation
def test_validate_acceptance_cases():
    assert validate_floor_offer(2, "full_property", []) == (2, "full_property", [])
    assert validate_floor_offer(2, "single_floor", [1]) == (2, "single_floor", [1])
    assert validate_floor_offer(2, "single_floor", [2]) == (2, "single_floor", [2])
    assert validate_floor_offer(3, "multiple_floors", [2, 1]) == (3, "multiple_floors", [1, 2])
    assert validate_floor_offer(2, "partial", []) == (2, "partial", [])
    # Legacy: sin datos nuevos -> propiedad completa por defecto
    assert validate_floor_offer(None, None, None) == (None, "full_property", [])
    assert validate_floor_offer(2, None, None) == (2, "full_property", [])
    # Legado: 0 ("no aplica" en registros antiguos) se normaliza a desconocido
    assert validate_floor_offer(0, None, None) == (None, "full_property", [])


def test_validate_rejects_impossible_states():
    with pytest.raises(ValueError):
        validate_floor_offer(2, "single_floor", [3])  # piso superior al total
    with pytest.raises(ValueError):
        validate_floor_offer(2, "single_floor", [])  # falta el piso
    with pytest.raises(ValueError):
        validate_floor_offer(2, "single_floor", [1, 2])  # más de uno
    with pytest.raises(ValueError):
        validate_floor_offer(3, "multiple_floors", [])  # ninguno
    with pytest.raises(ValueError):
        validate_floor_offer(2, "full_property", [1])  # completa no lleva pisos
    with pytest.raises(ValueError):
        validate_floor_offer(-1, "full_property", [])  # negativo inválido
    with pytest.raises(ValueError):
        validate_floor_offer(None, "single_floor", [1])  # sin total no se acota


def test_prune_dynamic_change_4_to_2():
    assert prune_offered_floors([4], 2) == []
    assert prune_offered_floors([1, 2, 4], 2) == [1, 2]
    assert prune_offered_floors([1, 2], 4) == [1, 2]


def test_floors_display_strings():
    assert floors_display(2, "full_property", []) == "2 pisos · Propiedad completa"
    assert floors_display(2, "single_floor", [1]) == "2 pisos · Piso 1"
    assert floors_display(2, "single_floor", [2]) == "2 pisos · Piso 2"
    assert floors_display(3, "multiple_floors", [1, 2]) == "3 pisos · Pisos 1 y 2"
    assert floors_display(2, "partial", []) == "2 pisos · Parte de la propiedad"


# ------------------------------------------------------------------- API CRUD
async def _create(client, headers, **over):
    r = await client.post("/properties", json=_base_payload(**over), headers=headers)
    return r


async def test_api_sale_full_property(client, admin_token):
    r = await _create(
        client, admin_token(), operation="SALE",
        floors=2, floor_offer_type="full_property", offered_floors=[],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["floors"] == 2
    assert body["floor_offer_type"] == "full_property"
    assert body["offered_floors"] == []
    await client.delete(f"/properties/{body['id']}", headers=admin_token())


async def test_api_rent_full_property(client, admin_token):
    r = await _create(
        client, admin_token(), operation="RENT",
        floors=2, floor_offer_type="full_property", offered_floors=[],
    )
    assert r.status_code == 200, r.text
    assert r.json()["floor_offer_type"] == "full_property"
    await client.delete(f"/properties/{r.json()['id']}", headers=admin_token())


@pytest.mark.parametrize("piso", [1, 2])
async def test_api_rent_single_floor(client, admin_token, piso):
    r = await _create(
        client, admin_token(), operation="RENT", title=f"Casa piso {piso}",
        floors=2, floor_offer_type="single_floor", offered_floors=[piso],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["offered_floors"] == [piso]
    # Recuperar: la información se conserva
    g = await client.get(f"/properties/{body['id']}")
    assert g.status_code == 200
    assert g.json()["offered_floors"] == [piso]
    # Editar conserva el modelo
    p = await client.patch(
        f"/properties/{body['id']}",
        json={"title": f"Casa piso {piso} editada"},
        headers=admin_token(),
    )
    assert p.status_code == 200, p.text
    assert p.json()["offered_floors"] == [piso]
    await client.delete(f"/properties/{body['id']}", headers=admin_token())


async def test_api_rent_multiple_floors(client, admin_token):
    r = await _create(
        client, admin_token(), operation="RENT",
        floors=3, floor_offer_type="multiple_floors", offered_floors=[1, 2],
    )
    assert r.status_code == 200, r.text
    assert r.json()["offered_floors"] == [1, 2]
    await client.delete(f"/properties/{r.json()['id']}", headers=admin_token())


async def test_api_rejects_floor_above_total(client, admin_token):
    r = await _create(
        client, admin_token(),
        floors=2, floor_offer_type="single_floor", offered_floors=[3],
    )
    assert r.status_code == 422, r.text


async def test_api_rejects_full_with_floors_selected(client, admin_token):
    r = await _create(
        client, admin_token(),
        floors=2, floor_offer_type="full_property", offered_floors=[1],
    )
    assert r.status_code == 422, r.text


async def test_api_sale_requires_full_property(client, admin_token):
    """En venta siempre se ofrece la propiedad completa (la UI ni lo pregunta)."""
    r = await _create(
        client, admin_token(), operation="SALE",
        floors=2, floor_offer_type="single_floor", offered_floors=[1],
    )
    assert r.status_code == 422, r.text
    assert "venta" in r.text.lower()


async def test_api_patch_rejects_inconsistent_offer(client, admin_token):
    r = await _create(client, admin_token(), operation="RENT", floors=2)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    # La propiedad quedó como completa: agregar pisos sin cambiar el tipo falla
    p = await client.patch(
        f"/properties/{pid}", json={"offered_floors": [1]}, headers=admin_token()
    )
    assert p.status_code == 422, p.text
    # Cambiar tipo + pisos juntos sí funciona
    p = await client.patch(
        f"/properties/{pid}",
        json={"floor_offer_type": "single_floor", "offered_floors": [2]},
        headers=admin_token(),
    )
    assert p.status_code == 200, p.text
    assert p.json()["offered_floors"] == [2]
    await client.delete(f"/properties/{pid}", headers=admin_token())


async def test_api_legacy_payload_defaults_to_full(client, admin_token):
    """Sin los campos nuevos el backend asume propiedad completa (compat)."""
    payload = _base_payload(floors=2)
    r = await client.post("/properties", json=payload, headers=admin_token())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["floor_offer_type"] == "full_property"
    assert body["offered_floors"] == []
    await client.delete(f"/properties/{body['id']}", headers=admin_token())


async def test_api_partial_offer(client, admin_token):
    r = await _create(
        client, admin_token(), operation="RENT",
        floors=2, floor_offer_type="partial", offered_floors=[],
        description="Apartamento interior en primer piso con entrada independiente.",
    )
    assert r.status_code == 200, r.text
    assert r.json()["floor_offer_type"] == "partial"
    await client.delete(f"/properties/{r.json()['id']}", headers=admin_token())


# ------------------------------------------------- compat + search
async def test_legacy_seed_properties_load_with_defaults(session):
    prop = await repo.get_property_by_code(session, "PROP-0001")
    assert prop is not None
    d = prop.to_dict()
    assert d["floors"] == 2 or d["floors"] is None  # seed puede variar, pero no rompe
    assert d["floor_offer_type"] == "full_property"
    assert d["offered_floors"] == []


def test_extract_offered_floor():
    f, _ = extract_filters("Busco una casa para arrendar solamente el segundo piso")
    assert f.operation == "RENT"
    assert f.offered_floor == 2
    f, _ = extract_filters("quiero el piso 1 en arriendo")
    assert f.offered_floor == 1
    f, _ = extract_filters("casa de 2 pisos")
    assert f.floors == 2
    assert f.offered_floor is None


async def test_search_offered_floor_distinguishes(session):
    """El piso 2 ofertado se distingue de la casa completa."""
    a = await repo.create_property(session, {
        "title": "Casa completa 2 pisos busqueda", "property_type": "casa",
        "operation": "RENT", "price": 1_000_000, "city": "Carepa",
        "floors": 2, "floor_offer_type": "full_property", "offered_floors": [],
    })
    b = await repo.create_property(session, {
        "title": "Piso 2 en casa busqueda", "property_type": "casa",
        "operation": "RENT", "price": 600_000, "city": "Carepa",
        "floors": 2, "floor_offer_type": "single_floor", "offered_floors": [2],
    })
    await session.commit()
    try:
        hits = await search_properties(
            session, SearchFilters(operation="RENT", offered_floor=2, limit=50), ""
        )
        ids = {h.property_id for h in hits}
        assert str(b.id) in ids
        by_id = {str(p.id): p for p in
                 await repo.get_properties(session, [h.property_id for h in hits], limit=50)}
        assert by_id[str(b.id)].to_dict()["floor_offer_type"] == "single_floor"
        assert by_id[str(b.id)].to_dict()["offered_floors"] == [2]
        # La casa completa contiene físicamente el piso 2 (alternativa válida)
        assert str(a.id) in ids
    finally:
        from sqlalchemy import delete as sa_delete

        from app.database.models import Property

        await session.execute(
            sa_delete(Property).where(Property.id.in_([a.id, b.id]))
        )
        await session.commit()
