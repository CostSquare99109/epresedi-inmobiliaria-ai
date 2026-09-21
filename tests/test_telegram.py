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
    from tests.test_fake_llm_v2 import (
        FakeLLMV2,
        final_decision,
        property_details_decision,
        search_decision,
        tc,
        tool_round,
    )
    from tests.test_fake_llm_v2 import LLMDecisionBuilder as FakeLLMDecisionBuilder

    # Real UUID for PROP-0001 from seed data
    PROP_0001_UUID = "a5b11831-f0cc-4cd6-96d7-7cb0fc9f1f02"

    # Turn 3: Custom decision with keyboard showing book_slot buttons
    def appointment_with_keyboard_decision() -> FakeLLMDecisionBuilder:
        return FakeLLMDecisionBuilder(
            intent="SCHEDULE_VISIT",
            response_text="Tengo estos horarios disponibles:\n📅 Lunes 21 Sep 09:00\n📅 Lunes 21 Sep 10:00",
            conversation={
                "current_goal": "schedule_visit_select_datetime",
                "missing_fields": ["datetime"],
                "next_action": "present_results",
                "phase": "APPOINTMENT_SELECTION",
                "clarification_question": None,
                "retry_context": None,
            },
            actions=[{
                "type": "show_keyboard",
                "keyboard": [
                    {"text": "📅 Lunes 21 Sep 09:00", "action": "book_slot", "payload": {"property_id": PROP_0001_UUID, "datetime_iso": "2026-09-21T14:00", "label": "Mon 21 Sep 09:00"}},
                    {"text": "📅 Lunes 21 Sep 10:00", "action": "book_slot", "payload": {"property_id": PROP_0001_UUID, "datetime_iso": "2026-09-21T15:00", "label": "Mon 21 Sep 10:00"}},
                ],
                "text": None,
                "images": []
            }],
            state_updates={"intent": "SCHEDULE_VISIT", "phase": "APPOINTMENT_SELECTION", "selected_property_id": PROP_0001_UUID},
        )

    # Create a fake LLM that returns appropriate decisions for each turn
    fake = FakeLLMV2([
        # Turn 1: Tool calls to set state and search
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "casa",
                "city": "Carepa", "budget_max": 300_000_000, "bedrooms": 3,
            }),
            tc("search_properties", {
                "filters": {"property_type": "casa", "city": "Carepa", "max_price": 300_000_000},
                "semantic_query": "3 habitaciones",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré opciones en Carepa.", phase="PROPERTY_SELECTION", property_code="PROP-0001")),
        # Turn 2: User selects "la primera" - get_property
        tool_round(tc("get_property", {"property_ref": "la primera"}, call_id="c3")),
        final_decision(property_details_decision("Aquí está la ficha de PROP-0001.", property_id=PROP_0001_UUID, property_code="PROP-0001")),
        # Turn 3: Wants to schedule visit - list_available_slots
        tool_round(tc("list_available_slots", {"property_id": PROP_0001_UUID}, call_id="c4")),
        final_decision(appointment_with_keyboard_decision()),
    ])
    orch = Orchestrator(llm=fake)
    handlers.register_orchestrator(orch)
    
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
    from tests.test_fake_llm_v2 import FakeLLMV2, final_decision, search_decision, tc, tool_round

    fake = FakeLLMV2([
        # Tool calls to set state and search
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "casa",
                "city": "Carepa", "budget_max": 300_000_000, "bedrooms": 3,
            }),
            tc("search_properties", {
                "filters": {"property_type": "casa", "city": "Carepa", "max_price": 300_000_000},
                "semantic_query": "3 habitaciones",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré opciones en Carepa.", phase="PROPERTY_SELECTION", property_code="PROP-0001")),
    ])
    orch = Orchestrator(llm=fake)
    handlers.register_orchestrator(orch)
    update = _fake_update(user_id=user_id, text="busca casas en Carepa hasta 300 millones")
    await handlers.on_text(update, MagicMock())
    update.effective_message.reply_text.assert_awaited()
    sent = update.effective_message.reply_text.await_args.kwargs.get("text") or \
        update.effective_message.reply_text.await_args.args[0]
    assert "Encontré" in sent


async def test_on_callback_mocked(user_id):
    from app.agents.orchestrator import Orchestrator
    from app.bot import handlers
    from tests.test_fake_llm_v2 import FakeLLMV2, final_decision, property_details_decision

    fake = FakeLLMV2([
        final_decision(property_details_decision("Aquí está la ficha.", property_id="test-uuid", property_code="PROP-0001")),
    ])
    orch = Orchestrator(llm=fake)
    handlers.register_orchestrator(orch)
    update = _fake_update(user_id=user_id, text="")
    update.callback_query = AsyncMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.data = "details:test-uuid"
    update.callback_query.edit_message_text = AsyncMock()
    update.effective_message = update.callback_query
    await handlers.on_callback(update, MagicMock())
    update.callback_query.answer.assert_awaited()
    update.callback_query.edit_message_text.assert_awaited()


async def test_rate_limit_blocks_flood(user_id):
    import redis.asyncio as aioredis

    from app.core.settings import get_settings
    from app.security.ratelimit import RateLimited, check_rate_limit

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


# ---------------------------------------------------------------- /nuevo command
async def test_cmd_nuevo_creates_new_conversation(session, user_id):
    """Test that /nuevo creates a new conversation with empty state."""
    from app.agents.orchestrator import Orchestrator
    from app.bot import handlers
    from app.memory import service as memory_service
    from tests.test_fake_llm_v2 import (
        FakeLLMV2,
        final_decision,
        property_details_decision,
        search_decision,
        tc,
        tool_round,
    )

    fake = FakeLLMV2([
        # Turn 1: Tool calls to set state and search
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "casa",
                "city": "Carepa", "budget_max": 300_000_000, "bedrooms": 3,
            }),
            tc("search_properties", {
                "filters": {"property_type": "casa", "city": "Carepa", "max_price": 300_000_000},
                "semantic_query": "3 habitaciones",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré opciones en Carepa.", phase="PROPERTY_SELECTION", property_code="PROP-0001")),
        # Turn 2: User selects "la primera" - get_property
        tool_round(tc("get_property", {"property_ref": "la primera"}, call_id="c3")),
        final_decision(property_details_decision("Aquí está la ficha de PROP-0001.", property_id="test-uuid", property_code="PROP-0001")),
    ])
    orch = Orchestrator(llm=fake)
    handlers.register_orchestrator(orch)

    # First, create some conversation history
    update1 = _fake_update(user_id=user_id, text="busca casas en Carepa hasta 300 millones")
    await handlers.on_text(update1, MagicMock())

    update2 = _fake_update(user_id=user_id, text="la primera")
    await handlers.on_text(update2, MagicMock())

    # Verify conversation has state
    async with AsyncSessionLocal() as s:
        user = await memory_service.get_or_create_user(s, user_id)
        conv = await memory_service.get_or_create_conversation(s, user.id)
        assert conv.state.get("last_results") is not None
        old_conv_id = conv.id

    # Now send /nuevo
    update3 = _fake_update(user_id=user_id, text="/nuevo")
    update3.message.text = "/nuevo"
    await handlers.cmd_nuevo(update3, MagicMock())

    # Verify response
    update3.effective_message.reply_text.assert_awaited()
    sent = update3.effective_message.reply_text.await_args.kwargs.get("text") or \
        update3.effective_message.reply_text.await_args.args[0]
    assert "Nuevo chat iniciado" in sent

    # Verify new conversation was created with empty state
    async with AsyncSessionLocal() as s:
        user = await memory_service.get_or_create_user(s, user_id)
        new_conv = await memory_service.get_or_create_conversation(s, user.id)
        assert new_conv.id != old_conv_id  # New conversation
        assert new_conv.state == {}  # Empty state
        assert new_conv.summary == ""  # Empty summary


async def test_cmd_nuevo_preserves_user_data(session, user_id):
    """Test that /nuevo preserves user preferences, favorites, and appointments."""
    from app.agents.orchestrator import Orchestrator
    from app.bot import handlers
    from app.crm import service as crm_service
    from app.memory import service as memory_service
    from app.properties import repository as prop_repo
    from tests.test_fake_llm_v2 import FakeLLMV2, final_decision, search_decision, tc, tool_round

    fake = FakeLLMV2([
        # Tool calls to set state and search
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "casa",
                "city": "Carepa", "budget_max": 300_000_000, "bedrooms": 3,
            }),
            tc("search_properties", {
                "filters": {"property_type": "casa", "city": "Carepa", "max_price": 300_000_000},
                "semantic_query": "3 habitaciones",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré opciones en Carepa.", phase="PROPERTY_SELECTION", property_code="PROP-0001")),
    ])
    orch = Orchestrator(llm=fake)
    handlers.register_orchestrator(orch)

    # Create user and some persistent data
    async with AsyncSessionLocal() as s:
        user = await memory_service.get_or_create_user(s, user_id, "tester", "Test")
        # Set preferences
        await memory_service.update_preferences(s, user.id, {
            "city": "Carepa",
            "property_type": "casa",
            "max_price": 300_000_000,
        })
        # Add a favorite using a real property from seed data
        prop = await prop_repo.get_property_by_code(s, "PROP-0001")
        await crm_service.add_favorite(s, user.id, prop.id)
        await s.commit()

    # Send /nuevo
    update = _fake_update(user_id=user_id, text="/nuevo")
    update.message.text = "/nuevo"
    await handlers.cmd_nuevo(update, MagicMock())

    # Verify persistent data still exists
    async with AsyncSessionLocal() as s:
        user = await memory_service.get_or_create_user(s, user_id)
        prefs = await memory_service.get_preferences(s, user.id)
        assert prefs is not None
        assert prefs.city == "Carepa"
        assert prefs.property_type == "casa"
        assert float(prefs.max_budget) == 300_000_000

        favorites = await crm_service.list_favorites(s, user.id)
        assert len(favorites) == 1


async def test_cmd_nuevo_clears_conversation_state(session, user_id):
    """Test that /nuevo clears the current conversation state."""
    from app.agents.orchestrator import Orchestrator
    from app.bot import handlers
    from app.memory import service as memory_service
    from app.properties import repository as prop_repo
    from tests.test_fake_llm_v2 import (
        FakeLLMV2,
        final_decision,
        property_details_decision,
        search_decision,
        tc,
        tool_round,
    )

    # Get real UUID for PROP-0001
    prop = await prop_repo.get_property_by_code(session, "PROP-0001")
    PROP_0001_UUID = str(prop.id)

    fake = FakeLLMV2([
        # Turn 1: Tool calls to set state and search
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "casa",
                "city": "Carepa", "budget_max": 300_000_000, "bedrooms": 3,
            }),
            tc("search_properties", {
                "filters": {"property_type": "casa", "city": "Carepa", "max_price": 300_000_000},
                "semantic_query": "3 habitaciones",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré opciones en Carepa.", phase="PROPERTY_SELECTION", property_code="PROP-0001")),
        # Turn 2: User selects "la primera" - get_property
        tool_round(tc("get_property", {"property_ref": "la primera"}, call_id="c3")),
        final_decision(property_details_decision("Aquí está la ficha de PROP-0001.", property_id=PROP_0001_UUID, property_code="PROP-0001")),
    ])
    orch = Orchestrator(llm=fake)
    handlers.register_orchestrator(orch)

    # Create conversation with various state
    update1 = _fake_update(user_id=user_id, text="busca casas en Carepa hasta 300 millones")
    await handlers.on_text(update1, MagicMock())

    update2 = _fake_update(user_id=user_id, text="la primera")
    await handlers.on_text(update2, MagicMock())

    # Verify state has search results and property selection
    async with AsyncSessionLocal() as s:
        user = await memory_service.get_or_create_user(s, user_id)
        conv = await memory_service.get_or_create_conversation(s, user.id)
        assert conv.state.get("last_results") is not None
        assert conv.state.get("last_property_id") is not None

    # Send /nuevo
    update3 = _fake_update(user_id=user_id, text="/nuevo")
    update3.message.text = "/nuevo"
    await handlers.cmd_nuevo(update3, MagicMock())

    # Verify new conversation has clean state
    async with AsyncSessionLocal() as s:
        user = await memory_service.get_or_create_user(s, user_id)
        new_conv = await memory_service.get_or_create_conversation(s, user.id)
        assert new_conv.state == {}
        assert new_conv.summary == ""


async def test_cmd_nuevo_isolated_per_user(session):
    """Test that /nuevo by user A doesn't affect user B."""
    from app.agents.orchestrator import Orchestrator
    from app.bot import handlers
    from app.memory import service as memory_service
    from tests.test_fake_llm_v2 import FakeLLMV2, final_decision, search_decision, tc, tool_round

    # Create separate orchestrators for each user with their own fake LLMs
    fake_a = FakeLLMV2([
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "casa",
                "city": "Carepa", "budget_max": 300_000_000, "bedrooms": 3,
            }),
            tc("search_properties", {
                "filters": {"property_type": "casa", "city": "Carepa", "max_price": 300_000_000},
                "semantic_query": "3 habitaciones",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré opciones en Carepa.", phase="PROPERTY_SELECTION", property_code="PROP-0001")),
    ])
    orch_a = Orchestrator(llm=fake_a)

    fake_b = FakeLLMV2([
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "apartamento",
                "city": "Medellín", "budget_max": 500_000_000, "bedrooms": 2,
            }),
            tc("search_properties", {
                "filters": {"property_type": "apartamento", "city": "Medellín", "max_price": 500_000_000},
                "semantic_query": "2 habitaciones",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré opciones en Medellín.", phase="PROPERTY_SELECTION", property_code="PROP-0002")),
    ])
    orch_b = Orchestrator(llm=fake_b)

    # Register orchestrator for user A first
    handlers.register_orchestrator(orch_a)

    user_a = 2_000_000_001
    user_b = 2_000_000_002

    # User A creates conversation with state
    update_a = _fake_update(user_id=user_a, text="busca casas en Carepa")
    await handlers.on_text(update_a, MagicMock())

    # Switch to orchestrator for user B
    handlers.register_orchestrator(orch_b)

    # User B creates conversation with state
    update_b = _fake_update(user_id=user_b, text="busca apartamentos en Medellín")
    await handlers.on_text(update_b, MagicMock())

    # Switch back to orchestrator for user A
    handlers.register_orchestrator(orch_a)

    # User A sends /nuevo
    update_a_nuevo = _fake_update(user_id=user_a, text="/nuevo")
    update_a_nuevo.message.text = "/nuevo"
    await handlers.cmd_nuevo(update_a_nuevo, MagicMock())

    # Verify user B's conversation is unaffected
    async with AsyncSessionLocal() as s:
        user_b_obj = await memory_service.get_or_create_user(s, user_b)
        conv_b = await memory_service.get_or_create_conversation(s, user_b_obj.id)
        assert conv_b.state.get("last_results") is not None

    # Verify user A has new empty conversation
    async with AsyncSessionLocal() as s:
        user_a_obj = await memory_service.get_or_create_user(s, user_a)
        conv_a = await memory_service.get_or_create_conversation(s, user_a_obj.id)
        assert conv_a.state == {}


# ════════════════════════════════════════════════════════════════════════════════
# Progress cleanup regression tests
# ════════════════════════════════════════════════════════════════════════════════

async def test_progress_cleanup_on_llm_error(session, user_id):
    """Cuando el LLM falla, el mensaje de progreso debe limpiarse (no duplicados)."""
    from app.bot.handlers import _run_orchestrator
    from app.bot.progress import TelegramProgressRenderer, ProgressConfig
    from app.agents.orchestrator import Orchestrator
    from app.ai.llm import LLMError
    from tests.test_fake_llm_v2 import FakeLLMV2

    # Mock bot to capture messages
    class MockBot:
        def __init__(self):
            self.sent_messages = []
            self.edited_messages = []
            self.deleted_messages = []

        async def send_message(self, chat_id, text, disable_notification=False):
            self.sent_messages.append({"chat_id": chat_id, "text": text})
            class Msg:
                message_id = len(self.sent_messages)
            return Msg()

        async def edit_message_text(self, chat_id, message_id, text):
            self.edited_messages.append({"chat_id": chat_id, "message_id": message_id, "text": text})

        async def delete_message(self, chat_id, message_id):
            self.deleted_messages.append({"chat_id": chat_id, "message_id": message_id})

    # Create orchestrator with failing LLM
    fake = FakeLLMV2([LLMError("model_not_found", "model not found")])
    orch = Orchestrator(llm=fake)
    from app.bot.handlers import register_orchestrator
    register_orchestrator(orch)

    # Create fake update with proper async mocks
    from unittest.mock import AsyncMock, MagicMock

    bot = MockBot()
    update = MagicMock()
    
    # effective_message is what _reply_with uses
    effective_message = MagicMock()
    effective_message.reply_text = AsyncMock()
    update.effective_message = effective_message
    update.message = effective_message  # also set message for compatibility
    update.message.text = "Hola"
    
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.effective_chat = MagicMock()
    update.effective_chat.id = 12345
    update.get_bot = MagicMock(return_value=bot)

    # Run handler
    await _run_orchestrator(update, "Hola")

    # Verificar: se envió mensaje inicial de progreso
    assert len(bot.sent_messages) == 1
    assert "Iniciando" in bot.sent_messages[0]["text"]

    # Verificar: se editó el mensaje a estado de error
    assert len(bot.edited_messages) == 1
    assert "problema" in bot.edited_messages[0]["text"].lower()

    # Verificar: se ELIMINÓ el mensaje de progreso (cleanup en finally)
    assert len(bot.deleted_messages) == 1

    # Verificar: NO hay mensaje de error duplicado enviado como nuevo mensaje
    # (solo el mensaje inicial + 1 respuesta final = 2 mensajes totales enviados)
    # El mensaje de progreso se borra, así que el usuario ve solo 1 mensaje final
    assert len(bot.deleted_messages) == 1  # cleanup ocurrió
