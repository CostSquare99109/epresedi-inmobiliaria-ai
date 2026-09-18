"""E2E: full conversational flows through the orchestrator + real database + RAG.

Flow 1: user → search → real properties → details → save → compare.
Flow 2: user → document question → RAG chunks → cited answer.
Flow 3: user → appointment scheduling via the property card buttons (Telegram UX).
"""
from __future__ import annotations

import pytest

from app.agents.intents import Intent
from app.agents.orchestrator import Orchestrator
from app.crm import service as crm
from sqlalchemy import select

from app.database.base import AsyncSessionLocal
from app.database.models import Appointment


@pytest.fixture
async def orch():
    return Orchestrator(llm=None)  # deterministic, real data, no network


async def _ask(orch, text, user_id, session):
    return await orch.handle_user_message(session, user_id, text, "e2e", "E2E")


def _action(reply, name):
    return next(payload for action, payload in reply.actions if action == name)


async def test_e2e_search_details_save_compare(orch, user_id):
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


async def test_e2e_document_question_with_citation(orch, user_id):
    async with AsyncSessionLocal() as session:
        # quantity question answered from the seeded PDF (Proyecto X → 120 apartamentos)
        r = await _ask(orch, "¿Cuántos apartamentos tiene el Proyecto X?", user_id, session)
        assert "120" in r.text
        assert "Fuente:" in r.text

        # a project with no documentation must NOT be answered with a guess
        r = await _ask(orch, "¿Cuál es el número de apartamentos del Proyecto Y?", user_id, session)
        assert "No tengo información confirmada" in r.text


async def test_e2e_financing_question_from_document(orch, user_id):
    async with AsyncSessionLocal() as session:
        r = await _ask(orch, "¿Cómo funciona la financiación de Villas de Carepa?", user_id, session)
        assert "Fuente:" in r.text
        assert "cuota inicial" in r.text.lower() or "financiacion" in r.text.lower()


async def test_e2e_appointment_flow(orch, user_id):
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

        # book the first offered slot through its payload
        slot_payload = r.actions[0][1]
        r = await orch.handle_action(session, user_id, "book_slot", slot_payload)
        assert "Visita solicitada" in r.text

        appts = (await session.execute(
            select(Appointment).where(Appointment.property_id == slot_payload["property_id"])
        )).scalars().all()
        assert any(a.status.value == "REQUESTED" for a in appts)

        # cancel via the offered action
        r = await orch.handle_action(session, user_id, "cancel_appt", appts[-1].id)
        assert "cancelada" in r.text.lower()


async def test_e2e_saved_search_alert_flow(orch, user_id):
    async with AsyncSessionLocal() as session:
        r = await _ask(orch, "busca apartamentos en Carepa hasta 150 millones", user_id, session)
        assert r.intent == Intent.SEARCH_PROPERTY

        r = await _ask(orch, "avísame cuando aparezca un apartamento de 2 habitaciones por menos de 150 millones", user_id, session)
        assert r.intent == Intent.SAVE_SEARCH
        assert "Alerta creada" in r.text

        sses = await crm.list_saved_searches(session, user_id)
        assert sses and sses[0].filters.get("max_price") == 150_000_000


async def test_e2e_full_journey_matches_definition_of_done(orch, user_id):
    """/start → búsqueda natural → detalles → guardar → comparar → IA/RAG → agendar."""
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
        assert "Visita solicitada" in r.text

        favorites = await crm.list_favorites(session, user_id)
        assert favorites


async def test_e2e_prop3_images_then_appointment_buttons_valid(orch, user_id):
    """Regression for telegram.error.BadRequest: Button_data_invalid.

    hola → comprar → la tercera → imágenes → 'Bueno quiero agendar una cita
    para verla en persona' must keep PROP-0003 selected and produce book_slot
    buttons whose callback_data fits Telegram's 64-byte limit; booking through
    the parsed callback works end to end and last_results survive."""
    from app.bot.keyboards import build_keyboard, parse_callback
    from app.memory import service as memory_service

    async with AsyncSessionLocal() as session:
        await _ask(orch, "hola", user_id, session)
        r = await _ask(orch, "Deseo comprar una casa", user_id, session)
        assert r.intent == Intent.SEARCH_PROPERTY

        r = await _ask(orch, "La tercera me interesa la puedo ver?", user_id, session)
        assert r.intent == Intent.PROPERTY_DETAILS
        assert "PROP-0003" in r.text
        user = await memory_service.get_or_create_user(session, user_id)
        conv = await memory_service.get_or_create_conversation(session, user.id)
        prop_id = conv.state.get("last_property_id")
        assert prop_id

        r = await _ask(orch, "Muéstrame imágenes porfa", user_id, session)
        assert r.intent == Intent.PROPERTY_IMAGES

        r = await _ask(orch, "Bueno quiero agendar una cita para verla en persona", user_id, session)
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
        assert "Visita solicitada" in r2.text

        booked_id = payload["property_id"]
        assert booked_id == prop_id  # the selected property was kept
        appts = (await session.execute(
            select(Appointment).where(Appointment.property_id == booked_id)
        )).scalars().all()
        assert any(a.status.value == "REQUESTED" for a in appts)

        r3 = await _ask(orch, "la tercera tiene piscina?", user_id, session)
        assert "PROP-0003" in r3.text  # last_results preserved after booking


async def test_e2e_ordinal_references_and_code_reference(orch, user_id):
    """'la primera..la cuarta' resolve in order; bare PROP-0003 resolves too."""
    from app.memory import service as memory_service

    async with AsyncSessionLocal() as session:
        r = await _ask(orch, "Deseo comprar una casa", user_id, session)
        assert r.intent == Intent.SEARCH_PROPERTY

        user = await memory_service.get_or_create_user(session, user_id)
        conv = await memory_service.get_or_create_conversation(session, user.id)
        expected = [item["code"] for item in (conv.state.get("last_results") or [])]
        assert len(expected) == 4

        for i, word in enumerate(("la primera", "la segunda", "la tercera", "la cuarta")):
            r = await _ask(orch, word, user_id, session)
            assert r.intent == Intent.PROPERTY_DETAILS, f"{word}: {r.text[:80]!r}"
            assert expected[i] in r.text, f"{word}: expected {expected[i]} in reply"

        r = await _ask(orch, "PROP-0003", user_id, session)
        assert r.intent == Intent.PROPERTY_DETAILS
        assert "PROP-0003" in r.text
