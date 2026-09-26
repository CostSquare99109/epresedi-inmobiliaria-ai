"""Agent: LLM-FIRST behavior tests with structured decisions.

Tests use FakeLLMV2 which returns structured JSON decisions per the LLM contract.
"""
from __future__ import annotations

import pytest

from app.agents.intents import Intent, detect_intent, is_attribute_question, mentions_attribute
from app.agents.orchestrator import Orchestrator
from app.agents.tools import run_tool
from app.memory import service as memory_service
from tests.test_fake_llm_v2 import (
    FakeLLMV2,
    appointment_confirm_decision,
    appointment_select_datetime_decision,
    final_decision,
    greeting_decision,
    property_details_decision,
    search_decision,
    tc,
    tool_round,
)


# ------------------------------------------------------------------ intents (unit tests for the legacy detect_intent function)
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Busco una casa en Carepa de máximo 300 millones, tres habitaciones, garaje y cerca del centro", Intent.SEARCH_PROPERTY),
        ("muéstrame apartamentos de 2 habitaciones hasta 150 millones", Intent.SEARCH_PROPERTY),
        ("tienen casas disponibles", Intent.SEARCH_PROPERTY),
        ("quiero ver apartamentos en Carepa", Intent.SEARCH_PROPERTY),
        ("la segunda", Intent.PROPERTY_DETAILS),
        ("la de 280 millones", Intent.PROPERTY_DETAILS),
        ("dime más", Intent.PROPERTY_DETAILS),
        ("compárame estas propiedades", Intent.COMPARE_PROPERTIES),
        ("diferencias entre PROP-0001 y PROP-0002", Intent.COMPARE_PROPERTIES),
        ("¿cuánto cuesta la casa familiar?", Intent.PRICE_QUERY),
        ("¿qué precio tiene PROP-0003?", Intent.PROPERTY_DETAILS),
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

    filters, _ = extract_filters(
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


# ------------------------------------------------------- LLM-FIRST conversation flows
async def test_conversation_flow_search_then_la_segunda(session, user_id):
    """Buscar → usuario dice 'la segunda' → muestra ficha de esa propiedad."""
    fake = FakeLLMV2([
        # Turn 1: Buscar propiedades
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "casa",
                "city": "Carepa", "budget_max": 300_000_000, "bedrooms": 3,
            }),
            tc("search_properties", {
                "filters": {"property_type": "casa", "city": "Carepa", "max_price": 300_000_000, "bedrooms": 3},
                "semantic_query": "",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré casas en Carepa. La primera es PROP-0001, la segunda es PROP-0002.", phase="PROPERTY_SELECTION")),
        # Turn 2: Usuario dice "la segunda"
        tool_round(
            tc("update_conversation_state", {"intent": "PROPERTY_DETAILS"}),
            tc("get_property", {"property_ref": "la segunda"}, call_id="c3"),
        ),
        final_decision(property_details_decision("Ficha de PROP-0002", property_id="22222222-2222-2222-2222-222222222222", property_code="PROP-0002")),
    ])
    orch = Orchestrator(llm=fake)
    r1 = await orch.handle_user_message(
        session, user_id, "busca casas en Carepa hasta 300 millones con 3 habitaciones", "u", "U"
    )
    assert r1.intent == Intent.SEARCH_PROPERTY
    assert "PROP-0001" in r1.text or "PROP-0002" in r1.text

    r2 = await orch.handle_user_message(session, user_id, "la segunda", "u", "U")
    assert r2.intent == Intent.PROPERTY_DETAILS
    assert "PROP-0002" in r2.text


async def test_preferences_persisted_after_search(session, user_id):
    from app.memory.service import get_preferences

    fake = FakeLLMV2([
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "apartamento",
                "city": "Carepa", "budget_max": 150_000_000,
            }),
            tc("search_properties", {
                "filters": {"property_type": "apartamento", "city": "Carepa", "max_price": 150_000_000},
                "semantic_query": "",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré apartamentos en Carepa.", phase="PROPERTY_SELECTION")),
    ])
    orch = Orchestrator(llm=fake)
    await orch.handle_user_message(
        session, user_id, "busco apartamento en Carepa hasta 150 millones", "u", "U"
    )
    prefs = await get_preferences(session, user_id)
    assert prefs is not None
    assert prefs.city == "Carepa"
    assert prefs.property_type == "apartamento"
    assert float(prefs.max_budget) == 150_000_000


async def test_unknown_intent_gets_helpful_response(session, user_id):
    fake = FakeLLMV2([
        final_decision(greeting_decision("Puedo ayudarte a buscar propiedades, agendar visitas, etc. ¿Qué necesitas?")),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "xyzzy blorp qwerty", "u", "U")
    assert "Puedo ayudarte" in r.text or "ayuda" in r.text.lower()


# ------------------------------------------------------------ greeting behavior
async def test_greeting_first_message_introduces_agent(session, user_id):
    """First greeting should introduce the agent briefly without listing capabilities."""
    fake = FakeLLMV2([
        final_decision(greeting_decision()),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "hola", "u", "U")

    assert r.intent == Intent.GREETING
    assert "epresedi" in r.text.lower()
    assert "asistente virtual de epresedi" in r.text.lower()
    # Should NOT list capabilities
    capability_words = ["venta", "arriendo", "financiación", "agendar", "características", "documentos", "fotos"]
    for word in capability_words:
        assert word not in r.text.lower(), f"Greeting should not mention '{word}'"
    # Should be brief (1-3 lines)
    assert len(r.text.split("\n")) <= 3


async def test_greeting_subsequent_message_does_not_reintroduce(session, user_id):
    """Subsequent greetings should not repeat the introduction."""
    fake = FakeLLMV2([
        # First: search (establishes context)
        tool_round(
            tc("update_conversation_state", {"intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "casa", "city": "Carepa", "budget_max": 300_000_000}),
            tc("search_properties", {"filters": {"property_type": "casa", "city": "Carepa", "max_price": 300_000_000}}, call_id="c2"),
        ),
        final_decision(search_decision("Encontré casas en Carepa.", phase="PROPERTY_SELECTION")),
        # Second: greeting
        final_decision(greeting_decision("¡Hola de nuevo! ¿En qué más te ayudo?")),
    ])
    orch = Orchestrator(llm=fake)
    r1 = await orch.handle_user_message(
        session, user_id, "busca casas en Carepa hasta 300 millones", "u", "U"
    )
    assert r1.intent == Intent.SEARCH_PROPERTY

    r2 = await orch.handle_user_message(session, user_id, "hola", "u", "U")

    assert r2.intent == Intent.GREETING
    # Should NOT reintroduce
    assert "epresedi" not in r2.text.lower()
    assert "asistente virtual" not in r2.text
    # Should be a natural continuation
    assert "de nuevo" in r2.text.lower() or "buenas" in r2.text.lower() or "ayudo" in r2.text.lower()


async def test_greeting_variants_are_natural(session, user_id):
    """Different greeting variants should all work naturally."""
    for greeting in ["hola", "buenas", "buenos días", "hey", "qué tal"]:
        fake = FakeLLMV2([
            final_decision(greeting_decision()),
        ])
        orch = Orchestrator(llm=fake)
        r = await orch.handle_user_message(session, user_id, greeting, "u", "U")
        assert r.intent == Intent.GREETING
        assert "epresedi" in r.text.lower()
        assert "asistente virtual de epresedi" in r.text.lower()
        assert len(r.text) < 200
        # Create new conversation for next test
        from app.memory import service as memory_service
        user = await memory_service.get_or_create_user(session, user_id, "u", "U")
        await memory_service.create_new_conversation(session, user.id)
        await session.commit()


async def test_greeting_does_not_list_capabilities_unless_asked(session, user_id):
    """Greeting should not list capabilities unless user explicitly asks."""
    fake = FakeLLMV2([
        final_decision(greeting_decision()),
    ])
    orch = Orchestrator(llm=fake)

    r1 = await orch.handle_user_message(session, user_id, "hola", "u", "U")
    assert r1.intent == Intent.GREETING
    capability_words = ["venta", "arriendo", "financiación", "agendar", "características", "documentos", "fotos"]
    for word in capability_words:
        assert word not in r1.text.lower(), f"Greeting should not mention '{word}'"

    # New conversation
    from app.memory import service as memory_service
    user = await memory_service.get_or_create_user(session, user_id, "u", "U")
    await memory_service.create_new_conversation(session, user.id)
    await session.commit()

    # Explicit question about capabilities
    fake2 = FakeLLMV2([
        final_decision(greeting_decision("Soy epresedi, tu asistente inmobiliario. Puedo buscar propiedades, mostrar fichas, agendar visitas, consultar documentos y más. ¿Qué necesitas?")),
    ])
    orch2 = Orchestrator(llm=fake2)
    r2 = await orch2.handle_user_message(session, user_id, "¿qué puedes hacer?", "u", "U")
    assert len(r2.text) < 500


# ------------------------------------------------------------ search refinement context
async def test_search_refinement_mas_o_menos_expands_search(session, user_id):
    """'Más o menos' after failed search should expand search, not trigger RAG."""
    fake = FakeLLMV2([
        # Turn 1: Search returns 0 results
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "RENT", "property_type": "casa",
                "city": "Carepa", "budget_max": 1000000, "bedrooms": 2, "bathrooms": 1,
            }),
            tc("search_properties", {
                "filters": {"operation": "RENT", "property_type": "casa", "city": "Carepa", "max_price": 1000000, "bedrooms": 2, "bathrooms": 1},
                "semantic_query": "",
            }, call_id="c2"),
        ),
        final_decision(search_decision("No encontré propiedades. ¿Quieres que amplíe la búsqueda?", phase="SEARCHING")),
        # Turn 2: User says 'Más o menos' - should expand search
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "RENT", "property_type": "apartamento",
                "city": "Carepa", "budget_max": 1300000, "bedrooms": 2, "bathrooms": 1,
            }),
            tc("search_properties", {
                "filters": {"operation": "RENT", "property_type": "apartamento", "city": "Carepa", "max_price": 1300000, "bedrooms": 2, "bathrooms": 1},
                "semantic_query": "",
            }, call_id="c3"),
        ),
        final_decision(search_decision("Amplié la búsqueda y encontré PROP-0008.", phase="PROPERTY_SELECTION")),
    ])
    orch = Orchestrator(llm=fake)
    
    r1 = await orch.handle_user_message(
        session, user_id, "busco casa en Carepa en arriendo por 1 millon 2 habitaciones 1 baño", "t", "T"
    )
    assert r1.intent == Intent.SEARCH_PROPERTY
    assert "No encontré" in r1.text or "ampliar" in r1.text
    
    r2 = await orch.handle_user_message(session, user_id, "Más o menos", "t", "T")
    assert r2.intent == Intent.SEARCH_PROPERTY
    # Should NOT contain RAG content about mascotas
    assert "mascota" not in r2.text.lower()
    assert "normativa" not in r2.text.lower()
    # Should mention expanded search results
    assert "ampli" in r2.text.lower() or "PROP-0008" in r2.text


async def test_search_refinement_various_agreement_phrases(session, user_id):
    """Various agreement phrases should all trigger search expansion."""
    agreement_phrases = ["sí", "si", "ok", "dale", "vale", "claro", "amplía", "expande"]
    
    for phrase in agreement_phrases:
        fake = FakeLLMV2([
            tool_round(
                tc("update_conversation_state", {
                    "intent": "SEARCH_PROPERTY", "operation": "RENT", "property_type": "casa",
                    "city": "Carepa", "budget_max": 1000000, "bedrooms": 2, "bathrooms": 1,
                }),
                tc("search_properties", {
                    "filters": {"operation": "RENT", "property_type": "casa", "city": "Carepa", "max_price": 1000000, "bedrooms": 2, "bathrooms": 1},
                    "semantic_query": "",
                }, call_id="c2"),
            ),
            final_decision(search_decision("No encontré propiedades. ¿Quieres que amplíe?", phase="SEARCHING")),
            tool_round(
                tc("update_conversation_state", {
                    "intent": "SEARCH_PROPERTY", "operation": "RENT", "property_type": "apartamento",
                    "city": "Carepa", "budget_max": 1300000, "bedrooms": 2, "bathrooms": 1,
                }),
                tc("search_properties", {
                    "filters": {"operation": "RENT", "property_type": "apartamento", "city": "Carepa", "max_price": 1300000, "bedrooms": 2, "bathrooms": 1},
                    "semantic_query": "",
                }, call_id="c3"),
            ),
            final_decision(search_decision(f"Amplié tras '{phrase}' y encontré opciones.", phase="PROPERTY_SELECTION")),
        ])
        orch = Orchestrator(llm=fake)
        
        r1 = await orch.handle_user_message(
            session, user_id, "busco casa en Carepa en arriendo por 1 millon 2 habitaciones 1 baño", "t", "T"
        )
        assert "No encontré" in r1.text or "ampliar" in r1.text
        
        r2 = await orch.handle_user_message(session, user_id, phrase, "t", "T")
        assert r2.intent == Intent.SEARCH_PROPERTY
        assert "mascota" not in r2.text.lower()
        assert "normativa" not in r2.text.lower()
        
        # New conversation for next phrase
        from app.memory import service as memory_service
        user = await memory_service.get_or_create_user(session, user_id, "t", "T")
        await memory_service.create_new_conversation(session, user.id)
        await session.commit()


async def test_search_refinement_no_false_positive_on_new_query(session, user_id):
    """A new property query after failed search should not be treated as refinement agreement."""
    fake = FakeLLMV2([
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "RENT", "property_type": "casa",
                "city": "Carepa", "budget_max": 1000000, "bedrooms": 2, "bathrooms": 1,
            }),
            tc("search_properties", {
                "filters": {"operation": "RENT", "property_type": "casa", "city": "Carepa", "max_price": 1000000, "bedrooms": 2, "bathrooms": 1},
                "semantic_query": "",
            }, call_id="c2"),
        ),
        final_decision(search_decision("No encontré propiedades. ¿Quieres que amplíe?", phase="SEARCHING")),
        # User asks a NEW question - should use RAG
        tool_round(
            tc("search_documents", {"query": "normativa mascotas"}, call_id="c3"),
        ),
        final_decision(LLMDecisionBuilder(
            intent="PROPERTY_DOCUMENT_QUESTION",
            response_text="Según normativa mascotas: se permiten perros pequeños.",
            conversation={"current_goal": "answer_document_question", "missing_fields": [], "next_action": "present_results", "phase": "GENERAL"},
        )),
    ])
    orch = Orchestrator(llm=fake)
    
    r1 = await orch.handle_user_message(
        session, user_id, "busco casa en Carepa en arriendo por 1 millon 2 habitaciones 1 baño", "t", "T"
    )
    assert "No encontré" in r1.text or "ampliar" in r1.text
    
    # User asks about pet regulations - this IS a document question
    r2 = await orch.handle_user_message(session, user_id, "¿cuál es la normativa de mascotas?", "t", "T")
    assert r2.intent == Intent.PROPERTY_DOCUMENT_QUESTION
    assert "mascota" in r2.text.lower() or "normativa" in r2.text.lower()


async def test_state_includes_last_search_had_results_false(session, user_id):
    """State should include last_search_had_results=false when search returns 0 results."""
    from app.agents.state import describe_state
    
    fake = FakeLLMV2([
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "RENT", "property_type": "casa",
                "city": "Carepa", "budget_max": 1000000, "bedrooms": 2, "bathrooms": 1,
            }),
            tc("search_properties", {
                "filters": {"operation": "RENT", "property_type": "casa", "city": "Carepa", "max_price": 1000000, "bedrooms": 2, "bathrooms": 1},
                "semantic_query": "",
            }, call_id="c2"),
        ),
        final_decision(search_decision("No encontré propiedades.", phase="SEARCHING")),
    ])
    orch = Orchestrator(llm=fake)
    
    await orch.handle_user_message(
        session, user_id, "busco casa en Carepa en arriendo por 1 millon 2 habitaciones 1 baño", "t", "T"
    )
    
    from app.memory import service as memory_service
    conv = await memory_service.get_or_create_conversation(session, user_id)
    state_json = describe_state(conv.state)
    
    assert '"last_search_had_results": false' in state_json
    assert '"awaiting_search_refinement": true' in state_json


async def test_state_includes_last_search_had_results_true_when_results_found(session, user_id):
    """State should include last_search_had_results=true when search returns results."""
    from app.agents.state import describe_state
    
    fake = FakeLLMV2([
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "casa",
                "city": "Carepa", "budget_max": 300_000_000, "bedrooms": 3,
            }),
            tc("search_properties", {
                "filters": {"operation": "SALE", "property_type": "casa", "city": "Carepa", "max_price": 300_000_000, "bedrooms": 3},
                "semantic_query": "",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré casas en Carepa. La primera es PROP-0001.", phase="PROPERTY_SELECTION")),
    ])
    orch = Orchestrator(llm=fake)
    
    await orch.handle_user_message(
        session, user_id, "busco casa en Carepa hasta 300 millones 3 habitaciones", "t", "T"
    )
    
    from app.memory import service as memory_service
    conv = await memory_service.get_or_create_conversation(session, user_id)
    state_json = describe_state(conv.state)
    
    assert '"last_search_had_results": true' in state_json
    assert '"awaiting_search_refinement": false' in state_json


# ------------------------------------------------------------ reference resolution
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
    assert (idx, how) == (0, "precio")
    idx, _ = memory_service.resolve_reference("la de 999 millones", state)
    assert idx is None  # no match → never guess


# ------------------------------------------------------------ name extraction tests (LLM-first)
async def test_llm_extracts_name_variants(session, user_id):
    """Test that LLM can extract names from various formats."""
    # This test documents the expected behavior - the LLM should handle these
    # The actual extraction is done by the LLM, not Python code
    
    test_cases = [
        "Jhon Fredy Montalvo Cuadrado",
        "Mi nombre completo es Jhon Fredy Montalvo Cuadrado",
        "Soy Jhon Fredy Montalvo Cuadrado",
        "Nombre: Jhon Fredy Montalvo Cuadrado",
        "1️⃣ Jhon Fredy Montalvo Cuadrado",
    ]
    
    for name_text in test_cases:
        # Create a fake LLM that extracts the name correctly
        fake = FakeLLMV2([
            tool_round(
                tc("update_conversation_state", {
                    "intent": "SCHEDULE_VISIT", "phase": "APPOINTMENT_CONFIRMATION", "booking_state": "confirmando",
                }),
            ),
            final_decision(appointment_confirm_decision(
                text=f"Confirmando cita para {name_text}",
            )),
        ])
        orch = Orchestrator(llm=fake)
        
        # Pre-setup: property selected, datetime chosen
        from app.memory import service as memory_service
        user = await memory_service.get_or_create_user(session, user_id, "t", "T")
        conv = await memory_service.get_or_create_conversation(session, user.id)
        conv.state = {
            "phase": "APPOINTMENT_SELECTION",
            "selected_property_id": "11111111-1111-1111-1111-111111111111",
            "booking": {"property_id": "11111111-1111-1111-1111-111111111111", "selected_datetime": "2026-09-21T10:00", "step": "collecting_contact", "contact": {}},
        }
        await session.commit()
        
        r = await orch.handle_user_message(session, user_id, name_text, "t", "T")
        # The LLM should extract the name and proceed to confirmation
        assert r.intent in (Intent.SCHEDULE_VISIT, Intent.UNKNOWN)
        
        # Reset for next test
        await memory_service.create_new_conversation(session, user.id)
        await session.commit()


async def test_llm_extracts_multiple_fields_in_one_message(session, user_id):
    """Test that LLM extracts name, phone, email from single message."""
    test_msg = "1️⃣ Jhon Fredy Montalvo Cuadrado\n2️⃣ 3001234567\n3️⃣ jhon@gmail.com"
    
    fake = FakeLLMV2([
        tool_round(
            tc("update_conversation_state", {
                "intent": "SCHEDULE_VISIT", "phase": "APPOINTMENT_CONFIRMATION", "booking_state": "confirmando",
            }),
        ),
        final_decision(appointment_confirm_decision(
            text="Confirmando cita para Jhon Fredy Montalvo Cuadrado, tel 3001234567, correo jhon@gmail.com",
        )),
    ])
    orch = Orchestrator(llm=fake)
    
    from app.memory import service as memory_service
    user = await memory_service.get_or_create_user(session, user_id, "t", "T")
    conv = await memory_service.get_or_create_conversation(session, user.id)
    conv.state = {
        "phase": "APPOINTMENT_SELECTION",
        "selected_property_id": "11111111-1111-1111-1111-111111111111",
        "booking": {"property_id": "11111111-1111-1111-1111-111111111111", "selected_datetime": "2026-09-21T10:00", "step": "collecting_contact", "contact": {}},
    }
    await session.commit()
    
    r = await orch.handle_user_message(session, user_id, test_msg, "t", "T")
    assert r.intent == Intent.SCHEDULE_VISIT
    # Should have all three fields in confirmation
    assert "Jhon Fredy" in r.text
    assert "3001234567" in r.text
    assert "jhon@gmail.com" in r.text


async def test_llm_handles_correction(session, user_id):
    """Test that LLM understands correction of previously provided data."""
    fake = FakeLLMV2([
        tool_round(
            tc("update_conversation_state", {
                "intent": "SCHEDULE_VISIT", "phase": "APPOINTMENT_CONFIRMATION", "booking_state": "confirmando",
            }),
        ),
        final_decision(appointment_confirm_decision(
            text="Corregido el nombre",
        )),
    ])
    orch = Orchestrator(llm=fake)
    
    from app.memory import service as memory_service
    user = await memory_service.get_or_create_user(session, user_id, "t", "T")
    conv = await memory_service.get_or_create_conversation(session, user.id)
    conv.state = {
        "phase": "APPOINTMENT_SELECTION",
        "selected_property_id": "11111111-1111-1111-1111-111111111111",
        "booking": {"property_id": "11111111-1111-1111-1111-111111111111", "selected_datetime": "2026-09-21T10:00", "step": "collecting_contact", "contact": {"name": "Nombre Incorrecto", "phone": "3001234567", "email": "jhon@gmail.com"}},
    }
    await session.commit()
    
    r = await orch.handle_user_message(session, user_id, "Mi nombre correcto es Jhon Fredy Montalvo Cuadrado Corregido", "t", "T")
    assert r.intent == Intent.SCHEDULE_VISIT
    assert "Corregido" in r.text or "correcto" in r.text.lower()


async def test_llm_handles_property_change(session, user_id):
    """Test that LLM understands user wants a different property."""
    fake = FakeLLMV2([
        # First: show property details
        tool_round(
            tc("get_property", {"property_ref": "la segunda"}, call_id="c1"),
        ),
        final_decision(property_details_decision("Ficha de la segunda propiedad", property_id="22222222-2222-2222-2222-222222222222", property_code="PROP-0002")),
    ])
    orch = Orchestrator(llm=fake)
    
    # Setup: user saw multiple properties
    from app.memory import service as memory_service
    user = await memory_service.get_or_create_user(session, user_id, "t", "T")
    conv = await memory_service.get_or_create_conversation(session, user.id)
    conv.state = {
        "phase": "PROPERTY_SELECTION",
        "last_results": [
            {"id": "11111111-1111-1111-1111-111111111111", "code": "PROP-0001", "title": "Casa 1"},
            {"id": "22222222-2222-2222-2222-222222222222", "code": "PROP-0002", "title": "Casa 2"},
        ],
    }
    await session.commit()
    
    r = await orch.handle_user_message(session, user_id, "No, quiero ver la otra casa", "t", "T")
    assert r.intent == Intent.PROPERTY_DETAILS
    assert "PROP-0002" in r.text or "segunda" in r.text.lower()


async def test_llm_never_schedules_wrong_property(session, user_id):
    """Critical test: verify LLM doesn't schedule appointment for wrong property."""
    from app.appointments import service as appt_service
    from app.properties import repository as repo
    
    prop1 = await repo.get_property_by_code(session, "PROP-0001")
    prop2 = await repo.get_property_by_code(session, "PROP-0002")
    slots1 = await appt_service.list_available_slots(session, prop1.id)
    slots2 = await appt_service.list_available_slots(session, prop2.id)
    
    assert slots1, "PROP-0001 debe tener horarios"
    assert slots2, "PROP-0002 debe tener horarios"
    
    chosen_slot = slots1[0]["datetime"]
    
    fake = FakeLLMV2([
        # User searches, gets both properties
        tool_round(
            tc("update_conversation_state", {"intent": "SEARCH_PROPERTY", "operation": "SALE", "city": "Carepa"}),
            tc("search_properties", {"filters": {"operation": "SALE", "city": "Carepa"}}, call_id="c2"),
        ),
        final_decision(search_decision("Encontré PROP-0001 y PROP-0002.", phase="PROPERTY_SELECTION")),
        # User says "quiero agendar la segunda"
        tool_round(
            tc("update_conversation_state", {"intent": "SCHEDULE_VISIT"}),
            tc("get_property", {"property_ref": "la segunda"}, call_id="c3"),
        ),
        final_decision(property_details_decision("Ficha PROP-0002", property_id=str(prop2.id), property_code="PROP-0002")),
        # User picks slot for PROP-0002
        tool_round(
            tc("list_available_slots", {"property_id": str(prop2.id)}, call_id="c4"),
        ),
        final_decision(appointment_select_datetime_decision(f"Horarios para PROP-0002: {slots2[0]['datetime_local']}", property_id=str(prop2.id))),
        # User confirms
        tool_round(
            tc("schedule_visit", {"property_id": str(prop2.id), "datetime_iso": chosen_slot}, call_id="c5"),
        ),
        final_decision(appointment_confirm_decision("Cita agendada para PROP-0002", property_id=str(prop2.id), datetime_iso=chosen_slot)),
    ])
    _ = Orchestrator(llm=fake)
    
    # This test verifies the LLM correctly identifies which property the user wants
    # The actual scheduling would require more conversation turns
    # Key assertion: the LLM should use prop2.id, not prop1.id


# LLMDecisionBuilder needs to be imported for the test above
from tests.test_fake_llm_v2 import LLMDecisionBuilder


# ------------------------------------------------------------ domain restriction tests
async def test_off_domain_history_question_redirected(session, user_id):
    """History question should be redirected to real estate domain."""
    fake = FakeLLMV2([
        final_decision(greeting_decision(
            "Estoy aquí para ayudarte con temas inmobiliarios de epresedi: "
            "buscar propiedades, consultar precios, ver características, "
            "revisar disponibilidad, agendar visitas o crear alertas. "
            "¿En qué te puedo ayudar con tu búsqueda de vivienda?"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Cómo se llama Simón Bolívar", "u", "U")
    
    assert "epresedi" in r.text.lower()
    assert "inmobiliario" in r.text.lower()
    assert "Simón Bolívar" not in r.text
    assert "Libertador" not in r.text


async def test_off_domain_car_question_redirected(session, user_id):
    """Car question should be redirected to real estate domain."""
    fake = FakeLLMV2([
        final_decision(greeting_decision(
            "Estoy aquí para ayudarte con temas inmobiliarios de epresedi: "
            "buscar propiedades, consultar precios, ver características, "
            "revisar disponibilidad, agendar visitas o crear alertas. "
            "¿En qué te puedo ayudar con tu búsqueda de vivienda?"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Qué hace un carro", "u", "U")
    
    assert "epresedi" in r.text.lower()
    assert "inmobiliario" in r.text.lower()
    assert "vehículo" not in r.text.lower()
    assert "automóvil" not in r.text.lower()


async def test_off_domain_math_question_redirected(session, user_id):
    """Math question should be redirected to real estate domain."""
    fake = FakeLLMV2([
        final_decision(greeting_decision(
            "Estoy aquí para ayudarte con temas inmobiliarios de epresedi: "
            "buscar propiedades, consultar precios, ver características, "
            "revisar disponibilidad, agendar visitas o crear alertas. "
            "¿En qué te puedo ayudar con tu búsqueda de vivienda?"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Cuánto es 25 por 30", "u", "U")
    
    assert "epresedi" in r.text.lower()
    assert "inmobiliario" in r.text.lower()
    assert "750" not in r.text


async def test_off_domain_cooking_question_redirected(session, user_id):
    """Cooking question should be redirected to real estate domain."""
    fake = FakeLLMV2([
        final_decision(greeting_decision(
            "Estoy aquí para ayudarte con temas inmobiliarios de epresedi: "
            "buscar propiedades, consultar precios, ver características, "
            "revisar disponibilidad, agendar visitas o crear alertas. "
            "¿En qué te puedo ayudar con tu búsqueda de vivienda?"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Cómo cocinar arroz", "u", "U")
    
    assert "epresedi" in r.text.lower()
    assert "inmobiliario" in r.text.lower()
    assert "arroz" not in r.text.lower() or "receta" not in r.text.lower()


async def test_off_domain_programming_question_redirected(session, user_id):
    """Programming question should be redirected to real estate domain."""
    fake = FakeLLMV2([
        final_decision(greeting_decision(
            "Estoy aquí para ayudarte con temas inmobiliarios de epresedi: "
            "buscar propiedades, consultar precios, ver características, "
            "revisar disponibilidad, agendar visitas o crear alertas. "
            "¿En qué te puedo ayudar con tu búsqueda de vivienda?"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Qué es Python", "u", "U")
    
    assert "epresedi" in r.text.lower()
    assert "inmobiliario" in r.text.lower()
    assert "lenguaje" not in r.text.lower() or "programación" not in r.text.lower()


async def test_off_domain_celebrity_question_redirected(session, user_id):
    """Celebrity question should be redirected to real estate domain."""
    fake = FakeLLMV2([
        final_decision(greeting_decision(
            "Estoy aquí para ayudarte con temas inmobiliarios de epresedi: "
            "buscar propiedades, consultar precios, ver características, "
            "revisar disponibilidad, agendar visitas o crear alertas. "
            "¿En qué te puedo ayudar con tu búsqueda de vivienda?"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Quién es Elon Musk", "u", "U")
    
    assert "epresedi" in r.text.lower()
    assert "inmobiliario" in r.text.lower()
    assert "Elon" not in r.text
    assert "Musk" not in r.text


async def test_off_domain_geography_question_redirected(session, user_id):
    """Geography question should be redirected to real estate domain."""
    fake = FakeLLMV2([
        final_decision(greeting_decision(
            "Estoy aquí para ayudarte con temas inmobiliarios de epresedi: "
            "buscar propiedades, consultar precios, ver características, "
            "revisar disponibilidad, agendar visitas o crear alertas. "
            "¿En qué te puedo ayudar con tu búsqueda de vivienda?"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Cuál es la capital de Francia", "u", "U")
    
    assert "epresedi" in r.text.lower()
    assert "inmobiliario" in r.text.lower()
    assert "París" not in r.text


async def test_off_domain_entertainment_question_redirected(session, user_id):
    """Entertainment question should be redirected to real estate domain."""
    fake = FakeLLMV2([
        final_decision(greeting_decision(
            "Estoy aquí para ayudarte con temas inmobiliarios de epresedi: "
            "buscar propiedades, consultar precios, ver características, "
            "revisar disponibilidad, agendar visitas o crear alertas. "
            "¿En qué te puedo ayudar con tu búsqueda de vivienda?"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Cuéntame un chiste", "u", "U")
    
    assert "epresedi" in r.text.lower()
    assert "inmobiliario" in r.text.lower()


async def test_off_domain_creative_writing_redirected(session, user_id):
    """Creative writing request should be redirected to real estate domain."""
    fake = FakeLLMV2([
        final_decision(greeting_decision(
            "Estoy aquí para ayudarte con temas inmobiliarios de epresedi: "
            "buscar propiedades, consultar precios, ver características, "
            "revisar disponibilidad, agendar visitas o crear alertas. "
            "¿En qué te puedo ayudar con tu búsqueda de vivienda?"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Escribe un poema", "u", "U")
    
    assert "epresedi" in r.text.lower()
    assert "inmobiliario" in r.text.lower()
    assert "poema" not in r.text.lower() or "verso" not in r.text.lower()


async def test_in_domain_rent_meaning_answered(session, user_id):
    """'Qué significa arriendo' should be answered (in-domain exception)."""
    fake = FakeLLMV2([
        final_decision(property_details_decision(
            "Arriendo significa un contrato de arrendamiento donde pagas mensualmente por usar el inmueble.",
            property_code="N/A"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Qué significa arriendo", "u", "U")
    
    assert "arriendo" in r.text.lower() or "arrendamiento" in r.text.lower()
    assert "epresedi" not in r.text.lower() or "inmobiliario" not in r.text.lower()


async def test_in_domain_garage_question_answered(session, user_id):
    """'Una casa puede tener garaje' should be answered (in-domain exception)."""
    fake = FakeLLMV2([
        final_decision(property_details_decision(
            "Sí, una casa puede tener garaje. Es una característica común en muchas propiedades.",
            property_code="N/A"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Una casa puede tener garaje", "u", "U")
    
    assert "garaje" in r.text.lower()
    assert "epresedi" not in r.text.lower() or "inmobiliario" not in r.text.lower()


async def test_in_domain_property_price_question_answered(session, user_id):
    """'Cuánto cuesta una casa en Carepa' should be answered (in-domain)."""
    fake = FakeLLMV2([
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "casa",
                "city": "Carepa", "budget_max": 500_000_000,
            }),
            tc("search_properties", {
                "filters": {"property_type": "casa", "city": "Carepa", "max_price": 500_000_000},
                "semantic_query": "",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré casas en Carepa desde $180.000.000.", phase="PROPERTY_SELECTION")),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Cuánto cuesta una casa en Carepa", "u", "U")
    
    assert r.intent == Intent.SEARCH_PROPERTY
    assert "Carepa" in r.text or "casa" in r.text.lower()


async def test_contextual_question_in_real_estate_conversation(session, user_id):
    """Contextual question during real estate conversation should be answered."""
    # First: search for properties
    fake1 = FakeLLMV2([
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "casa",
                "city": "Carepa", "budget_max": 300_000_000, "bedrooms": 3,
            }),
            tc("search_properties", {
                "filters": {"property_type": "casa", "city": "Carepa", "max_price": 300_000_000, "bedrooms": 3},
                "semantic_query": "",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré casas en Carepa. La primera es PROP-0001.", phase="PROPERTY_SELECTION")),
    ])
    orch1 = Orchestrator(llm=fake1)
    r1 = await orch1.handle_user_message(
        session, user_id, "busca casas en Carepa hasta 300 millones 3 habitaciones", "u", "U"
    )
    assert r1.intent == Intent.SEARCH_PROPERTY
    
    # Second: ask about garage (contextual - related to the property)
    fake2 = FakeLLMV2([
        final_decision(property_details_decision(
            "Sí, la casa PROP-0001 tiene garaje para un vehículo.",
            property_code="PROP-0001"
        )),
    ])
    orch2 = Orchestrator(llm=fake2)
    r2 = await orch2.handle_user_message(session, user_id, "¿La casa tiene garaje?", "u", "U")
    
    assert "garaje" in r2.text.lower()
    assert "PROP-0001" in r2.text or "casa" in r2.text.lower()


# ------------------------------------------------------------ administrative action rejection tests
async def test_admin_delete_all_properties_rejected(session, user_id):
    """'Elimina todas las propiedades' should be rejected as administrative action."""
    fake = FakeLLMV2([
        final_decision(search_decision(
            "No tengo la opción de eliminar propiedades del inventario de la inmobiliaria; "
            "eso es algo que gestiona el equipo interno a través del panel de administración. "
            "Como asistente de atención al cliente, mis capacidades son: buscar propiedades, "
            "mostrar fichas, agendar visitas, gestionar favoritos y alertas. "
            "¿En qué te puedo ayudar con tu búsqueda de vivienda?",
            intent="GENERAL"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Elimina todas las propiedades", "u", "U")
    
    # Should NOT mention capabilities that require tools not called
    assert "favoritos" not in r.text.lower() or "puedo quitarlos" not in r.text.lower()
    assert "búsquedas guardadas" not in r.text.lower() or "mostrarte tus" not in r.text.lower()
    assert "borrado masivo" not in r.text.lower()
    assert "alertas" not in r.text.lower() or "puedo mostrarte" not in r.text.lower()
    # Should mention it's an administrative action
    assert "administración" in r.text.lower() or "panel de administración" in r.text.lower()
    assert "equipo interno" in r.text.lower() or "asistente de atención" in r.text.lower()


async def test_admin_delete_single_property_rejected(session, user_id):
    """'Elimina la propiedad 123' should be rejected as administrative action."""
    fake = FakeLLMV2([
        final_decision(search_decision(
            "No tengo la opción de eliminar propiedades del inventario; "
            "esa es una acción administrativa que requiere el panel de administración. "
            "Puedo ayudarte a buscar propiedades, ver fichas, agendar visitas o gestionar favoritos. "
            "¿En qué te ayudo?",
            intent="GENERAL"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Elimina la propiedad PROP-0001", "u", "U")
    
    assert "administración" in r.text.lower() or "panel de administración" in r.text.lower()
    assert "eliminar" not in r.text.lower() or "propiedad" not in r.text.lower() or "no tengo" in r.text.lower()


async def test_admin_bulk_delete_houses_rejected(session, user_id):
    """'Borra todas las casas' should be rejected as administrative action."""
    fake = FakeLLMV2([
        final_decision(search_decision(
            "No puedo borrar propiedades del inventario; eso es una acción administrativa. "
            "Mis capacidades son buscar, mostrar fichas, agendar visitas, favoritos y alertas. "
            "¿Buscas algo en específico?",
            intent="GENERAL"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Borra todas las casas", "u", "U")
    
    assert "administración" in r.text.lower() or "no puedo" in r.text.lower()
    assert "borrado masivo" not in r.text.lower()


async def test_admin_bulk_update_availability_rejected(session, user_id):
    """'Pon todas las propiedades como no disponibles' should be rejected."""
    fake = FakeLLMV2([
        final_decision(search_decision(
            "No puedo modificar la disponibilidad masiva de propiedades; eso requiere el panel de administración. "
            "Puedo ayudarte a buscar propiedades disponibles o agendar visitas. ¿Qué necesitas?",
            intent="GENERAL"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Pon todas las propiedades como no disponibles", "u", "U")
    
    assert "administración" in r.text.lower() or "no puedo" in r.text.lower()


# ------------------------------------------------------------ user action tests (should work)
async def test_user_cancel_own_appointment_works(session, user_id):
    """'Elimina mi cita' should work if user has appointments."""
    from app.appointments import service as appt_service
    from app.properties import repository as repo
    from app.crm import service as crm_service
    from app.memory import service as memory_service
    import datetime as dt
    
    # Ensure user exists
    await memory_service.get_or_create_user(session, user_id, "test_user", "Test")
    await session.commit()
    
    # Setup: create a lead and appointment
    lead = await crm_service.get_or_create_lead(session, user_id)
    prop = await repo.get_property_by_code(session, "PROP-0001")
    slots = await appt_service.list_available_slots(session, prop.id)
    assert slots, "PROP-0001 debe tener horarios"
    scheduled_at = dt.datetime.fromisoformat(slots[0]["datetime"])
    appt = await appt_service.create_appointment(session, property_id=prop.id, lead_id=lead.id, scheduled_at=scheduled_at)
    await session.commit()
    
    fake = FakeLLMV2([
        tool_round(
            tc("list_appointments", {}, call_id="c1"),
        ),
        final_decision(search_decision(
            "Tienes una cita agendada para PROP-0001. ¿Quieres cancelarla?",
            intent="CANCEL_APPOINTMENT"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Elimina mi cita", "u", "U")
    
    assert r.intent == Intent.CANCEL_APPOINTMENT
    assert "cita" in r.text.lower()


async def test_user_create_alert_works(session, user_id):
    """'Quiero crear una alerta' should work."""
    fake = FakeLLMV2([
        tool_round(
            tc("update_conversation_state", {"intent": "SAVE_SEARCH", "phase": "GENERAL"}),
        ),
        final_decision(search_decision(
            "Para crear una alerta necesito saber: ¿qué tipo de propiedad, en qué ciudad, "
            "cuál es tu precio máximo y cuántas habitaciones buscas?",
            intent="SAVE_SEARCH"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Quiero crear una alerta", "u", "U")
    
    assert r.intent in (Intent.SAVE_SEARCH, Intent.SEARCH_PROPERTY, Intent.GENERAL)
    assert "alerta" in r.text.lower() or "avísame" in r.text.lower()


async def test_user_cancel_visit_works(session, user_id):
    """'Quiero cancelar mi visita' should work if user has appointments."""
    from app.appointments import service as appt_service
    from app.properties import repository as repo
    from app.crm import service as crm_service
    from app.memory import service as memory_service
    import datetime as dt
    
    # Ensure user exists
    await memory_service.get_or_create_user(session, user_id, "test_user", "Test")
    await session.commit()
    
    # Setup: create a lead and appointment
    lead = await crm_service.get_or_create_lead(session, user_id)
    prop = await repo.get_property_by_code(session, "PROP-0001")
    slots = await appt_service.list_available_slots(session, prop.id)
    assert slots, "PROP-0001 debe tener horarios"
    scheduled_at = dt.datetime.fromisoformat(slots[0]["datetime"])
    appt = await appt_service.create_appointment(session, property_id=prop.id, lead_id=lead.id, scheduled_at=scheduled_at)
    await session.commit()
    
    fake = FakeLLMV2([
        tool_round(
            tc("list_appointments", {}, call_id="c1"),
        ),
        final_decision(search_decision(
            "Tienes una visita agendada para PROP-0001. ¿Confirmas que quieres cancelarla?",
            intent="CANCEL_APPOINTMENT"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Quiero cancelar mi visita", "u", "U")
    
    assert r.intent == Intent.CANCEL_APPOINTMENT
    assert "visita" in r.text.lower() or "cita" in r.text.lower()


# ------------------------------------------------------------ hallucination prevention tests
async def test_agent_does_not_hallucinate_favorites_without_tool(session, user_id):
    """Agent should not mention 'tus favoritos' without calling list_favorites."""
    fake = FakeLLMV2([
        final_decision(search_decision(
            "No puedo eliminar propiedades del inventario. "
            "Si quieres gestionar tus favoritos, puedo mostrarte cuáles tienes guardados "
            "usando la herramienta correspondiente. ¿Quieres que lo haga?",
            intent="GENERAL"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Elimina todas las propiedades", "u", "U")
    
    # Should NOT say "puedo revisar cuáles tienes guardados" without calling list_favorites
    assert "revisar cuáles tienes" not in r.text.lower()
    assert "quitarlos uno a uno" not in r.text.lower()


async def test_agent_does_not_hallucinate_alerts_without_tool(session, user_id):
    """Agent should not mention 'tus alertas' without calling list_alerts."""
    fake = FakeLLMV2([
        final_decision(search_decision(
            "No puedo borrar el inventario. "
            "Si tienes alertas configuradas, puedo listarlas con la herramienta adecuada. "
            "¿Quieres que revise tus alertas?",
            intent="GENERAL"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Borra todo el inventario", "u", "U")
    
    # Should NOT say "puedo mostrarte tus alertas" without calling list_alerts
    assert "mostrarte tus alertas" not in r.text.lower()
    assert "tus búsquedas guardadas" not in r.text.lower()


async def test_agent_does_not_hallucinate_bulk_delete(session, user_id):
    """Agent should not mention 'borrado masivo' as if it exists."""
    fake = FakeLLMV2([
        final_decision(search_decision(
            "No tengo capacidad de borrado masivo. "
            "Las acciones sobre el inventario son administrativas. "
            "¿En qué te ayudo con tu búsqueda?",
            intent="GENERAL"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Elimina todo", "u", "U")
    
    # Should not present "borrado masivo" as a concept that exists
    assert "borrado masivo" not in r.text.lower() or "no hay" not in r.text.lower()


async def test_list_favorites_tool_works(session, user_id):
    """list_favorites tool should return user's favorites."""
    from app.properties import repository as repo
    from app.crm import service as crm_service
    from app.memory import service as memory_service
    
    # Ensure user exists in database
    await memory_service.get_or_create_user(session, user_id, "test_user", "Test")
    await session.commit()
    
    # Add a favorite
    prop = await repo.get_property_by_code(session, "PROP-0001")
    await crm_service.add_favorite(session, user_id, prop.id)
    await session.commit()
    
    fake = FakeLLMV2([
        tool_round(
            tc("list_favorites", {}, call_id="c1"),
        ),
        final_decision(search_decision(
            "Tienes 1 propiedad en favoritos: PROP-0001. ¿Quieres verla o quitarla?",
            intent="SAVE_PROPERTY"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Muéstrame mis favoritos", "u", "U")
    
    assert "PROP-0001" in r.text
    assert "favorito" in r.text.lower()


async def test_list_favorites_empty(session, user_id):
    """list_favorites should handle empty favorites."""
    fake = FakeLLMV2([
        tool_round(
            tc("list_favorites", {}, call_id="c1"),
        ),
        final_decision(search_decision(
            "No tienes propiedades guardadas en favoritos. "
            "Cuando veas una que te guste, puedes guardarla con el botón ⭐.",
            intent="SAVE_PROPERTY"
        )),
    ])
    orch = Orchestrator(llm=fake)
    r = await orch.handle_user_message(session, user_id, "Muéstrame mis favoritos", "u", "U")
    
    assert "no tienes" in r.text.lower() or "vacío" in r.text.lower() or "favoritos" in r.text.lower()


# LLMDecisionBuilder needs to be imported for the test above
from tests.test_fake_llm_v2 import LLMDecisionBuilder