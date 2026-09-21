"""Coordinador del turno del agente (LLM-first puro, agent-loop real).

División de responsabilidades (OBLIGATORIA, ver AGENTS.md):

- RUNTIME (app/agents/runtime.py): ejecutar tools, validar argumentos,
  reintentos técnicos, idempotencia, límites anti-loop, trazabilidad.
- AGENTE (el LLM): interpretar, decidir tools, orden, cuándo preguntar,
  cuándo investigar web, interpretar resultados, cuándo terminar.
- ESTE MÓDULO: bootstrap del turno (usuario/conversación/mensaje), persistir
  estado y mensajes, auditoría AiEvent y la respuesta DEGRADADA cuando el
  proveedor LLM muere a mitad de turno (construida solo con evidencia real,
  nunca con lógica inmobiliaria hardcodeada).
"""
from __future__ import annotations

import datetime as dt
import time
import uuid as uuid_mod

from sqlalchemy.orm.attributes import flag_modified

from app.agents.intents import Intent
from app.agents.metrics import METRICS
from app.agents.prompts_v2 import PROMPT_VERSION, build_system_prompt
from app.agents.reply import AgentReply
from app.agents.runtime import AgentRuntime, ProgressCallback, TurnOutcome
from app.agents.state import describe_state
from app.agents.tools import ToolContext
from app.ai.llm import LLMProvider
from app.core.bizconfig import get_business_timezone
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.database.models import AiEvent, Role
from app.memory import service as memory_service

log = get_logger(__name__)

MODEL_LABEL = "unavailable"


def _new_request_id() -> str:
    return uuid_mod.uuid4().hex[:16]


# ──────────────────────────────────────────────────────────────────────────
# Respuesta degradada: SOLO evidencia, presentada tal cual.
# Se usa cuando el proveedor LLM falla definitivamente después de que las
# tools produjeron datos. No decide nada: enumera lo confirmado y lo fallido.
# ──────────────────────────────────────────────────────────────────────────

def build_degraded_reply(evidence: list[dict], outcome: TurnOutcome) -> str:
    lines: list[str] = []
    for env in evidence:
        if env.get("ok") and env.get("tool") != "send_response":
            data = env.get("data") or {}
            meta = env.get("metadata") or {}
            tool = env.get("tool", "")
            if tool == "search_properties":
                props = data.get("properties") or []
                if props:
                    codes = [p.get("code", "?") for p in props[:4]]
                    total = data.get("count", meta.get("count", len(codes)))
                    lines.append(f"• Búsqueda: {total} propiedades ({', '.join(codes)}).")
                elif meta.get("count"):
                    lines.append(f"• Búsqueda: {meta['count']} propiedades coincidentes.")
            elif tool == "get_property" and (data.get("property") or meta.get("code")):
                p = data.get("property") or {}
                code = p.get("code") or meta.get("code") or ""
                lines.append(
                    f"• Propiedad {code}: {p.get('title', '')} "
                    f"(${float(p.get('price') or 0):,.0f})." if p else f"• Propiedad {code}."
                )
            elif tool == "get_property_images" and (data.get("property_id") or meta.get("property_id")):
                pid = data.get("property_id") or meta.get("property_id")
                n = len(data.get("images") or [])
                lines.append(
                    f"• Imágenes de {pid}: {n} disponible(s)." if n
                    else f"• Imágenes de {pid}: ninguna cargada."
                )
            elif tool == "list_available_slots" and (data.get("slots") or meta.get("count")):
                slots = data.get("slots") or []
                first = slots[0].get("label", "") if slots else ""
                total = meta.get("count", len(slots))
                lines.append(
                    f"• Horarios de visita: {total} disponibles"
                    + (f" (ej. {first})." if first else ".")
                )
            elif tool == "search_documents" and (data.get("chunks") or meta.get("count")):
                chunks = data.get("chunks") or []
                titles = {c.get("title", "documento") for c in chunks[:3]}
                lines.append(f"• Documentos relevantes: {', '.join(sorted(titles))}.")
            elif tool == "web_search" and (data.get("results") or meta.get("count")):
                n = meta.get("count", len(data.get("results") or []))
                lines.append(f"• Búsqueda web: {n} resultados externos.")
            elif tool == "list_appointments" and (data.get("appointments") or meta.get("count")):
                n = meta.get("count", len(data.get("appointments") or []))
                lines.append(f"• Citas: {n} registradas.")
            elif tool == "list_saved_searches" and (data.get("saved_searches") or meta.get("count")):
                n = meta.get("count", len(data.get("saved_searches") or []))
                lines.append(f"• Alertas guardadas: {n}.")
    failed = [env.get("tool", "?") for env in evidence if not env.get("ok")]
    if failed:
        lines.append(f"• No pude completar: {', '.join(sorted(set(failed)))}.")

    if not lines:
        return (
            "⚠️ Tuve un problema técnico procesando tu mensaje y no obtuve "
            "información confirmada. Intenta de nuevo en unos segundos."
        )
    head = (
        "Tuve un inconveniente técnico redactando la respuesta completa, "
        "pero esto es lo que pude confirmar con los datos reales:\n"
    )
    return head + "\n".join(lines[:12])


class PureLLMOrchestrator:
    """Turno completo: bootstrap → runtime (loop agentic) → persistencia/auditoría."""

    def __init__(self, provider: LLMProvider, on_progress: ProgressCallback | None = None):
        self.provider = provider
        self.settings = get_settings()
        self._on_progress = on_progress
        self.runtime = AgentRuntime(provider)

    # ------------------------------------------------------------------ turno
    async def handle_user_message(
        self,
        session,
        user_id: int,
        text: str,
        username: str = "",
        first_name: str = "",
        on_progress: ProgressCallback | None = None,
    ) -> AgentReply:
        started = time.monotonic()
        run_id = _new_request_id()
        METRICS.inc("agent_turns")

        reply: AgentReply | None = None
        outcome: TurnOutcome | None = None
        intent = Intent.UNKNOWN
        conv = None
        conv_id = None
        ctx: ToolContext | None = None

        try:
            user = await memory_service.get_or_create_user(session, user_id, username, first_name)
            conv = await memory_service.get_or_create_conversation(session, user.id)
            conv_id = conv.id
            await memory_service.add_message(session, conv.id, Role.USER, text)

            ctx = ToolContext(
                session=session,
                user_id=user.id,
                conversation_id=conv.id,
                state=dict(conv.state or {}),
                user_text=text,
                request_id=run_id,
            )
            messages = await self._build_messages(ctx, text)
            outcome = await self.runtime.run_turn(ctx, text, messages, on_progress=on_progress)
            intent = outcome.intent

            if outcome.reply_text.strip():
                reply = AgentReply(
                    text=outcome.reply_text,
                    intent=intent,
                    images=outcome.images or None,
                    actions=outcome.actions,
                )
            else:
                # El LLM murió a mitad de turno: responder con evidencia real.
                METRICS.inc("degraded_replies")
                METRICS.inc("llm_fallbacks")
                reply = AgentReply(
                    text=build_degraded_reply(outcome.evidence, outcome),
                    intent=intent,
                    error=outcome.error or outcome.status,
                )
        except Exception as e:
            await session.rollback()
            log.exception("agent_turn_crashed user=%s run_id=%s", user_id, run_id)
            reply = AgentReply(
                text="⚠️ Ocurrió un error interno procesando tu mensaje. Intenta de nuevo.",
                intent=intent,
                error=str(e),
            )
        else:
            try:
                if conv is not None and ctx is not None:
                    await self._persist(session, conv, ctx, outcome, reply)
            except Exception:
                await session.rollback()
                log.exception("agent_persist_failed user=%s run_id=%s", user_id, run_id)

        finally:
            await self._audit(
                session,
                run_id=run_id,
                user_id=user_id,
                conversation_id=(conv_id if conv is not None else None),
                intent=intent,
                outcome=outcome,
                reply=reply,
                retrieved_property_ids=(ctx.retrieved_property_ids if ctx else []),
                retrieved_chunk_ids=(ctx.retrieved_chunk_ids if ctx else []),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        return reply or AgentReply(text="⚠️ Error interno.", intent=intent)

    # ───────────────────────────────────────────────────────── persistencia
    async def _persist(self, session, conv, ctx: ToolContext, outcome, reply: AgentReply) -> None:
        # Traza compacta del turno para el próximo contexto (evita redundancia).
        if outcome is not None:
            ctx.state["last_turn_tools"] = [
                {"tool": t.get("tool"), "ok": bool(t.get("ok"))}
                for t in outcome.tool_trace[-8:]
            ]
        conv.state = ctx.state
        flag_modified(conv, "state")
        conv.summary = self._summarize(conv.summary, ctx.user_text, reply.text)
        await memory_service.add_message(
            session, conv.id, Role.ASSISTANT, reply.text,
            {"intent": reply.intent.value, "run_id": getattr(ctx, "request_id", "")},
        )
        await session.commit()

    def _summarize(self, current: str, user_text: str, reply_text: str) -> str:
        snapshot = f"Última consulta: {user_text[:120]} → {reply_text[:120]}"
        return snapshot if not current else f"{snapshot} | {current[:400]}"

    # ─────────────────────────────────────────────────────────── auditoría
    async def _audit(self, session, *, run_id, user_id, conversation_id, intent,
                     outcome, reply, retrieved_property_ids, retrieved_chunk_ids,
                     latency_ms) -> None:
        """AiEvent failure-safe (savepoint lógico: nunca rompe el turno)."""
        status = "ok"
        if outcome is not None:
            status = outcome.status
        elif reply is not None and reply.error:
            status = "error"
        tool_calls = []
        if outcome is not None:
            tool_calls = [
                {
                    "tool": t.get("tool"),
                    "call_id": t.get("call_id"),
                    "round": t.get("round"),
                    "ok": t.get("ok", False),
                    "error": t.get("error"),
                }
                for t in outcome.tool_trace
            ]
        try:
            session.add(AiEvent(
                request_id=run_id,
                user_id=user_id,
                conversation_id=conversation_id,
                intent=(intent.value if intent else "")[:40],
                prompt_version=PROMPT_VERSION[:64],
                model=(self.provider.model or "")[:120],
                tool_calls=tool_calls,
                retrieved_property_ids=retrieved_property_ids,
                retrieved_chunk_ids=retrieved_chunk_ids,
                response=(reply.text if reply else "")[:4000],
                latency_ms=latency_ms,
                status=status[:64],
            ))
            await session.commit()
        except Exception:  # noqa: BLE001 - audit write must never break the main flow
            await session.rollback()
            log.warning("audit_write_failed run_id=%s", run_id)

    # ─────────────────────────────────────────────────────────── contexto LLM
    async def _build_messages(self, ctx: ToolContext, text: str) -> list[dict]:
        """system(prompt de principios + estado + preferencias) + historial + user."""
        s = self.settings
        history: list[dict] = []
        if ctx.conversation_id is not None:
            # El historial crudo sirve solo para resolver referencias conversacionales
            # ("la segunda", "esa", tono) — NUNCA como fuente de datos de propiedades:
            # esa regla vive en el system prompt (ver prompts_v2.py). Los datos
            # confirmados viajan estructurados en state_context (last_results/last_filters).
            recent = await memory_service.recent_messages(
                ctx.session, ctx.conversation_id, limit=max(2, s.LLM_HISTORY_TURNS)
            )
            for m in recent:
                content = (m.content or "").strip()
                if not content:
                    continue
                history.append({
                    "role": "user" if m.role == Role.USER else "assistant",
                    "content": content[:600],
                })
            if history and history[-1]["role"] == "user" and history[-1]["content"][:400] == text[:400]:
                history.pop()

        extra = ""
        prefs = await memory_service.get_preferences(ctx.session, ctx.user_id)
        if prefs and (prefs.city or prefs.max_budget or prefs.property_type or prefs.operation):
            extra = (
                f"Preferencias persistentes del cliente: ciudad={prefs.city or 's/d'}, "
                f"tipo={prefs.property_type or 's/d'}, operación={prefs.operation or 's/d'}, "
                f"presupuesto máx={prefs.max_budget or 's/d'}."
            )
        import datetime as dt
        from zoneinfo import ZoneInfo
        from app.core.bizconfig import get_business_timezone
        # Obtener la zona horaria del negocio y la hora actual en esa zona
        business_tz_name = await get_business_timezone()
        try:
            business_tz = ZoneInfo(business_tz_name)
        except Exception:
            business_tz = ZoneInfo("America/Bogota")
        now_utc = dt.datetime.now(dt.UTC)
        now_business = now_utc.astimezone(business_tz)
        current_dt_business = now_business.isoformat()
        current_date_business = now_business.date().isoformat()
        current_day_business = now_business.strftime("%A")
        # Mapear día de la semana al español
        day_names_es = {
            "Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles",
            "Thursday": "jueves", "Friday": "viernes", "Saturday": "sábado", "Sunday": "domingo"
        }
        current_day_es = day_names_es.get(current_day_business, current_day_business.lower())
        state_context = describe_state(ctx.state)
        turn_context = (
            f"Conversación nueva: {'sí' if not history else 'no'}\n"
            f"Agente ya presentado: {'sí' if ctx.state.get('agent_introduced') is True else 'no'}\n"
            f"Fecha/hora actual del sistema (zona horaria del negocio: {business_tz_name}): {current_dt_business}\n"
            f"Fecha actual (zona horaria del negocio): {current_date_business}\n"
            f"Día de la semana actual (zona horaria del negocio): {current_day_es}"
        )
        messages: list[dict] = [{
            "role": "system",
            "content": build_system_prompt(
                extra_context=extra,
                state_context=state_context,
                turn_context=turn_context,
            ),
        }]
        messages.extend(history)
        messages.append({"role": "user", "content": text})
        return messages


# ──────────────────────────────────────────────────────────────────────────
# Fábrica (compatibilidad con main.py / app/agents/orchestrator.py)
# ──────────────────────────────────────────────────────────────────────────

async def create_orchestrator(llm: LLMProvider | None = None, on_progress: ProgressCallback | None = None):
    """Crea el orquestador agent-loop. Sin proveedor: error claro y honesto."""
    if llm is None:
        s = get_settings()
        raise RuntimeError(
            f"LLM_MODE={s.LLM_MODE} pero no hay proveedor configurado. "
            "El agent-loop requiere NVIDIA_API_KEY + NVIDIA_MODEL en .env."
        )
    return PureLLMOrchestrator(llm, on_progress=on_progress)
