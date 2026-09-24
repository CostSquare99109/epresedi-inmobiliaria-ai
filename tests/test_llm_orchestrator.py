"""Tests del agent-loop (runtime + orquestador): LLM → tools → LLM → respuesta.

Estos tests verifican la arquitectura real del loop:
- la evidencia de las tools vuelve al modelo (con call_id correlacionado);
- el runtime no decide semántica: solo ejecuta, valida, reintenta, protege;
- send_response es la tool terminal (opcional: texto plano también cierra);
- los fallos del proveedor degradan con evidencia, no con «intenta de nuevo».
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.agents.intents import Intent
from app.agents.metrics import METRICS
from app.agents.state import merge_state_update
from app.agents.tools import ToolContext, run_tool, tool_envelope
from app.ai.llm import LLMError, LLMProviderChain
from tests.test_fake_llm_v2 import (
    FakeLLMV2,
    plain_text,
    send_response_round,
    tc,
    tool_round,
)


def _search_and_state_round() -> object:
    return tool_round(
        tc("update_conversation_state", {
            "intent": "SEARCH_PROPERTY", "operation": "SALE", "property_type": "casa",
            "city": "Carepa", "budget_max": 300_000_000, "bedrooms": 3,
        }),
        tc("search_properties", {
            "filters": {"property_type": "casa", "city": "Carepa", "max_price": 300_000_000},
            "semantic_query": "3 habitaciones",
        }, call_id="c2"),
    )


# ─────────────────────────────────────────────────────── loop básico
async def test_agent_loop_executes_tools_and_persists_validated_state(session, user_id):
    from app.agents.orchestrator import Orchestrator
    from app.memory import service as memory_service

    fake = FakeLLMV2([
        _search_and_state_round(),
        send_response_round(
            "Encontré casas reales en Carepa. La primera es PROP-0001.",
            intent="SEARCH_PROPERTY",
        ),
    ])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(
        session, user_id, "Quiero una casa en Carepa de 3 habitaciones hasta 300 millones", "t", "T"
    )

    assert reply.intent == Intent.SEARCH_PROPERTY
    assert "PROP-0001" in reply.text
    assert len(fake.calls) == 2  # ronda tools + send_response terminal

    # la evidencia de la búsqueda llegó al modelo en la 2ª llamada
    tool_results = fake.tool_result_contents(call_index=1)
    assert any(r.get("tool") == "search_properties" for r in tool_results)
    assert any("PROP-0001" in str(r) for r in tool_results)

    conv = await memory_service.get_or_create_conversation(session, user_id)
    assert conv.state["operation"] == "SALE"
    assert conv.state["bedrooms"] == 3
    assert conv.state["last_results"]
    assert conv.state["last_turn_tools"][0]["tool"] == "update_conversation_state"


async def test_send_response_terminal_does_not_call_llm_again(session, user_id):
    from app.agents.orchestrator import Orchestrator

    fake = FakeLLMV2([
        send_response_round("Hola, soy epresedi. ¿Qué buscas hoy?", intent="GREETING"),
    ])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "hola", "t", "T")

    assert "epresedi" in reply.text.lower()
    assert reply.intent == Intent.GREETING
    assert len(fake.calls) == 1


async def test_plain_text_final_is_valid_too(session, user_id):
    from app.agents.orchestrator import Orchestrator

    fake = FakeLLMV2([
        tool_round(tc("get_customer_profile", {})),
        plain_text("Tu perfil está vacío todavía."),
    ])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "mira mi perfil", "t", "T")
    assert reply.text == "Tu perfil está vacío todavía."


async def test_tool_call_ids_are_correlated_round_trip(session, user_id):
    """El historial enviado al LLM conserva assistant.tool_calls ↔ role=tool.call_id."""
    from app.agents.orchestrator import Orchestrator

    fake = FakeLLMV2([
        tool_round(
            tc("get_property", {"property_ref": "PROP-0001"}, call_id="call_A"),
            tc("get_customer_profile", {}, call_id="call_B"),
        ),
        # dinámico: verifica correlación y responde
        lambda messages, tools: (
            send_response_round("detalle y perfil listos")
            if _assert_correlation(messages) else plain_text("correlación rota")
        ),
    ])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "ficha y perfil", "t", "T")
    assert "correlación rota" not in reply.text
    assert "listos" in reply.text


def _assert_correlation(messages: list[dict]) -> bool:
    assistant_ids = set()
    for m in messages:
        for call in m.get("tool_calls") or []:
            assistant_ids.add(call["id"])
    tool_ids = {m.get("tool_call_id") for m in messages if m.get("role") == "tool"}
    return assistant_ids == tool_ids and len(assistant_ids) == 2


# ─────────────────────────────────────────────── fallos del proveedor LLM
async def test_provider_error_first_round_returns_honest_error(session, user_id):
    from app.agents.orchestrator import Orchestrator

    METRICS.reset()
    fake = FakeLLMV2([LLMError("timeout", "provider down")])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "busca casas en Carepa", "t", "T")

    assert "inconveniente" in reply.text.lower() or "intenta" in reply.text.lower()
    assert reply.error  # el error queda registrado, no oculto
    snap = METRICS.snapshot()["counters"]
    assert snap["llm_errors"] >= 1


async def test_provider_error_mid_turn_degrades_with_real_evidence(session, user_id):
    """Tools ejecutadas OK + proveedor muere → respuesta con lo confirmado (§47)."""
    from app.agents.orchestrator import Orchestrator

    METRICS.reset()
    fake = FakeLLMV2([
        _search_and_state_round(),
        LLMError("timeout", "died after tools"),
    ])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "casas en Carepa", "t", "T")

    # evidencia, no error genérico
    assert "PROP-0001" in reply.text
    assert "pude confirmar" in reply.text
    assert reply.error and "timeout" in reply.error
    snap = METRICS.snapshot()["counters"]
    assert snap["degraded_replies"] >= 1


# ─────────────────────────────────────────────────── argumentos y contratos
async def test_malformed_tool_arguments_are_reported_back_to_the_model(session, user_id):
    from app.agents.orchestrator import Orchestrator

    fake = FakeLLMV2([
        tool_round(tc("search_properties", {}, call_id="c1",
                      arguments_error="argumentos JSON inválidos: Expecting value")),
        # dinámico: el modelo VIO el error estructurado y decide pedir criterios
        lambda messages, tools: (
            send_response_round("No pude ejecutar esa búsqueda, ¿me repites los criterios?")
            if any("BAD_ARGUMENTS" in json_str for json_str in [
                m["content"] for m in messages if m.get("role") == "tool"
            ]) else plain_text("no vi el error")
        ),
    ])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "busca algo", "t", "T")

    assert "repites" in reply.text.lower() or "criterios" in reply.text.lower()
    assert "no vi el error" not in reply.text


async def test_send_response_invalid_keyboard_action_is_rejected_then_fixed(session, user_id):
    from app.agents.orchestrator import Orchestrator

    fake = FakeLLMV2([
        send_response_round("elige", keyboard=[{"text": "hack", "action": "delete_everything", "payload": {}}]),
        lambda messages, tools: (
            send_response_round("opciones listas") if any(
                "no permitida" in (m.get("content") or "") for m in messages if m.get("role") == "tool"
            ) else plain_text("sin validación")
        ),
    ])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "quiero botones", "t", "T")
    assert reply.text == "opciones listas"
    assert "sin validación" not in reply.text


async def test_batched_send_response_reasks_with_real_results(session, user_id):
    """send_response en lote con otras tools → se pide decidir de nuevo (§5)."""
    from app.agents.orchestrator import Orchestrator

    fake = FakeLLMV2([
        tool_round(
            tc("search_properties", {"filters": {"city": "Carepa"}}, call_id="c1"),
            tc("send_response", {"text": "resultados"}, call_id="send"),
        ),
        lambda messages, tools: (
            send_response_round("Ahora sí: encontré casas en Carepa.")
            if any("BATCHED_TERMINAL_CALL" in (m.get("content") or "") for m in messages
                   if m.get("role") == "tool")
            else plain_text("lote no detectado")
        ),
    ])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "casas", "t", "T")

    assert "Ahora sí" in reply.text
    # el modelo vio el resultado de la búsqueda antes de reintentar send_response
    second_call_tools = fake.tool_result_contents(call_index=1)
    assert any(r.get("tool") == "search_properties" for r in second_call_tools)


# ─────────────────────────────────────────────────────────── protecciones
async def test_max_rounds_exhausted_forces_final_response(session, user_id):
    from app.agents.orchestrator import Orchestrator

    fake = FakeLLMV2([
        tool_round(tc("get_customer_profile", {})),
        tool_round(tc("get_customer_profile", {"x": 1})),
        tool_round(tc("get_customer_profile", {"x": 2})),
        tool_round(tc("get_customer_profile", {"x": 3})),
        plain_text("Suficiente por ahora: dime qué necesitas."),
    ])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "hola", "t", "T")

    assert "Suficiente" in reply.text
    assert len(fake.calls) == 5
    # la llamada forzada va SIN tools
    assert fake.calls[-1]["tools"] is None


async def test_identical_tool_calls_trigger_loop_protection(session, user_id):
    """§29: misma tool+args repetida → detección, parada segura y respuesta."""
    from app.agents.orchestrator import Orchestrator

    METRICS.reset()
    fake = FakeLLMV2([
        tool_round(tc("get_customer_profile", {})),   # 1ª vez: cuenta 1
        tool_round(tc("get_customer_profile", {})),   # 2ª vez: cuenta 2
        tool_round(tc("get_customer_profile", {})),   # 3ª vez: > límite → forced final
        plain_text("Tu perfil: sin datos registrados."),
    ])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "perfil", "t", "T")

    assert "sin datos registrados" in reply.text
    snap = METRICS.snapshot()["counters"]
    assert snap["loop_protections"] >= 1
    # la última llamada fue forzada (sin tools) y el contexto quedó intacto
    assert fake.calls[-1]["tools"] is None
    assert fake.calls[-2]["tools"] is not None


async def test_consecutive_zero_result_searches_trigger_loop_protection(session, user_id):
    from app.agents.orchestrator import Orchestrator

    METRICS.reset()
    impossible = {"filters": {"city": "CiudadInexistente999", "property_type": "lote"}}
    fake = FakeLLMV2([
        tool_round(tc("search_properties", impossible, call_id="c1")),
        tool_round(tc("search_properties", impossible, call_id="c2")),
        plain_text("No hay coincidencias. ¿Quieres ampliar criterios o crear una alerta?"),
    ])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "lotes en CiudadInexistente999", "t", "T")

    assert "No hay coincidencias" in reply.text
    snap = METRICS.snapshot()["counters"]
    assert snap["loop_protections"] >= 1


# ───────────────────────────────────────────────────────────── auditoría
async def test_audit_records_conversation_id_and_tool_trace(session, user_id):
    from app.agents.orchestrator import Orchestrator
    from app.database.models import AiEvent
    from app.memory import service as memory_service

    fake = FakeLLMV2([
        _search_and_state_round(),
        send_response_round("casas encontradas", intent="SEARCH_PROPERTY"),
    ])
    orch = Orchestrator(llm=fake)
    await orch.handle_user_message(session, user_id, "casas en Carepa", "t", "T")

    user = await memory_service.get_or_create_user(session, user_id)
    conv = await memory_service.get_or_create_conversation(session, user.id)
    events = (await session.execute(
        select(AiEvent).where(AiEvent.user_id == user.id).order_by(AiEvent.id.desc())
    )).scalars().all()
    assert events
    ev = events[0]
    assert ev.conversation_id == conv.id
    assert ev.tool_calls and ev.tool_calls[0]["tool"] == "update_conversation_state"
    assert all("call_id" in c and "round" in c for c in ev.tool_calls)
    assert ev.status == "ok"
    assert ev.intent == "SEARCH_PROPERTY"


# ─────────────────────────────────────────────────────── unit: estado
def test_state_update_validation_rejects_invalid_proposals():
    state: dict = {}
    applied, rejected = merge_state_update(state, {
        "budget_max": -5, "hack_the_db": "drop table", "bedrooms": 3, "intent": "SEARCH_PROPERTY",
    })
    assert applied == {"bedrooms": 3, "intent": "SEARCH_PROPERTY"}
    assert len(rejected) == 2
    assert any("hack_the_db" in r for r in rejected)
    assert state["bedrooms"] == 3


def test_phase_transitions_are_validated():
    state = {"phase": "IDLE"}
    applied, rejected = merge_state_update(state, {"phase": "APPOINTMENT_COMPLETED"})
    assert applied == {}
    assert rejected and "transición inválida" in rejected[0]

    applied, rejected = merge_state_update(state, {"phase": "SEARCHING"})
    assert applied == {"phase": "SEARCHING"} and not rejected


async def test_update_conversation_state_tool_is_validated(session, user_id):
    from app.memory import service as memory_service

    await memory_service.get_or_create_user(session, user_id, "t", "T")
    ctx = ToolContext(session=session, user_id=user_id, conversation_id=None, state={})
    res = await run_tool("update_conversation_state", {
        "city": "Carepa", "bedrooms": 99, "sql": "SELECT 1",
    }, ctx)
    assert res["ok"] is True
    assert res["applied"]["city"] == "Carepa"
    assert "bedrooms" not in res["applied"]      # fuera de rango
    assert any("sql" in r for r in res["rejected"])


# ──────────────────────────────────────────────────── unit: proveedores
async def test_provider_chain_falls_back_to_next_provider():
    primary = FakeLLMV2([LLMError("server", "boom")], name="primary")
    secondary = FakeLLMV2([plain_text("respuesta del secundario")], name="secondary")
    chain = LLMProviderChain([primary, secondary])

    resp = await chain.chat([{"role": "user", "content": "hola"}])
    assert "secundario" in resp.content
    assert chain.providers == ["primary", "secondary"]
    assert len(primary.calls) == 1 and len(secondary.calls) == 1


async def test_provider_chain_raises_when_all_providers_fail():
    chain = LLMProviderChain([
        FakeLLMV2([LLMError("timeout", "a")], name="a"),
        FakeLLMV2([LLMError("server", "b")], name="b"),
    ])
    with pytest.raises(LLMError):
        await chain.chat([{"role": "user", "content": "hola"}])


def test_llm_mode_semantics_auto_means_llm_first():
    from app.core.settings import Settings

    assert Settings(LLM_MODE="auto", NVIDIA_API_KEY="k", NVIDIA_MODEL="m").llm_first_enabled is True
    assert Settings(LLM_MODE="nvidia", NVIDIA_API_KEY="k", NVIDIA_MODEL="m").llm_first_enabled is True


# ───────────────────────────────────────────────────────────── métricas
def test_metrics_snapshot_rates():
    METRICS.reset()
    METRICS.inc("agent_turns", 4)
    METRICS.inc("llm_success", 3)
    METRICS.inc("llm_fallbacks", 1)
    METRICS.inc("tool_calls", 6)
    METRICS.inc("tool_errors", 2)

    rates = METRICS.snapshot()["rates"]
    assert rates["llm_usage_rate"] == 0.75
    assert rates["fallback_rate"] == 0.25
    assert rates["tool_error_rate"] == round(2 / 6, 4)
    assert rates["average_tool_calls_per_turn"] == 1.5
    METRICS.reset()


def test_tool_envelope_shapes():
    ok = tool_envelope("search_properties", {"ok": True, "count": 1, "properties": [{"code": "PROP-0001"}]})
    assert ok["ok"] is True
    assert ok["data"]["properties"][0]["code"] == "PROP-0001"
    assert ok["metadata"]["count"] == 1

    err = tool_envelope("get_property", {"ok": False, "error": "Propiedad no encontrada."})
    assert err["ok"] is False
    assert err["error"]["code"] == "TOOL_ERROR"
    assert "Propiedad no encontrada." in err["error"]["message"]


# ────────────────────────────────────────────────────────── current date injection
async def test_current_datetime_injected_in_system_prompt(session, user_id):
    """El system prompt debe contener la fecha/hora actual real del sistema."""
    from app.agents.orchestrator import Orchestrator
    from tests.test_fake_llm_v2 import FakeLLMV2, plain_text

    captured_prompt = {}

    def capture_prompt_agent(messages, tools):
        # El primer mensaje es el system prompt
        system_msg = messages[0]
        assert system_msg["role"] == "system"
        captured_prompt["content"] = system_msg["content"]
        return plain_text("ok")

    fake = FakeLLMV2([capture_prompt_agent])
    orch = Orchestrator(llm=fake)
    await orch.handle_user_message(session, user_id, "hola", "t", "T")

    content = captured_prompt["content"]
    # Verificar que existe la línea de fecha/hora actual
    assert "Fecha/hora actual del sistema (zona horaria del negocio:" in content
    # Verificar formato ISO con timezone
    import re
    iso_match = re.search(r"Fecha/hora actual del sistema \(zona horaria del negocio: [^)]+\): (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})", content)
    assert iso_match is not None, f"No se encontró datetime ISO en: {content[:500]}"
    # Verificar que el año es el actual (2026+)
    year = int(iso_match.group(1)[:4])
    assert year >= 2026, f"Año inyectado es {year}, esperado >= 2026"


# ─────────────────────────────────────────────────────────── BUG-1: images narration
async def test_send_response_rejected_if_claims_images_but_empty_array(session, user_id):
    """BUG-1: Si el LLM dice que envía imágenes pero images=[] → runtime rechaza send_response."""
    from app.agents.orchestrator import Orchestrator
    from tests.test_fake_llm_v2 import FakeLLMV2, plain_text, send_response_round

    # El LLM intenta enviar send_response con texto que dice "adjunto las imágenes"
    # pero sin array images[] → debe ser rechazado
    call_count = {"n": 0}

    def agent(messages, tools):
        call_count["n"] += 1
        n = call_count["n"]

        if n == 1:
            # Primer intento: afirma enviar imágenes (singular) pero sin images[]
            return send_response_round(
                "Aquí tienes una imagen de la casa (PROP-0009):",
                intent="PROPERTY_IMAGES",
                call_id="send1"
            )
        else:
            # Segunda llamada: el LLM vio el error de validación, responde sin alucinar
            tool_msgs = [m for m in messages if m.get("role") == "tool"]
            error_received = any(
                "afirma que envías imágenes pero send_response.images está vacío" in (m.get("content") or "")
                for m in tool_msgs
            )
            if error_received:
                return send_response_round(
                    "No tengo imágenes cargadas para esa propiedad en este momento.",
                    intent="PROPERTY_IMAGES",
                    call_id="send2"
                )
            return plain_text("ERROR: no recibió validación")

    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "muéstrame fotos de PROP-0001", "t", "T")

    # La respuesta final NO debe contener la alucinación de imágenes
    assert "Aquí tienes una imagen de la casa" not in reply.text
    assert "adjunto las imágenes" not in reply.text
    # Debe haber habido 2 llamadas al LLM (intento fallido + corrección)
    assert len(fake.calls) == 2
    # La primera send_response fue rechazada (tool result con ok=false)
    first_tool_results = fake.tool_result_contents(call_index=1)
    assert any("afirma que envías imágenes pero send_response.images está vacío" in str(r) for r in first_tool_results)


# ─────────────────────────────────────────────────────────── BUG-5: appointment status
async def test_appointment_status_requested_not_called_confirmed(session, user_id):
    """BUG-5: schedule_visit devuelve REQUESTED → LLM no debe decir 'confirmada'."""
    from app.agents.orchestrator import Orchestrator
    from app.appointments import service as appt_service
    from app.crm import service as crm_service
    from app.memory import service as memory_service
    from app.properties import repository as prop_repo
    from tests.test_fake_llm_v2 import FakeLLMV2, send_response_round, tc, tool_round

    # Setup: crear propiedad, usuario, lead, y slot disponible
    await memory_service.get_or_create_user(session, user_id, "test", "Test")
    prop = await prop_repo.get_property_by_code(session, "PROP-0001")
    slots = await appt_service.list_available_slots(session, prop.id)
    assert slots, "needs available slot"
    slot = slots[0]
    lead = await crm_service.get_or_create_lead(session, user_id)
    # Pre-populate contact info for scheduling
    await crm_service.update_lead(session, lead.id, {
        "name": "Test User",
        "phone": "+57 300 123 4567",
        "email": "test@example.com",
    })

    # Agente que agenda y luego verifica el estado
    call_count = {"n": 0}

    def agent(messages, tools):
        call_count["n"] += 1
        n = call_count["n"]

        if n == 1:
            # Agenda la cita
            return tool_round(
                tc("schedule_visit", {
                    "property_id": str(prop.id),
                    "datetime_iso": slot["datetime"],
                    "notes": "test booking"
                }, call_id="sv1"),
            )
        else:
            # Segunda llamada: el LLM vio el resultado con status=REQUESTED
            tool_msgs = [m for m in messages if m.get("role") == "tool"]
            sv_result = None
            for m in tool_msgs:
                try:
                    env = json.loads(m.get("content", "{}"))
                    if env.get("tool") == "schedule_visit" and env.get("ok"):
                        sv_result = env
                        break
                except (json.JSONDecodeError, TypeError):
                    pass

            if sv_result:
                appt = (sv_result.get("data") or {}).get("appointment") or {}
                status = appt.get("status")
                metadata_note = sv_result.get("metadata", {}).get("note", "")

                # Verificar que el metadata advierte sobre REQUESTED
                assert status == "REQUESTED", f"Expected REQUESTED, got {status}"
                assert "REQUESTED" in metadata_note
                assert "pendiente de confirmación" in metadata_note

                # Respuesta correcta: NO dice "confirmada"
                return send_response_round(
                    "Tu solicitud de cita quedó registrada (pendiente de confirmación del asesor).",
                    intent="SCHEDULE_VISIT",
                    call_id="send1"
                )

            return send_response_round("ERROR: no vio resultado", call_id="send_err")

    import json
    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(
        session, user_id,
        f"agéndame en {slot['datetime_local']} para PROP-0001",
        "t", "T"
    )

    # La respuesta NO debe contener "confirmada" ni "queda todo confirmado"
    assert "confirmada" not in reply.text.lower()
    assert "queda todo confirmado" not in reply.text.lower()
    assert "pendiente de confirmación" in reply.text.lower()
    assert "registrada" in reply.text.lower()


# ─────────────────────────────────────────────────────────── BUG-4: seller notification
async def test_no_seller_notification_promise(session, user_id):
    """BUG-4: LLM no debe prometer notificar al vendedor/propietario (no existe backend)."""
    from app.agents.orchestrator import Orchestrator
    from tests.test_fake_llm_v2 import FakeLLMV2, send_response_round

    # Agente que intenta prometer notificar al vendedor
    call_count = {"n": 0}

    def agent(messages, tools):
        call_count["n"] += 1
        n = call_count["n"]

        if n == 1:
            # Primer intento: promete notificar al vendedor (alucinación)
            return send_response_round(
                "No tengo línea directa con el vendedor, pero registraré tu interés y se lo notificaré.",
                intent="GENERAL",
                call_id="send1"
            )
        else:
            # Segunda llamada: el system prompt debería haber prevenido esto
            # Pero si sucede, corregimos a respuesta honesta
            return send_response_round(
                "No tengo canal directo con el propietario. Tu interés queda en tu perfil y el asesor lo verá al gestionar la cita.",
                intent="GENERAL",
                call_id="send2"
            )

    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(session, user_id, "quiero que avisen al dueño de PROP-0001 que me interesa", "t", "T")

    # La respuesta NO debe contener promesas de notificar al vendedor/propietario
    forbidden_phrases = [
        "notificaré al", "notificar al", "avisar al", "avisaré al",
        "registraré tu interés con el", "registrar tu interés con el",
        "contactaré al", "contactar al", "comunicaré al",
        "el vendedor recibir", "el propietario recibir", "el dueño recibir",
        "ya tengo registrada tu solicitud", "solicitud registrada con el",
    ]
    text_lower = reply.text.lower()
    for phrase in forbidden_phrases:
        assert phrase not in text_lower, f"Frase prohibida encontrada: '{phrase}' en: {reply.text}"

    # La respuesta debe ser honesta sobre la limitación
    assert "canal directo" in text_lower or "no tengo" in text_lower or "asesor" in text_lower


# ─────────────────────────────────────────────────────────── BUG-3: silent error recovery
async def test_silent_retry_after_tool_error_narrates_correction(session, user_id):
    """BUG-3: Si schedule_visit falla y luego tiene éxito, el LLM debe narrar qué corrigió."""
    import json

    from app.agents.orchestrator import Orchestrator
    from app.appointments import service as appt_service
    from app.crm import service as crm_service
    from app.memory import service as memory_service
    from app.properties import repository as prop_repo
    from tests.test_fake_llm_v2 import FakeLLMV2, send_response_round, tc, tool_round

    # Setup
    await memory_service.get_or_create_user(session, user_id, "test", "Test")
    prop = await prop_repo.get_property_by_code(session, "PROP-0001")
    slots = await appt_service.list_available_slots(session, prop.id)
    assert slots
    slot = slots[0]
    lead = await crm_service.get_or_create_lead(session, user_id)
    # Pre-populate contact info for scheduling
    await crm_service.update_lead(session, lead.id, {
        "name": "Test User",
        "phone": "+57 300 123 4567",
        "email": "test@example.com",
    })

    # Agente que primero usa property_id inválido, luego corrige
    call_count = {"n": 0}

    def agent(messages, tools):
        call_count["n"] += 1
        n = call_count["n"]

        if n == 1:
            # Primer intento: property_id inválido (UUID inexistente)
            return tool_round(
                tc("schedule_visit", {
                    "property_id": "00000000-0000-0000-0000-000000000000",
                    "datetime_iso": slot["datetime"],
                    "notes": "test"
                }, call_id="sv1"),
            )
        elif n == 2:
            # Segunda llamada: el LLM vio el error "Propiedad no encontrada"
            tool_msgs = [m for m in messages if m.get("role") == "tool"]
            error_seen = any(
                "Propiedad no encontrada" in (m.get("content") or "")
                for m in tool_msgs
            )
            if not error_seen:
                return send_response_round("ERROR: no vio el fallo", call_id="send_err")
            # Ahora usa el property_id correcto
            return tool_round(
                tc("schedule_visit", {
                    "property_id": str(prop.id),
                    "datetime_iso": slot["datetime"],
                    "notes": "test"
                }, call_id="sv2"),
            )
        else:
            # Tercera llamada: schedule_visit tuvo éxito, debe narrar la corrección
            tool_msgs = [m for m in messages if m.get("role") == "tool"]
            sv_ok = None
            for m in tool_msgs:
                try:
                    env = json.loads(m.get("content", "{}"))
                    if env.get("tool") == "schedule_visit" and env.get("ok"):
                        sv_ok = env
                        break
                except (json.JSONDecodeError, TypeError):
                    pass

            if sv_ok:
                # Verificar que el LLM narra la corrección
                return send_response_round(
                    "El primer intento falló porque usé un ID inválido. "
                    "Con el código correcto PROP-0001, tu solicitud de cita quedó registrada "
                    "(pendiente de confirmación del asesor).",
                    intent="SCHEDULE_VISIT",
                    call_id="send1"
                )
            return send_response_round("esperando resultado", call_id="send_wait")

    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)
    reply = await orch.handle_user_message(
        session, user_id,
        f"agéndame en {slot['datetime_local']} para PROP-0001",
        "t", "T"
    )

    # La respuesta DEBE mencionar la corrección
    text_lower = reply.text.lower()
    assert "primer intento falló" in text_lower or "falló porque" in text_lower or "correg" in text_lower
    assert "inválid" in text_lower or "incorrect" in text_lower
    assert "pendiente de confirmación" in text_lower
    # NO debe decir solo "confirmada" sin explicar
    assert not ("confirmada" in text_lower and "falló" not in text_lower and "correg" not in text_lower)
