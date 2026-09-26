"""Fake LLM para tests del agent-loop (runtime real + LLM scriptado).

Contrato del FakeLLMV2:
- ``responses`` es una lista de items, consumidos en orden, uno por llamada
  ``chat()``. Un item puede ser:
    * ``LLMResponse``  → se devuelve tal cual (tool_round / plain_text / ...).
    * ``Exception``    → se lanza (simula fallo del proveedor).
    * ``callable(messages, tools) -> LLMResponse | Exception``
      → respuesta DINÁMICA: puede inspeccionar los mensajes (incluidos los
        resultados de tools con role="tool") y decidir. Es lo que permite
        probar que el resultado de una tool cambia la siguiente decisión.
- Si se agotan los items, la última respuesta se repite (conveniencia).

Registra cada llamada en ``.calls`` = [{"messages": [...], "tools": tools}]
para verificar qué evidencia recibió el modelo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.ai.llm import LLMResponse, ToolCall


class FakeLLMV2:
    def __init__(self, responses: list, name: str = "fake-v2", model: str = "fake-model-v2"):
        self.name = name
        self.model = model
        self._responses = list(responses)
        self.calls: list[dict] = []
        self._last: object = None

    async def chat(self, messages, tools=None, temperature=0.2, max_tokens=2000, response_format=None) -> LLMResponse:
        self.calls.append({"messages": list(messages), "tools": tools})
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        item = self._responses[idx] if self._responses else None
        self._last = item
        if callable(item) and not isinstance(item, LLMResponse):
            item = item(list(messages), tools)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMResponse):
            return item
        return plain_text("")

    # ── utilidades de inspección (para asserts de tests) ─────────────────
    def tool_result_messages(self, call_index: int = -1) -> list[dict]:
        """Mensajes role="tool" de una llamada concreta (la evidencia que vio el LLM)."""
        msgs = self.calls[call_index]["messages"]
        return [m for m in msgs if m.get("role") == "tool"]

    def tool_result_contents(self, call_index: int = -1) -> list[dict]:
        out = []
        for m in self.tool_result_messages(call_index):
            try:
                out.append(json.loads(m["content"]))
            except (json.JSONDecodeError, KeyError, TypeError):
                out.append({"raw": m.get("content")})
        return out


# ─────────────────────────────────────────────────────────────── helpers

def tc(name: str, args: dict, call_id: str = "c1", arguments_error: str = "") -> ToolCall:
    """Crea un ToolCall (argumentos ya como dict; arguments_error simula JSON roto)."""
    return ToolCall(id=call_id, name=name, arguments=args, arguments_error=arguments_error)


def tool_round(*calls: ToolCall) -> LLMResponse:
    """Ronda con tool_calls nativos: el runtime los ejecuta y sigue el loop."""
    return LLMResponse(content="", tool_calls=list(calls), finish_reason="tool_calls")


def send_response_round(
    text: str,
    *,
    intent: str | None = None,
    images: list[str] | None = None,
    keyboard: list[dict] | None = None,
    call_id: str = "send",
) -> LLMResponse:
    """Ronda con la tool terminal send_response (única en el lote)."""
    args: dict = {"text": text}
    if intent:
        args["intent"] = intent
    if images is not None:
        args["images"] = images
    if keyboard is not None:
        args["keyboard"] = keyboard
    return LLMResponse(
        content="",
        tool_calls=[ToolCall(id=call_id, name="send_response", arguments=args)],
        finish_reason="tool_calls",
    )


def plain_text(content: str) -> LLMResponse:
    """Respuesta final sin tools (contrato de respaldo del runtime)."""
    return LLMResponse(content=content, tool_calls=[], finish_reason="stop")


def truncated_response(partial: str = "Respuesta truncada por límite de token") -> LLMResponse:
    return LLMResponse(content=partial, tool_calls=[], finish_reason="length")


def invalid_json_response(bad_json: str = "esto no es json válido {") -> LLMResponse:
    return LLMResponse(content=bad_json, tool_calls=[], finish_reason="stop")


def empty_response() -> LLMResponse:
    return LLMResponse(content="", tool_calls=[], finish_reason="stop")


# ─────────────────────────────────────── Decision helpers (compatibilidad con tests existentes)

@dataclass
class SimpleDecision:
    """Decisión simple que se convierte en send_response."""
    text: str
    intent: str | None = None
    images: list[str] | None = None
    keyboard: list[dict] | None = None


@dataclass
class LLMDecisionBuilder:
    """Builder para decisiones complejas con keyboard y state_updates (compatibilidad)."""
    intent: str = "GENERAL"
    response_text: str = ""
    conversation: dict = field(default_factory=dict)
    actions: list[dict] = field(default_factory=list)
    state_updates: dict = field(default_factory=dict)

    def build(self) -> SimpleDecision:
        keyboard = None
        for action in self.actions:
            if action.get("type") == "show_keyboard":
                keyboard = action.get("keyboard")
                break
        return SimpleDecision(
            text=self.response_text,
            intent=self.intent,
            images=[],
            keyboard=keyboard,
        )


def final_decision(decision: SimpleDecision | LLMDecisionBuilder) -> LLMResponse:
    """Convierte una decisión en LLMResponse con tool send_response."""
    if isinstance(decision, LLMDecisionBuilder):
        decision = decision.build()
    return send_response_round(
        decision.text,
        intent=decision.intent,
        images=decision.images,
        keyboard=decision.keyboard,
    )


def search_decision(text: str, *, phase: str = "PROPERTY_SELECTION", property_code: str | None = None, intent: str = "SEARCH_PROPERTY") -> SimpleDecision:
    return SimpleDecision(text=text, intent=intent)


def greeting_decision(text: str | None = None) -> SimpleDecision:
    default = "¡Hola! Soy el asistente virtual de Epresedi. ¿En qué te puedo ayudar?"
    return SimpleDecision(text=text or default, intent="GREETING")


def property_details_decision(text: str, *, property_id: str | None = None, property_code: str | None = None) -> SimpleDecision:
    if property_code and property_code not in text:
        text = f"{text} Código: {property_code}"
    return SimpleDecision(text=text, intent="PROPERTY_DETAILS")


def appointment_select_datetime_decision(text: str, *, property_id: str | None = None) -> SimpleDecision:
    return SimpleDecision(text=text, intent="SCHEDULE_VISIT")


def appointment_collect_contact_decision(text: str, *, property_id: str | None = None, datetime_iso: str | None = None) -> SimpleDecision:
    return SimpleDecision(text=text, intent="SCHEDULE_VISIT")


def appointment_confirm_decision(text: str, *, property_id: str | None = None, datetime_iso: str | None = None) -> SimpleDecision:
    return SimpleDecision(text=text, intent="SCHEDULE_VISIT")


# ─────────────────────────────────────── helpers de teclado (payload corto)

def book_slot_button(property_id: str, datetime_iso: str, label: str | None = None) -> dict:
    return {
        "text": label or datetime_iso[:16],
        "action": "book_slot",
        "payload": {"property_id": property_id, "datetime_iso": datetime_iso},
    }


def confirm_booking_button(property_id: str, datetime_iso: str) -> dict:
    return {
        "text": "✅ Sí, confirmar",
        "action": "confirm_booking",
        "payload": {"property_id": property_id, "datetime_iso": datetime_iso},
    }


def cancel_booking_button(property_id: str) -> dict:
    return {
        "text": "❌ No, cancelar",
        "action": "cancel_booking",
        "payload": {"property_id": property_id},
    }


def search_then_send(final_text: str, *, intent: str = "SEARCH_PROPERTY") -> list:
    """Secuencia típica: 1 ronda de tools de búsqueda → send_response final."""
    return [
        tool_round(
            tc("update_conversation_state", {
                "intent": intent, "operation": "SALE", "property_type": "casa",
                "city": "Carepa",
            }),
            tc("search_properties", {
                "filters": {"property_type": "casa", "city": "Carepa"},
            }, call_id="c2"),
        ),
        send_response_round(final_text, intent=intent),
    ]


# ══════════════════════════════════════════════════════════════════════════
# Agente dinámico de flujo completo (decisión por evidencia real)
# ══════════════════════════════════════════════════════════════════════════
#
# Un solo callable decide en CADA ronda inspeccionando:
#   1. el texto del último mensaje del usuario,
#   2. los envelopes reales de las tools ejecutadas ESTE turno (role="tool"),
#   3. el estado conversacional validado (JSON del prompt de sistema).
#
# Es orden-independiente (sobrevive a cualquier secuencia de turnos) y
# demuestra causalidad: la respuesta se construye SOLO con datos que una
# tool devolvió de verdad (códigos, horarios, citas, chunks), nunca con
# guiones hardcodeados.

import re as _re

_STATE_MARKER = "# Estado conversacional validado (JSON)"
_BOOK_RE = _re.compile(
    r"(?:reservar|confirmo) la visita a la propiedad\s+([\w-]+)\s+el\s+([\dT:.+-]+)",
    _re.IGNORECASE,
)
_CANCEL_APPT_RE = _re.compile(r"cita\s+([0-9a-fA-F-]{36})")
_PROP_REF_RE = _re.compile(r"propiedad\s+([\w-]+)", _re.IGNORECASE)
_ORDINAL_RE = _re.compile(
    r"\b(primera?|primer[ao]|segund[ao]|tercer[ao]|cuart[ao]|quint[ao]|PROP-\d{4})\b",
    _re.IGNORECASE,
)
_PHONE_RE = _re.compile(r"\b\d{7,}\b")
_EMAIL_RE = _re.compile(r"\S+@\S+")
_N_APARTMENTS_RE = _re.compile(r"(\d+)\s*apartamentos", _re.IGNORECASE)


def _last_user_message(messages) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content") or ""
    return ""


def _user_texts(messages) -> list[str]:
    return [m.get("content") or "" for m in messages if m.get("role") == "user"]


def _turn_envelopes(messages) -> list[dict]:
    """Envelopes (JSON parseado) de las tools ejecutadas en el turno actual."""
    out: list[dict] = []
    for m in reversed(messages):
        if m.get("role") == "user":
            break
        if m.get("role") == "tool":
            try:
                out.append(json.loads(m["content"]))
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
    out.reverse()
    return out


def _ok_env(envelopes: list[dict], name: str) -> dict | None:
    return next((e for e in envelopes if e.get("tool") == name and e.get("ok")), None)


def _any_env(envelopes: list[dict], name: str) -> dict | None:
    return next((e for e in envelopes if e.get("tool") == name), None)


def _state_snapshot(messages) -> dict:
    """Estado conversacional validado (JSON que el backend embebe en el system prompt)."""
    for m in messages:
        if m.get("role") != "system":
            continue
        content = m.get("content") or ""
        i = content.find(_STATE_MARKER)
        if i < 0:
            return {}
        rest = content[i + len(_STATE_MARKER):].strip()
        rest = rest.split("\n\n#")[0].strip()
        try:
            return json.loads(rest)
        except json.JSONDecodeError:
            return {}
    return {}


def _card_keyboard(code: str) -> list[dict]:
    """Ficha de propiedad: detalles, fotos, guardar y agendar (payload = código)."""
    return [
        {"text": "📋 Detalles", "action": "details", "payload": code},
        {"text": "📷 Fotos", "action": "images", "payload": code},
        {"text": "⭐ Guardar", "action": "save", "payload": code},
        {"text": "📅 Agendar visita", "action": "slots", "payload": code},
    ]


def _contact_from_history(messages) -> str | None:
    """Nombre/celular/correo del último mensaje del usuario que los aportó."""
    for text in reversed(_user_texts(messages)):
        phone = _PHONE_RE.search(text)
        email = _EMAIL_RE.search(text)
        if phone and email:
            first_line = text.strip().splitlines()[0].strip()
            return f"{first_line}\n{phone.group(0)}\n{email.group(0)}"
    return None


def _booked_slot_from_history(messages) -> tuple[str, str] | None:
    """(ref, datetime) de la reserva en curso: el botón book_slot/confirm más reciente."""
    for text in reversed(_user_texts(messages)):
        m = _BOOK_RE.search(text)
        if m:
            return m.group(1), m.group(2)[:16]
    return None


def make_flow_agent(*, search_filters: dict | None = None, search_query: str = "búsqueda del cliente"):
    """Agente de decisión dinámico para flujos conversacionales completos.

    Cada texto final se construye a partir de la evidencia real (envelopes de
    tools + estado validado); las mutaciones usan datos confirmados por las
    tools de este mismo turno o por el historial. Las fases/booking_states
    propuestos están en la lista blanca de ``app.agents.state``.
    """
    filters = dict(search_filters or {"property_type": "casa", "city": "Carepa"})

    def agent(messages, tools):
        raw = _last_user_message(messages)
        u = raw.lower()
        state = _state_snapshot(messages)
        envs = _turn_envelopes(messages)

        # ─── Ronda de seguimiento: este turno ya tiene evidencia de tools ──
        if envs:
            booked = _ok_env(envs, "schedule_visit")
            if booked:
                appt = (booked.get("data") or {}).get("appointment") or {}
                when = ""
                slot = _booked_slot_from_history(messages)
                if slot:
                    when = slot[1].replace("T", " ")
                if not when:
                    when = str(appt.get("scheduled_at") or "")[:16].replace("T", " ")
                return send_response_round(
                    f"✅ Cita confirmada para {appt.get('code')} el {when}. "
                    "Te esperamos; si necesitas cambiarla, avísame.",
                    intent="SCHEDULE_VISIT",
                    keyboard=[{"text": "✖️ Cancelar cita", "action": "cancel_appt", "payload": appt.get("id")}],
                )
            cancelled = _any_env(envs, "cancel_appointment")
            if cancelled:
                return send_response_round(
                    "Listo, tu cita fue cancelada. ¿Te ayudo con algo más?",
                    intent="CANCEL_APPOINTMENT",
                )
            slots_env = _ok_env(envs, "list_available_slots")
            if slots_env:
                slots = (slots_env.get("data") or {}).get("slots") or []
                prop_id = state.get("last_property_id") or state.get("selected_property_id") or state.get("selected_property_code")
                kb = []
                for s in slots[:4]:
                    when = str(s.get("datetime_local") or s.get("datetime") or "")[:16]
                    if not when:
                        continue
                    kb.append({
                        "text": str(s.get("label") or when),
                        "action": "book_slot",
                        "payload": {"property_id": prop_id, "datetime_iso": when,
                                    "label": s.get("label") or when},
                    })
                if not kb:
                    return send_response_round(
                        "No tengo horarios disponibles por ahora. ¿Probamos otro día?",
                        intent="SCHEDULE_VISIT",
                    )
                return send_response_round(
                    "Estos horarios están disponibles. Elige uno para reservar tu visita:",
                    intent="SCHEDULE_VISIT", keyboard=kb,
                )
            prop_env = _ok_env(envs, "get_property")
            if prop_env:
                prop = (prop_env.get("data") or {}).get("property") or {}
                if _any_env(envs, "update_conversation_state"):
                    code = prop.get("code") or ""
                    price = prop.get("price")
                    price_txt = f"${price:,.0f}".replace(",", ".") if price else "precio a consultar"
                    return send_response_round(
                        f"{prop.get('title')}\n{prop.get('description') or ''}\n\n"
                        f"{price_txt} · {prop.get('bedrooms') or '?'} habitaciones · "
                        f"{prop.get('bathrooms') or '?'} baños\nCódigo: {code}",
                        intent="PROPERTY_DETAILS", keyboard=_card_keyboard(code),
                    )
                # Fase solo cuando la transición es válida (p.ej. tras una cita
                # completada, APPOINTMENT_COMPLETED → PROPERTY_DETAILS no existe).
                upd = {
                    "intent": "PROPERTY_DETAILS",
                    "selected_property_id": prop.get("id"),
                    "selected_property_code": prop.get("code"),
                }
                cur = str(state.get("phase") or "")
                if cur in ("", "IDLE", "SEARCHING", "PROPERTY_SELECTION",
                           "GENERAL", "APPOINTMENT_SELECTION"):
                    upd["phase"] = "PROPERTY_DETAILS"
                return tool_round(
                    tc("update_conversation_state", upd, call_id="st-details"),
                )
            search_env = _ok_env(envs, "search_properties")
            if search_env:
                props = (search_env.get("data") or {}).get("properties") or []
                codes = [p.get("code") for p in props[:4] if p.get("code")]
                count = (search_env.get("metadata") or {}).get("count", len(props))
                if not codes:
                    return send_response_round(
                        "No encontré propiedades con esos criterios. "
                        "¿Quieres relajar algún filtro o crear una alerta?",
                        intent="SEARCH_PROPERTY",
                    )
                return send_response_round(
                    f"Encontré {count} propiedades: {', '.join(codes)}. "
                    "Dime «la primera» para ver la ficha de la más relevante.",
                    intent="SEARCH_PROPERTY",
                )
            img_env = _ok_env(envs, "get_property_images")
            if img_env:
                data = img_env.get("data") or {}
                code = data.get("property_code") or state.get("selected_property_code") or ""
                images = [data.get("property_id")] if data.get("property_id") else []
                return send_response_round(
                    f"Estas son las fotos de {code}." if code else "Estas son las fotos.",
                    intent="PROPERTY_IMAGES", images=images,
                )
            docs_env = _ok_env(envs, "search_documents")
            if docs_env:
                chunks = (docs_env.get("data") or {}).get("chunks") or []
                for ch in chunks:
                    m = _N_APARTMENTS_RE.search(ch.get("content") or "")
                    if m:
                        title = ch.get("title") or ch.get("filename") or "documento"
                        return send_response_round(
                            f"Según la documentación: {m.group(1)} apartamentos. Fuente: {title}",
                            intent="PROPERTY_DOCUMENT_QUESTION",
                        )
                return send_response_round(
                    "No tengo información confirmada sobre eso en los documentos.",
                    intent="PROPERTY_DOCUMENT_QUESTION",
                )
            save_env = _ok_env(envs, "save_property")
            if save_env:
                return send_response_round(
                    "Guardada en tus favoritos. ⭐ ¿Quieres agendar una visita?",
                    intent="SAVE_PROPERTY",
                )
            cmp_env = _ok_env(envs, "compare_properties")
            if cmp_env:
                props = (cmp_env.get("data") or {}).get("properties") or []
                codes = [p.get("code") for p in props if p.get("code")]
                return send_response_round(
                    "Comparación de " + ", ".join(codes) + ". "
                    "Revisa precios y características de cada una; dime cuál te interesa.",
                    intent="COMPARE_PROPERTIES",
                )
            if _any_env(envs, "update_conversation_state"):
                # Estado registrado; falta la respuesta final del turno.
                # Check if we just set booking_state to "esperando_horario" (FASE A)
                upd_env = _any_env(envs, "update_conversation_state")
                applied = (upd_env.get("data") or {}).get("applied") or {}
                if applied.get("booking_state") == "esperando_horario":
                    # FASE A: User asked to schedule without date/time -> respond with business hours
                    return send_response_round(
                        "Claro. Para visitar esta propiedad puedes agendar de lunes a viernes "
                        "de 8:00 a. m. a 6:00 p. m. y los sábados de 9:00 a. m. a 3:00 p. m. "
                        "Los domingos no hay citas.\n\n"
                        "¿Qué día y hora te gustaría?",
                        intent="SCHEDULE_VISIT",
                    )
                if "reservar la visita" in u:
                    code = state.get("selected_property_code") or ""
                    return send_response_round(
                        "Para confirmar tu cita necesito tus datos de contacto:\n\n"
                        "• Nombre completo\n• Celular\n• Correo electrónico",
                        intent="SCHEDULE_VISIT",
                        keyboard=[cancel_booking_button(code)],
                    )
                if _PHONE_RE.search(u) and _EMAIL_RE.search(u):
                    code = state.get("selected_property_code") or ""
                    slot = _booked_slot_from_history(messages) or (code, "")
                    when_txt = slot[1].replace("T", " ")
                    name = raw.strip().splitlines()[0].strip() if raw.strip() else ""
                    phone = _PHONE_RE.search(u).group(0)
                    email = _EMAIL_RE.search(u).group(0)
                    return send_response_round(
                        f"Por favor confirma tu cita, {name}: celular {phone}, correo {email}. "
                        f"Propiedad {code}, el {when_txt}.",
                        intent="SCHEDULE_VISIT",
                        keyboard=[confirm_booking_button(code, slot[1]), cancel_booking_button(code)],
                    )
            return plain_text(
                "No pude completar la operación con la información disponible. ¿Intentamos de nuevo?"
            )

        # ─── Nueva decisión (sin tools ejecutadas este turno) ───────────────
        m = _BOOK_RE.search(u)
        if m and "confirmo" in u:
            slot = _booked_slot_from_history(messages) or (m.group(1), m.group(2)[:16])
            args = {"property_id": slot[0], "datetime_iso": slot[1]}
            contact = _contact_from_history(messages)
            if contact:
                args["notes"] = contact
            return tool_round(
                tc("schedule_visit", args, call_id="sv"),
                tc("update_conversation_state", {
                    "booking_state": "agendado", "phase": "APPOINTMENT_COMPLETED",
                    "intent": "SCHEDULE_VISIT",
                }, call_id="st-confirm"),
            )
        if m and "reservar" in u:
            return tool_round(
                tc("update_conversation_state", {
                    "intent": "SCHEDULE_VISIT", "phase": "APPOINTMENT_CONFIRMATION",
                    "booking_state": "esperando_datos",
                }, call_id="st-datos"),
            )
        if "cancela mi cita" in u or "cancela ese agendamiento" in u:
            cm = _CANCEL_APPT_RE.search(u)
            appt_id = cm.group(1) if cm else state.get("last_appointment_id")
            if appt_id:
                return tool_round(
                    tc("cancel_appointment", {"appointment_id": appt_id}, call_id="ca"),
                    tc("update_conversation_state", {
                        "intent": "CANCEL_APPOINTMENT", "phase": "IDLE", "booking_state": None,
                    }, call_id="st-cancel"),
                )
        # Helper: detect date/time expressions in user message
        def _has_datetime_expr(text: str) -> bool:
            import re as _re_dt
            _DT_PATTERNS = [
                r"\b(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[áa]bado|domingo)\b.*\b\d{1,2}:\d{2}\b",  # "martes a las 10:00"
                r"\b(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[áa]bado|domingo)\b.*\b(?:a\s+las?|a\s+la)\s+\d{1,2}\b",  # "martes a las 10"
                r"\b(?:mañana|pasado\s+mañana)\b.*\b\d{1,2}\b",  # "mañana a las 10"
                r"\b\d{1,2}\s+de\s+\w+\b.*\b\d{1,2}\b",  # "22 de septiembre a las 10"
                r"\bel\s+\d{1,2}\b.*\b\d{1,2}\b",  # "el 22 a las 10"
                r"\b(?:pr[oó]ximo|esta|este)\s+(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[áa]bado)\b.*\b\d{1,2}\b",  # "próximo martes a las 10"
                r"\b(?:en\s+la\s+(?:mañana|tarde)|despu[eé]s\s+de\s+las?\s+\d{1,2}|a\s+las\s+\d{1,2}\s*(?:am|pm)?)\b",  # "en la mañana", "después de las 2", "a las 5 pm"
            ]
            return any(_re_dt.search(p, text, _re_dt.IGNORECASE) for p in _DT_PATTERNS)
        
        # Check if we're in a scheduling flow and user provides date/time
        booking_state = state.get("booking_state", "")
        in_scheduling_flow = booking_state in ("esperando_horario", "mostrando_horarios", "esperando_datos", "listo_para_confirmar", "confirmando")
        
        explicitly_asks_for_slots = "horarios disponibles" in u
        
        if ("horarios disponibles" in u or "agendar" in u or "agenda una cita" in u) or (in_scheduling_flow and _has_datetime_expr(u)):
            pm = _PROP_REF_RE.search(raw)
            ref = pm.group(1) if pm else None
            if not ref:
                ref = state.get("last_property_id") or state.get("selected_property_code")
            
            has_datetime = _has_datetime_expr(u)
            
            # If user explicitly asks for "horarios disponibles" (e.g., via slots button),
            # show available slots even without a specific date/time (FASE B without exact datetime)
            if explicitly_asks_for_slots and not has_datetime and not in_scheduling_flow:
                return tool_round(
                    tc("update_conversation_state", {
                        "intent": "SCHEDULE_VISIT", "phase": "APPOINTMENT_SELECTION",
                        "booking_state": "mostrando_horarios",
                    }, call_id="st-slots"),
                    tc("list_available_slots", {"property_id": ref}, call_id="ls"),
                )
            
            if not has_datetime and not in_scheduling_flow:
                # FASE A: No date/time provided -> update state to track we're waiting for date/time
                # Also store the property reference if mentioned
                state_update = {
                    "intent": "SCHEDULE_VISIT", "phase": "APPOINTMENT_SELECTION",
                    "booking_state": "esperando_horario",
                }
                if ref:
                    # Try to resolve ref to property ID
                    if ref.startswith("PROP-"):
                        state_update["selected_property_code"] = ref
                    else:
                        state_update["selected_property_id"] = ref
                return tool_round(
                    tc("update_conversation_state", state_update, call_id="st-wait-dt"),
                )
            
            # FASE B: Date/time provided (or continuing scheduling flow) -> validate before calling list_available_slots
            # Check for Sunday (closed) and other obviously invalid times
            if _has_datetime_expr(u):
                # Simple validation: check for Sunday
                if "domingo" in u:
                    return send_response_round(
                        "Ese horario está fuera del horario de visitas. "
                        "De lunes a viernes atendemos de 8:00 a. m. a 6:00 p. m. "
                        "y los sábados de 9:00 a. m. a 3:00 p. m. "
                        "Los domingos no hay citas. ¿Qué otro horario te gustaría?",
                        intent="SCHEDULE_VISIT",
                    )
                # Check for obviously outside hours (19:00+, 07:00-, etc.)
                # Pattern for hour mentions
                import re as _re_hr
                _hr_match = _re_hr.search(r'\b(\d{1,2})\s*(?::\d{2})?\s*(?:am|pm|a\.?\s*m\.?|p\.?\s*m\.?)?\b', u)
                if _hr_match:
                    try:
                        hr = int(_hr_match.group(1))
                        # Check if hour suggests outside business hours
                        # (simplified: 19-23 or 0-7 are likely outside)
                        if hr >= 19 or hr <= 7:
                            return send_response_round(
                                "Ese horario está fuera del horario de visitas. "
                                "De lunes a viernes atendemos de 8:00 a. m. a 6:00 p. m. "
                                "y los sábados de 9:00 a. m. a 3:00 p. m. "
                                "Los domingos no hay citas. ¿Qué otro horario te gustaría?",
                                intent="SCHEDULE_VISIT",
                            )
                    except (ValueError, IndexError):
                        pass
            
            return tool_round(
                tc("update_conversation_state", {
                    "intent": "SCHEDULE_VISIT", "phase": "APPOINTMENT_SELECTION",
                    "booking_state": "mostrando_horarios",
                }, call_id="st-slots"),
                tc("list_available_slots", {"property_id": ref}, call_id="ls"),
            )
        if _PHONE_RE.search(u) and _EMAIL_RE.search(u):
            # Extract name (first line), phone, email
            lines = raw.strip().splitlines()
            name = lines[0].strip() if lines else ""
            phone = _PHONE_RE.search(u).group(0)
            email = _EMAIL_RE.search(u).group(0)
            return tool_round(
                tc("create_lead", {"name": name, "phone": phone, "email": email}, call_id="cl"),
                tc("update_conversation_state", {
                    "intent": "SCHEDULE_VISIT", "booking_state": "listo_para_confirmar",
                }, call_id="st-contacto"),
            )
        if "imagen" in u or "imágen" in u or "foto" in u:
            ref = state.get("last_property_id") or state.get("selected_property_code")
            # Detectar petición singular: "una imagen", "una foto", "una sola", "solo una"
            import re as _re_local
            import unicodedata as _unicodedata_local
            u_no_accents = "".join(c for c in _unicodedata_local.normalize("NFD", u) if not _unicodedata_local.combining(c))
            is_singular = bool(_re_local.search(
                r"\b(?:una\s+sola|solo\s+una|solamente\s+una|mu[eé]strame\s+una|ens[eé]name\s+una|"
                r"quiero\s+ver\s+una|dame\s+una|env[ií]ame\s+una|mandame\s+una|"
                r"quiero\s+una|necesito\s+una)\s+(?:imagen|foto|fotografia)\b", u_no_accents
            ))
            # También detectar "una imagen de PROP-XXXX" o similar
            if not is_singular:
                is_singular = bool(_re_local.search(
                    r"\buna\s+(?:imagen|foto|fotografia)\s+(?:de|del|la|el)", u_no_accents
                ))
            limit = 1 if is_singular else None
            args = {"property_id": ref}
            if limit:
                args["limit"] = limit
            return tool_round(tc("get_property_images", args, call_id="gi"))
        if ("cuántos" in u or "cuantos" in u or "financiaci" in u
                or "reglamento" in u or "documentos" in u):
            return tool_round(tc("search_documents", {"query": raw}, call_id="sd"))
        if "guarda" in u or "guárdame" in u or "favorit" in u:
            ref = state.get("selected_property_code") or state.get("last_property_id")
            return tool_round(tc("save_property", {"property_id": ref}, call_id="sp"))
        if "compara" in u or "compá" in u:
            codes = [r.get("code") for r in (state.get("last_results") or []) if r.get("code")][:2]
            return tool_round(tc("compare_properties", {"property_refs": codes}, call_id="cp"))
        if u.strip().startswith("hola") and len(u.strip()) <= 24:
            return send_response_round(
                "¡Hola! Soy el asistente virtual de Epresedi. ¿En qué te puedo ayudar?",
                intent="GREETING",
            )
        if any(k in u for k in ("busca", "busco", "quiero comprar", "deseo comprar", "comprar una")):
            state_args: dict = {"intent": "SEARCH_PROPERTY", "phase": "PROPERTY_SELECTION"}
            if filters.get("property_type"):
                state_args["property_type"] = filters["property_type"]
            if filters.get("city"):
                state_args["city"] = filters["city"]
            if filters.get("max_price") is not None:
                state_args["budget_max"] = filters["max_price"]
            if filters.get("bedrooms") is not None:
                state_args["bedrooms"] = filters["bedrooms"]
            return tool_round(
                tc("update_conversation_state", state_args, call_id="st-search"),
                tc("search_properties", {"filters": filters, "semantic_query": search_query},
                   call_id="sp"),
            )
        om = _ORDINAL_RE.search(u)
        if om:
            return tool_round(tc("get_property", {"property_ref": om.group(1).lower()}, call_id="gp"))
        if "detalles" in u or "ficha" in u:
            pm = _PROP_REF_RE.search(u)
            ref = pm.group(1) if pm else state.get("selected_property_code")
            return tool_round(tc("get_property", {"property_ref": ref}, call_id="gp"))
        return plain_text(
            "No entendí tu mensaje. ¿Buscas una propiedad, quieres ver una ficha o agendar una visita?"
        )

    return agent
