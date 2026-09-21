"""Tests decisivos del AGENT-LOOP: ¿es un agente de verdad o un workflow disfrazado?

Cubren los requisitos especiales del mega-prompt:
- §82 anti-agentwashing: la evidencia de tools vuelve al LLM y él compone.
- §83 el resultado de una tool CAMBIA la siguiente decisión (resultado A → camino 1,
  resultado B → camino 2).
- §84 web_search cuando hace falta; herramientas internas cuando bastan.
- §85 tool → timeout → retry → éxito; y retry agotado → error estructurado →
  el agente continúa con lo demás.
- §86 escenario PROP-0008/PROP-0009 con fallo parcial y recuperación.
- §18/§19 lotes: varias calls independientes ejecutadas y correlacionadas.
- §31/§20/§73 continuidad conversacional sin llamadas redundantes.
"""
from __future__ import annotations

import json

from app.agents.intents import Intent
from app.agents.metrics import METRICS
from app.ai.llm import LLMError
from tests.test_fake_llm_v2 import (
    FakeLLMV2,
    send_response_round,
    tc,
    tool_round,
)


def _tool_data(messages: list[dict], tool_name: str) -> list[dict]:
    """Envelopes de un tool concreto tal como los vio el LLM."""
    out = []
    for m in messages:
        if m.get("role") != "tool":
            continue
        try:
            env = json.loads(m["content"])
        except (json.JSONDecodeError, TypeError):
            continue
        if env.get("tool") == tool_name:
            out.append(env)
    return out


def _last_trace(orch):
    return orch._pure_orchestrator.runtime._last_trace


async def _prop_id(session, code: str) -> str:
    from sqlalchemy import text as sql_text

    return str((await session.execute(
        sql_text("SELECT id FROM properties WHERE code = :c"), {"c": code}
    )).scalar_one())


# ══════════════════════════════════════════════════════════════ §83
async def test_tool_result_A_leads_to_path_1_result_B_leads_to_path_2(session, user_id):
    """El MISMO primer tool con dos resultados distintos → dos caminos distintos.

    Resultado A (hay propiedades) → el agente pide la ficha (get_property).
    Resultado B (0 propiedades) → el agente crea una alerta (save_search).
    """
    from app.agents.orchestrator import Orchestrator

    # ── camino 1: búsqueda con resultados → get_property
    def agent_with_results(messages, tools):
        searches = _tool_data(messages, "search_properties")
        if not searches:
            return tool_round(tc("search_properties", {
                "filters": {"city": "Carepa", "property_type": "casa"},
            }, call_id="s1"))
        data = searches[-1].get("data") or {}
        if data.get("count", 0) > 0:
            if not _tool_data(messages, "get_property"):
                return tool_round(tc("get_property", {"property_ref": "la primera"}, call_id="g1"))
            return send_response_round("Ficha lista con los datos reales.")
        return send_response_round("camino inesperado")

    orch = Orchestrator(llm=FakeLLMV2([agent_with_results]))
    reply = await orch.handle_user_message(session, user_id, "casas en Carepa", "t", "T")
    assert "Ficha lista" in reply.text
    executed = [t["tool"] for t in _last_trace(orch)]
    assert executed[:2] == ["search_properties", "get_property"]

    # ── camino 2: la misma tool, 0 resultados → save_search (alerta)
    def agent_no_results(messages, tools):
        searches = _tool_data(messages, "search_properties")
        if not searches:
            return tool_round(tc("search_properties", {
                "filters": {"city": "NoExisteCiudad", "property_type": "finca"},
            }, call_id="s1"))
        data = searches[-1].get("data") or {}
        if data.get("count", 0) == 0:
            if not _tool_data(messages, "save_search"):
                return tool_round(tc("save_search", {
                    "name": "Alerta finca", "filters": {"city": "NoExisteCiudad"},
                }, call_id="a1"))
            return send_response_round("No hay finca ahí: te creé una alerta.")
        return send_response_round("camino inesperado")

    orch_b = Orchestrator(llm=FakeLLMV2([agent_no_results]))
    reply_b = await orch_b.handle_user_message(
        session, user_id, "fincas en NoExisteCiudad", "t", "T"
    )
    assert "alerta" in reply_b.text.lower()
    executed_b = [t["tool"] for t in _last_trace(orch_b)]
    assert executed_b[:2] == ["search_properties", "save_search"]


# ══════════════════════════════════════════════════════════════ §82
async def test_no_agentwashing_evidence_reaches_the_model(session, user_id):
    """La respuesta final del agente se compone SOBRE la evidencia recibida."""
    from app.agents.orchestrator import Orchestrator

    def agent(messages, tools):
        searches = _tool_data(messages, "search_properties")
        if not searches:
            return tool_round(tc("search_properties", {
                "filters": {"city": "Carepa", "property_type": "casa"},
            }, call_id="s1"))
        if not _tool_data(messages, "get_customer_profile"):
            return tool_round(tc("get_customer_profile", {}, call_id="p1"))
        props = (searches[-1].get("data") or {}).get("properties") or []
        code = props[0]["code"] if props else "N/A"
        return send_response_round(f"La primera opción real es {code}.")

    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "casas para mí", "t", "T")

    # El agente compone la respuesta usando el código de la primera propiedad
    # devuelta por la búsqueda real (no un código hardcodeado).
    import re
    assert re.search(r"PROP-\d{4}", reply.text) is not None  # compuso desde evidencia real
    assert len(fake.calls) == 3               # search → profile → send_response
    # el modelo recibió TODA la evidencia antes de decidir
    assert len(fake.tool_result_messages(call_index=2)) == 2


# ══════════════════════════════════════════════════════════════ §84
async def test_web_search_used_when_internal_tools_cannot_answer(session, user_id, monkeypatch):
    from app.agents import websearch
    from app.agents.orchestrator import Orchestrator

    async def fake_search_web(query, *, max_results=None):
        return {
            "ok": True, "query": query, "count": 1, "external_content": True,
            "results": [{
                "title": "Ley 820 de 2003 - Régimen de arrendamiento urbano",
                "url": "https://example.gov/ley820",
                "domain": "example.gov",
                "snippet": "El contrato de arrendamiento urbano debe escriturarse...",
            }],
        }

    monkeypatch.setattr(websearch, "search_web", fake_search_web)

    def agent(messages, tools):
        web = _tool_data(messages, "web_search")
        if not web:
            return tool_round(tc("web_search", {
                "query": "ley arrendamiento urbano Colombia vigente",
            }, call_id="w1"))
        results = (web[-1].get("data") or {}).get("results") or []
        if results:
            return send_response_round(
                f"Según {results[0]['title']} ({results[0]['domain']}): "
                "el arrendamiento urbano se regula por la Ley 820."
            )
        return send_response_round("no encontré fuentes")

    METRICS.reset()
    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(
        session, user_id, "¿qué ley regula el arrendamiento urbano en Colombia?", "t", "T"
    )

    assert "Ley 820" in reply.text
    assert "example.gov" in reply.text  # cita la fuente
    assert METRICS.snapshot()["counters"]["web_search_calls"] >= 1


async def test_no_web_search_when_internal_data_suffices(session, user_id):
    from app.agents.orchestrator import Orchestrator

    def agent(messages, tools):
        if not _tool_data(messages, "get_property"):
            return tool_round(tc("get_property", {"property_ref": "PROP-0001"}, call_id="g1"))
        prop = (_tool_data(messages, "get_property")[-1].get("data") or {}).get("property") or {}
        return send_response_round(f"La casa cuesta ${float(prop.get('price') or 0):,.0f}.")

    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "¿cuánto cuesta la primera?", "t", "T")

    assert "$" in reply.text
    # web_search quedó DISPONIBLE como opción (está en las specs ofrecidas)
    # pero el agente NUNCA la ejecutó: la fuente interna bastaba.
    executed_tools = [t["tool"] for t in _last_trace(orch)]
    assert "web_search" not in executed_tools
    assert "get_property" in executed_tools  # sí usó la tool interna


# ══════════════════════════════════════════════════════════════ §85
async def test_tool_timeout_retry_then_success_agent_continues(session, user_id, monkeypatch):
    """tool → timeout → retry técnico → éxito → el agente continúa."""
    from app.agents import runtime as runtime_mod
    from app.agents.orchestrator import Orchestrator
    from app.core.settings import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "RETRY_BASE_DELAY", 0.01)
    monkeypatch.setattr(s, "RETRY_MAX_DELAY", 0.02)

    real_run_tool = runtime_mod.run_tool
    calls = {"n": 0}

    async def flaky_run_tool(name, args, ctx):
        if name == "search_properties" and calls["n"] == 0:
            calls["n"] += 1
            raise TimeoutError("db pool timeout simulado")
        calls["n"] += 1
        return await real_run_tool(name, args, ctx)

    monkeypatch.setattr(runtime_mod, "run_tool", flaky_run_tool)

    fake = FakeLLMV2([
        tool_round(tc("search_properties", {"filters": {"city": "Carepa"}}, call_id="s1")),
        send_response_round("Búsqueda confirmada tras el reintento."),
    ])
    METRICS.reset()
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "casas en Carepa", "t", "T")

    assert "confirmada" in reply.text
    snap = METRICS.snapshot()["counters"]
    assert snap["tool_retries"] >= 1
    searches = _tool_data(fake.calls[1]["messages"], "search_properties")
    assert searches and searches[-1]["ok"] is True


async def test_tool_timeout_retry_exhausted_agent_continues_with_rest(session, user_id, monkeypatch):
    """tool → timeout → retries agotados → error estructurado → respuesta parcial."""
    from app.agents import runtime as runtime_mod
    from app.agents.orchestrator import Orchestrator
    from app.core.settings import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "RETRY_BASE_DELAY", 0.01)
    monkeypatch.setattr(s, "RETRY_MAX_DELAY", 0.02)

    real_run_tool = runtime_mod.run_tool

    async def dead_run_tool(name, args, ctx):
        if name == "list_available_slots":
            raise TimeoutError("agenda caída")
        return await real_run_tool(name, args, ctx)

    monkeypatch.setattr(runtime_mod, "run_tool", dead_run_tool)

    def agent(messages, tools):
        slots = _tool_data(messages, "list_available_slots")
        if not slots:
            return tool_round(
                tc("get_property", {"property_ref": "PROP-0001"}, call_id="g1"),
                tc("list_available_slots", {"property_id": "PROP-0001"}, call_id="l1"),
            )
        slot_env = slots[-1]
        ficha_ok = any(e.get("ok") for e in _tool_data(messages, "get_property"))
        if ficha_ok and slot_env.get("ok") is False and slot_env["error"]["retryable"]:
            return send_response_round(
                "Tienes la ficha de PROP-0001, pero la agenda no respondió: "
                "la disponibilidad quedó pendiente."
            )
        return send_response_round("estado inesperado")

    fake = FakeLLMV2([agent])
    METRICS.reset()
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(
        session, user_id, "ficha y horarios de PROP-0001", "t", "T"
    )

    assert "PROP-0001" in reply.text
    assert "pendiente" in reply.text
    assert "estado inesperado" not in reply.text
    snap = METRICS.snapshot()["counters"]
    assert snap["tool_errors"] >= 1
    assert snap["tool_retries"] >= 1


# ══════════════════════════════════════════════════════════════ §86
async def test_prop0008_prop0009_partial_failure_scenario(session, user_id):
    """Escenario de regresión: 2 propiedades × (imágenes, requisitos, disponibilidad).

    - los requisitos (RAG) de las propiedades no existen en el seed → parcial;
    - la respuesta conserva AMBAS propiedades y aclara solo lo pendiente;
    - nada de «todo falló», no hay operaciones duplicadas.
    """
    from app.agents.orchestrator import Orchestrator

    pid8 = await _prop_id(session, "PROP-0008")
    pid9 = await _prop_id(session, "PROP-0009")

    def agent(messages, tools):
        if not _tool_data(messages, "get_property_images"):
            return tool_round(
                tc("get_property_images", {"property_id": pid8}, call_id="i8"),
                tc("get_property_images", {"property_id": pid9}, call_id="i9"),
                tc("search_documents", {"query": "requisitos arriendo PROP-0008"}, call_id="d8"),
                tc("search_documents", {"query": "requisitos arriendo PROP-0009"}, call_id="d9"),
                tc("list_available_slots", {"property_id": pid8}, call_id="s8"),
                tc("list_available_slots", {"property_id": pid9}, call_id="s9"),
            )
        imgs = _tool_data(messages, "get_property_images")
        docs = _tool_data(messages, "search_documents")
        slots = _tool_data(messages, "list_available_slots")
        ok_docs = [e for e in docs if e.get("ok") and (e.get("data") or {}).get("chunks")]
        ok_slots = [e for e in slots if e.get("ok") and (e.get("data") or {}).get("slots")]
        return send_response_round(
            f"PROP-0008 y PROP-0009: imágenes consultadas ({len(imgs)}), "
            f"requisitos documentados ({len(ok_docs)}), "
            f"disponibilidad confirmada ({len(ok_slots)})."
        )

    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(
        session, user_id,
        "quiero imágenes, requisitos y disponibilidad de PROP-0008 y PROP-0009", "t", "T",
    )

    assert "PROP-0008" in reply.text
    assert "PROP-0009" in reply.text
    assert "disponibilidad" in reply.text
    # sin duplicados: 6 tools de datos ejecutadas 1 vez cada una, call_ids
    # únicos y ninguna deduplicación por idempotencia. (send_response es la
    # tool terminal del turno: también aparece en la traza, se excluye aquí.)
    trace = _last_trace(orch)
    data_trace = [t for t in trace if t["tool"] != "send_response"]
    assert len(data_trace) == 6
    assert len({t["call_id"] for t in data_trace}) == 6
    assert not any(t.get("idempotent_skip") for t in data_trace)


# ══════════════════════════════════════════════════════════════ §18/§19
async def test_batch_of_independent_calls_executed_and_correlated(session, user_id):
    from app.agents.orchestrator import Orchestrator

    pid1 = await _prop_id(session, "PROP-0001")
    pid2 = await _prop_id(session, "PROP-0002")

    fake = FakeLLMV2([
        tool_round(
            tc("get_property_images", {"property_id": pid1}, call_id="img1"),
            tc("get_property_images", {"property_id": pid2}, call_id="img2"),
        ),
        send_response_round("Imágenes de ambas propiedades listas."),
    ])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(
        session, user_id, "muéstrame fotos de las dos primeras", "t", "T"
    )
    assert "Imágenes" in reply.text

    # correlación: cada resultado vuelve con SU call_id y SU property_id
    tool_msgs = [m for m in fake.calls[1]["messages"] if m.get("role") == "tool"]
    assert {m["tool_call_id"] for m in tool_msgs} == {"img1", "img2"}
    by_id = {m["tool_call_id"]: json.loads(m["content"]) for m in tool_msgs}
    assert by_id["img1"]["data"]["property_id"] == pid1
    assert by_id["img2"]["data"]["property_id"] == pid2


# ══════════════════════════════════════════════════════════════ §31/§20/§73
# ══════════════════════════════════════════════════════════════ §31/§20/§73
async def test_full_conversation_keeps_context_without_redundant_searches(session, user_id):
    """búsqueda → cambio de criterio (re-busca JUSTIFICADO) → "la segunda" →
    imágenes → requisitos → visita (SIN re-buscar en los turnos de contexto)."""
    from app.agents.orchestrator import Orchestrator
    from app.core.settings import get_settings
    from app.memory import service as memory_service
    from tests.test_fake_llm_v2 import tc

    # Asegurar que todo el historial esté disponible para el conteo de turnos
    s = get_settings()
    original_history_turns = s.LLM_HISTORY_TURNS
    s.LLM_HISTORY_TURNS = 50

    # Track turns by counting user messages in the conversation history.
    # Each turn adds one user message to the history.
    turn_state = {"count": -1}

    def agent(messages, tools, tc=tc):
        # Count user messages in history to determine turn
        user_msgs = [m for m in messages if m.get("role") == "user"]
        turn = len(user_msgs) - 1  # -1 because first message is current turn
        turn_state["count"] = turn

        if turn == 0:
            if _tool_data(messages, "search_properties"):
                return send_response_round("Casas en Carepa encontradas.")
            return tool_round(
                tc("update_conversation_state", {
                    "operation": "SALE", "property_type": "casa",
                    "city": "Carepa", "bedrooms": 3, "intent": "SEARCH_PROPERTY",
                    "budget_max": 300_000_000,
                }),
                tc("search_properties", {
                    "filters": {"city": "Carepa", "property_type": "casa",
                                "operation": "SALE", "max_price": 300_000_000},
                }, call_id="s1"),
            )
        if turn == 1:
            if _tool_data(messages, "search_properties"):
                return send_response_round("Amplié el presupuesto; hay opciones nuevas.")
            return tool_round(tc("search_properties", {
                "filters": {"city": "Carepa", "property_type": "casa",
                            "operation": "SALE", "max_price": 500_000_000},
            }, call_id="s2"))
        if turn == 2:
            if _tool_data(messages, "get_property"):
                return send_response_round("Ficha de la segunda opción.")
            return tool_round(tc("get_property", {"property_ref": "la segunda"}, call_id="g1"))
        if turn == 3:
            if _tool_data(messages, "get_property_images"):
                return send_response_round("Imágenes listas.")
            return tool_round(tc("get_property_images", {"property_id": "la segunda"}, call_id="im1"))
        if turn == 4:
            if _tool_data(messages, "search_documents"):
                return send_response_round("Requisitos consultados en los documentos.")
            return tool_round(tc("search_documents", {
                "query": "requisitos compra", "property_id": "la segunda",
            }, call_id="d1"))
        # turn 5: visita
        if _tool_data(messages, "list_available_slots"):
            return send_response_round("Horarios de visita listos.")
        return tool_round(tc("list_available_slots", {"property_id": "la segunda"}, call_id="sl1"))

    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)

    async def say(text):
        return await orch.handle_user_message(session, user_id, text, "t", "T")

    r1 = await say("Busco casa en Carepa de 3 habitaciones por máximo 300 millones")
    assert r1.text
    r2 = await say("Mmm, mejor hasta 500 millones")
    assert r2.text
    r3 = await say("La segunda, ¿puedo verla?")
    assert "segunda" in r3.text.lower()
    r4 = await say("Muéstrame imágenes")
    assert r4.text
    r5 = await say("¿Cuáles son los requisitos para comprarla?")
    assert r5.text
    r6 = await say("¿Y cuándo puedo visitarla?")
    assert r6.text

    user = await memory_service.get_or_create_user(session, user_id)
    conv = await memory_service.get_or_create_conversation(session, user.id)
    assert conv.state.get("operation") == "SALE"

    # NO hubo búsquedas redundantes: solo las 2 justificadas por cambio de criterio
    # Consultar AiEvent para contar tools ejecutadas en toda la conversación
    from sqlalchemy import select

    from app.database.models import AiEvent
    ai_events = (await session.execute(
        select(AiEvent).where(AiEvent.conversation_id == conv.id)
    )).scalars().all()
    all_tool_calls = []
    for event in ai_events:
        for tool_call in event.tool_calls:
            if tool_call.get("tool") != "send_response":
                all_tool_calls.append(tool_call["tool"])
    assert all_tool_calls.count("search_properties") == 2
    assert all_tool_calls.count("get_property") == 1
    assert all_tool_calls.count("get_property_images") == 1
    assert all_tool_calls.count("search_documents") == 1
    assert all_tool_calls.count("list_available_slots") == 1
    # Restore settings
    s.LLM_HISTORY_TURNS = original_history_turns


# ══════════════════════════════════════════════════════════════ idempotencia
async def test_mutating_tool_executed_once_per_turn(session, user_id):
    from sqlalchemy import select

    from app.agents.orchestrator import Orchestrator
    from app.appointments import service as appt_service
    from app.crm import service as crm_service
    from app.database.models import Appointment
    from app.memory import service as memory_service
    from app.properties import repository as prop_repo

    # Ensure user exists before creating lead (FK constraint)
    await memory_service.get_or_create_user(session, user_id, "t", "T")

    prop = await prop_repo.get_property_by_code(session, "PROP-0001")
    slots = await appt_service.list_available_slots(session, prop.id)
    assert slots
    chosen = slots[0]
    user = await memory_service.get_or_create_user(session, user_id, "t", "T")
    await session.flush()
    lead = await crm_service.get_or_create_lead(session, user.id)
    # Pre-populate contact info for scheduling
    await crm_service.update_lead(session, lead.id, {
        "name": "Test User",
        "phone": "+57 300 123 4567",
        "email": "test@example.com",
    })

    # el modelo duplica la llamada (bug del LLM): el runtime debe deduplicar
    fake = FakeLLMV2([
        tool_round(
            tc("schedule_visit", {
                "property_id": str(prop.id), "datetime_iso": chosen["datetime"],
            }, call_id="b1"),
            tc("schedule_visit", {
                "property_id": str(prop.id), "datetime_iso": chosen["datetime"],
            }, call_id="b2"),
        ),
        send_response_round("Cita agendada."),
    ])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(
        session, user_id, f"agéndame en {chosen['datetime_local']}", "t", "T"
    )
    assert reply.text

    appts = (await session.execute(
        select(Appointment).where(
            Appointment.property_id == prop.id, Appointment.lead_id == lead.id
        )
    )).scalars().all()
    assert len(appts) == 1


# ═══════════════════════ validación de slots: agente que alucina un horario
async def test_schedule_visit_hallucinated_time_redecides_from_real_slots(session, user_id):
    """Anti-alucinación de agenda: el LLM propone un horario inexistente y la
    validación determinista lo rechaza; el agente RE-DECIDE usando un slot real
    del envelope de error. La cita final solo puede existir en un slot real.
    """
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from app.agents.orchestrator import Orchestrator
    from app.crm import service as crm_service
    from app.database.models import Appointment
    from app.memory import service as memory_service
    from app.properties import repository as prop_repo

    await memory_service.get_or_create_user(session, user_id, "t", "T")
    prop = await prop_repo.get_property_by_code(session, "PROP-0001")
    user = await memory_service.get_or_create_user(session, user_id, "t", "T")
    await session.flush()
    lead = await crm_service.get_or_create_lead(session, user.id)
    # Pre-populate contact info for scheduling
    await crm_service.update_lead(session, lead.id, {
        "name": "Test User",
        "phone": "+57 300 123 4567",
        "email": "test@example.com",
    })

    # Usar un horario DENTRO del horario comercial pero que NO sea un slot exacto
    # (ej. 10:30 - los slots son en punto: 10:00, 11:00, etc.)
    # Esto activa la categoría C: horario permitido pero no disponible exacto.
    bogus = "2026-12-24T10:30"

    def _redecide(messages, tools):
        envs = _tool_data(messages, "schedule_visit")
        assert envs, "el agente debe haber visto el envelope de schedule_visit"
        last = envs[-1]
        # rechazo estructurado + evidencia real dentro del envelope de error
        assert last.get("ok") is False
        # El error puede ser por "business_hours" (categoría B) o "booked" (categoría C)
        # En ambos casos, debe haber evidencia para re-decidir
        error_msg = (last["error"]["message"] or "").lower()
        assert "horario" in error_msg or "slot" in error_msg, f"error inesperado: {error_msg}"
        slots = (last.get("data") or {}).get("slots") or (last.get("data") or {}).get("nearest_slots")
        assert slots, f"el envelope de error debe ofrecer slots reales: {json.dumps(last, default=str)[:1200]}"
        real_local = slots[0]["datetime_local"]
        return tool_round(
            tc("schedule_visit", {
                "property_id": str(prop.id), "datetime_iso": real_local,
                "notes": "re-decisión: slot real del envelope de error",
            }, call_id="sv-real"),
        )

    fake = FakeLLMV2([
        tool_round(
            tc("schedule_visit", {
                "property_id": str(prop.id), "datetime_iso": bogus,
                "notes": "Agente alucinó un horario inexistente",
            }, call_id="sv-bogus"),
        ),
        _redecide,
        send_response_round("Cita confirmada en el horario real."),
    ])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(
        session, user_id, "agéndame el 24 de diciembre a las 10:30", "t", "T"
    )
    assert "horario real" in reply.text

    user = await memory_service.get_or_create_user(session, user_id, "t", "T")
    lead = await crm_service.get_or_create_lead(session, user.id)
    appts = (await session.execute(
        select(Appointment).where(
            Appointment.property_id == prop.id, Appointment.lead_id == lead.id
        )
    )).scalars().all()
    assert len(appts) == 1, "el horario inventado no debe crear cita alguna"
    # la cita creada debe estar en un horario laboral real (America/Bogota)
    local_hour = appts[0].scheduled_at.astimezone(ZoneInfo("America/Bogota")).hour
    # Mon-Fri: 8-17, Sat: 9-14
    allowed = set(range(8, 18)) | set(range(9, 15))
    assert local_hour in allowed, f"cita fuera de horario laboral: {local_hour}"

    # Cleanup: liberar el slot para no romper otros tests de agenda del mismo
    # proceso (test_appointments/test_e2e agendan el primer slot real del día).
    await session.delete(appts[0])
    await session.commit()


# ═════════════════════════════════════════════════════ degradado honesto
async def test_degraded_reply_lists_evidence_and_pending(session, user_id):
    """Proveedor muerto tras las tools → respuesta con hechos, no «intenta de nuevo»."""
    from app.agents.orchestrator import Orchestrator

    fake = FakeLLMV2([
        tool_round(
            tc("search_properties", {"filters": {"city": "Carepa", "property_type": "finca"}},
               call_id="s1"),
            tc("get_property", {"property_ref": "PROP-9999"}, call_id="g1"),
        ),
        LLMError("server", "proveedor caído tras las tools"),
    ])
    METRICS.reset()
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "casas y ficha fantasma", "t", "T")

    assert "pude confirmar" in reply.text
    assert "PROP-0013" in reply.text         # lo que sí devolvió la búsqueda (la única finca de Carepa)
    assert "No pude completar" in reply.text  # lo que falló, explícito
    assert METRICS.snapshot()["counters"]["degraded_replies"] >= 1


# ═════════════════════════════════════════════════════ regresión: LLM falla en primera ronda sin tools
async def test_llm_fails_first_round_no_tools_produces_single_degraded_reply(session, user_id):
    """LLM falla en la primera ronda (sin tools ejecutadas) → una sola respuesta degradada, sin duplicados."""
    from app.agents.orchestrator import Orchestrator
    from app.ai.llm import LLMError

    # Simula fallo del proveedor en la primera llamada (antes de cualquier tool)
    fake = FakeLLMV2([LLMError("model_not_found", "model not found")])
    METRICS.reset()
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "Hola", "testuser", "Test")

    # Debe producir respuesta degradada genérica (sin evidencia de tools)
    assert "problema técnico" in reply.text
    assert "información confirmada" in reply.text
    assert reply.error is not None
    assert "model_not_found" in reply.error
    # Métrica de respuesta degradada
    assert METRICS.snapshot()["counters"]["degraded_replies"] >= 1
    # El error original se preserva en reply.error
    assert reply.error is not None


async def test_greeting_first_message_new_session(session, user_id):
    """Primera interacción en sesión nueva con saludo simple → respuesta conversacional normal."""
    from app.agents.intents import Intent
    from app.agents.orchestrator import Orchestrator
    from tests.test_fake_llm_v2 import send_response_round

    # Simula un LLM que responde directamente con send_response (saludo)
    def greeting_agent(messages, tools):
        # Verificar que es un saludo simple en conversación nueva
        user_msgs = [m for m in messages if m.get("role") == "user"]
        last_user = user_msgs[-1]["content"] if user_msgs else ""
        if last_user.strip().lower() in ("hola", "buenos días", "buenas", "hi", "hello"):
            return send_response_round(
                "¡Hola! ¿En qué te puedo ayudar hoy?",
                intent=Intent.GREETING.value,
                call_id="send_1"
            )
        return send_response_round("Respuesta genérica", call_id="send_1")

    fake = FakeLLMV2([greeting_agent])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "Hola", "testuser", "Test")

    # Debe responder con saludo, no con fallback técnico
    assert "problema técnico" not in reply.text.lower()
    assert "información confirmada" not in reply.text.lower()
    assert reply.intent == Intent.GREETING
    assert len(reply.text.strip()) > 0


# ════════════════════════════════════════════════════════════════════════
# Tests para cardinalidad de imágenes (singular vs plural)
# ════════════════════════════════════════════════════════════════════════

async def _prop_id(session, code: str) -> str:
    from sqlalchemy import text as sql_text
    return str((await session.execute(
        sql_text("SELECT id FROM properties WHERE code = :c"), {"c": code}
    )).scalar_one())


async def _setup_conversation_state(session, user_id, property_id, property_code):
    """Configura el estado de conversación para tests de imágenes."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.memory import service as memory_service
    user = await memory_service.get_or_create_user(session, user_id, "t", "T")
    conv = await memory_service.get_or_create_conversation(session, user.id)
    conv.state = {
        "selected_property_id": property_id,
        "selected_property_code": property_code,
        "phase": "PROPERTY_DETAILS",
    }
    flag_modified(conv, "state")
    await session.commit()


async def test_singular_image_request_returns_one_image(session, user_id):
    """Usuario pide 'una imagen' → se envía exactamente 1 imagen."""
    from app.agents.orchestrator import Orchestrator
    from tests.test_fake_llm_v2 import make_flow_agent

    pid8 = await _prop_id(session, "PROP-0008")
    await _setup_conversation_state(session, user_id, pid8, "PROP-0008")

    fake = FakeLLMV2([make_flow_agent()])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(
        session, user_id, "muéstrame una imagen de PROP-0008", "t", "T"
    )

    # Verificar que el agente usó limit=1 en get_property_images
    # Los tool results están en la segunda llamada (index 1)
    tool_msgs = [m for m in fake.calls[1]["messages"] if m.get("role") == "tool"]
    img_envs = [json.loads(m["content"]) for m in tool_msgs
                if json.loads(m["content"]).get("tool") == "get_property_images"]
    assert len(img_envs) == 1
    img_data = img_envs[0].get("data", {})
    assert len(img_data.get("images", [])) == 1, f"Expected 1 image, got {len(img_data.get('images', []))}"

    # Verificar que la respuesta final tiene 1 imagen
    assert len(reply.images) == 1, f"Expected 1 image in reply, got {len(reply.images)}"
    assert reply.intent == Intent.PROPERTY_IMAGES


async def test_singular_image_request_variations(session, user_id):
    """Variaciones de petición singular: 'una foto', 'una sola imagen', 'solo una foto'."""
    from app.agents.orchestrator import Orchestrator
    from tests.test_fake_llm_v2 import make_flow_agent

    pid8 = await _prop_id(session, "PROP-0008")

    variations = [
        "envíame una foto",
        "mándame una imagen",
        "quiero ver una foto",
        "enséñame una imagen",
        "dame una foto",
        "una sola imagen",
        "solo una foto",
    ]

    for i, msg in enumerate(variations):
        await _setup_conversation_state(session, user_id, pid8, "PROP-0008")

        fake = FakeLLMV2([make_flow_agent()])
        orch = Orchestrator(llm=fake)
        reply = await orch.handle_user_message(session, user_id, msg, "t", "T")

        # Verificar que se envió 1 imagen
        assert len(reply.images) == 1, f"Variation '{msg}': expected 1 image, got {len(reply.images)}"


async def test_explicit_count_image_request(session, user_id):
    """Usuario pide '3 fotos' → se envían exactamente 3 imágenes."""
    from app.agents.orchestrator import Orchestrator
    from tests.test_fake_llm_v2 import make_flow_agent

    pid8 = await _prop_id(session, "PROP-0008")
    await _setup_conversation_state(session, user_id, pid8, "PROP-0008")

    fake = FakeLLMV2([make_flow_agent()])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(
        session, user_id, "envíame 3 fotos de PROP-0008", "t", "T"
    )

    # Verificar que se enviaron 3 imágenes (o menos si no hay 3 disponibles)
    # PROP-0008 tiene 3 imágenes en el seed
    assert len(reply.images) == 3, f"Expected 3 images, got {len(reply.images)}"
    assert reply.intent == Intent.PROPERTY_IMAGES


async def test_plural_all_images_request(session, user_id):
    """Usuario pide 'todas las imágenes' → se envían todas las disponibles."""
    from app.agents.orchestrator import Orchestrator
    from tests.test_fake_llm_v2 import make_flow_agent

    pid8 = await _prop_id(session, "PROP-0008")
    await _setup_conversation_state(session, user_id, pid8, "PROP-0008")

    fake = FakeLLMV2([make_flow_agent()])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(
        session, user_id, "muéstrame todas las imágenes", "t", "T"
    )

    # PROP-0008 tiene 3 imágenes en el seed
    assert len(reply.images) == 3, f"Expected 3 images (all), got {len(reply.images)}"


async def test_ambiguous_image_request_defaults_to_all(session, user_id):
    """Petición ambigua 'fotos', 'imágenes' sin cuantificador → todas por defecto."""
    from app.agents.orchestrator import Orchestrator
    from tests.test_fake_llm_v2 import make_flow_agent

    pid8 = await _prop_id(session, "PROP-0008")
    await _setup_conversation_state(session, user_id, pid8, "PROP-0008")

    fake = FakeLLMV2([make_flow_agent()])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(
        session, user_id, "muéstrame las fotos", "t", "T"
    )

    # Por defecto debe enviar todas (3 para PROP-0008)
    assert len(reply.images) == 3, f"Expected 3 images (default all), got {len(reply.images)}"


async def test_tool_returns_multiple_but_singular_request_limits_to_one(session, user_id):
    """Tool devuelve 3 imágenes pero request=1 → envío=1 (regresión del bug original).
    
    Este test verifica que el FIX funciona: el flow_agent usa limit=1 cuando
    el usuario pide una imagen en singular, aunque la propiedad tenga 3 imágenes.
    """
    from app.agents.orchestrator import Orchestrator
    from tests.test_fake_llm_v2 import make_flow_agent

    pid8 = await _prop_id(session, "PROP-0008")
    await _setup_conversation_state(session, user_id, pid8, "PROP-0008")

    # El flow_agent actualizado usa limit=1 para peticiones singulares
    fake = FakeLLMV2([make_flow_agent()])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(
        session, user_id, "muéstrame una imagen", "t", "T"
    )

    # Verificar que se envió 1 imagen (el fix funciona)
    assert len(reply.images) == 1, f"Expected 1 image with singular request, got {len(reply.images)}"
