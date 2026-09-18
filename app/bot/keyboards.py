"""Inline keyboards built from AgentReply actions. Buttons add value, menus don't.

Telegram Bot API hard limit: callback_data must be a 1-64 byte UTF-8 string
(otherwise the API rejects the whole message with BUTTON_DATA_INVALID).
build_keyboard() validates every button and drops invalid ones (with a
diagnostic warning) instead of producing markup Telegram would reject.
"""
from __future__ import annotations

import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.logging import get_logger

log = get_logger(__name__)

MAX_CALLBACK_BYTES = 64

ACTION_LABELS = {
    "details": "🔎 Ver detalles",
    "images": "📷 Ver fotos",
    "save": "⭐ Guardar",
    "compare": "⚖️ Comparar",
    "slots": "📅 Agendar visita",
    "contact_agent": "👤 Hablar con asesor",
    "docs": "📄 Ver documentos",
    "location": "🗺 Ubicación",
    "book_slot": None,  # label = slot time
    "cancel_appt": "✖️ Cancelar cita",
    "save_search": "🔔 Crear alerta",
    "share_contact": None,
}


def validate_callback_data(data: object) -> bool:
    """True when callback_data is a non-empty string of at most 64 bytes."""
    if not isinstance(data, str) or not data:
        return False
    try:
        size = len(data.encode("utf-8"))
    except UnicodeEncodeError:
        return False
    return size <= MAX_CALLBACK_BYTES


def _cb(action: str, payload) -> str:
    if payload is None:
        return action
    if isinstance(payload, dict):
        return f"{action}:{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    return f"{action}:{payload}"


def _book_slot_callback(payload: dict) -> str:
    """Compact, stable slot reference: book_slot:{property_id}:{local datetime}.

    The property id (UUID or code) is resolved server-side by _find_property;
    the datetime is business-local naive (schedule_visit interprets naive
    values in the business timezone). Full slot dicts, labels or UTC offsets
    never reach callback_data.
    """
    ref = str(payload.get("property_id") or "")
    when = str(payload.get("datetime_iso") or payload.get("datetime") or "")[:16]
    if not (ref and when):
        return ""
    return f"book_slot:{ref}:{when}"


def _resolve_button(action: str, payload) -> tuple[str | None, str]:
    """Maps (action, payload) to (label, callback_data); label None → drop."""
    if action == "book_slot":
        if isinstance(payload, dict):
            label = payload.get("label") or str(payload.get("datetime_iso") or "")[:16]
            return f"📅 {label}", _book_slot_callback(payload)
        return f"📅 {payload}", _cb(action, payload)
    if action == "cancel_appt":
        return ACTION_LABELS[action], _cb(action, payload)
    label = ACTION_LABELS.get(action)
    if label is None:
        return None, ""
    return label, _cb(action, payload)


def build_keyboard(actions: list[tuple]) -> InlineKeyboardMarkup | None:
    """Maps orchestrator actions to inline keyboard rows (max 2 per row).

    Buttons whose callback_data violates the Telegram 64-byte limit are
    dropped with a warning so the Bot API never receives invalid markup."""
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    for action, payload in actions:
        label, callback = _resolve_button(action, payload)
        if label is None:
            continue
        if not validate_callback_data(callback):
            size = len(callback.encode("utf-8", errors="replace")) if isinstance(callback, str) else -1
            log.warning(
                "invalid_callback_data action=%s text=%r callback=%r length=%s limit=%d",
                action, label, callback, size, MAX_CALLBACK_BYTES,
            )
            continue
        log.debug(
            "keyboard_button action=%s text=%r callback=%r length=%d",
            action, label, callback, len(callback.encode("utf-8")),
        )
        current.append(InlineKeyboardButton(label, callback_data=callback))
        if len(current) >= 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    return InlineKeyboardMarkup(rows) if rows else None


def parse_callback(data: str) -> tuple[str, object]:
    action, _, raw = data.partition(":")
    if raw.startswith("{"):
        try:
            return action, json.loads(raw)
        except json.JSONDecodeError:
            return action, raw
    if action == "book_slot" and raw:
        ref, _, when = raw.partition(":")
        return action, {"property_id": ref, "datetime_iso": when}
    return action, raw
