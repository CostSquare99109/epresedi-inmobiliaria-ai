"""Floor offer model: total floors vs. which part of the property is offered.

A property physically has N floors (``floors``). Independently, the listing
offers one of:

- ``full_property``  — "Propiedad completa" (whole building, sale or rent)
- ``single_floor``   — "Piso completo" (exactly one floor, e.g. Piso 1)
- ``multiple_floors`` — "Varios pisos" (one or more specific floors)
- ``partial``        — "Parte de la propiedad" (apartment/annex/room inside,
  described in free text; no individual floor selection)

``offered_floors`` is the normalized list of offered floor numbers (1-based).
All validation lives here so repository, API schemas and search share it.
"""
from __future__ import annotations

FULL_PROPERTY = "full_property"
SINGLE_FLOOR = "single_floor"
MULTIPLE_FLOORS = "multiple_floors"
PARTIAL = "partial"

FLOOR_OFFER_TYPES: tuple[str, ...] = (
    FULL_PROPERTY,
    SINGLE_FLOOR,
    MULTIPLE_FLOORS,
    PARTIAL,
)

FLOOR_OFFER_LABELS: dict[str, str] = {
    FULL_PROPERTY: "Propiedad completa",
    SINGLE_FLOOR: "Piso completo",
    MULTIPLE_FLOORS: "Varios pisos",
    PARTIAL: "Parte de la propiedad",
}

MAX_FLOORS = 99


def normalize_offer_type(value: str | None) -> str:
    """Legacy/empty values default to offering the whole property."""
    v = (value or "").strip()
    return v if v in FLOOR_OFFER_TYPES else FULL_PROPERTY


def normalize_offered_floors(value: object) -> list[int]:
    """Coerce anything list-like into a sorted unique list of ints."""
    if value is None:
        return []
    if isinstance(value, int):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        raise ValueError("Pisos ofertados inválidos: debe ser una lista de números")
    out: list[int] = []
    for item in items:
        try:
            n = int(item)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ValueError(f"Piso ofertado inválido: {item!r} no es un número") from None
        if isinstance(item, bool):
            raise ValueError(f"Piso ofertado inválido: {item!r} no es un número")
        out.append(n)
    return sorted(set(out))


def validate_floor_offer(
    floors: int | None,
    offer_type: str | None,
    offered_floors: object,
) -> tuple[int | None, str, list[int]]:
    """Validate the trio and return normalized ``(floors, offer, offered)``.

    Raises ``ValueError`` with a human (Spanish) message on any impossible state.
    ``floors=None`` (unknown) is allowed for backwards compatibility, except when
    specific floors are offered (then the total is required to bound them).
    """
    offer = normalize_offer_type(offer_type)
    offered = normalize_offered_floors(offered_floors)

    if floors is not None:
        if isinstance(floors, bool) or not isinstance(floors, int):
            try:
                floors = int(floors)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                raise ValueError("Número de pisos inválido: debe ser un entero positivo") from None
        if floors == 0:
            # Legado: registros antiguos usan 0 como "no aplica".
            # Se normaliza a desconocido en escrituras nuevas; las filas
            # existentes con 0 se siguen leyendo sin romperse.
            floors = None
        elif floors < 1 or floors > MAX_FLOORS:
            raise ValueError(f"Número de pisos inválido: debe estar entre 1 y {MAX_FLOORS}")

    for n in offered:
        if n < 1 or n > MAX_FLOORS:
            raise ValueError(f"Piso ofertado inválido: Piso {n} (debe estar entre 1 y {MAX_FLOORS})")

    if offer == FULL_PROPERTY:
        if offered:
            raise ValueError("Propiedad completa no requiere seleccionar pisos individuales")
        return floors, offer, []

    if offer == PARTIAL:
        if offered:
            raise ValueError(
                "Parte de la propiedad no usa selección de pisos: "
                "describe la unidad en la descripción"
            )
        return floors, offer, []

    # single_floor / multiple_floors need a known total to bound the selection.
    if floors is None:
        raise ValueError("Indica el número total de pisos para ofertar pisos específicos")
    too_high = [n for n in offered if n > floors]
    if too_high:
        raise ValueError(
            f"Piso {too_high[0]} no existe: la propiedad tiene {floors} "
            f"{'piso' if floors == 1 else 'pisos'}"
        )
    if offer == SINGLE_FLOOR:
        if len(offered) != 1:
            raise ValueError("Piso completo requiere seleccionar exactamente un piso")
        return floors, offer, offered
    # MULTIPLE_FLOORS
    if len(offered) < 1:
        raise ValueError("Varios pisos requiere seleccionar al menos un piso")
    return floors, offer, offered


def prune_offered_floors(offered: list[int], floors: int | None) -> list[int]:
    """Drop selections above the total (frontend dynamic behaviour, shared)."""
    if floors is None:
        return list(offered)
    return [n for n in offered if 1 <= n <= floors]


def floor_offer_label(offer_type: str | None) -> str:
    return FLOOR_OFFER_LABELS.get(normalize_offer_type(offer_type), "Propiedad completa")


def floors_display(floors: int | None, offer_type: str | None, offered: list[int] | None) -> str:
    """Human display string, e.g. '2 pisos · Piso 1' or '3 pisos · Pisos 1 y 2'."""
    offer = normalize_offer_type(offer_type)
    items = normalize_offered_floors(offered)
    base = f"{floors} {'piso' if floors == 1 else 'pisos'}" if floors else "Pisos sin especificar"
    if offer == FULL_PROPERTY:
        return f"{base} · Propiedad completa"
    if offer == PARTIAL:
        return f"{base} · Parte de la propiedad"
    if offer == SINGLE_FLOOR and len(items) == 1:
        return f"{base} · Piso {items[0]}"
    if items:
        many = "Piso" if len(items) == 1 else "Pisos"
        return f"{base} · {many} {' y '.join(str(n) for n in items)}"
    return f"{base} · {floor_offer_label(offer)}"


def embedding_fragment(floors: int | None, offer_type: str | None, offered: list[int] | None) -> str:
    """Short text fragment so semantic search can tell floor offers apart."""
    offer = normalize_offer_type(offer_type)
    items = normalize_offered_floors(offered)
    parts: list[str] = []
    if floors:
        parts.append(f"{floors} pisos")
    else:
        parts.append("pisos sin especificar")
    if offer == FULL_PROPERTY:
        parts.append("se ofrece la propiedad completa")
    elif offer == PARTIAL:
        parts.append("se ofrece una parte de la propiedad (apartamento, anexo, local o habitación independiente)")
    elif offer == SINGLE_FLOOR and items:
        parts.append(f"se arrienda solamente el piso {items[0]}")
    elif items:
        parts.append(f"se arriendan los pisos {' y '.join(str(n) for n in items)}")
    return " ".join(parts)
