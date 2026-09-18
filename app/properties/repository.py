"""Property repository: all SQL for the inventory lives here (LLM never touches it)."""
from __future__ import annotations

import uuid as uuid_mod

from sqlalchemy import delete, func, select
from sqlalchemy import text as sqlalchemy_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import get_embedding_provider, normalize_text
from app.core.logging import get_logger
from app.database.models import Operation, Property, PropertyStatus, PropertyType

log = get_logger(__name__)


def property_text_for_embedding(p: Property) -> str:
    features = " ".join(p.features or [])
    return " ".join(
        str(x) for x in [
            p.title, p.property_type.value, p.operation.value, p.city, p.neighborhood,
            features, p.description or "",
        ]
    )


async def sync_property_embedding(session: AsyncSession, prop: Property) -> None:
    provider = get_embedding_provider()
    vec = (await provider.embed([property_text_for_embedding(prop)]))[0]
    prop.title_embedding = vec


async def get_property(session: AsyncSession, property_id) -> Property | None:
    try:
        pid = property_id if isinstance(property_id, uuid_mod.UUID) else uuid_mod.UUID(str(property_id))
    except (ValueError, AttributeError):
        return None
    return (await session.execute(select(Property).where(Property.id == pid))).scalar_one_or_none()


async def get_property_by_code(session: AsyncSession, code: str) -> Property | None:
    return (
        await session.execute(select(Property).where(Property.code == code.upper()))
    ).scalar_one_or_none()


async def get_properties(session: AsyncSession, ids: list[str] | None = None, limit: int = 50, offset: int = 0):
    stmt = select(Property).order_by(Property.created_at.desc()).limit(limit).offset(offset)
    if ids:
        parsed = []
        for i in ids:
            try:
                parsed.append(uuid_mod.UUID(str(i)))
            except ValueError:
                pass
        stmt = select(Property).where(Property.id.in_(parsed))
    return (await session.execute(stmt)).scalars().all()


async def list_locations(session: AsyncSession) -> dict[str, str]:
    """normalized lowercase name → canonical name (cities + neighborhoods)."""
    rows = (await session.execute(select(Property.city, Property.neighborhood).distinct())).all()
    out: dict[str, str] = {}
    for city, hood in rows:
        for name in (city, hood):
            if name:
                out[name.lower().strip()] = name
    return out


async def create_property(session: AsyncSession, data: dict) -> Property:
    valid_types = {t.value for t in PropertyType}
    ptype = data.get("property_type")
    if ptype not in valid_types:
        raise ValueError(f"property_type inválido: {ptype}. Válidos: {sorted(valid_types)}")
    operation = data.get("operation", "SALE")
    if operation not in {o.value for o in Operation}:
        raise ValueError(f"operation inválida: {operation}")
    status = data.get("status", "AVAILABLE")
    if status not in {s.value for s in PropertyStatus}:
        raise ValueError(f"status inválido: {status}")

    code = data.get("code") or (await _next_code(session))
    prop = Property(
        code=code,
        title=data["title"],
        description=data.get("description", ""),
        property_type=PropertyType(ptype),
        operation=Operation(operation),
        price=float(data["price"]),
        currency=data.get("currency", "COP"),
        city=data.get("city", ""),
        neighborhood=data.get("neighborhood", ""),
        address=data.get("address", ""),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        area_m2=data.get("area_m2"),
        bedrooms=data.get("bedrooms"),
        bathrooms=data.get("bathrooms"),
        parking_spaces=data.get("parking_spaces"),
        status=PropertyStatus(status),
        features=data.get("features", []),
        project_id=data.get("project_id"),
    )
    session.add(prop)
    await session.flush()
    await sync_property_embedding(session, prop)
    await session.flush()
    log.info("property_created code=%s id=%s", prop.code, prop.id)
    return prop


async def _next_code(session: AsyncSession) -> str:
    n = (await session.execute(select(func.count()).select_from(Property))).scalar() or 0
    return f"PROP-{n + 1:04d}"


async def update_property(session: AsyncSession, property_id, data: dict) -> Property | None:
    prop = await get_property(session, property_id)
    if prop is None:
        return None
    allowed = {
        "title", "description", "price", "currency", "city", "neighborhood", "address",
        "latitude", "longitude", "area_m2", "bedrooms", "bathrooms", "parking_spaces",
        "features", "project_id", "code",
    }
    for field_name in allowed:
        if field_name in data and data[field_name] is not None:
            setattr(prop, field_name, data[field_name])
    if data.get("property_type") in {t.value for t in PropertyType}:
        prop.property_type = PropertyType(data["property_type"])
    if data.get("operation") in {o.value for o in Operation}:
        prop.operation = Operation(data["operation"])
    if data.get("status") in {s.value for s in PropertyStatus}:
        prop.status = PropertyStatus(data["status"])
    await session.flush()
    await sync_property_embedding(session, prop)
    await session.flush()
    return prop


async def delete_property(session: AsyncSession, property_id) -> bool:
    prop = await get_property(session, property_id)
    if prop is None:
        return False
    await session.execute(delete(Property).where(Property.id == property_id))
    return True


STOPWORDS_ES = frozenset(
    "de la el los las un una unos unas y o u e en con para por del al que se su sus"
    " mi mis tu tus es son esta este estos estas me te le les nos yo tu ella"
    " quiero busco busca necesito cerca maximo max menos entre desde hasta donde"
    " cual cuales cuanto cuantos cuanta cuantas precio cuesta vale valor tiene tienen"
    " hay estan dime muestrame mostrar datos informacion propiedad propiedades"
).union({"a", "sin", "sobre"})

# Feature/amenity nouns are never identifiers — they are what the user asks about.
ATTRIBUTE_TOKENS = frozenset(
    normalize_text(
        "piscina garaje parqueadero ascensor jardin terraza balcon amoblado amueblado"
        " mascota closet deposito chimenea jacuzzi gimnasio vista"
    )
)


async def find_property_by_text(
    session: AsyncSession, query_text: str, min_matches: int = 2
) -> Property | None:
    """Deterministic natural-language property lookup by name/title.

    Uses Spanish full-text to shortlist candidates, then requires the best
    candidate to share at least `min_matches` significant tokens with the user
    message AND to beat the runner-up strictly. Ambiguous input returns None
    (the agent then asks which property) — it never guesses.
    """
    if not query_text or not query_text.strip():
        return None
    q_tokens = sorted(set(normalize_text(query_text)) - STOPWORDS_ES)
    if len(q_tokens) < min_matches:
        return None
    # Attribute nouns ("piscina") are what the user is ASKING ABOUT, not an
    # identifier: "la casa familiar tiene piscina?" must not match
    # "Casa amplia con piscina". Keep them only for the FTS shortlist.
    id_tokens = [t for t in q_tokens if t not in ATTRIBUTE_TOKENS]
    if len(id_tokens) < min_matches:
        return None
    id_token_set = set(id_tokens)
    tsquery = " | ".join(q_tokens)
    # OR the terms: "la casa familiar tiene piscina" must still reach PROP-0001
    # even though "piscina" appears in no property vector.
    tsquery = " | ".join(q_tokens)
    sql = sqlalchemy_text(
        "SELECT p.id, p.title FROM properties p "
        "WHERE p.search_vector @@ to_tsquery('spanish', :q) "
        "ORDER BY ts_rank(p.search_vector, to_tsquery('spanish', :q)) DESC "
        "LIMIT 20"
    )
    try:
        rows = (await session.execute(sql, {"q": tsquery})).mappings().all()
    except Exception as e:  # pragma: no cover - defensive
        log.warning("find_property_by_text_failed error=%s", e)
        return None

    scored: list[tuple[int, str]] = []
    for row in rows:
        title_tokens = set(normalize_text(row["title"] or "")) - STOPWORDS_ES
        matched = len(title_tokens & id_token_set)
        if matched >= min_matches:
            scored.append((matched, str(row["id"])))
    if not scored:
        return None
    scored.sort(reverse=True)
    best_score, best_id = scored[0]
    if len(scored) > 1 and scored[1][0] == best_score:
        return None  # ambiguous → do not guess
    log.info("property_text_match id=%s matched=%s", best_id, best_score)
    return await get_property(session, best_id)


async def count_by_status(session: AsyncSession) -> dict[str, int]:
    rows = (await session.execute(select(Property.status, func.count()).group_by(Property.status))).all()
    return {status.value: n for status, n in rows}

