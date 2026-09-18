"""Agent: intent detection, tool selection, contextual references, memory."""
from __future__ import annotations

import pytest

from app.agents.intents import Intent, detect_intent, is_attribute_question, mentions_attribute
from app.agents.tools import run_tool
from app.database.base import AsyncSessionLocal
from app.memory import service as memory_service


# ------------------------------------------------------------------ intents
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Busco una casa en Carepa de máximo 300 millones, tres habitaciones, garaje y cerca del centro", Intent.SEARCH_PROPERTY),
        ("muéstrame apartamentos de 2 habitaciones hasta 150 millones", Intent.SEARCH_PROPERTY),
        ("tienen lotes disponibles", Intent.SEARCH_PROPERTY),
        ("quiero ver oficinas en Carepa", Intent.SEARCH_PROPERTY),
        ("la segunda", Intent.PROPERTY_DETAILS),
        ("la de 280 millones", Intent.PROPERTY_DETAILS),
        ("dime más", Intent.PROPERTY_DETAILS),
        ("compárame estas propiedades", Intent.COMPARE_PROPERTIES),
        ("diferencias entre PROP-0001 y PROP-0002", Intent.COMPARE_PROPERTIES),
        ("¿cuánto cuesta la casa familiar?", Intent.PRICE_QUERY),
        ("¿qué precio tiene PROP-0003?", Intent.PROPERTY_DETAILS),  # explicit code wins
        ("¿dónde queda la casa con garaje?", Intent.LOCATION_QUERY),
        ("cuál es la ubicación del apartamento penthouse", Intent.LOCATION_QUERY),
        ("guarda esta propiedad", Intent.SAVE_PROPERTY),
        ("quita esa de favoritos", Intent.REMOVE_PROPERTY),
        ("avísame cuando aparezca una casa por menos de 300 millones con tres habitaciones", Intent.SAVE_SEARCH),
        ("mis búsquedas guardadas", Intent.LIST_SAVED_SEARCHES),
        ("quiero agendar una visita", Intent.SCHEDULE_VISIT),
        ("cancela mi cita", Intent.CANCEL_APPOINTMENT),
        ("quiero hablar con un asesor", Intent.CONTACT_AGENT),
        ("¿cómo funciona la financiación?", Intent.FINANCING_QUESTION),
        ("quiero vender mi casa", Intent.SELL_PROPERTY),
        ("quiero arrendar mi apartamento", Intent.RENT_PROPERTY),
        ("hola", Intent.GREETING),
        ("gracias", Intent.GENERAL_FAQ),
    ],
)
def test_intent_detection(text, expected):
    assert detect_intent(text) == expected


def test_attribute_question_vs_new_search():
    assert is_attribute_question("¿la casa familiar tiene piscina?")
    assert is_attribute_question("¿tiene ascensor el apartamento?")
    assert not is_attribute_question("¿tienen casas con piscina?")  # new search
    assert not is_attribute_question("¿dónde queda la casa con jardín?")  # location
    assert mentions_attribute("¿tiene piscina?")


# ------------------------------------------------------------- tools: search
async def test_search_tool_returns_real_available_properties(session, user_id):
    from app.properties.search import extract_filters

    filters, semantic = extract_filters(
        "Busco una casa en Carepa de máximo 300 millones, tres habitaciones, garaje"
    )
    assert filters.property_type == "casa"
    assert filters.max_price == 300_000_000
    assert filters.bedrooms == 3
    assert filters.parking == 1

    ctx = await _ctx(session, user_id)
    res = await run_tool("search_properties", {"filters": filters.to_dict()}, ctx)
    codes = {p["code"] for p in res["properties"]}
    assert "PROP-0001" in codes  # 285M, 3 hab, garaje
    assert "PROP-0002" not in codes  # 320M > 300M
    assert "PROP-0014" not in codes  # SOLD never matches
    assert ctx.state["last_results"]


async def test_search_tool_hides_unavailable(session, user_id):
    ctx = await _ctx(session, user_id)
    res = await run_tool(
        "search_properties",
        {"filters": {"property_type": "casa", "city": "Carepa"}},
        ctx,
    )
    codes = {p["code"] for p in res["properties"]}
    assert codes
    assert not codes & {"PROP-0014", "PROP-0015", "PROP-0016"}


async def test_get_property_by_code_and_ambiguous(session, user_id):
    ctx = await _ctx(session, user_id)
    res = await run_tool("get_property", {"property_ref": "PROP-0004"}, ctx)
    assert res["ok"] and res["property"]["code"] == "PROP-0004"
    bad = await run_tool("get_property", {"property_ref": "PROP-9999"}, ctx)
    assert not bad["ok"] and bad["error"]


async def test_unknown_tool_rejected(session, user_id):
    ctx = await _ctx(session, user_id)
    res = await run_tool("drop_table", {}, ctx)
    assert not res["ok"] and "unknown tool" in res["error"]


async def _ctx(session, user_id):
    from app.agents.tools import ToolContext
    from app.memory import service as memory_service

    await memory_service.get_or_create_user(session, user_id, "t", "T")
    return ToolContext(session=session, user_id=user_id, conversation_id=None, state={})


# ------------------------------------------------------- contextual references
async def test_reference_resolution_ordinal_and_price(session):
    state = {
        "last_results": [
            {"id": "11111111-1111-1111-1111-111111111111", "price": 285_000_000, "title": "Casa A"},
            {"id": "22222222-2222-2222-2222-222222222222", "price": 320_000_000, "title": "Casa B"},
            {"id": "33333333-3333-3333-3333-333333333333", "price": 180_000_000, "title": "Casa C"},
        ]
    }
    idx, how = memory_service.resolve_reference("la segunda", state)
    assert (idx, how) == (1, "ordinal")
    idx, how = memory_service.resolve_reference("la de 285 millones", state)
    assert (idx, how) == (0, "precio")  # 285M seeded
    idx, _ = memory_service.resolve_reference("la de 999 millones", state)
    assert idx is None  # no match → never guess


async def test_conversation_flow_search_then_la_segunda(session, user_id):
    from app.agents.orchestrator import Orchestrator

    orch = Orchestrator(llm=None)
    r1 = await orch.handle_user_message(
        session, user_id, "busca casas en Carepa hasta 300 millones con 3 habitaciones", "u", "U"
    )
    assert r1.intent == Intent.SEARCH_PROPERTY
    assert "Encontré" in r1.text

    r2 = await orch.handle_user_message(session, user_id, "la segunda", "u", "U")
    assert r2.intent == Intent.PROPERTY_DETAILS
    assert "🏠" in r2.text  # full property card rendered


async def test_preferences_persisted_after_search(session, user_id):
    from app.agents.orchestrator import Orchestrator
    from app.memory.service import get_preferences

    orch = Orchestrator(llm=None)
    await orch.handle_user_message(
        session, user_id, "busco apartamento en Carepa hasta 150 millones", "u", "U"
    )
    prefs = await get_preferences(session, user_id)
    assert prefs is not None
    assert prefs.city == "Carepa"
    assert prefs.property_type == "apartamento"
    assert float(prefs.max_budget) == 150_000_000


async def test_unknown_intent_gets_fallback_menu(session, user_id):
    from app.agents.orchestrator import Orchestrator

    orch = Orchestrator(llm=None)
    r = await orch.handle_user_message(session, user_id, "xyzzy blorp qwerty", "u", "U")
    assert "Puedo ayudarte" in r.text
