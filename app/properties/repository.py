"""Property repository: all SQL for the inventory lives here (LLM never touches it)."""
from __future__ import annotations

import uuid as uuid_mod

from sqlalchemy import delete, func, select
from sqlalchemy import text as sqlalchemy_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import get_embedding_provider, normalize_text
from app.core.logging import get_logger
from app.database.models import Branch, BusinessHour, Operation, Property, PropertyImage, PropertyStatus, PropertyType
from app.properties.flooring import (
    embedding_fragment,
    normalize_offer_type,
    normalize_offered_floors,
    validate_floor_offer,
)

log = get_logger(__name__)


def property_text_for_embedding(p: Property) -> str:
    features = " ".join(p.features or [])
    floors = getattr(p, "floors", None)
    offer = getattr(p, "floor_offer_type", None) or "full_property"
    offered = list(getattr(p, "offered_floors", None) or [])
    floor_text = embedding_fragment(floors, offer, offered)
    return " ".join(
        str(x) for x in [
            p.title, p.property_type.value, p.operation.value, p.city, p.neighborhood,
            features, floor_text, p.description or "",
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
    from sqlalchemy.orm import selectinload
    return (await session.execute(
        select(Property).options(
            selectinload(Property.branch),
            selectinload(Property.images)
        ).where(Property.id == pid)
    )).scalar_one_or_none()


async def get_property_by_code(session: AsyncSession, code: str) -> Property | None:
    return (
        await session.execute(select(Property).where(Property.code == code.upper()))
    ).scalar_one_or_none()


async def get_properties(session: AsyncSession, ids: list[str] | None = None, limit: int = 50, offset: int = 0):
    limit = max(0, min(limit, 200))
    offset = max(0, offset)
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

    # Validate services_included
    services_included = data.get("services_included", "no_incluye")
    if services_included not in ("incluye", "no_incluye"):
        raise ValueError(f"services_included inválido: {services_included}. Válidos: incluye, no_incluye")

    # Validate branch if provided
    branch_id = data.get("branch_id")
    if branch_id:
        branch = await session.get(Branch, uuid_mod.UUID(str(branch_id)))
        if branch is None:
            raise ValueError(f"branch_id no encontrado: {branch_id}")

    code = data.get("code") or (await _next_code(session))
    floors, offer_type, offered = validate_floor_offer(
        data.get("floors"),
        data.get("floor_offer_type"),
        data.get("offered_floors"),
    )
    if operation == "SALE" and (offer_type != "full_property" or offered):
        raise ValueError("En venta se ofrece la propiedad completa")
    prop = Property(
        code=code,
        title=data["title"],
        description=data.get("description", ""),
        property_type=PropertyType(ptype),
        operation=Operation(operation),
        price=float(data["price"]),
        currency=data.get("currency", "COP"),
        price_period=data.get("price_period", "") or ("month" if operation == "RENT" else ""),
        city=data.get("city", ""),
        neighborhood=data.get("neighborhood", ""),
        address=data.get("address", ""),
        street=data.get("street", ""),
        street_number=data.get("street_number", ""),
        descriptive_location=data.get("descriptive_location", ""),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        area_m2=data.get("area_m2"),
        bedrooms=data.get("bedrooms"),
        bathrooms=data.get("bathrooms"),
        parking_spaces=data.get("parking_spaces"),
        floors=floors,
        floor_offer_type=offer_type,
        offered_floors=offered,
        has_kitchen=data.get("has_kitchen", True),
        has_living_room=data.get("has_living_room", True),
        has_laundry_area=data.get("has_laundry_area", False),
        # New detailed fields
        bedrooms_description=data.get("bedrooms_description", ""),
        bathrooms_description=data.get("bathrooms_description", ""),
        living_room_description=data.get("living_room_description", ""),
        laundry_area_description=data.get("laundry_area_description", ""),
        has_parking=data.get("has_parking", False),
        parking_description=data.get("parking_description", ""),
        rent_price=data.get("rent_price"),
        services_included=services_included,
        nomenclatura=data.get("nomenclatura", ""),
        visiting_hours=data.get("visiting_hours", []),
        status=PropertyStatus(status),
        features=data.get("features", []),
        branch_id=branch_id,
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
        "title", "description", "price", "currency", "price_period", "city", "neighborhood", "address",
        "street", "street_number", "descriptive_location",
        "latitude", "longitude", "area_m2", "bedrooms", "bathrooms", "parking_spaces",
        "floors", "floor_offer_type", "offered_floors",
        "has_kitchen", "has_living_room", "has_laundry_area",
        "features", "branch_id",
        # NOTE: "code" is intentionally NOT updatable (stable public identifier).
        # New detailed fields
        "bedrooms_description", "bathrooms_description", "living_room_description",
        "laundry_area_description", "has_parking", "parking_description",
        "rent_price", "services_included", "nomenclatura", "visiting_hours",
    }
    floor_fields = {"floors", "floor_offer_type", "offered_floors"}
    if floor_fields & set(data.keys()) or data.get("operation") == "SALE":
        merged_floors = data.get("floors", prop.floors)
        merged_offer = data.get("floor_offer_type", getattr(prop, "floor_offer_type", None))
        merged_offered = data.get(
            "offered_floors", list(getattr(prop, "offered_floors", None) or [])
        )
        merged_floors, merged_offer, merged_offered = validate_floor_offer(
            merged_floors, merged_offer, merged_offered
        )
        merged_operation = data.get("operation", None)
        if merged_operation is None:
            current_op = getattr(prop, "operation", None)
            merged_operation = current_op.value if hasattr(current_op, "value") else current_op
        if merged_operation == "SALE" and (merged_offer != "full_property" or merged_offered):
            raise ValueError("En venta se ofrece la propiedad completa")
        prop.floors = merged_floors
        prop.floor_offer_type = merged_offer
        prop.offered_floors = merged_offered
    for field_name in allowed - floor_fields:
        if field_name in data and data[field_name] is not None:
            setattr(prop, field_name, data[field_name])
    if data.get("property_type") in {t.value for t in PropertyType}:
        prop.property_type = PropertyType(data["property_type"])
    if data.get("operation") in {o.value for o in Operation}:
        prop.operation = Operation(data["operation"])
        # Auto-set price_period for rent
        if data["operation"] == "RENT" and not prop.price_period:
            prop.price_period = "month"
    if data.get("status") in {s.value for s in PropertyStatus}:
        prop.status = PropertyStatus(data["status"])
    # Validate services_included
    if "services_included" in data and data["services_included"] is not None:
        if data["services_included"] not in ("incluye", "no_incluye"):
            raise ValueError(f"services_included inválido: {data['services_included']}. Válidos: incluye, no_incluye")
        prop.services_included = data["services_included"]
    # Validate branch if provided
    if "branch_id" in data and data["branch_id"] is not None:
        branch = await session.get(Branch, uuid_mod.UUID(str(data["branch_id"])))
        if branch is None:
            raise ValueError(f"branch_id no encontrado: {data['branch_id']}")
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


async def list_properties_admin(
    session: AsyncSession,
    *,
    status: str | None = None,
    city: str | None = None,
    q: str | None = None,
    property_type: str | None = None,
    operation: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 12,
    offset: int = 0,
) -> tuple[list[Property], int]:
    """Admin inventory listing: combined filters + real total count.

    `q` searches the computed search_vector (FTS, sanitized via
    plainto_tsquery) with ilike fallbacks for title/code partial matches.
    """
    from sqlalchemy import or_

    conds = []
    if status:
        conds.append(Property.status == status)
    if city:
        conds.append(Property.city.ilike(f"%{city}%"))
    if property_type:
        conds.append(Property.property_type == property_type)
    if operation:
        conds.append(Property.operation == operation)
    if min_price is not None:
        conds.append(Property.price >= min_price)
    if max_price is not None:
        conds.append(Property.price <= max_price)
    if q and q.strip():
        needle = q.strip()
        conds.append(or_(
            Property.search_vector.op("@@")(func.plainto_tsquery("spanish", needle)),
            Property.title.ilike(f"%{needle}%"),
            Property.code.ilike(f"%{needle}%"),
        ))
    stmt = select(Property)
    count_stmt = select(func.count()).select_from(Property)
    if conds:
        stmt = stmt.where(*conds)
        count_stmt = count_stmt.where(*conds)
    total = (await session.execute(count_stmt)).scalar() or 0
    limit = max(0, min(limit, 200))
    offset = max(0, offset)
    stmt = stmt.order_by(Property.created_at.desc()).limit(limit).offset(offset)
    props = (await session.execute(stmt)).scalars().all()
    return props, total


# ----------------------------------------------------------------- property images
VALID_IMAGE_GROUPS = frozenset({
    "portada", "piso", "bano", "cocina", "lavadero", "parqueadero",
    "extra", "general",
})


def normalize_image_group(group: str | None) -> str:
    """Valida el grupo/característica de una imagen (default 'general')."""
    g = (group or "general").strip().lower()
    if g not in VALID_IMAGE_GROUPS:
        raise ValueError(
            f"Grupo de imagen inválido: {group}. "
            f"Válidos: {sorted(VALID_IMAGE_GROUPS)}"
        )
    return g


async def add_property_image(
    session: AsyncSession,
    property_id: uuid.UUID,
    filename: str,
    is_cover: bool = False,
    sort_order: int = 0,
    alt_text: str = "",
    file_size: int = 0,
    mime_type: str = "",
    name: str = "",
    description: str = "",
    group: str | None = None,
    extra_name: str = "",
) -> PropertyImage:
    """Add an image record for a property."""
    image_group = normalize_image_group(group)
    if image_group == "extra" and not (extra_name or "").strip():
        raise ValueError("Las imágenes del grupo 'extra' requieren el nombre del extra (extra_name)")
    # If this is the cover, unset any existing cover
    if is_cover:
        await session.execute(
            PropertyImage.__table__.update()
            .where(PropertyImage.property_id == property_id)
            .values(is_cover=False)
        )
    # Determine sort_order if not provided
    if sort_order == 0:
        max_order = await session.scalar(
            select(func.max(PropertyImage.sort_order)).where(PropertyImage.property_id == property_id)
        )
        sort_order = (max_order or 0) + 1
    img = PropertyImage(
        property_id=property_id,
        filename=filename,
        is_cover=is_cover,
        sort_order=sort_order,
        alt_text=alt_text,
        file_size=file_size,
        mime_type=mime_type,
        name=name,
        description=description,
        group=image_group,
        extra_name=(extra_name or "").strip()[:200],
    )
    session.add(img)
    await session.flush()
    return img


async def get_property_images(
    session: AsyncSession,
    property_id: uuid.UUID,
    group: str | None = None,
    extra_name: str | None = None,
) -> list[PropertyImage]:
    """Get all images for a property, ordered by cover first then sort_order.

    Filtra opcionalmente por grupo/característica (`group`) y, para el grupo
    'extra', por nombre del extra (`extra_name`).
    """
    stmt = (
        select(PropertyImage)
        .where(PropertyImage.property_id == property_id)
        .order_by(PropertyImage.is_cover.desc(), PropertyImage.sort_order)
    )
    if group is not None:
        stmt = stmt.where(PropertyImage.group == normalize_image_group(group))
    if extra_name is not None:
        stmt = stmt.where(PropertyImage.extra_name == extra_name.strip())
    return list((await session.execute(stmt)).scalars().all())


def group_property_images(images: list[PropertyImage]) -> dict[str, list[dict]]:
    """Agrupa dicts de imágenes por característica para el agente/API."""
    grouped: dict[str, list[dict]] = {}
    for img in images:
        d = img.to_dict() if hasattr(img, "to_dict") else dict(img)
        key = d.get("extra_name") or "" if d.get("group") == "extra" else None
        gkey = f"extra:{key}" if key else (d.get("group") or "general")
        grouped.setdefault(gkey, []).append(d)
    return grouped


async def apply_image_renames(
    session: AsyncSession, property_id: uuid.UUID, mapping: dict[str, str]
) -> None:
    """Sync DB filenames after a disk rename (cover/reorder/delete).

    Without this, rows keep pointing at the old disk names and the images
    serve 404. Flush is left to the caller (single commit per endpoint).
    """
    for old, new in mapping.items():
        if not old or not new or old == new:
            continue
        await session.execute(
            PropertyImage.__table__.update()
            .where(PropertyImage.property_id == property_id, PropertyImage.filename == old)
            .values(filename=new)
        )


async def set_property_cover_image(session: AsyncSession, property_id: uuid.UUID, image_id: uuid.UUID) -> bool:
    """Set a specific image as the cover for a property."""
    # Unset all covers
    await session.execute(
        PropertyImage.__table__.update()
        .where(PropertyImage.property_id == property_id)
        .values(is_cover=False)
    )
    # Set new cover
    result = await session.execute(
        PropertyImage.__table__.update()
        .where(PropertyImage.id == image_id, PropertyImage.property_id == property_id)
        .values(is_cover=True)
    )
    return result.rowcount > 0


async def reorder_property_images(session: AsyncSession, property_id: uuid.UUID, image_ids: list[uuid.UUID]) -> list[PropertyImage]:
    """Reorder images by providing a list of image IDs in the desired order."""
    for i, img_id in enumerate(image_ids):
        await session.execute(
            PropertyImage.__table__.update()
            .where(PropertyImage.id == img_id, PropertyImage.property_id == property_id)
            .values(sort_order=i, is_cover=(i == 0))
        )
    return await get_property_images(session, property_id)


async def delete_property_image(session: AsyncSession, property_id: uuid.UUID, image_id: uuid.UUID) -> bool:
    """Delete a specific image."""
    result = await session.execute(
        delete(PropertyImage).where(PropertyImage.id == image_id, PropertyImage.property_id == property_id)
    )
    return result.rowcount > 0


# ----------------------------------------------------------------- branches
async def get_branch(session: AsyncSession, branch_id: uuid.UUID) -> Branch | None:
    """Get a branch by ID."""
    return await session.get(Branch, branch_id)


async def get_branch_by_name(session: AsyncSession, name: str) -> Branch | None:
    """Get a branch by name."""
    return (await session.execute(select(Branch).where(Branch.name == name))).scalar_one_or_none()


async def list_branches(session: AsyncSession, active_only: bool = True) -> list[Branch]:
    """List all branches."""
    stmt = select(Branch).order_by(Branch.name)
    if active_only:
        stmt = stmt.where(Branch.is_active == True)
    return list((await session.execute(stmt)).scalars().all())


async def create_branch(
    session: AsyncSession,
    name: str,
    city: str,
    neighborhood: str = "",
    street: str = "",
    street_number: str = "",
    descriptive_location: str = "",
    is_active: bool = True,
) -> Branch:
    """Create a new branch."""
    branch = Branch(
        name=name,
        city=city,
        neighborhood=neighborhood,
        street=street,
        street_number=street_number,
        descriptive_location=descriptive_location,
        is_active=is_active,
    )
    session.add(branch)
    await session.flush()
    return branch


async def update_branch(session: AsyncSession, branch_id: uuid.UUID, data: dict) -> Branch | None:
    """Update a branch."""
    branch = await get_branch(session, branch_id)
    if branch is None:
        return None
    allowed = {"name", "city", "neighborhood", "street", "street_number", "descriptive_location", "is_active"}
    for field_name in allowed:
        if field_name in data and data[field_name] is not None:
            setattr(branch, field_name, data[field_name])
    await session.flush()
    return branch


# ----------------------------------------------------------------- business hours
async def get_business_hours_for_branch(
    session: AsyncSession, branch_id: uuid.UUID | None
) -> list[BusinessHour]:
    """Get business hours for a branch (or global if branch_id is None)."""
    from app.database.models import BusinessHour
    stmt = select(BusinessHour).where(BusinessHour.branch_id == branch_id).order_by(
        BusinessHour.weekday, BusinessHour.interval_order
    )
    return list((await session.execute(stmt)).scalars().all())

