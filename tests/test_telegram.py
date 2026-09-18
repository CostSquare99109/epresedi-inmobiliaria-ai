"""Telegram layer: keyboards, callback parsing, command registration, handlers."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bot.keyboards import build_keyboard, parse_callback
from app.database.base import AsyncSessionLocal


# ---------------------------------------------------------------- keyboards
def test_build_keyboard_rows_and_labels():
    kb = build_keyboard([("details", "abc"), ("save", "abc"), ("compare", "abc"), ("slots", "abc")])
    assert kb is not None
    rows = kb.inline_keyboard
    assert len(rows) == 2  # pairs of two
    flat = [b for row in rows for b in row]
    labels = [b.text for b in flat]
    assert "🔎 Ver detalles" in labels
    assert "⭐ Guardar" in labels
    assert "⚖️ Comparar" in labels
    assert "📅 Agendar visita" in labels


def test_build_keyboard_book_slot_uses_time_label():
    payload = {"label": "lun 05 oct 10:00", "datetime_iso": "2026-10-05T10:00:00", "property_id": "p1"}
    kb = build_keyboard([("book_slot", payload)])
    assert kb.inline_keyboard[0][0].text == "📅 lun 05 oct 10:00"


def test_build_keyboard_empty_returns_none():
    assert build_keyboard([]) is None
    assert build_keyboard([("unknown_action", "x")]) is None  # labels without value are dropped


def test_callback_roundtrip():
    action, payload = parse_callback("details:abc-123")
    assert action == "details" and payload == "abc-123"
    action, payload = parse_callback(f"book_slot:{json.dumps({'label': 'lun', 'property_id': 'p1'})}")
    assert action == "book_slot" and payload["property_id"] == "p1"


def test_parse_callback_invalid_json_is_raw_string():
    action, payload = parse_callback("book_slot:{broken json")
    assert action == "book_slot" and isinstance(payload, str)


# ------------------------------------------------- callback_data validation
def test_validate_callback_data_rules():
    from app.bot.keyboards import MAX_CALLBACK_BYTES, validate_callback_data

    assert MAX_CALLBACK_BYTES == 64
    assert validate_callback_data("details:PROP-0003")
    assert validate_callback_data("a" * 64)
    assert not validate_callback_data("a" * 65)
    assert not validate_callback_data(123)
    assert not validate_callback_data(None)
    assert not validate_callback_data("")


def test_book_slot_callback_within_telegram_limit():
    """Regression for Button_data_invalid: full slot dicts as JSON were 180 bytes."""
    from app.bot.keyboards import build_keyboard

    payload = {
        "property_id": "301dbc2d-ef6f-4ddc-a189-bf330031e451",
        "datetime_iso": "2026-09-17T09:00",
        "label": "Thu 17 Sep 09:00",
    }
    kb = build_keyboard([("book_slot", payload)])
    cb = kb.inline_keyboard[0][0].callback_data
    assert cb == "book_slot:301dbc2d-ef6f-4ddc-a189-bf330031e451:2026-09-17T09:00"
    assert len(cb.encode("utf-8")) <= 64


def test_book_slot_callback_with_uuid_fits_64_bytes():
    from app.bot.keyboards import build_keyboard

    payload = {
        "property_id": "aa94cfc7-9395-427a-b4b9-82e190a442f8",
        "datetime_iso": "2026-09-18T14:00",
        "label": "Fri 18 Sep 09:00",
    }
    kb = build_keyboard([("book_slot", payload)])
    cb = kb.inline_keyboard[0][0].callback_data
    assert len(cb.encode("utf-8")) <= 64


def test_build_keyboard_drops_oversized_callback():
    from app.bot.keyboards import build_keyboard

    assert build_keyboard([("details", {"detail": "x" * 200})]) is None
    assert build_keyboard([("book_slot", {"property_id": "x" * 100, "datetime_iso": "2026-09-17T09:00"})]) is None


def test_build_keyboard_multiple_buttons_with_book_slot():
    from app.bot.keyboards import build_keyboard

    actions = [
        ("book_slot", {"property_id": "PROP-0003", "datetime_iso": "2026-09-17T09:00", "label": "Thu 17 Sep 09:00"}),
        ("book_slot", {"property_id": "PROP-0003", "datetime_iso": "2026-09-17T10:00", "label": "Thu 17 Sep 10:00"}),
        ("cancel_appt", "aa94cfc7-9395-427a-b4b9-82e190a442f8"),
    ]
    kb = build_keyboard(actions)
    flat = [b for row in kb.inline_keyboard for b in row]
    assert len(flat) == 3
    for b in flat:
        assert len(b.callback_data.encode("utf-8")) <= 64


def test_book_slot_callback_roundtrip_compact():
    from app.bot.keyboards import build_keyboard, parse_callback

    payload = {"property_id": "PROP-0003", "datetime_iso": "2026-09-17T09:00", "label": "Thu 17 Sep 09:00"}
    kb = build_keyboard([("book_slot", payload)])
    action, parsed = parse_callback(kb.inline_keyboard[0][0].callback_data)
    assert action == "book_slot"
    assert parsed["property_id"] == "PROP-0003"
    assert parsed["datetime_iso"] == "2026-09-17T09:00"


# ------------------------------------------------------- _reply_with fallback
def _reply_update() -> MagicMock:
    update = MagicMock()
    update.effective_user.id = 424242
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    return update


_SLOT_REF = "301dbc2d-ef6f-4ddc-a189-bf330031e451"


async def test_reply_with_button_data_invalid_falls_back_without_keyboard(user_id):
    """Regression: the fallback must NOT re-send the same invalid keyboard."""
    from telegram.error import BadRequest

    from app.agents.orchestrator import AgentReply
    from app.bot import handlers

    update = _reply_update()
    update.effective_message.reply_text.side_effect = [BadRequest("Button_data_invalid"), None]
    await handlers._reply_with(update, AgentReply(text="hola", actions=[("slots", _SLOT_REF)]))

    assert update.effective_message.reply_text.await_count == 2
    first = update.effective_message.reply_text.await_args_list[0]
    second = update.effective_message.reply_text.await_args_list[1]
    assert first.kwargs.get("reply_markup") is not None
    assert second.kwargs.get("reply_markup") is None
    assert second.args[0] == "hola"


async def test_reply_with_parse_error_drops_parse_mode_keeps_keyboard(user_id):
    from telegram.error import BadRequest

    from app.agents.orchestrator import AgentReply
    from app.bot import handlers

    update = _reply_update()
    update.effective_message.reply_text.side_effect = [
        BadRequest("Can't parse entities: unclosed tag"), None,
    ]
    await handlers._reply_with(update, AgentReply(text="hola", actions=[("slots", _SLOT_REF)]))

    first = update.effective_message.reply_text.await_args_list[0]
    second = update.effective_message.reply_text.await_args_list[1]
    assert first.kwargs.get("parse_mode") is not None
    assert second.kwargs.get("parse_mode") is None
    assert second.kwargs.get("reply_markup") is not None


async def test_reply_with_other_telegram_errors_are_reraised(user_id):
    from telegram.error import BadRequest

    from app.agents.orchestrator import AgentReply
    from app.bot import handlers

    update = _reply_update()
    update.effective_message.reply_text.side_effect = BadRequest("Chat not found")
    with pytest.raises(BadRequest):
        await handlers._reply_with(update, AgentReply(text="hola"))


async def test_reply_with_persistent_markup_error_does_not_loop(user_id):
    from telegram.error import BadRequest

    from app.agents.orchestrator import AgentReply
    from app.bot import handlers

    update = _reply_update()
    update.effective_message.reply_text.side_effect = BadRequest("BUTTON_DATA_INVALID")
    with pytest.raises(BadRequest):
        await handlers._reply_with(update, AgentReply(text="hola", actions=[("slots", _SLOT_REF)]))
    assert update.effective_message.reply_text.await_count == 2


async def test_on_text_appointment_flow_sends_valid_keyboard(user_id):
    """'Bueno quiero agendar una cita para verla en persona' → valid book_slot keyboard."""
    from app.agents.orchestrator import Orchestrator
    from app.bot import handlers

    handlers.register_orchestrator(Orchestrator(llm=None))
    update = _fake_update(user_id=user_id, text="busca casas en Carepa hasta 300 millones")
    await handlers.on_text(update, MagicMock())
    update = _fake_update(user_id=user_id, text="la primera")
    await handlers.on_text(update, MagicMock())
    update = _fake_update(user_id=user_id, text="Bueno quiero agendar una cita para verla en persona")
    await handlers.on_text(update, MagicMock())

    update.effective_message.reply_text.assert_awaited()
    kb = update.effective_message.reply_text.await_args.kwargs.get("reply_markup")
    assert kb is not None
    buttons = [b for row in kb.inline_keyboard for b in row]
    assert buttons
    assert any(b.callback_data.startswith("book_slot:") for b in buttons)
    for b in buttons:
        assert len(b.callback_data.encode("utf-8")) <= 64


# ---------------------------------------------------------------- commands
def test_welcome_mentions_natural_language():
    from app.bot.handlers import HELP, WELCOME

    assert "/help" in WELCOME
    assert "Busco una casa en Carepa" in WELCOME
    for cmd in ("/buscar", "/propiedades", "/favoritos", "/busquedas", "/citas", "/perfil"):
        assert cmd in HELP


def test_build_application_requires_token():
    from app.bot.handlers import build_application

    with pytest.raises(RuntimeError):
        build_application()  # conftest clears TELEGRAM_BOT_TOKEN


def _fake_update(user_id: int = 424242, text: str = "hola") -> MagicMock:
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = "tester"
    update.effective_user.first_name = "Test"
    update.message.text = text
    update.effective_message = update.message
    update.effective_message.reply_text = AsyncMock()
    return update


async def test_on_text_end_to_end_mocked(user_id):
    """User message → orchestrator → reply sent through reply_text."""
    from app.agents.orchestrator import Orchestrator
    from app.bot import handlers

    handlers.register_orchestrator(Orchestrator(llm=None))
    update = _fake_update(user_id=user_id, text="busca casas en Carepa hasta 300 millones")
    await handlers.on_text(update, MagicMock())
    update.effective_message.reply_text.assert_awaited()
    sent = update.effective_message.reply_text.await_args.kwargs.get("text") or \
        update.effective_message.reply_text.await_args.args[0]
    assert "Encontré" in sent


async def test_on_callback_mocked(user_id):
    from app.agents.orchestrator import Orchestrator
    from app.bot import handlers

    handlers.register_orchestrator(Orchestrator(llm=None))
    update = _fake_update(user_id=user_id, text="")
    update.callback_query = MagicMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.data = "details:nonexistent-uuid"
    update.callback_query.message = MagicMock()
    update.callback_query.message.reply_text = AsyncMock()
    update.effective_message = update.callback_query.message
    await handlers.on_callback(update, MagicMock())
    update.callback_query.answer.assert_awaited()
    update.callback_query.message.reply_text.assert_awaited()


async def test_rate_limit_blocks_flood(user_id):
    from app.security.ratelimit import RateLimited, check_rate_limit

    import redis.asyncio as aioredis
    from app.core.settings import get_settings

    key = f"test:flood:{user_id}"
    client = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
    try:
        for k in await client.keys(f"rl:{key}:*"):
            await client.delete(k)
        await check_rate_limit(key, limit=2)
        await check_rate_limit(key, limit=2)
        with pytest.raises(RateLimited):
            await check_rate_limit(key, limit=2)
    finally:
        for k in await client.keys(f"rl:{key}:*"):
            await client.delete(k)
        await client.aclose()
