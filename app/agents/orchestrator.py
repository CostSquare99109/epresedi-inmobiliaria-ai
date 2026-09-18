"""AI orchestrator: intent → deterministic tool plan → LLM (when available) → reply.

- With NVIDIA configured: real tool-calling loop (model chooses tools).
- Without key: deterministic pipeline executes the same tools and renders
  answers strictly from tool output (honest, no fabrication).
- Everything is audited into ai_events (prompt version, tools, retrieved ids).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from zoneinfo import ZoneInfo
import unicodedata
import uuid as uuid_mod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.intents import Intent, detect_intent, mentions_attribute
from app.agents.prompts import PROMPT_VERSION, build_system_prompt
from app.agents.tools import ToolContext, run_tool
from app.appointments.service import to_business_time
from app.ai.llm import LLMError, LLMProvider, ToolCall
from app.core.logging import get_logger, new_request_id
from app.core.settings import get_settings
from app.database.models import AiEvent, Conversation, Message, Role
from app.memory import service as memory_service
from app.properties.search import SearchFilters, extract_filters
from app.rag import retrieval as rag_retrieval

log = get_logger(__name__)

MAX_TOOL_ROUNDS = 4
MODEL_LABEL_DETERMINISTIC = "deterministic-rules-engine"

# Words that describe the alert request itself, not a search criterion.
ALERT_NOISE_RE = re.compile(
    r"\b(?:av[i\u00ed]same|notif[i\u00ed]came|cuando|aparezca|aparezcan|salga|ingrese|"
    r"llegue|gu[a\u00e1]rdame|guardar|alerta|alertas|b[u\u00fa]squeda|por favor)\b",
    re.IGNORECASE,
)


@dataclass
class AgentReply:
    text: str
    intent: Intent = Intent.UNKNOWN
    actions: list[tuple] = field(default_factory=list)  # (action, payload)
    images: list[str] = field(default_factory=list)     # file paths to send
    error: str | None = None


def extract_doc_answer(question: str, chunks: list[dict]) -> tuple[str, dict | None]:
    """Deterministic answer extraction from retrieved chunks (no fabrication).

    1) Filters chunks by required entity terms ("Proyecto X", "Torre 2"...):
       if no chunk mentions the asked entity, there is NO confirmed information.
    2) Scores sentences by query-token overlap (+ digit bonus for quantity
       questions) and quotes only document text."""
    import re as _re

    from app.ai.embeddings import normalize_text

    low_q = (question or "").lower()
    q_tokens = set(normalize_text(low_q))
    asks_quantity = any(
        w in "".join(c for c in unicodedata.normalize("NFD", low_q) if not unicodedata.combining(c))
        for w in ("cuanto", "cuantos", "cuantas", "numero de")
    )

    # --- entity gate: the exact phrase ("proyecto x", "torres del sinu") must exist
    deaccented = "".join(
        c for c in unicodedata.normalize("NFD", low_q) if not unicodedata.combining(c)
    )
    entity_phrases = []
    for m in _re.finditer(
        r"(proyecto|conjunto|torre|edificio|barrio|ciudad|villa|villas|torres)\s+([a-z0-9]+)",
        deaccented,
    ):
        kw, term = m.group(1), m.group(2)
        if term in ("de", "del", "la", "el", "los", "las", "y", "o", "en", "con", "sin", "al"):
            # "Proyecto Y" (capitalized proper name) is an entity; "villas de"
            # (lowercase preposition inside the name) is not.
            original_span = (question or "")[m.start():m.end()]
            if not any(ch.isupper() for ch in original_span[len(kw):]):
                continue
        entity_phrases.append(f"{kw} {term}")
    if entity_phrases:
        def _has_phrase(content: str, phrase: str) -> bool:
            return _re.search(rf"\b{_re.escape(phrase)}\b", content.lower()) is not None

        filtered = [c for c in chunks if all(_has_phrase(c.get("content") or "", p) for p in entity_phrases)]
        if not filtered:
            return "No tengo información confirmada sobre eso en los documentos.", None
        chunks = filtered

    best_chunk, best_score, best_sentence = None, -1.0, ""
    # mini-IDF over the retrieved chunks: tokens appearing in many chunks
    # ("villa", "carepa") are weak discriminators; rare tokens ("financiacion")
    # decide. Prevents project-name mentions from crushing the real answer.
    import math as _math

    n_chunks = max(len(chunks), 1)
    df = {t: sum(1 for c in chunks if t in set(normalize_text(c.get("content") or ""))) for t in q_tokens}
    idf = {t: _math.log(1 + n_chunks / (1 + df[t])) for t in q_tokens}
    # normalize by MATCHABLE weight only: query tokens absent from every chunk
    # ("¿cómo funciona...?") must not drown the discriminating signal.
    total_weight = sum(idf[t] for t in q_tokens if df[t] > 0) or 1.0
    min_df = min((df[t] for t in q_tokens if df[t] > 0), default=0)
    rare_tokens = {t for t in q_tokens if df[t] > 0 and df[t] == min_df}
    for chunk in chunks:
        content = chunk.get("content", "")
        c_tokens = set(normalize_text(content))
        chunk_overlap = len(q_tokens & c_tokens) / (len(q_tokens) or 1)
        section_tokens = set(normalize_text(chunk.get("section") or ""))
        section_bonus = len(q_tokens & section_tokens) / (len(q_tokens) or 1)
        for raw_sentence in _sentences(content):
            s_tokens = set(normalize_text(raw_sentence))
            if not s_tokens:
                continue
            overlap = sum(idf[t] for t in q_tokens if t in s_tokens) / total_weight
            score = overlap * 2.0 + section_bonus * 1.0
            if s_tokens & rare_tokens:
                score += 1.0  # the rarest query token is present: strong signal
            if asks_quantity and any(ch.isdigit() for ch in raw_sentence):
                score += 0.8
            # headings/titles carry high token overlap but no information
            if _looks_like_heading(raw_sentence):
                score -= 0.9
            score += min(len(raw_sentence), 240) / 2000.0  # tiny preference for substance
            if score > best_score:
                best_score = score
                best_sentence = raw_sentence.strip()
                best_chunk = chunk
    if best_chunk is None:
        return "No tengo información confirmada sobre eso.", None

    page = f" (página {best_chunk['page']})" if best_chunk.get("page") else ""
    title = best_chunk.get("title") or best_chunk.get("filename", "documento")
    related = len(chunks) - 1
    extra = f"\n\n(+{related} fragmento(s) relacionados)" if related > 0 else ""
    return (
        f"Según {title}{page}:\n\n«{best_sentence}»\n\n"
        f"Fuente: {title}{page}{extra}"
    ), best_chunk


def _sentences(text: str) -> list[str]:
    import re as _re

    parts = _re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _looks_like_heading(sentence: str) -> bool:
    """Titles/section headers overlap heavily with the query but say nothing.

    "FICHA TECNICA - VILLAS DE CAREPA" must not be quoted as the answer to
    "¿qué documentos tienen sobre las Villas de Carepa?".
    """
    s = sentence.strip()
    if not s:
        return True
    letters = [c for c in s if c.isalpha()]
    if letters and s.upper() == s:  # ALL CAPS
        return True
    words = s.split()
    if len(words) <= 6 and len(s) <= 48 and not any(ch in s for ch in ".:;,"):
        return True
    return False


class Orchestrator:
    def __init__(self, llm: LLMProvider | None = None):
        self.llm = llm

    @property
    def uses_llm(self) -> bool:
        return self.llm is not None

    # ------------------------------------------------------------- main entry
    async def handle_user_message(
        self,
        session: AsyncSession,
        user_id: int,
        text: str,
        username: str = "",
        first_name: str = "",
    ) -> AgentReply:
        started = time.monotonic()
        request_id = new_request_id()
        intent = Intent.UNKNOWN
        tool_calls: list[dict] = []
        prop_ids: list[str] = []
        chunk_ids: list[str] = []
        status = "ok"
        reply = None
        try:
            user = await memory_service.get_or_create_user(session, user_id, username, first_name)
            conv = await memory_service.get_or_create_conversation(session, user.id)
            await memory_service.add_message(session, conv.id, Role.USER, text)

            # contextual reference ("la segunda", "la de 280 millones")
            ref_index, ref_how = memory_service.resolve_reference(text, conv.state)
            pre_ctx = ToolContext(session=session, user_id=user.id, conversation_id=conv.id,
                                  state=dict(conv.state or {}), user_text=text)

            intent = self._intent_for(text, ref_index, has_context=bool(conv.state.get("last_results")))

            if intent == Intent.PROPERTY_DETAILS:
                if ref_index is not None:
                    target = (conv.state.get("last_results") or [])[ref_index]
                    reply = await self._details_flow(session, pre_ctx, conv, target["id"])
                else:
                    code_match = re.search(r"\bPROP[- ]?\d+\b", text, re.IGNORECASE)
                    code_ref = code_match.group(0).replace(" ", "-").upper() if code_match else None
                    reply = await self._details_flow(session, pre_ctx, conv, code_ref)
            elif intent == Intent.PROPERTY_IMAGES:
                image_ref = None
                if ref_index is not None:
                    results = conv.state.get("last_results") or []
                    if ref_index < len(results):
                        image_ref = results[ref_index]["id"]
                else:
                    code_match = re.search(r"\bPROP[- ]?\d+\b", text, re.IGNORECASE)
                    if code_match:
                        image_ref = code_match.group(0).replace(" ", "-").upper()
                reply = await self._images_action(pre_ctx, image_ref)
            else:
                reply = await self._intent_flow(session, pre_ctx, conv, intent, text)

            tool_calls = pre_ctx.executed
            prop_ids = pre_ctx.retrieved_property_ids
            chunk_ids = pre_ctx.retrieved_chunk_ids

            conv.state = pre_ctx.state
            conv.summary = self._summarize(conv.summary, text, reply.text)
            await memory_service.add_message(
                session, conv.id, Role.ASSISTANT, reply.text, {"intent": intent.value}
            )
            await session.commit()
        except LLMError as e:
            await session.rollback()
            status = f"llm_error:{e.kind}"
            reply = AgentReply(
                text=(
                    "⚠️ No pude consultar el modelo de lenguaje en este momento "
                    f"({e.kind}). No voy a inventar una respuesta.\n"
                    "Intenta de nuevo en unos segundos; si el problema persiste "
                    "revisa la configuración de NVIDIA (python -m scripts.doctor)."
                ),
                intent=intent,
                error=str(e),
            )
            log.error("llm_error kind=%s user=%s", e.kind, user_id)
        except Exception as e:  # never crash the bot loop; report honestly
            await session.rollback()
            status = "error"
            log.exception("orchestrator_error user=%s", user_id)
            reply = AgentReply(
                text="⚠️ Ocurrió un error interno procesando tu mensaje. El equipo ya fue notificado en los logs.",
                intent=intent, error=str(e),
            )
        finally:
            await self._audit(
                session, request_id=request_id, user_id=user_id, intent=intent,
                prompt_version=PROMPT_VERSION, model=(self.llm.model if self.llm else MODEL_LABEL_DETERMINISTIC),
                tool_calls=tool_calls, prop_ids=prop_ids, chunk_ids=chunk_ids,
                response=reply.text if reply else "", latency_ms=int((time.monotonic() - started) * 1000),
                status=status,
            )
        return reply or AgentReply(text="⚠️ Error interno.")

    # ------------------------------------------------------------- intents
    def _intent_for(self, text: str, ref_index: int | None, has_context: bool = False) -> Intent:
        intent = detect_intent(text)
        # attribute follow-ups ("¿tiene piscina?") refer to the property already
        # in context; answer from its stored data instead of running a search.
        if (
            intent not in (
                Intent.PROPERTY_DETAILS,
                Intent.PROPERTY_IMAGES,
                Intent.PRICE_QUERY,
                Intent.LOCATION_QUERY,
            )
            and mentions_attribute(text)
            and (has_context or ref_index is not None)
        ):
            intent = Intent.PROPERTY_DETAILS
        if intent == Intent.UNKNOWN and self.llm is not None:
            intent = Intent.GENERAL_FAQ  # LLM loop will decide with tools
        return intent

    async def _intent_flow(
        self, session: AsyncSession, ctx: ToolContext, conv: Conversation,
        intent: Intent, text: str,
    ) -> AgentReply:
        if intent == Intent.GREETING:
            return AgentReply(
                text=(
                    "¡Hola! 👋 Soy el asistente virtual de Expresedi. "
                    "Puedo ayudarte a buscar casas en venta o arriendo, resolver dudas "
                    "sobre el proyecto o agendar una visita. ¿Qué necesitas?"
                ),
                intent=intent,
            )
        if intent == Intent.SEARCH_PROPERTY:
            return await self._search_flow(session, ctx, conv, text)
        if intent == Intent.PROPERTY_DETAILS:
            return await self._details_flow(session, ctx, conv, None)
        if intent == Intent.PROPERTY_IMAGES:
            return await self._images_action(ctx, None)
        if intent == Intent.COMPARE_PROPERTIES:
            return await self._compare_flow(session, ctx, text)
        # Structured data is the source of truth: price/location questions about
        # a known property are answered from the inventory, not from documents.
        if intent == Intent.PRICE_QUERY:
            data_reply = await self._property_data_flow(ctx, kind="price")
            if data_reply is not None:
                return data_reply
            return await self._document_question_flow(session, ctx, conv, text, intent)
        if intent == Intent.LOCATION_QUERY:
            data_reply = await self._property_data_flow(ctx, kind="location")
            if data_reply is not None:
                return data_reply
            return await self._document_question_flow(session, ctx, conv, text, intent)
        if intent in (Intent.PROPERTY_DOCUMENT_QUESTION, Intent.FINANCING_QUESTION, Intent.GENERAL_FAQ):
            return await self._document_question_flow(session, ctx, conv, text, intent)
        if intent == Intent.SAVE_PROPERTY:
            return await self._simple_tool_flow(ctx, "save_property", {}, "has_pick")
        if intent == Intent.REMOVE_PROPERTY:
            return await self._simple_tool_flow(ctx, "remove_saved_property", {}, "has_pick")
        if intent == Intent.SAVE_SEARCH:
            return await self._save_search_flow(ctx, text)
        if intent == Intent.LIST_SAVED_SEARCHES:
            return await self._simple_tool_flow(ctx, "list_saved_searches", {}, "saved_list")
        if intent == Intent.SCHEDULE_VISIT:
            return await self._visit_flow(session, ctx, text)
        if intent == Intent.CANCEL_APPOINTMENT:
            appt_id = ctx.state.get("last_appointment_id")
            res = await run_tool("cancel_appointment", {"appointment_id": appt_id}, ctx)
            if res.get("cancelled"):
                return AgentReply(text="✅ Cita cancelada.", intent=intent)
            return AgentReply(
                text="No encontré una cita activa para cancelar. Revisa tus citas con /citas.",
                intent=intent,
            )
        if intent == Intent.CONTACT_AGENT:
            await run_tool("create_lead", {"status": "CONTACTED"}, ctx)
            return AgentReply(
                text=(
                    "🙌 Un asesor humano se pondrá en contacto contigo. "
                    "Deja tu nombre y teléfono en un mensaje para agilizar el contacto."
                ),
                intent=intent,
                actions=[("share_contact", None)],
            )
        if intent in (Intent.SELL_PROPERTY, Intent.RENT_PROPERTY):
            notes = f"Propietario interesado en {'vender' if intent == Intent.SELL_PROPERTY else 'arrendar'}: {text[:200]}"
            await run_tool("create_lead", {"status": "NEW", "notes": notes}, ctx)
            return AgentReply(
                text=(
                    "📋 Registramos tu interés en poner tu propiedad en el mercado. Un asesor "
                    "te contactará para el avalúo y la estrategia. Si dejas nombre y teléfono, agilizamos el proceso."
                ),
                intent=intent,
            )
        return AgentReply(
            text=(
                "Puedo ayudarte a:\n"
                "• 🔍 Buscar propiedades («busco casa en Carepa hasta 300 millones con 3 habitaciones»)\n"
                "• 🏠 Ver detalles, fotos y comparar opciones\n"
                "• 📄 Consultar documentos oficiales (reglamentos, fichas)\n"
                "• ⭐ Guardar favoritos y alertas de búsqueda\n"
                "• 📅 Agendar visitas\n\n¿Qué buscas hoy?"
            ),
            intent=Intent.UNKNOWN,
        )

    # ------------------------------------------------------------- flows
    async def _search_flow(self, session: AsyncSession, ctx: ToolContext, conv: Conversation, text: str) -> AgentReply:
        filters, semantic = extract_filters(text)
        if not filters.city and not filters.neighborhood:
            filters = await self._resolve_location(session, filters, text)
        args = {
            "filters": {k: v for k, v in filters.to_dict().items() if k != "query_text"},
            "semantic_query": semantic or filters.query_text,
        }
        res = await run_tool("search_properties", args, ctx)
        props = res.get("properties", [])
        if not props:
            return AgentReply(
                text=(
                    "No encontré propiedades disponibles con esos criterios. Puedo ampliar la "
                    "búsqueda (otro rango de precio, tipo o zona) o guardar una alerta para "
                    "avisarte cuando llegue algo nuevo. ¿Te parece?"
                ),
                intent=Intent.SEARCH_PROPERTY,
                actions=[("save_search", None)],
            )
        if self.llm is not None:
            llm_reply = await self._llm_answer(ctx, text, res, Intent.SEARCH_PROPERTY)
            if llm_reply is not None:
                return llm_reply
        from app.bot.formatting import property_line

        lines = [f"Encontré {len(props)} propiedad/es:\n"]
        actions = []
        for i, p in enumerate(props, start=1):
            lines.append(property_line(_PropView(p), i))
            actions.append(("details", p["id"]))
        lines.append("\nEscribe «la segunda» o toca una opción para ver la ficha completa.")
        return AgentReply(text="\n".join(lines), intent=Intent.SEARCH_PROPERTY, actions=actions)

    def _attribute_answer(self, prop: dict, question: str) -> AgentReply | None:
        """Anti-hallucination: answers feature questions strictly from stored data."""
        if not question:
            return None
        import unicodedata as _ud

        low = "".join(
            c for c in _ud.normalize("NFD", question.lower()) if not _ud.combining(c)
        )
        # attr -> (feature keywords, structured column, label)
        # A NULL column means "not informed" (never "no"); 0 means a confirmed "no".
        attr_map: dict[str, tuple[tuple[str, ...], str | None, str]] = {
            "piscina": (("piscina",), None, "piscina"),
            "garaje": (("garaje", "parqueadero", "parqueo"), "parking_spaces", "parqueadero"),
            "mascotas": (("mascota",), None, "mascotas"),
            "ascensor": (("ascensor",), None, "ascensor"),
            "jardin": (("jardin",), None, "jardín"),
            "terraza": (("terraza",), None, "terraza"),
            "balcon": (("balcon",), None, "balcón"),
            "amoblado": (("amoblad", "amueblad"), None, "amoblado"),
            "closet": (("closet",), None, "closets"),
            "deposito": (("deposito",), None, "depósito"),
        }
        asked = [attr for attr, (words, _c, _l) in attr_map.items() if any(w in low for w in words)]
        if not asked:
            return None
        features_low = " ".join(str(f).lower() for f in (prop.get("features") or []))
        project_text = (prop.get("project") or "").lower()
        positives: list[str] = []
        negatives: list[str] = []
        confirmed_no: list[str] = []
        for attr in asked:
            words, col, label = attr_map[attr]
            if any(w in features_low for w in words):
                positives.append(label)
                continue
            value = prop.get(col) if col else None
            if col and value is not None:
                if float(value) > 0:
                    positives.append(f"{label} ({int(value)})")
                else:
                    confirmed_no.append(label)
                continue
            negatives.append(label)
        lines = []
        if positives:
            lines.append(
                f"✅ {prop.get('code')} — {prop.get('title')}: incluye "
                f"{', '.join(sorted(set(positives)))} (registrado en la ficha)."
            )
        if confirmed_no:
            lines.append(
                f"❌ {prop.get('code')} — {prop.get('title')}: no tiene "
                + ", ".join(sorted(set(confirmed_no)))
                + " (dato registrado)."
            )
        if negatives:
            lines.append(
                "❌ No tengo información confirmada sobre "
                + ", ".join(sorted(set(negatives)))
                + f" en {prop.get('code')}. No lo doy por hecho: puedo confirmarlo con un asesor del equipo."
                + (f" (proyecto: {prop.get('project')})" if project_text else "")
            )
        if not lines:
            return None
        return AgentReply(
            text="\n\n".join(lines),
            intent=Intent.PROPERTY_DETAILS,
            actions=[("contact_agent", prop.get("id")), ("save", prop.get("id")), ("slots", prop.get("id"))],
        )

    async def _property_data_flow(self, ctx: ToolContext, kind: str) -> AgentReply | None:
        """Price / location answered from the inventory (source of truth).

        Returns None when no property can be resolved, so the caller can fall
        back to the document flow (e.g. "¿cuál es el precio de la cuota?").
        """
        from app.bot.formatting import (
            OPERATION_LABEL,
            STATUS_LABEL,
            fmt_money,
            fmt_opt,
        )

        res = await run_tool("get_property", {"property_ref": None}, ctx)
        prop = res.get("property")
        if not res.get("ok") or not prop:
            return None
        ctx.state["last_property_id"] = prop["id"]

        code = prop.get("code", "")
        title = prop.get("title", "")
        status = STATUS_LABEL.get(prop.get("status", ""), prop.get("status", ""))
        actions = [
            ("details", prop["id"]), ("images", prop["id"]), ("save", prop["id"]),
            ("slots", prop["id"]), ("contact_agent", prop["id"]),
        ]

        if kind == "price":
            price = fmt_money(prop.get("price"), prop.get("currency") or "COP")
            op = OPERATION_LABEL.get(prop.get("operation", ""), prop.get("operation", ""))
            lines = [
                f"💰 **{title}** ({code})",
                f"Precio: {price} · Operación: {op}",
                f"Estado: **{status}**",
            ]
            if status != "Disponible":
                lines.append("⚠️ Esta propiedad no figura como disponible en este momento.")
            return AgentReply(
                text="\n".join(lines), intent=Intent.PRICE_QUERY, actions=actions,
            )

        # location
        parts = [p for p in (prop.get("neighborhood"), prop.get("city")) if p]
        coords = None
        if prop.get("latitude") is not None and prop.get("longitude") is not None:
            coords = f"{prop['latitude']}, {prop['longitude']}"
        lines = [f"📍 **{title}** ({code})"]
        lines.append(f"Zona: {', '.join(parts) if parts else 'No informado'}")
        lines.append(f"Dirección: {fmt_opt(prop.get('address'))}")
        lines.append(f"Coordenadas: {coords or 'No informado'}")
        return AgentReply(
            text="\n".join(lines), intent=Intent.LOCATION_QUERY, actions=actions,
        )

    async def _details_flow(self, session: AsyncSession, ctx: ToolContext, conv: Conversation, ref: str | None) -> AgentReply:
        res = await run_tool("get_property", {"property_ref": ref}, ctx)
        if not res.get("ok") or not res.get("property"):
            return AgentReply(
                text="No identifiqué cuál propiedad quieres ver. Menciona el código (ej: PROP-0003) o pídeme una búsqueda primero.",
                intent=Intent.PROPERTY_DETAILS,
            )
        prop = res["property"]
        # remember what the user is looking at: enables "¿tiene piscina?" later
        ctx.state["last_property_id"] = prop["id"]
        attribute_answer = self._attribute_answer(prop, ctx.user_text)
        if attribute_answer is not None:
            return attribute_answer
        if self.llm is not None:
            llm_reply = await self._llm_answer(ctx, "Detalle de propiedad", res, Intent.PROPERTY_DETAILS)
            if llm_reply is not None:
                return llm_reply
        from app.bot.formatting import property_card

        return AgentReply(
            text=property_card(_PropView(prop)),
            intent=Intent.PROPERTY_DETAILS,
            actions=[
                ("images", prop["id"]), ("save", prop["id"]), ("compare", prop["id"]),
                ("slots", prop["id"]), ("contact_agent", prop["id"]), ("docs", prop["id"]),
            ],
        )

    async def _compare_flow(self, session: AsyncSession, ctx: ToolContext, text: str) -> AgentReply:
        codes = re.findall(r"PROP-\d+", text.upper())
        args = {"property_refs": codes} if len(codes) >= 2 else {"property_refs": []}
        res = await run_tool("compare_properties", args, ctx)
        props = res.get("properties", [])
        if len(props) < 2:
            return AgentReply(
                text="Para comparar necesito al menos dos opciones: haz una búsqueda y dime «compárame estas propiedades».",
                intent=Intent.COMPARE_PROPERTIES,
            )
        from app.bot.formatting import comparison_table

        return AgentReply(
            text=f"Comparación ({len(props)} propiedades, solo datos registrados):\n"
                 + comparison_table(_PropView.wrap(props)),
            intent=Intent.COMPARE_PROPERTIES,
            actions=[("details", p["id"]) for p in props],
        )

    async def _document_question_flow(
        self, session: AsyncSession, ctx: ToolContext, conv: Conversation, text: str,
        intent: Intent,
    ) -> AgentReply:
        query = self._doc_query(text)
        res = await run_tool("search_documents", {"query": query}, ctx)
        chunks = res.get("chunks", [])
        if self.llm is not None:
            llm_reply = await self._llm_answer(ctx, text, res, intent)
            if llm_reply is not None:
                return llm_reply
        if not chunks:
            return AgentReply(
                text="No tengo información confirmada sobre eso en los documentos. Puedo buscar en el inventario de propiedades si quieres.",
                intent=intent,
            )
        answer, best = extract_doc_answer(text, chunks)
        return AgentReply(
            text=answer,
            intent=intent,
            actions=[("docs", str(best["chunk_id"])) if best else ("docs", None)],
        )


    async def _simple_tool_flow(self, ctx: ToolContext, tool: str, args: dict, kind: str) -> AgentReply:
        res = await run_tool(tool, args, ctx)
        if kind == "has_pick":
            prop = res.get("property") or {}
            if res.get("ok") is False and not prop:
                last = ctx.state.get("last_results") or []
                if len(last) > 1:
                    options = "\n".join(f"• {p['code']} — {p['title']}" for p in last[:5])
                    return AgentReply(
                        text=f"Tengo varias opciones en contexto. ¿Cuál quieres?\n{options}\n\nEscribe el código o «la primera/la segunda».",
                        intent=Intent.SAVE_PROPERTY if tool == "save_property" else Intent.REMOVE_PROPERTY,
                    )
                return AgentReply(
                    text="Primero muéstrame una propiedad: pídeme una búsqueda o envía su código (ej: PROP-0001).",
                    intent=Intent.PROPERTY_DETAILS,
                )
            if tool == "save_property":
                verb = "⭐ Guardada en favoritos" if res.get("saved") else "Ya estaba en tus favoritos"
            else:
                verb = "✖️ Eliminada de favoritos" if res.get("removed") else "No estaba en tus favoritos"
            return AgentReply(
                text=f"{verb}: {prop.get('title', '')} ({prop.get('code', '')}).",
                intent=Intent.SAVE_PROPERTY if tool == "save_property" else Intent.REMOVE_PROPERTY,
            )
        if kind == "saved_list":
            items = res.get("saved_searches", [])
            if not items:
                return AgentReply(
                    text="No tienes búsquedas guardadas. Pide «avísame cuando aparezca una casa de 2 habitaciones en Carepa».",
                    intent=Intent.LIST_SAVED_SEARCHES,
                )
            lines = ["Tus búsquedas guardadas:"]
            for s in items:
                desc = ", ".join(f"{k}={v}" for k, v in s["filters"].items())
                lines.append(f"• {s['name']}: {desc or 'sin filtros'}")
            return AgentReply(text="\n".join(lines), intent=Intent.LIST_SAVED_SEARCHES)
        return AgentReply(text="Listo.", intent=Intent.UNKNOWN)

    async def _save_search_flow(self, ctx: ToolContext, text: str = "") -> AgentReply:
        filters = {}
        if text:
            parsed, _semantic = extract_filters(text)
            filters = parsed.to_dict()
            noise = ALERT_NOISE_RE.sub(" ", str(filters.get("query_text") or "")).strip()
            if noise:
                filters["query_text"] = noise
            else:
                filters.pop("query_text", None)
        if not filters:
            filters = ctx.state.get("last_filters") or {}
        if not filters:
            return AgentReply(
                text="Primero hazme una búsqueda (ej: «busco casa en Carepa hasta 300 millones») y luego te la guardo como alerta.",
                intent=Intent.SAVE_SEARCH,
            )
        name = "Alerta: " + ", ".join(f"{k}={v}" for k, v in list(filters.items())[:3])
        res = await run_tool("save_search", {"name": name, "filters": filters}, ctx)
        ss = res.get("saved_search", {})
        return AgentReply(
            text=f"🔔 Alerta creada. Te avisaré cuando ingrese una propiedad que coincida con: {ss.get('filters')}.",
            intent=Intent.SAVE_SEARCH,
        )

    async def _visit_flow(self, session: AsyncSession, ctx: ToolContext, text: str) -> AgentReply:
        last_results = ctx.state.get("last_results") or []
        if not last_results:
            return AgentReply(
                text=(
                    "Para agendar una visita primero necesito saber qué propiedad te interesa. "
                    "Hazme una búsqueda (ej: «casa en Carepa de 3 habitaciones hasta 300 millones») "
                    "y luego dime «agendar visita»."
                ),
                intent=Intent.SCHEDULE_VISIT,
            )
        when = self._parse_datetime(text)
        target_id = None
        target_title = ""

        ref_index, _how = memory_service.resolve_reference(text, ctx.state)

        if ref_index is not None and ref_index < len(last_results):
            target_id = last_results[ref_index]["id"]
            target_title = last_results[ref_index].get("title", "")
        else:
            last_property_id = ctx.state.get("last_property_id")
            if last_property_id:
                selected = next(
                    (p for p in last_results if p.get("id") == last_property_id),
                    None,
                )
                if selected:
                    target_id = selected["id"]
                    target_title = selected.get("title", "")

        if target_id is None and len(last_results) == 1:
            target_id = last_results[0]["id"]
            target_title = last_results[0].get("title", "")

        if target_id is None:
            options = "\n".join(
                f"• {p['code']} — {p['title']}" for p in last_results[:5]
            )
            return AgentReply(
                text=(
                    "¿Para cuál propiedad quieres la visita?\n"
                    f"{options}\n\nToca «📅 Agendar visita» en la ficha que te interesa "
                    "o dime su código (ej: PROP-0001)."
                ),
                intent=Intent.SCHEDULE_VISIT,
                actions=[("details", p["id"]) for p in last_results[:5]],
            )
        if when is not None:
            res = await run_tool("schedule_visit", {"property_id": target_id, "datetime_iso": when.isoformat()}, ctx)
            if res.get("ok") and res.get("appointment"):
                appt = res["appointment"]
                ctx.state["last_appointment_id"] = appt["id"]
                return AgentReply(
                    text=(
                        f"📅 Visita solicitada para **{appt['property']}** ({appt['code']})\n"
                        f"Fecha: {(await to_business_time(dt.datetime.fromisoformat(appt['scheduled_at']))).strftime('%a %d %b %Y %H:%M')}\nEstado: pendiente de confirmación."
                    ),
                    intent=Intent.SCHEDULE_VISIT,
                    actions=[("cancel_appt", appt["id"])],
                )
            if res.get("error"):
                return AgentReply(text=f"⚠️ {res['error']}", intent=Intent.SCHEDULE_VISIT)
        res = await run_tool("list_available_slots", {"property_id": target_id}, ctx)
        if res.get("ok") is False:
            return AgentReply(text=res.get("error", "No encontré la propiedad."), intent=Intent.SCHEDULE_VISIT)
        slots = res.get("slots", [])
        if not slots:
            return AgentReply(text="No hay horarios disponibles esta semana para esa propiedad.", intent=Intent.SCHEDULE_VISIT)
        lines = [f"Horarios disponibles para {target_title}:"]
        actions = []
        for s in slots[:8]:
            lines.append(f"• {s['label']}")
            actions.append(("book_slot", {
                "property_id": target_id,
                "datetime_iso": s.get("datetime_local") or s["datetime"],
                "label": s["label"],
            }))
        return AgentReply(text="\n".join(lines), intent=Intent.SCHEDULE_VISIT, actions=actions)

    async def _resolve_location(self, session: AsyncSession, filters: SearchFilters, text: str) -> SearchFilters:
        from app.properties.repository import list_locations

        low = text.lower()
        try:
            locations = await list_locations(session)
        except Exception:
            return filters
        for key, canonical in locations.items():
            if key and len(key) >= 3 and f" {key} " in f" {low} ":
                filters.city = filters.city or canonical
                if filters.neighborhood is None and key != (filters.city or "").lower():
                    filters.neighborhood = canonical
        if filters.city and filters.neighborhood == filters.city:
            filters.neighborhood = None
        return filters

    def _doc_query(self, text: str) -> str:
        noise = re.compile(
            r"\b(hola|por favor|gracias|quiero saber|sabes|me puedes decir|puedes decirme|"
            r"cu[aá]nto|cu[aá]l|cu[aá]les|qu[eé]|donde|d[oó]nde|es|son|el|la|los|las|de|del|"
            r"seg[uú]n|documentaci[oó]n|documento|reglamento)\b"
        )
        q = noise.sub(" ", text.lower())
        return re.sub(r"\s+", " ", q).strip() or text.strip()

    def _parse_datetime(self, text: str) -> dt.datetime | None:
        low = text.lower().strip()
        business_tz = ZoneInfo("America/Bogota")

        m = re.search(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})", low)
        if m:
            try:
                return dt.datetime.fromisoformat(
                    f"{m.group(1)} {m.group(2)}"
                ).replace(tzinfo=business_tz)
            except ValueError:
                return None

        now = dt.datetime.now(business_tz).replace(
            minute=0, second=0, microsecond=0
        )

        day_map = {
            "pasado mañana": 2,
            "pasado manana": 2,
            "mañana": 1,
            "manana": 1,
            "hoy": 0,
        }

        base = None
        for word, offset in sorted(day_map.items(), key=lambda item: -len(item[0])):
            if re.search(rf"\b{re.escape(word)}\b", low):
                base = now + dt.timedelta(days=offset)
                break

        if base is None:
            months = {
                "enero": 1,
                "febrero": 2,
                "marzo": 3,
                "abril": 4,
                "mayo": 5,
                "junio": 6,
                "julio": 7,
                "agosto": 8,
                "septiembre": 9,
                "setiembre": 9,
                "octubre": 10,
                "noviembre": 11,
                "diciembre": 12,
            }

            weekdays = {
                "lunes": 0,
                "martes": 1,
                "miércoles": 2,
                "miercoles": 2,
                "jueves": 3,
                "viernes": 4,
                "sábado": 5,
                "sabado": 5,
                "domingo": 6,
            }

            month_pattern = "|".join(months)

            date_match = re.search(
                rf"\b(\d{{1,2}})\s+de\s+({month_pattern})(?:\s+de\s+(\d{{4}}))?\b",
                low,
            )

            if not date_match:
                date_match = re.search(
                    rf"\b(\d{{1,2}})\s+({month_pattern})(?:\s+(\d{{4}}))?\b",
                    low,
                )

            if date_match:
                day = int(date_match.group(1))
                month = months[date_match.group(2)]
                year = int(date_match.group(3)) if date_match.group(3) else now.year

                try:
                    base = dt.datetime(
                        year,
                        month,
                        day,
                        tzinfo=business_tz,
                    )
                except ValueError:
                    return None

                if date_match.group(3) is None and base < now:
                    base = base.replace(year=now.year + 1)

                weekday_match = re.search(
                    r"\b(" + "|".join(weekdays) + r")\b",
                    low,
                )

                if weekday_match:
                    expected = weekdays[weekday_match.group(1)]
                    if base.weekday() != expected:
                        return None

        if base is None:
            return None

        time_match = re.search(
            r"(?:a\s+las|para\s+las|a|@)\s*"
            r"(\d{1,2})(?::(\d{2}))?\s*"
            r"(am|pm|de\s+la\s+tarde|de\s+la\s+mañana|de\s+la\s+manana)\b",
            low,
        )

        if not time_match:
            time_match = re.search(
                r"\b(\d{1,2}):(\d{2})\s*(am|pm)\b",
                low,
            )

        if not time_match:
            time_match = re.search(
                r"\b(\d{1,2})\s*(am|pm)\b",
                low,
            )

        if not time_match:
            return base.replace(hour=10, minute=0)

        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        suffix = (time_match.group(3) or "").lower()

        if ("pm" in suffix or "tarde" in suffix) and hour < 12:
            hour += 12

        if "am" in suffix and hour == 12:
            hour = 0

        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            return None

        return base.replace(hour=hour, minute=minute)

    async def _llm_answer(
        self, ctx: ToolContext, user_text: str, seed_result: dict, intent: Intent
    ) -> AgentReply | None:
        """Runs the tool-calling loop; returns None to fall back to deterministic."""
        assert self.llm is not None
        from app.agents.tool_specs import TOOL_SPECS

        recent = await memory_service.recent_messages(ctx.session, ctx.conversation_id, limit=6)
        history = [
            {"role": "user" if m.role == Role.USER else "assistant", "content": m.content[:600]}
            for m in recent[:-1]
        ]
        prefs = await memory_service.get_preferences(ctx.session, ctx.user_id)
        extra = ""
        if prefs and (prefs.city or prefs.max_budget or prefs.property_type):
            extra = (f"Preferencias persistentes del cliente: ciudad={prefs.city or 's/d'}, "
                     f"tipo={prefs.property_type or 's/d'}, presupuesto máx={prefs.max_budget or 's/d'}.")
        messages: list[dict] = [
            {"role": "system", "content": build_system_prompt(extra)},
            *history,
            {
                "role": "user",
                "content": (
                    f"{user_text}\n\nResultado de herramientas ya ejecutadas (fuente de verdad):\n"
                    f"```json\n{json.dumps(seed_result, ensure_ascii=False, default=str)[:6000]}\n```"
                ),
            },
        ]
        for _round in range(MAX_TOOL_ROUNDS):
            resp = await self.llm.chat(messages, tools=TOOL_SPECS)
            if not resp.tool_calls:
                return AgentReply(text=resp.content.strip() or "…", intent=intent)
            messages.append({
                "role": "assistant",
                "content": resp.content or None,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)}}
                    for tc in resp.tool_calls
                ],
            })
            for tc in resp.tool_calls:
                result = await run_tool(tc.name, tc.arguments, ctx)
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str)[:4000],
                })
        return None  # exceeded rounds → deterministic fallback

    def _summarize(self, current: str, user_text: str, reply_text: str) -> str:
        """Rolling summary to keep context bounded (recent + persistent prefs)."""
        snapshot = f"Última consulta: {user_text[:120]} → {reply_text[:120]}"
        return snapshot if not current else f"{snapshot} | {current[:400]}"

    async def _audit(
        self, session: AsyncSession, *, request_id, user_id, intent, prompt_version,
        model, tool_calls, prop_ids, chunk_ids, response, latency_ms, status,
    ) -> None:
        try:
            session.add(AiEvent(
                request_id=request_id, user_id=user_id,
                intent=intent.value if intent else "",
                prompt_version=prompt_version, model=model, tool_calls=tool_calls,
                retrieved_property_ids=prop_ids, retrieved_chunk_ids=chunk_ids,
                response=(response or "")[:4000], latency_ms=latency_ms, status=status,
            ))
            await session.commit()
        except Exception:
            await session.rollback()
            log.warning("audit_write_failed", exc_info=True)

    # ------------------------------------------------------------- callbacks
    async def handle_action(self, session: AsyncSession, user_id: int, action: str, payload) -> AgentReply:
        """Handles inline-keyboard actions (deterministic path, no LLM needed)."""
        user = await memory_service.get_or_create_user(session, user_id)
        conv = await memory_service.get_or_create_conversation(session, user.id)
        ctx = ToolContext(session=session, user_id=user.id, conversation_id=conv.id, state=dict(conv.state or {}))
        started = time.monotonic()
        reply = None
        try:
            if action == "details":
                reply = await self._details_flow(session, ctx, conv, str(payload))
            elif action == "images":
                reply = await self._images_action(ctx, payload)
            elif action == "save":
                reply = await self._simple_tool_flow(ctx, "save_property", {"property_id": str(payload)}, "has_pick")
            elif action == "compare":
                reply = await self._compare_action(ctx, payload)
            elif action == "slots":
                reply = await self._slots_action(ctx, payload)
            elif action == "book_slot":
                reply = await self._book_slot_action(ctx, payload)
            elif action == "cancel_appt":
                res = await run_tool("cancel_appointment", {"appointment_id": str(payload)}, ctx)
                reply = AgentReply(
                    text="✅ Cita cancelada." if res.get("cancelled") else "No encontré esa cita activa.",
                    intent=Intent.CANCEL_APPOINTMENT,
                )
            elif action == "contact_agent":
                await run_tool("create_lead", {"status": "CONTACTED"}, ctx)
                reply = AgentReply(text="🙌 Un asesor te contactará pronto.", intent=Intent.CONTACT_AGENT)
            elif action == "docs":
                reply = await self._docs_action(ctx)
            elif action == "save_search":
                reply = await self._save_search_action(ctx, payload)
            elif action == "list_saved":
                reply = await self._simple_tool_flow(ctx, "list_saved_searches", {}, "saved_list")
            else:
                reply = AgentReply(text="Acción no reconocida.", intent=Intent.UNKNOWN)
            conv.state = ctx.state
            await session.commit()
        except Exception as e:
            await session.rollback()
            log.exception("action_error action=%s", action)
            reply = AgentReply(text="⚠️ Error procesando la acción.", intent=Intent.UNKNOWN, error=str(e))
        finally:
            await self._audit(
                session, request_id=new_request_id(), user_id=user_id,
                intent=reply.intent if reply else Intent.UNKNOWN,
                prompt_version=PROMPT_VERSION,
                model=(self.llm.model if self.llm else MODEL_LABEL_DETERMINISTIC),
                tool_calls=ctx.executed, prop_ids=ctx.retrieved_property_ids,
                chunk_ids=ctx.retrieved_chunk_ids,
                response=reply.text if reply else "",
                latency_ms=int((time.monotonic() - started) * 1000), status="ok",
            )
        return reply

    async def _images_action(self, ctx: ToolContext, payload) -> AgentReply:
        from app.api.files import list_property_images

        res = await run_tool("get_property", {"property_ref": payload}, ctx)
        if not res.get("property"):
            return AgentReply(
                text=(
                    "No identifiqué qué propiedad quieres ver. "
                    "Dime el código de la propiedad o indícame cuál opción quieres."
                ),
                intent=Intent.PROPERTY_IMAGES,
            )

        prop = res["property"]
        ctx.state["last_property_id"] = prop["id"]
        pid = str(prop["id"])
        imgs = list_property_images(pid)

        if not imgs:
            return AgentReply(
                text="En este momento esta propiedad no tiene fotografías disponibles.",
                intent=Intent.PROPERTY_IMAGES,
            )

        paths = [
            str(get_settings().storage_dir / "properties" / pid / filename)
            for filename in imgs
        ]

        return AgentReply(
            text="Aquí tienes las fotografías de esta propiedad.",
            intent=Intent.PROPERTY_IMAGES,
            images=paths,
        )

    async def _compare_action(self, ctx: ToolContext, payload) -> AgentReply:
        res = await run_tool("compare_properties", {"property_refs": [str(payload)]}, ctx)
        props = res.get("properties", [])
        if len(props) >= 2:
            from app.bot.formatting import comparison_table

            return AgentReply(
                text=f"Comparación ({len(props)} propiedades):\n" + comparison_table(_PropView.wrap(props)),
                intent=Intent.COMPARE_PROPERTIES,
            )
        return AgentReply(text="Necesito al menos dos opciones para comparar.", intent=Intent.COMPARE_PROPERTIES)

    async def _slots_action(self, ctx: ToolContext, payload) -> AgentReply:
        res = await run_tool("list_available_slots", {"property_id": str(payload)}, ctx)
        slots = res.get("slots", [])
        if not slots:
            return AgentReply(text="No hay horarios disponibles esta semana.", intent=Intent.SCHEDULE_VISIT)
        lines = ["Horarios disponibles:"]
        actions = [
            ("book_slot", {
                "property_id": str(payload),
                "datetime_iso": s.get("datetime_local") or s["datetime"],
                "label": s["label"],
            })
            for s in slots[:8]
        ]
        lines.extend(f"• {s['label']}" for s in slots[:8])
        return AgentReply(text="\n".join(lines), intent=Intent.SCHEDULE_VISIT, actions=actions)

    async def _book_slot_action(self, ctx: ToolContext, payload) -> AgentReply:
        data = payload if isinstance(payload, dict) else {}
        res = await run_tool("schedule_visit", {
            "property_id": data.get("property_id"), "datetime_iso": data.get("datetime_iso"),
        }, ctx)
        if res.get("ok") and res.get("appointment"):
            appt = res["appointment"]
            ctx.state["last_appointment_id"] = appt["id"]
            return AgentReply(
                text=(f"📅 Visita solicitada: {appt['property']} — "
                      f"{(await to_business_time(dt.datetime.fromisoformat(appt['scheduled_at']))).strftime('%a %d %b %H:%M')} (pendiente de confirmación)."),
                intent=Intent.SCHEDULE_VISIT, actions=[("cancel_appt", appt["id"])],
            )
        return AgentReply(text=f"⚠️ {res.get('error', 'No se pudo agendar.')}", intent=Intent.SCHEDULE_VISIT)

    async def _docs_action(self, ctx: ToolContext) -> AgentReply:
        res = await run_tool("search_documents", {"query": "reglamento ficha proyecto"}, ctx)
        chunks = res.get("chunks", [])
        if chunks:
            lines = ["📄 Documentos con información:"]
            lines += [f"• {c['title']} — {c['filename']}" for c in chunks[:5]]
            return AgentReply(text="\n".join(lines), intent=Intent.PROPERTY_DOCUMENT_QUESTION)
        return AgentReply(text="No tengo documentos registrados para esa consulta.", intent=Intent.PROPERTY_DOCUMENT_QUESTION)

    async def _save_search_action(self, ctx: ToolContext, payload) -> AgentReply:
        filt: dict = {}
        if payload:
            try:
                filt = json.loads(str(payload)) or {}
            except (json.JSONDecodeError, TypeError):
                filt = {}
        if not filt:
            filt = dict(ctx.state.get("last_filters") or {})
        if not filt:
            return AgentReply(text="No hay filtros para guardar.", intent=Intent.SAVE_SEARCH)
        res = await run_tool("save_search", {"name": "Alerta", "filters": filt}, ctx)
        return AgentReply(
            text=f"🔔 Alerta creada con filtros: {res.get('saved_search', {}).get('filters', {})}",
            intent=Intent.SAVE_SEARCH,
        )


class _PropView:
    """Adaptador de presentación: envuelve un dict real (``Property.to_dict()``)
    para reutilizar los helpers de formato, que reciben objetos ``Property``.
    No contiene datos propios: todo sale del resultado real del tool."""

    def __init__(self, d: dict):
        from app.database.models import Operation, PropertyStatus, PropertyType

        self.id = d.get("id")
        self.code = d.get("code", "")
        self.title = d.get("title", "")
        self.description = d.get("description", "")
        self.price = d.get("price")
        self.currency = d.get("currency", "COP")
        self.city = d.get("city", "")
        self.neighborhood = d.get("neighborhood", "")
        self.area_m2 = d.get("area_m2")
        self.bedrooms = d.get("bedrooms")
        self.bathrooms = d.get("bathrooms")
        self.parking_spaces = d.get("parking_spaces")
        self.features = d.get("features", [])
        self.status = PropertyStatus(d.get("status", "AVAILABLE"))
        self.operation = Operation(d.get("operation", "SALE"))
        self.property_type = PropertyType(d.get("property_type", "casa"))
        self.project = type("P", (), {"name": d.get("project")})() if d.get("project") else None

    @classmethod
    def wrap(cls, dicts: list[dict]) -> list["_PropView"]:
        return [cls(d) for d in dicts]
