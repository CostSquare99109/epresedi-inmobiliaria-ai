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
from app.core.logging import get_logger
from app.crm import service as crm_service
from app.database.models import Property
from app.memory import service as memory_service
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
    """
    validation = await appt_service.list_available_slots(
        session, property_id, requested_datetime=when
    )
    if isinstance(validation, dict) and validation.get("exact_match"):
        return None
    slots = validation.get("available_slots", []) if isinstance(validation, dict) else []
    nearest = validation.get("nearest_slots", []) if isinstance(validation, dict) else []
    return {
        "ok": False,
        "error": (
            "Ese horario no es un slot disponible (horario laboral, sin citas "
            "ocupadas y con al menos 2 horas de anticipación). Ofrece uno de "
            "los horarios reales de 'nearest_slots' o 'slots'."
        ),
        "nearest_slots": nearest,
        "slots": slots,
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
        filters = SearchFilters()
        if raw.get("property_type"): filters.property_type = raw["property_type"]
        if raw.get("operation"): filters.operation = raw["operation"]
        if raw.get("city"): filters.city = raw["city"]
        if raw.get("min_price") is not None: filters.min_price = float(raw["min_price"])
        if raw.get("max_price") is not None: filters.max_price = float(raw["max_price"])
        if raw.get("bedrooms") is not None: filters.bedrooms = int(raw["bedrooms"])
        if raw.get("bathrooms") is not None: filters.bathrooms = int(raw["bathrooms"])
        if raw.get("parking") is not None: filters.parking = int(raw["parking"])
        if raw.get("min_area") is not None: filters.min_area = float(raw["min_area"])
        if semantic and not filters.query_text:
            filters.query_text = semantic
        hits = await search_properties(session, filters, semantic)
        props = await prop_repo.get_properties(session, [h.property_id for h in hits], limit=max(len(hits), 1))
        ordered = {str(p.id): p.to_dict() for p in props}
        items = [ordered[h.property_id] for h in hits if h.property_id in ordered]
        ctx.state["last_results"] = items
        ctx.state["last_filters"] = filters.to_dict()
        # Signal if search returned no results so LLM knows to ask about expanding
        if not items:
            ctx.state["awaiting_search_refinement"] = True
            ctx.state["last_search_had_results"] = False
        else:
            ctx.state["awaiting_search_refinement"] = False
            ctx.state["last_search_had_results"] = True
        ctx.retrieved_property_ids.extend(str(p["id"]) for p in items)
        result["count"] = len(items)
        result["properties"] = items
        # NOTA: ya no se persisten preferencias automáticamente en cada búsqueda.
        # Los filtros de una búsqueda pueden ser exploratorios o (antes del fix de
        # alucinaciones) inventados por el LLM; guardarlos ciegamente como "preferencia
        # confirmada del cliente" contaminaba el perfil permanentemente entre conversaciones.
        # Las preferencias reales se registran vía update_conversation_state, donde el LLM
        # las declara explícitamente y bajo la regla de no inventar datos.

    elif name == "get_property":
        prop = await _find_property(session, ctx, args.get("property_ref"))
        if prop is None:
            result = {"ok": False, "error": "Propiedad no encontrada o referencia ambigua."}
        else:
            result["property"] = prop.to_dict()
            ctx.retrieved_property_ids.append(str(prop.id))
            ctx.state["last_property_id"] = str(prop.id)
            ctx.state["last_property_code"] = prop.code

    elif name == "compare_properties":
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
        from app.api.files import list_property_images

        prop = await _find_property(session, ctx, args.get("property_id"))
        if prop is None:
            # Distinguir "propiedad no encontrada" de "sin imágenes cargadas"
            # es evidencia distinta para el agente (§7/§25).
            result = {
                "ok": False, "retryable": False,
                "error": "Propiedad no encontrada o referencia ambigua.",
            }
        else:
            result["images"] = list_property_images(str(prop.id))
            result["property_id"] = str(prop.id)
            result["property_code"] = prop.code

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

    elif name == "create_lead":
        lead = await crm_service.get_or_create_lead(session, ctx.user_id)
        data = {k: v for k, v in args.items() if k in ("name", "phone", "budget", "status", "notes")}
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
            # Backward compatibility: if requested_datetime not provided, service returns list
            # If provided, service returns dict with structured data
            if isinstance(slots_result, list):
                result["slots"] = slots_result
            else:
                result["slots"] = slots_result.get("available_slots", [])
                result["slots_data"] = slots_result

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

