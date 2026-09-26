"""Hybrid search: structured filters, availability, FTS, vector, saved searches."""
from __future__ import annotations

from app.properties import repository as repo
from app.properties.search import (
    SearchFilters,
    extract_filters,
    match_saved_search,
    parse_price_token,
    search_properties,
    similar_properties,
)

UNAVAILABLE_CODES = {"PROP-0014", "PROP-0015", "PROP-0016"}  # SOLD / RESERVED / INACTIVE


async def _codes(session, filters: SearchFilters, semantic: str = "") -> list[str]:
    hits = await search_properties(session, filters, semantic)
    props = await repo.get_properties(session, [h.property_id for h in hits], limit=len(hits) or 1)
    by_id = {str(p.id): p.code for p in props}
    return [by_id[h.property_id] for h in hits if h.property_id in by_id]


# --------------------------------------------------------------- price parsing
def test_parse_price_token_understands_millions():
    assert parse_price_token("300", "millones") == 300_000_000
    assert parse_price_token("1.5", "millones") == 1_500_000
    assert parse_price_token("1.500", "millones") == 1_500_000_000  # thousands separator
    assert parse_price_token("285.000.000", None) == 285_000_000
    assert parse_price_token("300000000", None) == 300_000_000
    assert parse_price_token("300", None) == 300_000_000  # bare small number = millions
    assert parse_price_token("abc", None) is None


def test_extract_filters_parses_the_reference_sentence():
    filters, semantic = extract_filters(
        "Busco una casa en Carepa de maximo 300 millones, tres habitaciones, garaje y cerca del centro"
    )
    assert filters.property_type == "casa"
    assert filters.operation == "SALE"
    assert filters.max_price == 300_000_000
    assert filters.bedrooms == 3
    assert filters.parking == 1
    assert "centro" in semantic


def test_extract_filters_detects_rent_operation():
    filters, _ = extract_filters("casa en arriendo en Carepa")
    assert filters.operation == "RENT"
    assert filters.property_type == "casa"


def test_extract_filters_handles_area_and_bathrooms():
    filters, _ = extract_filters("apartamento con 2 habitaciones y 1 bano y 80 m2")
    assert filters.bedrooms == 2
    assert filters.bathrooms == 1
    assert filters.min_area == 80


def test_filters_to_dict_roundtrip():
    original = SearchFilters(
        property_type="casa", operation="RENT", city="Carepa",
        min_price=1, max_price=2, bedrooms=3, bathrooms=2, parking=1, query_text="x",
    )
    restored = SearchFilters.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()
    assert SearchFilters.from_dict({"basura": 1}).describe() == "sin filtros"


# ------------------------------------------------------------------ price filters
async def test_max_price_excludes_more_expensive(session):
    filters = SearchFilters(property_type="casa", operation="SALE", max_price=300_000_000, limit=20)
    codes = await _codes(session, filters)
    assert "PROP-0001" in codes
    assert "PROP-0003" in codes
    assert "PROP-0004" not in codes  # 480M > 300M


async def test_min_price_filters_low_end(session):
    filters = SearchFilters(property_type="casa", operation="SALE", min_price=300_000_000, limit=20)
    codes = await _codes(session, filters)
    assert "PROP-0002" in codes and "PROP-0004" in codes
    assert "PROP-0003" not in codes


async def test_bedrooms_and_parking_filters(session):
    filters = SearchFilters(property_type="casa", operation="SALE", bedrooms=3, parking=1, limit=20)
    codes = await _codes(session, filters)
    # filters are minimums: "3+ habitaciones", "1+ parqueaderos"
    assert "PROP-0001" in codes  # 3 hab / 1 parqueadero
    assert "PROP-0002" in codes  # 4 hab / 2 parqueaderos
    assert "PROP-0003" not in codes, "0 parqueaderos must fail a 1+ filter"


async def test_min_area_filter(session):
    codes = await _codes(session, SearchFilters(property_type="casa", min_area=200, limit=20))
    assert codes == ["PROP-0004"], "only the 210 m2 house qualifies"


async def test_city_and_neighborhood_filters(session):
    by_city = SearchFilters(city="Carepa", limit=20)
    assert len(await _codes(session, by_city)) >= 5
    codes = await _codes(session, SearchFilters(neighborhood="El Centro", limit=20))
    assert "PROP-0001" in codes and "PROP-0004" in codes
    assert await _codes(session, SearchFilters(city="Ciudad Inexistente", limit=20)) == []


async def test_property_type_filters(session):
    casas = await _codes(session, SearchFilters(property_type="casa", limit=20))
    assert "PROP-0001" in casas
    assert "PROP-0010" in casas
    assert "PROP-0013" in casas
    aptos = await _codes(session, SearchFilters(property_type="apartamento", limit=20))
    assert "PROP-0005" in aptos
    assert "PROP-0011" in aptos
    assert "PROP-0012" in aptos
    # Los tipos eliminados ya no existen en el inventario.
    for dead in ("lote", "local", "oficina", "finca", "proyecto"):
        assert await _codes(session, SearchFilters(property_type=dead, limit=20)) == []


async def test_search_never_returns_unavailable_properties(session):
    codes = set(await _codes(session, SearchFilters(max_price=10**12, limit=50)))
    assert not (codes & UNAVAILABLE_CODES), "SOLD/RESERVED/INACTIVE must never be offered"


async def test_include_unavailable_is_opt_in_for_admin_use(session):
    codes = set(await _codes(session, SearchFilters(include_unavailable=True, limit=50)))
    assert codes & UNAVAILABLE_CODES


async def test_rent_operation_isolated_from_sale(session):
    codes = await _codes(session, SearchFilters(operation="RENT", limit=20))
    assert "PROP-0008" in codes and "PROP-0009" in codes
    assert "PROP-0001" not in codes


# ------------------------------------------------------------ hybrid ranking
async def test_semantic_query_ranks_matching_property_first(session):
    filters, _ = extract_filters("casa con piscina")
    hits = await search_properties(session, filters, "piscina")
    assert hits, "hybrid search must return candidates"
    top = await repo.get_property(session, hits[0].property_id)
    assert "piscina" in top.title.lower()


async def test_full_text_match_scores_above_zero(session):
    hits = await search_properties(session, SearchFilters(limit=10), "ascensor")
    assert hits
    assert max(h.text_rank for h in hits) > 0


async def test_vector_similarity_is_computed(session):
    hits = await search_properties(session, SearchFilters(limit=5), "casa moderna amplia")
    assert hits
    assert any(h.vec_sim > 0 for h in hits)


async def test_limit_is_respected(session):
    hits = await search_properties(session, SearchFilters(limit=2), "")
    assert len(hits) <= 2


# --------------------------------------------------------------- similar / alerts
async def test_similar_properties_are_real_and_in_price_band(session):
    target = await repo.get_property_by_code(session, "PROP-0001")
    hits = await similar_properties(session, str(target.id), limit=3)
    assert hits
    for hit in hits:
        other = await repo.get_property(session, hit.property_id)
        assert other.id != target.id
        assert other.status.value == "AVAILABLE"
        assert float(target.price) * 0.6 <= float(other.price) <= float(target.price) * 1.4


async def test_similar_properties_of_unknown_id_returns_empty(session):
    import uuid as uuid_mod

    assert await similar_properties(session, str(uuid_mod.uuid4())) == []


async def test_match_saved_search_uses_stored_filters(session):
    hits = await match_saved_search(
        session, {"property_type": "casa", "operation": "SALE", "max_price": 300_000_000}, limit=5
    )
    props = await repo.get_properties(session, [h.property_id for h in hits], limit=len(hits) or 1)
    assert props
    for p in props:
        assert p.property_type.value == "casa"
        assert float(p.price) <= 300_000_000
        assert p.status.value == "AVAILABLE"


async def test_search_properties_is_scoped_by_availability_status_enum(session):
    from app.database.models import PropertyStatus

    hits = await search_properties(session, SearchFilters(limit=50), "")
    props = await repo.get_properties(session, [h.property_id for h in hits], limit=len(hits) or 1)
    assert props
    assert all(p.status is PropertyStatus.AVAILABLE for p in props)

