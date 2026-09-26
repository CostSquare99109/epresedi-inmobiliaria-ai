"""E2E: full conversational flows through the orchestrator + real database + RAG.

Flow 1: user → search → real properties → details → save → compare.
Flow 2: user → document question → RAG chunks → cited answer.
Flow 3: user → appointment scheduling via the property card buttons (Telegram UX).

These tests use FakeLLMV2 to simulate LLM decisions per the LLM-FIRST architecture.
"""
from __future__ import annotations

from sqlalchemy import select

from app.agents.intents import Intent
from app.agents.orchestrator import Orchestrator
from app.crm import service as crm
from app.database.base import AsyncSessionLocal
from app.database.models import Appointment
from tests.test_fake_llm_v2 import (
    FakeLLMV2,
    final_decision,
    make_flow_agent,
    property_details_decision,
    search_decision,
    tc,
    tool_round,
)


async def _ask(orch, text, user_id, session):
    return await orch.handle_user_message(session, user_id, text, "e2e", "E2E")


def _action(reply, name):
    return next(payload for action, payload in reply.actions if action == name)


def _make_search_orchestrator():
    """Orchestrator for search → details → save → compare flow."""
    return Orchestrator(llm=FakeLLMV2([
        # Turn 1: Search
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "casa",
                "city": "Carepa", "budget_max": 300_000_000, "bedrooms": 3,
            }),
            tc("search_properties", {
                "filters": {"property_type": "casa", "city": "Carepa", "max_price": 300_000_000, "bedrooms": 3},
                "semantic_query": "casa 3 habitaciones Carepa",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré casas en Carepa. La primera es PROP-0001.", phase="PROPERTY_SELECTION")),
        # Turn 2: "la primera"
        tool_round(tc("get_property", {"property_ref": "la primera"}, call_id="c3")),
        final_decision(property_details_decision("Casa familiar en Carepa - 3 habitaciones, 2 baños, garaje.", property_code="PROP-0001")),
        # Turn 3: "¿tiene garaje?"
        final_decision(property_details_decision("Sí, la propiedad tiene garaje (1 parqueadero).", property_code="PROP-0001")),
        # Turn 4: "guarda esta"
        tool_round(tc("save_property", {"property_id": "PROP-0001"}, call_id="c4")),
        final_decision(property_details_decision("Guardada en favoritos.", property_code="PROP-0001")),
        # Turn 5: "compárame estas propiedades"
        tool_round(tc("compare_properties", {"property_refs": ["PROP-0001", "PROP-0002"]}, call_id="c5")),
        final_decision(property_details_decision("Comparación de propiedades...", property_code="PROP-0001")),
    ]))


def _make_document_qa_orchestrator():
    """Orchestrator for document Q&A flow."""
    return Orchestrator(llm=FakeLLMV2([
        tool_round(tc("search_documents", {"query": "cuántos apartamentos Proyecto X"}, call_id="c1")),
        final_decision(search_decision("Según ficha Proyecto X: 120 apartamentos. Fuente: ficha_proyecto_x.pdf", phase="GENERAL")),
        tool_round(tc("search_documents", {"query": "cuántos apartamentos Proyecto Y"}, call_id="c2")),
        final_decision(search_decision("No tengo información confirmada sobre Proyecto Y.", phase="GENERAL")),
    ]))


def _make_financing_orchestrator():
    """Orchestrator for the financing-question flow (separate fixture, single turn)."""
    return Orchestrator(llm=FakeLLMV2([
        tool_round(tc("search_documents", {"query": "financiación Villas de Carepa"}, call_id="c1")),
        final_decision(search_decision("Financiación: cuota inicial 30%, resto en cuotas. Fuente: ficha_villas_carepa.pdf", phase="GENERAL")),
    ]))


def _make_flow_orchestrator(**agent_kwargs):
    """Orchestrator con el agente dinámico: decide en cada ronda a partir de
    la evidencia real (envelopes de tools + estado validado), sin guiones."""
    return Orchestrator(llm=FakeLLMV2([make_flow_agent(**agent_kwargs)]))


def _make_appointment_orchestrator():
    """Agente dinámico para el flujo de citas.

    Filtros angostos (casa · Carepa · ≤300M · 3 habitaciones) cuya relevancia
    real deja PROP-0001 primera — verificado contra la BD de test—, así la
    referencia «la primera» es determinista sin hardcodear la respuesta.
    """
    return _make_flow_orchestrator(
        search_filters={"property_type": "casa", "city": "Carepa",
                        "max_price": 300_000_000, "bedrooms": 3},
        search_query="casa familiar Carepa 3 habitaciones",
    )


def _make_saved_search_orchestrator():
    """Orchestrator for saved search alert flow."""
    return Orchestrator(llm=FakeLLMV2([
        # Turn 1: Search
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "apartamento",
                "city": "Carepa", "budget_max": 150_000_000,
            }),
            tc("search_properties", {
                "filters": {"property_type": "apartamento", "city": "Carepa", "max_price": 150_000_000},
                "semantic_query": "apartamento Carepa 150 millones",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré apartamentos en Carepa.", phase="PROPERTY_SELECTION")),
        # Turn 2: Save search
        tool_round(tc("save_search", {
            "name": "Apartamentos Carepa < 150M",
            "filters": {"property_type": "apartamento", "city": "Carepa", "max_price": 150_000_000, "bedrooms": 2}
        }, call_id="c3")),
        final_decision(search_decision("Alerta creada: Apartamentos Carepa < 150M con 2 habitaciones.", phase="GENERAL", intent="SAVE_SEARCH")),
    ]))


def _make_full_journey_orchestrator():
    """Agente dinámico para el journey completo (saludo → búsqueda → detalles
    → guardar → comparar → RAG → agendar). Sin bedrooms en los filtros no:
    PROP-0001 sigue primera con 3 habitaciones verificadas en BD."""
    return _make_flow_orchestrator(
        search_filters={"property_type": "casa", "city": "Carepa",
                        "max_price": 300_000_000, "bedrooms": 3},
        search_query="casa Carepa 3 habitaciones 300 millones",
    )


def _make_ordinal_orchestrator():
    """Orchestrator for ordinal reference tests."""
    return Orchestrator(llm=FakeLLMV2([
        # Turn 1: Search
        tool_round(
            tc("update_conversation_state", {
                "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "casa",
                "city": "Carepa", "budget_max": 300_000_000,
            }),
            tc("search_properties", {
                "filters": {"property_type": "casa", "city": "Carepa", "max_price": 300_000_000},
                "semantic_query": "casa Carepa",
            }, call_id="c2"),
        ),
        final_decision(search_decision("Encontré 4 casas en Carepa.", phase="PROPERTY_SELECTION")),
        # Turns 2-5: "la primera".."la cuarta" (orden real de relevancia: PROP-0010, PROP-0003, PROP-0009, PROP-0001)
        tool_round(tc("get_property", {"property_ref": "la primera"}, call_id="c3")),
        final_decision(property_details_decision("Casa - PROP-0010", property_code="PROP-0010")),
        tool_round(tc("get_property", {"property_ref": "la segunda"}, call_id="c4")),
        final_decision(property_details_decision("Casa - PROP-0003", property_code="PROP-0003")),
        tool_round(tc("get_property", {"property_ref": "la tercera"}, call_id="c5")),
        final_decision(property_details_decision("Casa - PROP-0009", property_code="PROP-0009")),
        tool_round(tc("get_property", {"property_ref": "la cuarta"}, call_id="c6")),
        final_decision(property_details_decision("Casa - PROP-0001", property_code="PROP-0001")),
        # Turn 6: Direct code reference
        tool_round(tc("get_property", {"property_ref": "PROP-0003"}, call_id="c7")),
        final_decision(property_details_decision("Casa - PROP-0003", property_code="PROP-0003")),
    ]))


async def test_e2e_search_details_save_compare(user_id):
    orch = _make_search_orchestrator()
    async with AsyncSessionLocal() as session:
        # 1) natural-language search (2 available results)
        r = await _ask(orch, "busca casas en Carepa hasta 300 millones con 3 habitaciones", user_id, session)
        assert r.intent == Intent.SEARCH_PROPERTY
        assert "PROP-0001" in r.text

        # 2) details via contextual reference
        r = await _ask(orch, "la primera", user_id, session)
        assert r.intent == Intent.PROPERTY_DETAILS
        assert "Casa familiar" in r.text  # PROP-0001 title
        assert "Código: PROP-0001" in r.text

        # 3) attribute question answered from stored data (garaje confirmed)
        r = await _ask(orch, "¿tiene garaje?", user_id, session)
        assert "PARQUEADERO" in r.text.upper() or "garaje" in r.text.lower()

        # 4) save to favorites (focused property in context)
        r = await _ask(orch, "guarda esta", user_id, session)
        assert "Guardada" in r.text or "favoritos" in r.text
        favorites = await crm.list_favorites(session, user_id)
        assert any(p.code == "PROP-0001" for p in favorites)

        # 5) comparison from last results (data-only)
        r = await _ask(orch, "compárame estas propiedades", user_id, session)
        assert "Comparación" in r.text
        assert "PROP-0001" in r.text


async def test_e2e_document_question_with_citation(user_id):
    orch = _make_document_qa_orchestrator()
    async with AsyncSessionLocal() as session:
        # quantity question answered from the seeded PDF (Proyecto X → 120 apartamentos)
        r = await _ask(orch, "¿Cuántos apartamentos tiene el Proyecto X?", user_id, session)
        assert "120" in r.text
        assert "Fuente:" in r.text

        # a project with no documentation must NOT be answered with a guess
        r = await _ask(orch, "¿Cuál es el número de apartamentos del Proyecto Y?", user_id, session)
        assert "No tengo información confirmada" in r.text


async def test_e2e_financing_question_from_document(user_id):
    orch = _make_financing_orchestrator()
    async with AsyncSessionLocal() as session:
        r = await _ask(orch, "¿Cómo funciona la financiación de Villas de Carepa?", user_id, session)
        assert "Fuente:" in r.text
        assert "cuota inicial" in r.text.lower() or "financiacion" in r.text.lower()


async def test_e2e_appointment_flow(user_id):
    orch = _make_appointment_orchestrator()
    async with AsyncSessionLocal() as session:
        # search → several results → user focuses one via reference
        r = await _ask(orch, "busca la casa familiar en Carepa de 3 habitaciones", user_id, session)
        assert r.intent == Intent.SEARCH_PROPERTY

        r = await _ask(orch, "la primera", user_id, session)
        assert r.intent == Intent.PROPERTY_DETAILS
        prop_id = _action(r, "slots")  # the card offers "📅 Agendar visita"

        # slots → book_slot buttons
        r = await orch.handle_action(session, user_id, "slots", prop_id)
        assert r.intent == Intent.SCHEDULE_VISIT
        assert r.actions and r.actions[0][0] == "book_slot"

        # book the first offered slot through its payload - now asks for contact info
        slot_payload = r.actions[0][1]
        r = await orch.handle_action(session, user_id, "book_slot", slot_payload)
        assert "Para confirmar tu cita necesito" in r.text
        assert "Nombre completo" in r.text

        # provide contact info
        r = await _ask(orch, "Juan Pérez\n3001234567\njuan@gmail.com", user_id, session)
        assert "Por favor confirma tu cita" in r.text
        assert "Juan Pérez" in r.text
        assert "3001234567" in r.text
        assert "juan@gmail.com" in r.text
        assert r.actions and any(a[0] == "confirm_booking" for a in r.actions)

        # confirm the booking
        confirm_payload = next(payload for action, payload in r.actions if action == "confirm_booking")
        r = await orch.handle_action(session, user_id, "confirm_booking", confirm_payload)
        assert "Cita confirmada" in r.text

        appts = (await session.execute(
            select(Appointment).where(Appointment.property_id == slot_payload["property_id"])
        )).scalars().all()
        assert any(a.status.value == "REQUESTED" for a in appts)

        # cancel via the offered action
        r = await orch.handle_action(session, user_id, "cancel_appt", appts[-1].id)
        assert "cancelada" in r.text.lower()


async def test_e2e_saved_search_alert_flow(user_id):
    orch = _make_saved_search_orchestrator()
    async with AsyncSessionLocal() as session:
        r = await _ask(orch, "busca apartamentos en Carepa hasta 150 millones", user_id, session)
        assert r.intent == Intent.SEARCH_PROPERTY

        r = await _ask(orch, "avísame cuando aparezca un apartamento de 2 habitaciones por menos de 150 millones", user_id, session)
        assert r.intent == Intent.SAVE_SEARCH
        assert "Alerta creada" in r.text

        sses = await crm.list_saved_searches(session, user_id)
        assert sses and sses[0].filters.get("max_price") == 150_000_000


async def test_e2e_full_journey_matches_definition_of_done(user_id):
    """/start → búsqueda natural → detalles → guardar → comparar → IA/RAG → agendar."""
    orch = _make_full_journey_orchestrator()
    async with AsyncSessionLocal() as session:
        r = await _ask(orch, "hola", user_id, session)
        assert r.text  # /start welcome equivalent

        r = await _ask(orch, "busco casa en Carepa hasta 300 millones con 3 habitaciones", user_id, session)
        assert r.intent == Intent.SEARCH_PROPERTY and "Encontré" in r.text

        r = await _ask(orch, "la primera", user_id, session)
        assert r.intent == Intent.PROPERTY_DETAILS
        slots_ref = _action(r, "slots")

        r = await _ask(orch, "guarda esta", user_id, session)
        assert "Guardada" in r.text or "favoritos" in r.text

        r = await _ask(orch, "compárame estas propiedades", user_id, session)
        assert "Comparación" in r.text

        r = await _ask(orch, "¿Cuántos apartamentos tiene el Proyecto X?", user_id, session)
        assert "120" in r.text and "Fuente:" in r.text

        # schedule on the focused property via the card button
        r = await orch.handle_action(session, user_id, "slots", slots_ref)
        assert r.actions and r.actions[0][0] == "book_slot"
        r = await orch.handle_action(session, user_id, "book_slot", r.actions[0][1])
        assert "Para confirmar tu cita necesito" in r.text

        # provide contact info
        r = await _ask(orch, "Juan Pérez\n3001234567\njuan@gmail.com", user_id, session)
        assert "Por favor confirma tu cita" in r.text
        confirm_payload = next(payload for action, payload in r.actions if action == "confirm_booking")
        r = await orch.handle_action(session, user_id, "confirm_booking", confirm_payload)
        assert "Cita confirmada" in r.text

        favorites = await crm.list_favorites(session, user_id)
        assert favorites


async def test_e2e_prop3_images_then_appointment_buttons_valid(user_id):
    """Regression for telegram.error.BadRequest: Button_data_invalid.

    hola → comprar → la tercera → imágenes → 'Bueno quiero agendar una cita
    para verla en persona' must keep PROP-0003 selected and produce book_slot
    buttons whose callback_data fits Telegram's 64-byte limit; booking through
    the parsed callback works end to end and last_results survive."""
    from app.bot.keyboards import build_keyboard, parse_callback
    from app.memory import service as memory_service

    # Agente dinámico: sin filtro de habitaciones, la relevancia real deja
    # PROP-0003 primera (verificado contra la BD de test).
    orch = _make_flow_orchestrator(
        search_filters={"property_type": "casa", "city": "Carepa",
                        "max_price": 300_000_000},
        search_query="casa en Carepa",
    )
    async with AsyncSessionLocal() as session:
        await _ask(orch, "hola", user_id, session)
        r = await _ask(orch, "Deseo comprar una casa", user_id, session)
        assert r.intent == Intent.SEARCH_PROPERTY

        r = await _ask(orch, "La primera me interesa la puedo ver?", user_id, session)
        assert r.intent == Intent.PROPERTY_DETAILS
        assert "PROP-0003" in r.text
        user = await memory_service.get_or_create_user(session, user_id)
        conv = await memory_service.get_or_create_conversation(session, user.id)
        prop_id = conv.state.get("last_property_id")
        assert prop_id

        r = await _ask(orch, "Muéstrame imágenes porfa", user_id, session)
        assert r.intent == Intent.PROPERTY_IMAGES

        # FASE A: User wants to schedule but no date/time -> agent responds with business hours
        r = await _ask(orch, "Bueno quiero agendar una cita para verla en persona", user_id, session)
        assert r.intent == Intent.SCHEDULE_VISIT
        assert "lunes a viernes" in r.text and "sábados" in r.text and "domingos no hay citas" in r.text
        assert not r.actions  # No slots offered yet

        # FASE B: User provides date/time -> agent shows slots
        r = await _ask(orch, "Mañana a las 10", user_id, session)
        assert r.intent == Intent.SCHEDULE_VISIT
        assert r.actions and r.actions[0][0] == "book_slot"

        kb = build_keyboard(r.actions)
        assert kb is not None
        buttons = [b for row in kb.inline_keyboard for b in row]
        assert buttons
        for b in buttons:
            assert len(b.callback_data.encode("utf-8")) <= 64

        action, payload = parse_callback(buttons[0].callback_data)
        assert action == "book_slot"
        r2 = await orch.handle_action(session, user_id, action, payload)
        # Now asks for contact info instead of booking immediately
        assert "Para confirmar tu cita necesito" in r2.text

        # Provide contact info and confirm
        r3 = await _ask(orch, "Juan Pérez\n3001234567\njuan@gmail.com", user_id, session)
        assert "Por favor confirma tu cita" in r3.text
        confirm_payload = next(p for a, p in r3.actions if a == "confirm_booking")
        r4 = await orch.handle_action(session, user_id, "confirm_booking", confirm_payload)
        assert "Cita confirmada" in r4.text

        booked_id = payload["property_id"]
        assert booked_id == prop_id  # the selected property was kept
        appts = (await session.execute(
            select(Appointment).where(Appointment.property_id == booked_id)
        )).scalars().all()
        assert any(a.status.value == "REQUESTED" for a in appts)

        r5 = await _ask(orch, "la primera tiene piscina?", user_id, session)
        assert "PROP-0003" in r5.text  # last_results preserved after booking


async def test_e2e_ordinal_references_and_code_reference(user_id):
    """'la primera..la cuarta' resolve in order; bare PROP-0003 resolves too."""
    from app.memory import service as memory_service

    orch = _make_ordinal_orchestrator()
    async with AsyncSessionLocal() as session:
        r = await _ask(orch, "Deseo comprar una casa", user_id, session)
        assert r.intent == Intent.SEARCH_PROPERTY

        user = await memory_service.get_or_create_user(session, user_id)
        conv = await memory_service.get_or_create_conversation(session, user.id)
        expected = [item["code"] for item in (conv.state.get("last_results") or [])]
        assert len(expected) == 4  # inventario real: 4 casas ≤300M en Carepa (PROP-0010/0003/0009/0001)

        for i, word in enumerate(("la primera", "la segunda", "la tercera", "la cuarta")):
            r = await _ask(orch, word, user_id, session)
            assert r.intent == Intent.PROPERTY_DETAILS, f"{word}: {r.text[:80]!r}"
            assert expected[i] in r.text, f"{word}: expected {expected[i]} in reply"

        r = await _ask(orch, "PROP-0003", user_id, session)
        assert r.intent == Intent.PROPERTY_DETAILS
        assert "PROP-0003" in r.text


# ──────────────────────────────────────────────────────────────────────────────
# Tests for correct appointment scheduling flow (FASE A: business hours first)
# ──────────────────────────────────────────────────────────────────────────────

async def test_appointment_fase_a_business_hours_first(user_id):
    """Test that agent responds with business hours when user asks to schedule without date/time.
    
    This is the REGRESSION TEST for the bug where agent would immediately show all slots.
    """
    from tests.test_fake_llm_v2 import FakeLLMV2, make_flow_agent
    from app.agents.orchestrator import Orchestrator
    from app.memory import service as memory_service
    
    agent = make_flow_agent(
        search_filters={'property_type': 'casa', 'city': 'Carepa', 'max_price': 300_000_000},
        search_query='casa Carepa'
    )
    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)
    
    async with AsyncSessionLocal() as session:
        user = await memory_service.get_or_create_user(session, user_id, 'test', 'Test')
        await memory_service.create_new_conversation(session, user.id)
        await session.commit()
        
        # Search for a property first
        r = await orch.handle_user_message(session, user.id, 'busca casa en Carepa hasta 300 millones', 'test', 'Test')
        assert r.intent == Intent.SEARCH_PROPERTY
        
        # User asks to schedule WITHOUT date/time - should get business hours, NOT slots
        r2 = await orch.handle_user_message(session, user.id, 'Quiero agendar una cita para la propiedad PROP-0001', 'test', 'Test')
        
# Verify response contains business hours info
        assert r2.intent == Intent.SCHEDULE_VISIT
        text_lower = r2.text.lower()
        assert 'lunes' in text_lower
        assert 'viernes' in text_lower
        assert 'sábado' in text_lower or 'sabado' in text_lower
        assert 'domingo' in text_lower
        assert '8:00' in r2.text or '08:00' in r2.text
        assert '18:00' in r2.text or '6:00' in r2.text
        assert '9:00' in r2.text
        assert '15:00' in r2.text or '3:00' in r2.text
        
        # Verify NO slots are enumerated (no book_slot actions)
        assert not r2.actions or not any(a[0] == 'book_slot' for a in r2.actions)
        
        # Verify the response asks for date/time
        assert 'qué día' in text_lower or 'qué hora' in text_lower or 'día y hora' in text_lower


async def test_appointment_fase_b_datetime_provided_shows_slots(user_id):
    """Test that agent shows slots when user provides a specific date/time."""
    from tests.test_fake_llm_v2 import FakeLLMV2, make_flow_agent
    from app.agents.orchestrator import Orchestrator
    from app.memory import service as memory_service
    
    agent = make_flow_agent(
        search_filters={'property_type': 'casa', 'city': 'Carepa', 'max_price': 300_000_000},
        search_query='casa Carepa'
    )
    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)
    
    async with AsyncSessionLocal() as session:
        user = await memory_service.get_or_create_user(session, user_id + 1000, 'test', 'Test')
        await memory_service.create_new_conversation(session, user.id)
        await session.commit()
        
        # Search for a property first
        r = await orch.handle_user_message(session, user.id, 'busca casa en Carepa hasta 300 millones', 'test', 'Test')
        assert r.intent == Intent.SEARCH_PROPERTY
        
        # User asks to schedule WITHOUT date/time - gets business hours
        r2 = await orch.handle_user_message(session, user.id, 'Quiero agendar una cita para la propiedad PROP-0001', 'test', 'Test')
        assert r2.intent == Intent.SCHEDULE_VISIT
        assert not r2.actions or not any(a[0] == 'book_slot' for a in r2.actions)
        
        # User provides date/time - should show slots
        r3 = await orch.handle_user_message(session, user.id, 'el martes a las 10', 'test', 'Test')
        
        # Verify slots are shown
        assert r3.intent == Intent.SCHEDULE_VISIT
        assert r3.actions and any(a[0] == 'book_slot' for a in r3.actions)
        assert len(r3.actions) > 0


async def test_appointment_full_flow_scheduling(user_id):
    """Test the complete appointment scheduling flow: search -> schedule (no dt) -> datetime -> book -> contact -> confirm."""
    from tests.test_fake_llm_v2 import FakeLLMV2, make_flow_agent
    from app.agents.orchestrator import Orchestrator
    from app.memory import service as memory_service
    from app.database.models import Appointment, Property
    from sqlalchemy import select
    
    agent = make_flow_agent(
        search_filters={'property_type': 'casa', 'city': 'Carepa', 'max_price': 300_000_000},
        search_query='casa Carepa'
    )
    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)
    
    async with AsyncSessionLocal() as session:
        user = await memory_service.get_or_create_user(session, user_id + 2000, 'test', 'Test')
        await memory_service.create_new_conversation(session, user.id)
        await session.commit()
        
        # Turn 1: Search
        r = await orch.handle_user_message(session, user.id, 'busca casa en Carepa hasta 300 millones', 'test', 'Test')
        assert r.intent == Intent.SEARCH_PROPERTY
        
        # Turn 2: Schedule without date/time -> business hours
        r2 = await orch.handle_user_message(session, user.id, 'Quiero agendar una cita para la propiedad PROP-0001', 'test', 'Test')
        assert r2.intent == Intent.SCHEDULE_VISIT
        text_lower = r2.text.lower()
        assert 'lunes' in text_lower
        assert 'viernes' in text_lower
        assert 'sábado' in text_lower or 'sabado' in text_lower
        assert not r2.actions or not any(a[0] == 'book_slot' for a in r2.actions)
        
        # Turn 3: Provide date/time -> slots
        r3 = await orch.handle_user_message(session, user.id, 'el martes a las 10', 'test', 'Test')
        assert r3.intent == Intent.SCHEDULE_VISIT
        assert r3.actions and any(a[0] == 'book_slot' for a in r3.actions)
        
        # Turn 4: Book a slot
        slot_payload = r3.actions[0][1]
        r4 = await orch.handle_action(session, user.id, 'book_slot', slot_payload)
        assert 'contacto' in r4.text.lower() or 'nombre' in r4.text.lower()
        
        # Turn 5: Provide contact info
        r5 = await orch.handle_user_message(session, user.id, 'Juan Pérez\n3001234567\njuan@gmail.com', 'test', 'Test')
        assert r5.intent == Intent.SCHEDULE_VISIT
        assert r5.actions and any(a[0] == 'confirm_booking' for a in r5.actions)
        
        # Turn 6: Confirm booking
        confirm_payload = next(payload for action, payload in r5.actions if action == 'confirm_booking')
        r6 = await orch.handle_action(session, user.id, 'confirm_booking', confirm_payload)
        assert 'Cita confirmada' in r6.text or 'confirmada' in r6.text.lower()
        
        # Verify appointment was created in database (use property UUID, not code)
        prop = (await session.execute(
            select(Property).where(Property.code == "PROP-0001")
        )).scalar_one()
        appts = (await session.execute(
            select(Appointment).where(Appointment.property_id == prop.id)
        )).scalars().all()
        assert any(a.status.value == "REQUESTED" for a in appts)


async def test_appointment_rejects_sunday(user_id):
    """Test that agent rejects Sunday scheduling without checking availability."""
    from tests.test_fake_llm_v2 import FakeLLMV2, make_flow_agent
    from app.agents.orchestrator import Orchestrator
    from app.memory import service as memory_service
    
    agent = make_flow_agent(
        search_filters={'property_type': 'casa', 'city': 'Carepa', 'max_price': 300_000_000},
        search_query='casa Carepa'
    )
    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)
    
    async with AsyncSessionLocal() as session:
        user = await memory_service.get_or_create_user(session, user_id + 3000, 'test', 'Test')
        await memory_service.create_new_conversation(session, user.id)
        await session.commit()
        
        r = await orch.handle_user_message(session, user.id, 'busca casa en Carepa hasta 300 millones', 'test', 'Test')
        
        # User tries to schedule for Sunday
        r2 = await orch.handle_user_message(session, user.id, 'Quiero agendar para el domingo a las 10', 'test', 'Test')
        
        # Should reject Sunday
        assert r2.intent == Intent.SCHEDULE_VISIT
        assert 'domingo' in r2.text.lower()
        assert 'no hay citas' in r2.text.lower() or 'cerrado' in r2.text.lower()
        # Should NOT show slots
        assert not r2.actions or not any(a[0] == 'book_slot' for a in r2.actions)


async def test_appointment_rejects_outside_hours(user_id):
    """Test that agent rejects times outside business hours without checking availability."""
    from tests.test_fake_llm_v2 import FakeLLMV2, make_flow_agent
    from app.agents.orchestrator import Orchestrator
    from app.memory import service as memory_service
    
    agent = make_flow_agent(
        search_filters={'property_type': 'casa', 'city': 'Carepa', 'max_price': 300_000_000},
        search_query='casa Carepa'
    )
    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)
    
    async with AsyncSessionLocal() as session:
        user = await memory_service.get_or_create_user(session, user_id + 4000, 'test', 'Test')
        await memory_service.create_new_conversation(session, user.id)
        await session.commit()
        
        r = await orch.handle_user_message(session, user.id, 'busca casa en Carepa hasta 300 millones', 'test', 'Test')
        
        # User tries to schedule at 19:00 (outside Mon-Fri 8-18)
        r2 = await orch.handle_user_message(session, user.id, 'Quiero agendar para el martes a las 19', 'test', 'Test')
        
        # Should reject
        assert r2.intent == Intent.SCHEDULE_VISIT
        assert 'fuera' in r2.text.lower() or 'horario' in r2.text.lower()
        assert not r2.actions or not any(a[0] == 'book_slot' for a in r2.actions)