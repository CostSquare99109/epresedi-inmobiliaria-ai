"""Agent tool executor: LLM → Tool → Service → Repository → Database.

run_tool() is the ONLY path from the model to data. Every tool returns a
JSON-safe dict that is appended to the LLM context (compact, no secrets).
"""
from __future__ import annotations

import datetime as dt
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
    if low in ORDINALS:
        idx = ORDINALS[low]
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
        ctx.retrieved_property_ids.extend(str(p["id"]) for p in items)
        result["count"] = len(items)
        result["properties"] = items
        await memory_service.update_preferences(session, ctx.user_id, filters.to_dict())

    elif name == "get_property":
        prop = await _find_property(session, ctx, args.get("property_ref"))
        if prop is None:
            result = {"ok": False, "error": "Propiedad no encontrada o referencia ambigua."}
        else:
            result["property"] = prop.to_dict()
            ctx.retrieved_property_ids.append(str(prop.id))

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
        pid = args.get("property_id") or None
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
        result["images"] = list_property_images(str(prop.id)) if prop else []

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
            result["slots"] = await appt_service.list_available_slots(session, prop.id)

    elif name == "schedule_visit":
        prop = await _find_property(session, ctx, args.get("property_id"))
        if prop is None:
            result = {"ok": False, "error": "Propiedad no encontrada."}
        else:
            try:
                when = dt.datetime.fromisoformat(str(args.get("datetime_iso") or ""))
            except ValueError:
                result = {"ok": False, "error": "datetime_iso inválido.",
                          "slots": await appt_service.list_available_slots(session, prop.id)}
            else:
                lead = await crm_service.get_or_create_lead(session, ctx.user_id)
                try:
                    appt = await appt_service.create_appointment(
                        session, property_id=prop.id, lead_id=lead.id,
                        scheduled_at=when, notes=str(args.get("notes") or ""),
                    )
                    await crm_service.set_lead_status_from_appointment(session, lead.id)
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

    else:
        result = {"ok": False, "error": f"unknown tool {name}"}


    ctx.executed.append({"tool": name, "args": args, "ok": bool(result.get("ok", True))})
    log.info("tool_exec name=%s ok=%s user=%s", name, result.get("ok", True), ctx.user_id)
    return result

