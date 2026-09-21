"""Estado conversacional estructurado: la superficie de decisión del LLM.

El LLM PROPONE actualizaciones de estado llamando a la herramienta
``update_conversation_state``; este módulo las VALIDA (tipos, rangos, enums,
lista blanca de campos) antes de tocar ``conversation.state``. Una propuesta
inválida se rechaza con un motivo que vuelve al modelo, nunca corrompe el estado.

El pipeline determinista y el loop LLM-first leen exactamente el mismo estado,
así ambos cerebros son compatibles durante la migración (LLM-FIRST /
DETERMINISTIC-SAFETY, ver docs/architecture.md).
"""
from __future__ import annotations

import uuid as uuid_mod
from enum import Enum

from app.agents.intents import Intent

# --------------------------------------------------------------------- phases


class ConversationPhase(str, Enum):
    """Fases conversacionales. El backend valida las transiciones; el LLM opera dentro."""

    IDLE = "IDLE"
    SEARCHING = "SEARCHING"
    PROPERTY_SELECTION = "PROPERTY_SELECTION"
    PROPERTY_DETAILS = "PROPERTY_DETAILS"
    APPOINTMENT_SELECTION = "APPOINTMENT_SELECTION"
    APPOINTMENT_CONFIRMATION = "APPOINTMENT_CONFIRMATION"
    APPOINTMENT_COMPLETED = "APPOINTMENT_COMPLETED"
    GENERAL = "GENERAL"
    ERROR = "ERROR"


PHASE_TRANSITIONS: dict[ConversationPhase, set[ConversationPhase]] = {
    ConversationPhase.IDLE: {
        ConversationPhase.SEARCHING, ConversationPhase.PROPERTY_SELECTION,
        ConversationPhase.PROPERTY_DETAILS, ConversationPhase.APPOINTMENT_SELECTION,
        ConversationPhase.GENERAL, ConversationPhase.ERROR,
    },
    ConversationPhase.SEARCHING: {
        ConversationPhase.PROPERTY_SELECTION, ConversationPhase.PROPERTY_DETAILS,
        ConversationPhase.IDLE, ConversationPhase.GENERAL, ConversationPhase.ERROR,
    },
    ConversationPhase.PROPERTY_SELECTION: {
        ConversationPhase.PROPERTY_DETAILS, ConversationPhase.APPOINTMENT_SELECTION,
        ConversationPhase.SEARCHING, ConversationPhase.GENERAL,
        ConversationPhase.IDLE, ConversationPhase.ERROR,
    },
    ConversationPhase.PROPERTY_DETAILS: {
        ConversationPhase.APPOINTMENT_SELECTION, ConversationPhase.PROPERTY_SELECTION,
        ConversationPhase.SEARCHING, ConversationPhase.GENERAL,
        ConversationPhase.IDLE, ConversationPhase.ERROR,
    },
    ConversationPhase.APPOINTMENT_SELECTION: {
        ConversationPhase.APPOINTMENT_CONFIRMATION, ConversationPhase.APPOINTMENT_COMPLETED,
        ConversationPhase.PROPERTY_DETAILS, ConversationPhase.IDLE, ConversationPhase.ERROR,
    },
    ConversationPhase.APPOINTMENT_CONFIRMATION: {
        ConversationPhase.APPOINTMENT_COMPLETED, ConversationPhase.APPOINTMENT_SELECTION,
        ConversationPhase.IDLE, ConversationPhase.ERROR,
    },
    ConversationPhase.APPOINTMENT_COMPLETED: {
        ConversationPhase.IDLE, ConversationPhase.SEARCHING,
        ConversationPhase.PROPERTY_SELECTION, ConversationPhase.ERROR,
    },
    ConversationPhase.GENERAL: {
        ConversationPhase.IDLE, ConversationPhase.SEARCHING,
        ConversationPhase.PROPERTY_DETAILS, ConversationPhase.ERROR,
    },
    ConversationPhase.ERROR: {
        ConversationPhase.IDLE, ConversationPhase.SEARCHING,
        ConversationPhase.GENERAL, ConversationPhase.ERROR,
    },
}


def phase_for_booking_state(booking_state: str | None) -> ConversationPhase | None:
    """Maps the deterministic booking state machine onto a conversation phase."""
    if not booking_state:
        return None
    low = str(booking_state).lower()
    if low in ("agendado",):
        return ConversationPhase.APPOINTMENT_COMPLETED
    if low in ("confirmando", "listo_para_confirmar"):
        return ConversationPhase.APPOINTMENT_CONFIRMATION
    if low.startswith("esperando_") or low == "mostrando_horarios":
        return ConversationPhase.APPOINTMENT_SELECTION
    return None


def validate_phase_transition(current: str | None, new: str) -> tuple[bool, str]:
    """Never allows an invalid phase jump. Unknown current phase → allow (bootstrap)."""
    try:
        target = ConversationPhase(new)
    except ValueError:
        return False, f"phase inválida: {new!r}"
    if not current:
        return True, ""
    try:
        origin = ConversationPhase(current)
    except ValueError:
        return True, ""
    if origin == target or target in PHASE_TRANSITIONS.get(origin, set()):
        return True, ""
    return False, f"transición inválida {origin.value} → {target.value}"


# ---------------------------------------------------------------- field specs

PROPERTY_TYPES = ("casa", "apartamento", "lote", "local", "oficina", "finca", "proyecto")
OPERATIONS = ("SALE", "RENT")
BOOKING_STATES = (
    "esperando_inicio", "mostrando_horarios", "esperando_horario", "esperando_datos",
    "esperando_nombre", "esperando_celular", "esperando_correo", "listo_para_confirmar",
    "confirmando", "agendado",
)
INTENT_VALUES = tuple(i.value for i in Intent)
MISSING_FIELDS = (
    "operation", "property_type", "city", "budget_max", "bedrooms",
    "property", "datetime", "contact",
)
MAX_PRICE = 1e13  # COP: techo absurdo pero finito; evita contaminar filtros SQL
MAX_COUNT = 50

# Estado que el LLM puede proponer. Todo lo demás (last_results, last_filters,
# last_property_id...) lo escriben las herramientas: el modelo NO los toca.
FIELD_SPECS: dict[str, tuple[str, object]] = {
    "awaiting_search_refinement": ("bool", None),
    "last_search_had_results": ("bool", None),
    "intent": ("enum", INTENT_VALUES),
    "operation": ("enum", OPERATIONS),
    "property_type": ("enum", PROPERTY_TYPES),
    "city": ("text", 80),
    "neighborhood": ("text", 80),
    "budget_min": ("number", (0.0, MAX_PRICE)),
    "budget_max": ("number", (0.0, MAX_PRICE)),
    "bedrooms": ("int", (0, MAX_COUNT)),
    "bathrooms": ("int", (0, MAX_COUNT)),
    "parking": ("int", (0, MAX_COUNT)),
    "min_area": ("number", (0.0, 100_000.0)),
    "selected_property_id": ("uuid", None),
    "selected_property_code": ("text", 40),
    "booking_state": ("enum", BOOKING_STATES),
    "phase": ("enum", tuple(p.value for p in ConversationPhase)),
    "missing_fields": ("strlist", MISSING_FIELDS),
    "notes": ("text", 300),
    "agent_introduced": ("bool", None),
}

LLM_OWNED_FIELDS = frozenset(FIELD_SPECS)


def _clean_text(value: object, max_len: int) -> str:
    return str(value).strip().replace("\n", " ")[:max_len]


def _validate_field(key: str, value: object, state: dict) -> tuple[object | None, str]:
    """Returns (validated_value, "") or (None, reason). Never raises."""
    kind, spec = FIELD_SPECS[key]
    if value is None:
        return None, ""  # explicit clear is allowed
    if kind == "text":
        text = _clean_text(value, int(spec))
        return (text or None), ""
    if kind == "enum":
        candidate = str(value).strip()
        if candidate not in spec:  # type: ignore[operator]
            return None, f"{key}={candidate!r} no es un valor permitido"
        if key == "phase":
            ok, reason = validate_phase_transition(state.get("phase"), candidate)
            if not ok:
                return None, reason
        return candidate, ""
    if kind == "uuid":
        try:
            return str(uuid_mod.UUID(str(value).strip())), ""
        except (ValueError, AttributeError, TypeError):
            return None, f"{key} no es un UUID válido"
    if kind == "int":
        try:
            num = int(value)
        except (TypeError, ValueError):
            return None, f"{key} debe ser entero"
        low, high = spec  # type: ignore[misc]
        if not low <= num <= high:
            return None, f"{key} fuera de rango [{low}, {high}]"
        return num, ""
    if kind == "number":
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None, f"{key} debe ser numérico"
        low, high = spec  # type: ignore[misc]
        if not low <= num <= high:
            return None, f"{key} fuera de rango [{low:,.0f}, {high:,.0f}]"
        return num, ""
    if kind == "strlist":
        if not isinstance(value, (list, tuple)):
            return None, f"{key} debe ser una lista"
        cleaned = [str(v).strip() for v in value if str(v).strip() in spec]  # type: ignore[operator]
        return cleaned, ""
    return None, f"{key} sin validador"


def merge_state_update(state: dict, patch: dict) -> tuple[dict, list[str]]:
    """Validates and merges an LLM state proposal. Returns (applied, rejected)."""
    applied: dict = {}
    rejected: list[str] = []
    if not isinstance(patch, dict):
        return applied, ["el estado propuesto debe ser un objeto JSON"]
    for key, value in patch.items():
        if key not in FIELD_SPECS:
            rejected.append(f"campo no permitido: {key}")
            continue
        draft = {**state, **applied}
        validated, reason = _validate_field(key, value, draft)
        if reason:
            rejected.append(reason)
            continue
        applied[key] = validated
    for key, value in applied.items():
        state[key] = value
    return applied, rejected


# ------------------------------------------------------------- prompt helpers

_STATE_PROMPT_FIELDS = (
    "intent", "operation", "property_type", "city", "neighborhood",
    "budget_min", "budget_max", "bedrooms", "bathrooms", "parking",
    "selected_property_code", "selected_property_id", "booking_state", "phase",
    "missing_fields", "agent_introduced", "awaiting_search_refinement",
    "last_search_had_results",
)


def compact_state(state: dict) -> dict:
    """Small JSON-safe snapshot of the decision state (no secrets, no raw rows)."""
    snapshot = {k: state[k] for k in _STATE_PROMPT_FIELDS if state.get(k) not in (None, "", [], {})}
    results = state.get("last_results") or []
    if results:
        snapshot["last_results"] = [
            {
                "position": i + 1,
                "code": r.get("code"),
                "title": r.get("title"),
                "price": r.get("price"),
                "city": r.get("city"),
                "bedrooms": r.get("bedrooms"),
                "property_type": r.get("property_type"),
                "status": r.get("status"),
            }
            for i, r in enumerate(results[:8])
        ]
        snapshot["last_search_had_results"] = True
    else:
        # Explicitly signal that a search was attempted but returned no results
        if state.get("last_filters"):
            snapshot["last_search_had_results"] = False
    filters = state.get("last_filters") or {}
    if filters:
        snapshot["last_filters"] = {k: v for k, v in filters.items() if k != "query_text"}
    if state.get("last_property_id"):
        snapshot["last_property_id"] = state["last_property_id"]
    if state.get("last_appointment_id"):
        snapshot["last_appointment_id"] = state["last_appointment_id"]
    # Trazabilidad del turno anterior: evita llamadas redundantes (el agente ve
    # qué tools ya ejecutó y con qué resultado).
    if state.get("last_turn_tools"):
        snapshot["last_turn_tools"] = state["last_turn_tools"]
    # Track if we're awaiting user confirmation to refine search
    if state.get("awaiting_search_refinement"):
        snapshot["awaiting_search_refinement"] = True
    return snapshot


def describe_state(state: dict) -> str:
    """Human/LLM readable JSON of the current decision state."""
    import json

    return json.dumps(compact_state(state), ensure_ascii=False, default=str)