"""Agent tool executor: LLM → Tool → Service → Repository → Database.

run_tool() is the ONLY path from the model to data. Every tool returns a
JSON-safe dict that is appended to the LLM context (compact, no secrets).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid as uuid_mod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.appointments import service as appt_service
from app.core.bizconfig import get_business_timezone
from app.core.logging import get_logger
from app.crm import service as crm_service
from app.database.models import Property
from app.properties import repository as prop_repo
from app.properties.search import SearchFilters, search_properties, similar_properties
from app.rag import retrieval as rag_retrieval

log = get_logger(__name__)


@dataclass
class ToolContext:
    session: AsyncSession
    user_id: int
    conversation_id: uuid_mod.UUID
    state: dict = field(default_factory=dict)
    executed: list[dict] = field(default_factory=list)
    retrieved_property_ids: list[str] = field(default_factory=list)
    retrieved_chunk_ids: list[str] = field(default_factory=list)
    user_text: str = ""
    # Set by the orchestrator when the LLM-first turn failed: deterministic
    # sub-flows must not retry the provider (failsafe, not double failure).
    llm_degraded: bool = False
    # Idempotency keys for executed mutating operations to prevent duplicate execution
    idempotency_keys: dict[str, str] = field(default_factory=dict)
    # Correlación de trazas del runtime (run_id)
    request_id: str = ""


ORDINALS = {"primera": 0, "primero": 0, "1": 0, "1ª": 0, "1a": 0,
            "segunda": 1, "segundo": 1, "2": 1, "2ª": 1, "2a": 1,
            "tercera": 2, "tercero": 2, "3": 2, "3ª": 2, "3a": 2,
            "cuarta": 3, "cuarto": 3, "4": 3, "quinta": 4, "quinto": 4, "5": 4}

# Referencias anafóricas genéricas ("la casa", "esa propiedad", ...): no son
# identificadores literales; se resuelven contra el contexto conversacional
# (última propiedad mostrada) en vez de buscarse como texto.
_GENERIC_PROPERTY_REFS = frozenset({
    "la casa", "esa casa", "esta casa", "una casa", "de la casa",
    "la propiedad", "esa propiedad", "esta propiedad", "una propiedad",
    "la que me mostraste", "la anterior",
    "el inmueble", "ese inmueble", "este inmueble",
    "la ficha", "esa ficha",
})


def _normalize_image_ref(ref: Any) -> Any:
    """Convierte referencias genéricas de fotos en resolución contextual.

    Si el LLM pasa literalmente «la casa» / «esa propiedad» como property_id,
    tratarlo como texto fallaría (no es código ni UUID). Devolver None activa
    la resolución contextual de _find_property (último resultado / foco).
    """
    if ref is None:
        return None
    text = str(ref).strip()
    if not text:
        return None
    low = re.sub(r"\s+", " ", text.lower().strip(" .,:;"))
    if low in _GENERIC_PROPERTY_REFS:
        return None
    return ref

# ------------------------------------------------------------------ contact validation

_REQUIRED_CONTACT_FIELDS = ("name", "phone", "email")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^[\d\s()+.-]{7,}$")
# Fallbacks para el patrón histórico notes="Nombre:...|Celular:...|Email:..."
_EMAIL_FIND_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_NAME_IN_NOTES_RE = re.compile(r"(?:nombre|name)\s*[:\-]\s*([^\n|;]+)", re.IGNORECASE)
_PHONE_IN_NOTES_RE = re.compile(r"(?:celular|telefono|tel[eé]fono|phone|cel)\s*[:\-]\s*([+\d][\d\s().-]{6,}\d)", re.IGNORECASE)


def _extract_contact_from_notes(notes: str) -> dict[str, str]:
    """Extrae contacto del patrón histórico en notes (no inventa: solo parsea)."""
    out: dict[str, str] = {}
    if not notes:
        return out
    m = _EMAIL_FIND_RE.search(notes)
    if m and _EMAIL_RE.match(m.group(0).strip().lower()):
        out["email"] = m.group(0).strip().lower()[:160]
    m = _NAME_IN_NOTES_RE.search(notes)
    if m:
        name = re.sub(r"\s+", " ", m.group(1).strip())
        if len(name) >= 3 and len(name.split()) >= 2:
            out["name"] = name[:160]
    m = _PHONE_IN_NOTES_RE.search(notes)
    if m and _PHONE_RE.match(m.group(1).strip()):
        out["phone"] = m.group(1).strip()[:40]
    return out

# Preferencias que el LLM declaró explícitamente en update_conversation_state
# (campos validados por FIELD_SPECS) → columnas de user_preferences.
# Es el reemplazo de la auto-persistencia ciega eliminada de search_properties:
# solo se guarda lo declarado y validado, nunca lo que una búsqueda exploratoria
# filtró por su cuenta.
_PREFERENCE_FIELDS = {
    "city": "city",
    "property_type": "property_type",
    "operation": "operation",
    "budget_min": "min_price",
    "budget_max": "max_price",
    "bedrooms": "bedrooms",
    "bathrooms": "bathrooms",
    "parking": "parking",
}


def _unsupported_type_request(ctx: ToolContext, extra_text: str = "") -> tuple[str | None, bool]:
    """Detecta si el turno pide un tipo fuera del inventario (finca, lote, ...).

    Devuelve (tipo_no_disponible, tiene_tipo_valido_en_mismo_mensaje).
    Usa la misma fuente que la ruta determinística (detect_unsupported_type) para
    no divergir: si el usuario pidió solo un tipo inexistente, la tool debe
    BLOQUEAR resultados de otro tipo y pedir aclaración primero.
    """
    from app.properties.search import TYPE_RE, _deaccent, detect_unsupported_type

    combined = f"{ctx.user_text or ''} {extra_text or ''}".strip()
    if not combined:
        return None, False
    unsupported = detect_unsupported_type(combined)
    if not unsupported:
        return None, False
    low = _deaccent(combined.lower())
    has_supported = bool(TYPE_RE.search(low))
    return unsupported, has_supported


async def _get_missing_contact_fields(session: AsyncSession, user_id: int) -> list[str]:
    """Returns list of missing required contact fields for the lead."""
    from app.crm import service as crm_service
    lead = await crm_service.get_or_create_lead(session, user_id)
    missing = []
    if not lead.name or not lead.name.strip():
        missing.append("name")
    if not lead.phone or not _PHONE_RE.match(lead.phone.strip()):
        missing.append("phone")
    if not lead.email or not _EMAIL_RE.match(lead.email.strip()):
        missing.append("email")
    return missing


async def _validate_and_update_contact(
    session: AsyncSession, user_id: int, data: dict
) -> tuple[bool, list[str]]:
    """Validates and updates contact fields. Returns (all_present, missing_fields)."""
    from app.crm import service as crm_service

    # Get current lead to check existing fields
    lead = await crm_service.get_or_create_lead(session, user_id)

    # Fallback: el patrón histórico empaquetaba contacto en notes
    # ("Nombre:...|Celular:...|Email:..."). Si faltan top-level, parsear notes.
    notes_fallback = _extract_contact_from_notes(str(data.get("notes") or ""))

    # Update any provided fields
    update_data = {}
    name_raw = data.get("name") or notes_fallback.get("name")
    if name_raw:
        name = str(name_raw).strip()
        if len(name) >= 3 and len(name.split()) >= 2:
            update_data["name"] = name[:160]
    elif lead.name and lead.name.strip():
        update_data["name"] = lead.name.strip()

    phone_raw = data.get("phone") or notes_fallback.get("phone")
    if phone_raw:
        phone = str(phone_raw).strip()
        if _PHONE_RE.match(phone):
            update_data["phone"] = phone[:40]
    elif lead.phone and lead.phone.strip():
        update_data["phone"] = lead.phone.strip()

    email_raw = data.get("email") or notes_fallback.get("email")
    if email_raw:
        email = str(email_raw).strip().lower()
        if _EMAIL_RE.match(email):
            update_data["email"] = email[:160]
    elif lead.email and lead.email.strip():
        update_data["email"] = lead.email.strip()
    
    if update_data:
        await crm_service.update_lead(session, lead.id, update_data)
        # Refresh lead to get updated values
        lead = await crm_service.get_or_create_lead(session, user_id)
    
    # Check for missing required fields
    missing = []
    if not lead.name or not lead.name.strip():
        missing.append("name")
    if not lead.phone or not _PHONE_RE.match(lead.phone.strip()):
        missing.append("phone")
    if not lead.email or not _EMAIL_RE.match(lead.email.strip()):
        missing.append("email")
    
    return len(missing) == 0, missing


def _format_missing_fields(missing: list[str]) -> str:
    """Formats missing fields for user-friendly message."""
    labels = {"name": "nombre completo", "phone": "teléfono", "email": "correo electrónico"}
    return ", ".join(labels.get(f, f) for f in missing)


async def _find_property(session: AsyncSession, ctx: ToolContext, ref: Any) -> Property | None:
    """Resolve id/code/ordinal/reference. Deterministic, conversation-aware.

    Resolution order when no explicit ref is given:
    1. the single property in context
    2. a strict title match on the user's words ("la casa familiar")
    3. the property the user last looked at ("¿tiene piscina?")
    Ambiguity returns None — the agent asks instead of guessing.
    """
    last = ctx.state.get("last_results") or []
    if not ref:
        if len(last) == 1:
            return await prop_repo.get_property(session, last[0]["id"])
        by_text = await prop_repo.find_property_by_text(session, ctx.user_text)
        if by_text is not None:
            return by_text
        focused = ctx.state.get("last_property_id")
        if focused:
            prop = await prop_repo.get_property(session, focused)
            if prop is not None:
                return prop
        return None
    ref = str(ref).strip()
    low = ref.lower()
    # El modelo puede pasar "la primera"/"opción 2": normaliza el artículo antes
    # de resolver el ordinal.
    ordinal_key = re.sub(
        r"^(?:la|el|los|las|esa|ese|esas|esos|opci[oó]n|n[uú]mero)\s+", "", low
    ).strip()
    if ordinal_key in ORDINALS:
        idx = ORDINALS[ordinal_key]
        if len(last) > idx:
            return await prop_repo.get_property(session, last[idx]["id"])
        return None
    try:
        prop = await prop_repo.get_property(session, uuid_mod.UUID(ref))
    except ValueError:
        prop = None
    if prop is None:
        prop = await prop_repo.get_property_by_code(session, ref)
    # Try numeric shorthand: "8" -> "PROP-0008"
    if prop is None and ref.isdigit():
        for fmt in (f"PROP-{int(ref):04d}", f"PROP-{int(ref):03d}", f"PROP-{int(ref)}"):
            prop = await prop_repo.get_property_by_code(session, fmt)
            if prop is not None:
                break
    if prop is None and last:
        for item in last:
            if ref.lower() in (item.get("code", "").lower(), item.get("title", "").lower()):
                prop = await prop_repo.get_property(session, item["id"])
                break
    return prop


async def _validate_real_slot(
    session: AsyncSession, property_id, when: dt.datetime
) -> dict[str, Any] | None:
    """Anti-alucinación de agenda: solo se puede agendar un slot REAL.

    Compara `when` contra los slots disponibles reales (horario laboral, sin
    citas ocupadas, ≥2h de anticipación). Devuelve None si coincide exactamente
    con un slot disponible; si no, devuelve un envelope de error estructurado
    con `nearest_slots` y `slots` para que el agente re-decida con evidencia.
    
    Diferencia tres casos:
    A. Horario permitido y disponible → None (OK)
    B. Horario NO permitido (fuera de horario comercial o domingo) → error con reason="business_hours"
    C. Horario permitido pero ocupado → error con reason="booked" + nearest_slots
    """
    # First check business hours (category B)
    from app.core.bizconfig import is_within_business_hours
    when_utc = when
    if when_utc.tzinfo is None:
        from app.appointments.service import _business_timezone
        tz = await _business_timezone()
        when_utc = when_utc.replace(tzinfo=tz).astimezone(dt.UTC)
    
    is_within, reason = await is_within_business_hours(when_utc)
    if not is_within:
        # Category B: outside business hours
        return {
            "ok": False,
            "error": reason,
            "reason": "business_hours",
            "nearest_slots": [],
            "nearest_slots_count": 0,
            "nearest_slots_omitted": 0,
            "slots": [],
            "available_slots_count": 0,
            "slots_omitted": 0,
        }
    
    # Category A or C: within business hours, check availability
    validation = await appt_service.list_available_slots(
        session, property_id, requested_datetime=when
    )
    if isinstance(validation, dict) and validation.get("exact_match"):
        return None
    slots = validation.get("available_slots", []) if isinstance(validation, dict) else []
    nearest = validation.get("nearest_slots", []) if isinstance(validation, dict) else []
    # Cap evidencia para garantizar que el envelope de error quepa íntegro en
    # el contexto (LLM_TOOL_RESULT_MAX_CHARS); si se excede, el runtime
    # descarta TODO el data y el agente no puede re-decidir con evidencia.
    _MAX_SHOWN = 8
    total = len(slots)
    extras = len(nearest)
    return {
        "ok": False,
        "error": (
            "Ese horario está dentro del horario de atención pero no está disponible "
            "(ya reservado o no cumple anticipación mínima). Ofrece uno de "
            "los horarios reales de 'nearest_slots' o 'slots'."
        ),
        "reason": "booked",
        "nearest_slots": nearest[:_MAX_SHOWN],
        "nearest_slots_count": extras,
        "nearest_slots_omitted": max(0, extras - _MAX_SHOWN),
        "slots": slots[:_MAX_SHOWN],
        "available_slots_count": total,
        "slots_omitted": max(0, total - _MAX_SHOWN),
    }


_COUNT_KEYS = ("properties", "chunks", "slots", "images", "saved_searches", "appointments")


def _compact_data(data: dict, serialized: str, max_chars: int) -> dict:
    """Reduce los campos más grandes (listas primero) hasta caber en max_chars.

    Conserva SIEMPRE evidencia real: recorta listas por el final (los primeros
    elementos son los más relevantes en búsquedas/rankings) y marca cuántos
    elementos se omitieron, para que el modelo sepa que hay más.
    """
    budget = max_chars - (len(serialized) - len(json.dumps(data, ensure_ascii=False, default=str)))
    compact = {k: (list(v) if isinstance(v, list) else v) for k, v in data.items()}
    # 1) recortar listas más largas primero, iterativamente
    while True:
        payload = json.dumps(compact, ensure_ascii=False, default=str)
        if len(payload) <= budget:
            return compact
        list_sizes = [
            (k, len(json.dumps(v, ensure_ascii=False, default=str)))
            for k, v in compact.items() if isinstance(v, list) and len(v) > 1
        ]
        if not list_sizes:
            break
        list_sizes.sort(key=lambda kv: -kv[1])
        key, _ = list_sizes[0]
        keep = max(1, len(compact[key]) - 1)
        compact[f"_{key}_omitted"] = len(compact[key]) - keep
        compact[key] = compact[key][:keep]
    # 2) strings largos
    for key, value in list(compact.items()):
        if isinstance(value, str) and len(value) > 400:
            compact[key] = value[:400] + "…"
        payload = json.dumps(compact, ensure_ascii=False, default=str)
        if len(payload) <= budget:
            return compact
    # 3) último recurso: strings a 120
    for key, value in list(compact.items()):
        if isinstance(value, str) and len(value) > 120:
            compact[key] = value[:120] + "…"
    return compact


def tool_envelope(name: str, result: dict[str, Any], *, max_chars: int = 4000) -> dict[str, Any]:
    """Normalizes a tool result into the structured envelope the LLM consumes.

    ``{tool, ok, data, metadata}`` or ``{tool, ok: false, error: {code, message}}``.
    Compact and JSON-safe so the model always understands what actually happened.
    Los resultados grandes se recortan (nunca se cortan a mitad de JSON): el
    envelope final siempre es JSON válido y conserva conteos reales.

    En fallos con evidencia estructurada (p.ej. slots reales al rechazar un
    horario inventado) el ``data`` viaja igual: un error nunca debe dejar al
    agente sin los datos para re-decidir.
    """
    ok = bool(result.get("ok", True))
    envelope: dict[str, Any] = {"tool": name, "ok": ok}
    if ok:
        data = {k: v for k, v in result.items() if k not in ("ok", "error")}
        envelope["data"] = data
        metadata: dict[str, Any] = {}
        if isinstance(data.get("count"), int):
            metadata["count"] = data["count"]
        else:
            for key in _COUNT_KEYS:
                value = data.get(key)
                if isinstance(value, list):
                    metadata["count"] = len(value)
                    break
        if name == "search_properties":
            metadata["note"] = "si count=0, informa al usuario y pregunta si quiere ajustar criterios; NO repitas búsqueda sin confirmación"
        if name == "list_available_slots":
            slots_data = data.get("slots_data", {})
            if slots_data.get("exact_match") or slots_data.get("is_available"):
                exact_local = slots_data.get("exact_slot_local") or slots_data.get("exact_slot", {}).get("datetime_local")
                metadata["note"] = f"DISPONIBLE: el horario solicitado SÍ está disponible (is_available=true). exact_slot_local = {exact_local}. Confirma disponibilidad al usuario y agenda si el usuario quiere."
            elif slots_data.get("nearest_slots"):
                metadata["note"] = f"NO exact_match. nearest_slots tiene {len(slots_data.get('nearest_slots', []))} alternativas cercanas. Ofrece al usuario."
        if name == "schedule_visit":
            appt = data.get("appointment")
            if appt:
                status = appt.get("status", "REQUESTED")
                metadata["note"] = (
                    f"Cita creada con estado: {status}. "
                    + ("ESTADO = REQUESTED (pendiente de confirmación del asesor). "
                       "NO digas 'confirmada' ni 'queda todo confirmado'. "
                       "Di: 'Tu solicitud de cita quedó registrada (pendiente de confirmación del asesor)'."
                       if status == "REQUESTED"
                       else "Estado confirmado por el asesor.")
                )
        if metadata:
            envelope["metadata"] = metadata
    else:
        extra = {k: v for k, v in result.items() if k not in ("ok", "error", "code", "retryable")}
        if extra:
            envelope["data"] = extra
        envelope["error"] = {
            "code": str(result.get("code") or "TOOL_ERROR"),
            "message": str(result.get("error") or "operación no completada"),
            "retryable": bool(result.get("retryable", True)),
        }
    serialized = json.dumps(envelope, ensure_ascii=False, default=str)
    if len(serialized) <= max_chars:
        return envelope
    # Compacción: preservar metadata real + primeras evidencias, JSON válido.
    compacted = dict(envelope)
    compacted["data"] = _compact_data(envelope.get("data") or {}, serialized, max_chars)
    if len(json.dumps(compacted, ensure_ascii=False, default=str)) <= max_chars:
        return compacted
    compacted.pop("data", None)
    compacted["data_omitted"] = True
    compacted["note"] = "resultado demasiado grande; usa metadata y refina la consulta"
    return compacted


async def run_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Executes a tool against services. Returns a JSON-safe dict for the LLM."""
    session = ctx.session
    result: dict[str, Any] = {"ok": True}

    if name == "search_properties":
        raw = args.get("filters") or {}
        semantic = (args.get("semantic_query") or "").strip()
        # Guard LLM-first para tipo no disponible: si el usuario pidió en ESTE
        # turno un tipo fuera del inventario (finca, lote, bodega, local, ...)
        # sin mencionar casa/apartamento, NO se consulta el inventario ni se
        # devuelven propiedades de otro tipo. Se devuelve aclaración primero.
        _unsupported, _has_supported = _unsupported_type_request(ctx, semantic)
        if _unsupported and not _has_supported:
            ctx.state["last_results"] = []
            ctx.state["last_filters"] = {
                "unsupported_type": _unsupported, "tipo_no_disponible": _unsupported,
            }
            ctx.state["awaiting_search_refinement"] = True
            ctx.state["last_search_had_results"] = False
            log.info("search_blocked_tipo_no_disponible unsupported=%s user=%s", _unsupported, ctx.user_id)
            result["count"] = 0
            result["properties"] = []
            result["exact_match"] = False
            result["closest_properties"] = []
            result["tipo_no_disponible"] = _unsupported
            result["clarify"] = True
            result["message"] = (
                f"El tipo '{_unsupported}' no está disponible actualmente en el inventario "
                f"(solo hay casas y apartamentos). NO muestres fichas de otro tipo como si "
                f"calzaran: informa que no hay '{_unsupported}' y pregunta si quiere ver "
                f"alternativas o que le avisemos cuando haya disponibilidad."
            )
        else:
            filters = SearchFilters()
            if raw.get("property_type"): filters.property_type = raw["property_type"]
            if raw.get("unsupported_type"): filters.unsupported_type = raw["unsupported_type"]
            # Si el usuario mencionó ambos (ej. "casa o finca"), se conserva el
            # aviso para que el agente aclare la parte no disponible.
            if _unsupported and _has_supported:
                filters.unsupported_type = filters.unsupported_type or _unsupported
                result["tipo_no_disponible"] = _unsupported
                result["tipo_no_disponible_note"] = (
                    f"El usuario también pidió '{_unsupported}', que no está disponible. "
                    f"Si muestras resultados del tipo válido, aclara primero que "
                    f"'{_unsupported}' no hay y que lo que sigue es solo la parte válida."
                )
            if raw.get("operation"): filters.operation = raw["operation"]
            if raw.get("city"): filters.city = raw["city"]
            if raw.get("min_price") is not None: filters.min_price = float(raw["min_price"])
            if raw.get("max_price") is not None: filters.max_price = float(raw["max_price"])
            if raw.get("bedrooms") is not None: filters.bedrooms = int(raw["bedrooms"])
            if raw.get("bathrooms") is not None: filters.bathrooms = int(raw["bathrooms"])
            if raw.get("parking") is not None: filters.parking = int(raw["parking"])
            if raw.get("floors") is not None: filters.floors = int(raw["floors"])
            if raw.get("offered_floor") is not None: filters.offered_floor = int(raw["offered_floor"])
            if raw.get("floor_offer_type") in ("full_property", "single_floor", "multiple_floors", "partial"):
                filters.floor_offer_type = raw["floor_offer_type"]
            if raw.get("min_area") is not None: filters.min_area = float(raw["min_area"])
            if semantic and not filters.query_text:
                filters.query_text = semantic
            hits = await search_properties(session, filters, semantic)

            props = await prop_repo.get_properties(session, [h.property_id for h in hits], limit=max(len(hits), 1))
            ordered = {str(p.id): p.to_dict() for p in props}
            items = [ordered[h.property_id] for h in hits if h.property_id in ordered]
            ctx.state["last_results"] = items
            ctx.state["last_filters"] = filters.to_dict()

            closest_items: list[dict] = []
            if not items and (filters.max_price or filters.min_price or filters.bedrooms or filters.bathrooms):
                # Sin resultados exactos: el CÓDIGO (nunca el LLM) busca reales las
                # 5 propiedades más cercanas por precio/habitaciones/baños, manteniendo
                # ciudad/operación/tipo como filtros duros. Se devuelven AMBOS resultados:
                # el exacto (vacío) y las alternativas reales más parecidas.
                from app.properties.search import find_closest_properties
                closest_ids = await find_closest_properties(session, filters, limit=5)
                if closest_ids:
                    closest_props = await prop_repo.get_properties(session, closest_ids, limit=len(closest_ids))
                    closest_by_id = {str(p.id): p.to_dict() for p in closest_props}
                    closest_items = [closest_by_id[cid] for cid in closest_ids if cid in closest_by_id]

            if not items:
                ctx.state["awaiting_search_refinement"] = True
                ctx.state["last_search_had_results"] = False
            else:
                ctx.state["awaiting_search_refinement"] = False
                ctx.state["last_search_had_results"] = True
            ctx.retrieved_property_ids.extend(str(p["id"]) for p in items)
            result["count"] = len(items)
            result["properties"] = items
            if closest_items:
                ctx.retrieved_property_ids.extend(str(p["id"]) for p in closest_items)
                result["exact_match"] = False
                result["closest_properties"] = closest_items
                result["closest_note"] = (
                    "No hay resultados EXACTOS para lo que pidió el usuario (ver filtros aplicados). "
                    "`closest_properties` son propiedades REALES del inventario, las más parecidas por "
                    "precio/habitaciones/baños, en la misma ciudad/tipo/operación pedidos. Preséntaselas "
                    "como alternativas cercanas dejando CLARO que no cumplen exactamente lo solicitado — "
                    "nunca las presentes como si fueran un match exacto. Menciona en qué se diferencian "
                    "(precio más alto, menos habitaciones, etc.) usando los datos reales de cada una."
                )
            elif not items:
                result["exact_match"] = False
                result["closest_properties"] = []
            # NOTA: ya no se persisten preferencias automáticamente en cada búsqueda.
            # Los filtros de una búsqueda pueden ser exploratorios o (antes del fix de
            # alucinaciones) inventados por el LLM; guardarlos ciegamente como "preferencia
            # confirmada del cliente" contaminaba el perfil permanentemente entre conversaciones.
            # Las preferencias reales se registran vía update_conversation_state, donde el LLM
            # las declara explícitamente y bajo la regla de no inventar datos.

    elif name == "get_property":
        _unsupported_gp, _has_supported_gp = _unsupported_type_request(ctx)
        if _unsupported_gp and not _has_supported_gp:
            result = {
                "ok": False, "retryable": False,
                "code": "TIPO_NO_DISPONIBLE",
                "tipo_no_disponible": _unsupported_gp,
                "error": (
                    f"El tipo '{_unsupported_gp}' no está disponible actualmente en el inventario "
                    f"(solo hay casas y apartamentos). NO muestres la ficha de otra propiedad "
                    f"como si fuera '{_unsupported_gp}': informa que no hay disponibilidad y "
                    f"pregunta si quiere ver alternativas o que le avisemos cuando haya."
                ),
            }
        else:
            prop = await _find_property(session, ctx, args.get("property_ref"))
            if prop is None:
                result = {"ok": False, "error": "Propiedad no encontrada o referencia ambigua."}
            else:
                result["property"] = prop.to_dict()
                ctx.retrieved_property_ids.append(str(prop.id))
                ctx.state["last_property_id"] = str(prop.id)
                ctx.state["last_property_code"] = prop.code

    elif name == "compare_properties":
        _unsupported_cp, _has_supported_cp = _unsupported_type_request(ctx)
        if _unsupported_cp and not _has_supported_cp:
            result = {
                "ok": False, "retryable": False,
                "code": "TIPO_NO_DISPONIBLE",
                "tipo_no_disponible": _unsupported_cp,
                "error": (
                    f"El tipo '{_unsupported_cp}' no está disponible actualmente. "
                    f"No compares ni muestres propiedades de otro tipo como si calzaran: "
                    f"aclara primero si quiere ver alternativas."
                ),
            }
        else:
            refs = args.get("property_refs") or []
            props: list[dict] = []
            seen: set[str] = set()
            for ref in refs:
                p = await _find_property(session, ctx, ref)
                if p is not None and str(p.id) not in seen:
                    props.append(p.to_dict())
                    seen.add(str(p.id))
            if len(props) < 2:  # contextual comparison from last results
                for item in (ctx.state.get("last_results") or []):
                    if item["id"] not in seen:
                        props.append(item)
                        seen.add(item["id"])
                    if len(props) >= 4:
                        break
            result["properties"] = props
            result["count"] = len(props)
            ctx.retrieved_property_ids.extend(p["id"] for p in props)

    elif name == "search_documents":
        # El agente puede pasar código/ordinal/ref contextual: se resuelve igual
        # que en get_property. Si no resuelve, error estructurado (no crash SQL).
        pid = None
        ref = args.get("property_id")
        if ref:
            prop = await _find_property(session, ctx, ref)
            if prop is not None:
                pid = prop.id
            else:
                result = {
                    "ok": False, "retryable": False,
                    "error": "Propiedad no encontrada o referencia ambigua para filtrar documentos.",
                }
        if result.get("ok", True):
            chunks = await rag_retrieval.retrieve_chunks(session, args.get("query") or "", k=5,
                                                         property_id=pid)
            ctx.retrieved_chunk_ids.extend(str(c.chunk_id) for c in chunks)
            result["chunks"] = [
                {"chunk_id": str(c.chunk_id), "document_id": str(c.document_id),
                 "title": c.document_title, "filename": c.filename, "page": c.page,
                 "section": c.section, "score": c.score, "content": c.content[:1200]}
                for c in chunks
            ]

    elif name == "get_property_images":
        _unsupported_img, _has_supported_img = _unsupported_type_request(ctx)
        if _unsupported_img and not _has_supported_img:
            result = {
                "ok": False, "retryable": False,
                "code": "TIPO_NO_DISPONIBLE",
                "tipo_no_disponible": _unsupported_img,
                "reason": "tipo_no_disponible",
                "error": (
                    f"El tipo '{_unsupported_img}' no está disponible actualmente. "
                    f"No muestres fotos de otro tipo como si fueran '{_unsupported_img}': "
                    f"aclara primero si quiere ver alternativas."
                ),
            }
        else:
            prop = await _find_property(session, ctx, _normalize_image_ref(args.get("property_id")))
            if prop is None:
                result = {
                    "ok": False, "retryable": False,
                    "code": "PROPERTY_NOT_FOUND",
                    "error": "Propiedad no encontrada o referencia ambigua. Pide al usuario que precise cuál propiedad.",
                    "reason": "property_not_found",
                }
            else:
                group = args.get("group")
                extra_name = args.get("extra_name")
                try:
                    images = await prop_repo.get_property_images(
                        session, prop.id, group=group, extra_name=extra_name,
                    )
                except ValueError as e:
                    result = {
                        "ok": False, "retryable": False,
                        "code": "INVALID_GROUP",
                        "error": str(e),
                        "reason": "invalid_group",
                    }
                    images = None
                if images is None:
                    pass
                else:
                    limit = args.get("limit")
                    if isinstance(limit, int) and limit > 0:
                        images = images[: min(limit, 10)]
                    log.info(
                        "property_image_request property_id=%s code=%s db_count=%s limit=%s group=%s",
                        prop.id, prop.code, len(images), limit, group,
                    )
                    if not images:
                        if group:
                            result = {
                                "ok": False, "retryable": False,
                                "code": "NO_IMAGES",
                                "error": (
                                    f"Esta propiedad no tiene fotografías de "
                                    f"'{extra_name or group}' disponibles."
                                ),
                                "reason": "no_image",
                                "property_id": str(prop.id),
                                "property_code": prop.code,
                                "group": group,
                            }
                        else:
                            result = {
                                "ok": False, "retryable": False,
                                "code": "NO_IMAGES",
                                "error": "En este momento esta propiedad no tiene fotografías disponibles.",
                                "reason": "no_image",
                                "property_id": str(prop.id),
                                "property_code": prop.code,
                            }
                    else:
                        result["images"] = [img.to_dict() for img in images]
                        result["count"] = len(images)
                        result["property_id"] = str(prop.id)
                        result["property_code"] = prop.code
                        # Resumen por característica para que el LLM elija bien.
                        by_group: dict[str, int] = {}
                        for img in images:
                            g = img.group or "general"
                            key = f"extra:{img.extra_name}" if g == "extra" and img.extra_name else g
                            by_group[key] = by_group.get(key, 0) + 1
                        result["groups"] = by_group

    elif name == "get_branch_info":
        prop = await _find_property(session, ctx, args.get("property_id"))
        if prop is None:
            result = {
                "ok": False, "retryable": False,
                "error": "Propiedad no encontrada o referencia ambigua.",
            }
        elif prop.branch is None:
            result = {
                "ok": False, "retryable": False,
                "error": "Esta propiedad no tiene sede asignada.",
            }
        else:
            result["branch"] = prop.branch.to_dict()

    elif name == "get_business_hours":
        # Can be called with property_id (gets branch hours) or branch_id directly
        branch_id = None
        if args.get("property_id"):
            prop = await _find_property(session, ctx, args.get("property_id"))
            if prop is None:
                result = {"ok": False, "error": "Propiedad no encontrada."}
            else:
                branch_id = prop.branch_id
        elif args.get("branch_id"):
            try:
                branch_id = uuid_mod.UUID(str(args.get("branch_id")))
            except ValueError:
                result = {"ok": False, "error": "branch_id inválido."}

        if result.get("ok", True):
            if branch_id is None:
                # Global hours
                from app.core.bizconfig import get_appointment_hours_by_weekday
                hours_map = await get_appointment_hours_by_weekday()
                tz = await get_business_timezone()
                result["timezone"] = tz
                result["hours"] = {}
                day_names = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
                for day_num, hours in hours_map.items():
                    if hours:
                        result["hours"][day_names[day_num]] = {
                            "open": f"{hours[0]:02d}:00",
                            "close": f"{hours[-1]+1:02d}:00",
                            "slots": [f"{h:02d}:00" for h in hours],
                        }
                    else:
                        result["hours"][day_names[day_num]] = {"closed": True}
            else:
                # Branch-specific hours from DB
                hours = await prop_repo.get_business_hours_for_branch(session, branch_id)
                if not hours:
                    # Fallback to global
                    from app.core.bizconfig import get_appointment_hours_by_weekday
                    hours_map = await get_appointment_hours_by_weekday()
                    tz = await get_business_timezone()
                    result["timezone"] = tz
                    result["hours"] = {}
                    day_names = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
                    for day_num, h_list in hours_map.items():
                        if h_list:
                            result["hours"][day_names[day_num]] = {
                                "open": f"{h_list[0]:02d}:00",
                                "close": f"{h_list[-1]+1:02d}:00",
                                "slots": [f"{h:02d}:00" for h in h_list],
                            }
                        else:
                            result["hours"][day_names[day_num]] = {"closed": True}
                else:
                    tz = await get_business_timezone()
                    result["timezone"] = tz
                    result["hours"] = {}
                    day_names = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
                    for day_num in range(7):
                        day_hours = [h for h in hours if h.weekday == day_num]
                        if day_hours:
                            intervals = []
                            for h in day_hours:
                                if h.is_closed:
                                    intervals.append({"closed": True})
                                else:
                                    intervals.append({
                                        "open": h.open_time.strftime("%H:%M") if h.open_time else None,
                                        "close": h.close_time.strftime("%H:%M") if h.close_time else None,
                                    })
                            result["hours"][day_names[day_num]] = {"intervals": intervals}
                        else:
                            result["hours"][day_names[day_num]] = {"closed": True}

    elif name == "list_branches":
        active_only = args.get("active_only", True)
        branches = await prop_repo.list_branches(session, active_only=active_only)
        result["branches"] = [b.to_dict() for b in branches]
        result["count"] = len(branches)

    elif name == "save_property":
        prop = await _find_property(session, ctx, args.get("property_id"))
        if prop is None:
            result = {"ok": False, "error": "Propiedad no encontrada."}
        else:
            result["saved"] = await crm_service.add_favorite(session, ctx.user_id, prop.id)
            result["property"] = prop.to_dict()

    elif name == "remove_saved_property":
        prop = await _find_property(session, ctx, args.get("property_id"))
        if prop is None:
            result = {"ok": False, "error": "Propiedad no encontrada."}
        else:
            result["removed"] = await crm_service.remove_favorite(session, ctx.user_id, prop.id)

    elif name == "save_search":
        filt = dict(args.get("filters") or ctx.state.get("last_filters") or {})
        ss = await crm_service.save_search(session, ctx.user_id, args.get("name") or "Búsqueda guardada", filt)
        result["saved_search"] = {"id": str(ss.id), "name": ss.name, "filters": ss.filters}

    elif name == "list_saved_searches":
        sses = await crm_service.list_saved_searches(session, ctx.user_id)
        result["saved_searches"] = [{"id": str(s.id), "name": s.name, "filters": s.filters} for s in sses]

    elif name == "list_favorites":
        favs = await crm_service.list_favorites(session, ctx.user_id)
        result["favorites"] = [f.to_dict() for f in favs]
        result["count"] = len(favs)

    elif name == "create_alert":
        # Create a new property alert with full Telegram context
        telegram_user_id = ctx.state.get("telegram_user_id", ctx.user_id)
        telegram_chat_id = ctx.state.get("telegram_chat_id", ctx.user_id)
        user_name = ctx.state.get("user_name", "Usuario")

        name = args.get("name") or "Alerta de propiedades"
        filters = dict(args.get("filters") or ctx.state.get("last_filters") or {})
        frequency_hours = max(1, min(168, int(args.get("frequency_hours") or 1)))

        alert = await crm_service.create_alert(
            session,
            ctx.user_id,
            telegram_user_id,
            telegram_chat_id,
            user_name,
            name,
            filters,
            frequency_hours,
        )
        result["alert"] = {
            "id": str(alert.id),
            "name": alert.name,
            "filters": alert.filters,
            "status": alert.status.value,
            "frequency_hours": alert.frequency_hours,
        }

    elif name == "list_alerts":
        status = args.get("status")
        alerts = await crm_service.list_alerts(session, ctx.user_id, status)
        result["alerts"] = [
            {
                "id": str(a.id),
                "name": a.name,
                "filters": a.filters,
                "status": a.status.value,
                "frequency_hours": a.frequency_hours,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "last_checked_at": a.last_checked_at.isoformat() if a.last_checked_at else None,
            }
            for a in alerts
        ]

    elif name == "get_alert":
        alert_id = uuid_mod.UUID(str(args.get("alert_id")))
        alert = await crm_service.get_alert(session, ctx.user_id, alert_id)
        if alert is None:
            result = {"ok": False, "error": "Alerta no encontrada."}
        else:
            result["alert"] = {
                "id": str(alert.id),
                "name": alert.name,
                "filters": alert.filters,
                "status": alert.status.value,
                "frequency_hours": alert.frequency_hours,
                "created_at": alert.created_at.isoformat() if alert.created_at else None,
                "last_checked_at": alert.last_checked_at.isoformat() if alert.last_checked_at else None,
            }

    elif name == "update_alert":
        alert_id = uuid_mod.UUID(str(args.get("alert_id")))
        data = {k: v for k, v in args.items() if k != "alert_id"}
        alert = await crm_service.update_alert(session, ctx.user_id, alert_id, data)
        if alert is None:
            result = {"ok": False, "error": "Alerta no encontrada."}
        else:
            result["alert"] = {
                "id": str(alert.id),
                "name": alert.name,
                "filters": alert.filters,
                "status": alert.status.value,
                "frequency_hours": alert.frequency_hours,
            }

    elif name == "pause_alert":
        alert_id = uuid_mod.UUID(str(args.get("alert_id")))
        ok = await crm_service.pause_alert(session, ctx.user_id, alert_id)
        result["paused"] = ok
        if not ok:
            result["error"] = "Alerta no encontrada."

    elif name == "resume_alert":
        alert_id = uuid_mod.UUID(str(args.get("alert_id")))
        ok = await crm_service.resume_alert(session, ctx.user_id, alert_id)
        result["resumed"] = ok
        if not ok:
            result["error"] = "Alerta no encontrada."

    elif name == "delete_alert":
        alert_id = uuid_mod.UUID(str(args.get("alert_id")))
        ok = await crm_service.delete_alert(session, ctx.user_id, alert_id)
        result["deleted"] = ok
        if not ok:
            result["error"] = "Alerta no encontrada."

    elif name == "get_notification_history":
        alert_id = None
        if args.get("alert_id"):
            alert_id = uuid_mod.UUID(str(args.get("alert_id")))
        limit = int(args.get("limit") or 50)
        history = await crm_service.get_notification_history(session, ctx.user_id, alert_id, limit)
        result["notifications"] = [
            {
                "id": str(h.id),
                "alert_id": str(h.saved_search_id),
                "property_id": str(h.property_id),
                "channel": h.channel,
                "status": h.status,
                "sent_at": h.sent_at.isoformat() if h.sent_at else None,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in history
        ]

    elif name == "create_lead":
        lead = await crm_service.get_or_create_lead(session, ctx.user_id)
        data = {k: v for k, v in args.items() if k in ("name", "phone", "email", "budget", "status", "notes")}
        await crm_service.update_lead(session, lead.id, data)
        result["lead"] = await crm_service.get_customer_profile(session, ctx.user_id)

    elif name == "get_customer_profile":
        result["profile"] = await crm_service.get_customer_profile(session, ctx.user_id)

    elif name == "list_available_slots":
        prop = await _find_property(session, ctx, args.get("property_id"))
        if prop is None:
            result = {"ok": False, "error": "Propiedad no encontrada."}
        else:
            requested_datetime = None
            if args.get("requested_datetime"):
                try:
                    requested_datetime = dt.datetime.fromisoformat(str(args.get("requested_datetime")))
                except ValueError:
                    pass
            window_hours = int(args.get("window_hours") or 2)
            slots_result = await appt_service.list_available_slots(
                session, prop.id, requested_datetime=requested_datetime, window_hours=window_hours
            )
            if isinstance(slots_result, list):
                result["slots"] = slots_result  # backward compat
                # No slots_data when no requested_datetime (test expectation)
            else:
                available_slots = slots_result.get("available_slots", [])
                result["slots"] = available_slots[:20]  # backward compat
                if requested_datetime is not None:
                    exact_match = slots_result.get("exact_match", False)
                    exact_slot = slots_result.get("exact_slot")
                    # Put availability at top level for LLM visibility
                    result["available"] = exact_match
                    result["slot_local"] = exact_slot.get("datetime_local") if exact_slot else None
                    result["summary"] = (
                        f"EL HORARIO SOLICITADO {'SÍ' if exact_match else 'NO'} ESTÁ DISPONIBLE. "
                        f"Slot local: {exact_slot.get('datetime_local') if exact_slot else 'N/A'}. "
                        f"Alternativas cercanas: {len(slots_result.get('nearest_slots', []))}. "
                        f"Total slots libres: {len(available_slots)}."
                    )
                    result["slots_data"] = {
                        "requested_datetime": slots_result.get("requested_datetime"),
                        "exact_match": exact_match,
                        "is_available": exact_match,
                        "exact_slot": exact_slot,
                        "exact_slot_local": exact_slot.get("datetime_local") if exact_slot else None,
                        "nearest_slots": slots_result.get("nearest_slots", []),
                        "available_slots_count": len(available_slots),
                    }
                # When no requested_datetime, don't include slots_data (test expectation)

    elif name == "schedule_visit":
        prop = await _find_property(session, ctx, args.get("property_id"))
        if prop is None:
            result = {"ok": False, "error": "Propiedad no encontrada."}
        else:
            try:
                when = dt.datetime.fromisoformat(str(args.get("datetime_iso") or ""))
            except ValueError:
                result = {"ok": False, "error": "datetime_iso inválido.",
                          "slots": await appt_service.list_available_slots(session, prop.id, requested_datetime=None, window_hours=2)}
            else:
                invalid_slot = await _validate_real_slot(session, prop.id, when)
                if invalid_slot is not None:
                    result = invalid_slot
                else:
                    # Validate required contact info before scheduling
                    has_all, missing = await _validate_and_update_contact(session, ctx.user_id, args)
                    if not has_all:
                        result = {
                            "ok": False,
                            "error": f"Faltan datos de contacto para agendar: {_format_missing_fields(missing)}.",
                            "missing_fields": missing,
                            "code": "MISSING_CONTACT_INFO",
                        }
                    else:
                        lead = await crm_service.get_or_create_lead(session, ctx.user_id)
                        try:
                            appt = await appt_service.create_appointment(
                                session, property_id=prop.id, lead_id=lead.id,
                                scheduled_at=when, notes=str(args.get("notes") or ""),
                            )
                            await crm_service.set_lead_status_from_appointment(session, lead.id)
                            ctx.state["last_appointment_id"] = str(appt.id)
                            result["appointment"] = {
                                "id": str(appt.id), "property": prop.title, "code": prop.code,
                                "scheduled_at": appt.scheduled_at.isoformat(), "status": appt.status.value,
                            }
                        except appt_service.SlotUnavailable as e:
                            result = {"ok": False, "error": str(e),
                                      "slots": await appt_service.list_available_slots(session, prop.id)}

    elif name == "cancel_appointment":
        ok = False
        try:
            ok = await appt_service.cancel_appointment(session, uuid_mod.UUID(str(args.get("appointment_id"))))
        except (ValueError, AttributeError, TypeError):
            pass
        result = {"ok": True, "cancelled": ok}
        if not ok:
            result["error"] = "No se encontró una cita activa con ese id."

    elif name == "recommend_similar":
        _unsupported_rs, _has_supported_rs = _unsupported_type_request(ctx)
        if _unsupported_rs and not _has_supported_rs:
            result = {
                "ok": False, "retryable": False,
                "code": "TIPO_NO_DISPONIBLE",
                "tipo_no_disponible": _unsupported_rs,
                "error": (
                    f"El tipo '{_unsupported_rs}' no está disponible actualmente. "
                    f"No recomiendes propiedades de otro tipo como si calzaran: "
                    f"aclara primero si quiere ver alternativas."
                ),
            }
        else:
            prop = await _find_property(session, ctx, args.get("property_id"))
            if prop is None:
                result = {"ok": False, "error": "Propiedad no encontrada."}
            else:
                hits = await similar_properties(session, str(prop.id))
                props = await prop_repo.get_properties(session, [h.property_id for h in hits])
                ordered = {str(p.id): p.to_dict() for p in props}
                items = [ordered[h.property_id] for h in hits if h.property_id in ordered]
                result["properties"] = items
                if items:
                    ctx.state["last_results"] = items

    elif name == "web_search":
        from app.agents import websearch

        result = await websearch.search_web(
            str(args.get("query") or ""), max_results=args.get("max_results")
        )

    elif name == "send_response":
        # Herramienta TERMINAL: la intercepta el runtime del agente antes de
        # llegar aquí. Si aparece, es un bug de integración: error honesto.
        result = {
            "ok": False, "code": "RUNTIME_ONLY_TOOL",
            "error": "send_response debe ejecutarla el runtime del agente.",
            "retryable": False,
        }

    elif name == "update_conversation_state":
        from app.agents.metrics import METRICS
        from app.agents.state import merge_state_update

        applied, rejected = merge_state_update(ctx.state, args or {})
        result["applied"] = applied
        if rejected:
            result["rejected"] = rejected
        METRICS.inc("state_updates")
        if rejected:
            METRICS.inc("state_update_rejections", len(rejected))
        prefs_patch = {
            dst: applied[src] for src, dst in _PREFERENCE_FIELDS.items() if src in applied
        }
        if prefs_patch:
            from app.memory import service as memory_service

            await memory_service.update_preferences(session, ctx.user_id, prefs_patch)

    elif name == "list_appointments":
        lead = await crm_service.get_or_create_lead(session, ctx.user_id)
        appts = await appt_service.list_appointments(session, lead_id=lead.id, limit=20)
        result["appointments"] = [
            {
                "id": str(a.id), "scheduled_at": a.scheduled_at.isoformat(),
                "status": a.status.value, "notes": (a.notes or "")[:200],
            }
            for a in appts
        ]

    elif name == "reschedule_appointment":
        try:
            appt_id = uuid_mod.UUID(str(args.get("appointment_id")))
            when = dt.datetime.fromisoformat(str(args.get("datetime_iso") or ""))
        except (ValueError, TypeError):
            result = {"ok": False, "error": "appointment_id o datetime_iso inválido."}
        else:
            current = await appt_service.get_appointment(session, appt_id)
            if current is None:
                result = {"ok": False, "error": "Cita no encontrada."}
            else:
                invalid_slot = await _validate_real_slot(session, current.property_id, when)
                if invalid_slot is not None:
                    result = invalid_slot
                else:
                    try:
                        appt = await appt_service.reschedule_appointment(session, appt_id, when)
                    except appt_service.SlotUnavailable as e:
                        result = {"ok": False, "error": str(e)}
                    else:
                        if appt is None:
                            result = {"ok": False, "error": "Cita no encontrada."}
                        else:
                            ctx.state["last_appointment_id"] = str(appt.id)
                            result["appointment"] = {
                                "id": str(appt.id), "scheduled_at": appt.scheduled_at.isoformat(),
                                "status": appt.status.value,
                            }

    else:
        result = {"ok": False, "error": f"unknown tool {name}"}


    ctx.executed.append({"tool": name, "args": args, "ok": bool(result.get("ok", True))})
    from app.agents.metrics import METRICS

    METRICS.inc("tool_calls")
    if not result.get("ok", True):
        METRICS.inc("tool_errors")
    if name == "search_properties":
        METRICS.inc("property_search")
    if name == "search_documents":
        METRICS.inc("rag_retrieval")
    if name == "web_search":
        METRICS.inc("web_search_calls")
    if name == "schedule_visit" and result.get("appointment"):
        METRICS.inc("appointment_created")
    log.info("tool_exec name=%s ok=%s user=%s", name, result.get("ok", True), ctx.user_id)
    return result

