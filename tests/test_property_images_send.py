"""Envío REAL de fotografías de propiedades por Telegram (regresión del bug textual).

Cubre los 7 casos del megaprompt + el bypass por texto libre:
1. Una imagen (singular → limit=1, envío real verificado en disco).
2. Propiedad sin imagen (success=false, reason=no_image, respuesta honesta).
3. Archivo inexistente (DB huérfana → no se afirma envío).
4. Propiedad diferente (la foto pertenece a la propiedad solicitada).
5. Varias fotos (plural → todas).
6. Contexto conversacional («quiero una imagen» resuelve la anterior sin código).
7. Error Telegram (fallo de envío visible, sin mentir).
8. Texto libre que alucina («Aquí tienes una imagen» sin tools → bloqueado).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import text as sql_text
from sqlalchemy.orm.attributes import flag_modified

from app.agents.orchestrator import Orchestrator
from tests.test_fake_llm_v2 import FakeLLMV2, plain_text, send_response_round, tc, tool_round


async def _prop_id(session, code: str) -> str:
    return str((await session.execute(
        sql_text("SELECT id FROM properties WHERE code = :c"), {"c": code}
    )).scalar_one())


async def _setup_single_result_state(session, user_id, code: str = "PROP-0008"):
    """Estado como si el turno anterior hubiera mostrado UNA propiedad."""
    from app.memory import service as memory_service
    from app.properties import repository as prop_repo

    user = await memory_service.get_or_create_user(session, user_id, "t", "T")
    conv = await memory_service.get_or_create_conversation(session, user.id)
    prop = await prop_repo.get_property_by_code(session, code)
    assert prop is not None
    d = prop.to_dict()
    conv.state = {
        "last_results": [d],
        "last_property_id": str(prop.id),
        "selected_property_id": str(prop.id),
        "selected_property_code": code,
        "phase": "PROPERTY_DETAILS",
    }
    flag_modified(conv, "state")
    await session.commit()
    return str(prop.id)


def _image_tool_results(fake: FakeLLMV2):
    """Envelopes get_property_images vistos por el LLM en su última llamada."""
    out = []
    for call in fake.calls:
        for m in call["messages"]:
            if m.get("role") != "tool":
                continue
            try:
                payload = json.loads(m["content"])
            except (json.JSONDecodeError, TypeError):
                continue
            if payload.get("tool") == "get_property_images":
                out.append(payload)
    return out


# ── Caso 1: una imagen ──────────────────────────────────────────────
async def test_case1_single_image_sends_real_file(session, user_id):
    pid = await _prop_id(session, "PROP-0008")
    await _setup_single_result_state(session, user_id, "PROP-0008")

    def agent(messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            return tool_round(tc("get_property_images", {"property_id": pid, "limit": 1}, call_id="g1"))
        return send_response_round(
            "Te comparto la fotografía de la propiedad.",
            intent="PROPERTY_IMAGES", images=[pid],
        )

    fake = FakeLLMV2([agent])
    reply = await Orchestrator(llm=fake).handle_user_message(
        session, user_id, "Quiero una imagen de esa casa", "t", "T"
    )
    assert len(reply.images) == 1, f"esperaba 1 foto, got {reply.images}"
    assert Path(reply.images[0]).is_file(), f"no es archivo real: {reply.images[0]}"
    assert Path(reply.images[0]).stat().st_size > 0
    envs = _image_tool_results(fake)
    assert envs and envs[0].get("ok") is True
    assert len((envs[0].get("data") or {}).get("images", [])) == 1


# ── Caso 2: propiedad sin imagen ────────────────────────────────────
async def test_case2_property_without_images_honest(session, user_id):
    from app.memory import service as memory_service
    from app.properties import repository as prop_repo

    prop = await prop_repo.create_property(session, {
        "title": "Casa sin fotos para prueba honesta",
        "property_type": "casa", "operation": "RENT", "price": 1_000_000,
        "city": "Carepa", "status": "AVAILABLE",
    })
    await session.commit()
    pid = str(prop.id)
    prop_id_for_cleanup = prop.id
    user = await memory_service.get_or_create_user(session, user_id, "t", "T")
    conv = await memory_service.get_or_create_conversation(session, user.id)
    conv.state = {"last_results": [prop.to_dict()], "last_property_id": pid}
    flag_modified(conv, "state")
    await session.commit()

    def agent(messages, tools):
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if not tool_msgs:
            return tool_round(tc("get_property_images", {"property_id": pid}, call_id="g1"))
        # La tool debió fallar con NO_IMAGES: responder honesto, sin images[]
        return send_response_round(
            "En este momento esta propiedad no tiene fotografías disponibles.",
            intent="PROPERTY_IMAGES",
        )

    fake = FakeLLMV2([agent])
    reply = await Orchestrator(llm=fake).handle_user_message(
        session, user_id, "Quiero una imagen de esa casa", "t", "T"
    )
    assert not reply.images, f"no debe adjuntar nada, got {reply.images}"
    assert "no tiene fotografías disponibles" in reply.text.lower()
    assert "aquí tienes una imagen" not in reply.text.lower()
    envs = _image_tool_results(fake)
    assert envs and envs[0].get("ok") is False
    data = envs[0].get("data") or {}
    assert data.get("reason") == "no_image"
    await prop_repo.delete_property(session, prop_id_for_cleanup)
    await session.commit()


# ── Caso 3: archivo inexistente (DB huérfana) ───────────────────────
async def test_case3_missing_file_fails_honestly(session, user_id):
    from app.memory import service as memory_service
    from app.properties import repository as prop_repo

    prop = await prop_repo.create_property(session, {
        "title": "Casa con foto fantasma en disco",
        "property_type": "casa", "operation": "RENT", "price": 1_100_000,
        "city": "Carepa", "status": "AVAILABLE",
    })
    await session.commit()
    # Registro DB sin archivo real en disco (divergencia DB↔fs)
    await prop_repo.add_property_image(
        session, prop.id, "ghost-missing.jpg", is_cover=True, sort_order=0,
        mime_type="image/jpeg",
    )
    await session.commit()
    pid = str(prop.id)
    user = await memory_service.get_or_create_user(session, user_id, "t", "T")
    conv = await memory_service.get_or_create_conversation(session, user.id)
    conv.state = {"last_results": [prop.to_dict()], "last_property_id": pid}
    flag_modified(conv, "state")
    await session.commit()

    def agent(messages, tools):
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if not tool_msgs:
            return tool_round(tc("get_property_images", {"property_id": pid}, call_id="g1"))
        return send_response_round(
            "En este momento no pude adjuntar las fotografías de esa propiedad.",
            intent="PROPERTY_IMAGES",
        )

    fake = FakeLLMV2([agent])
    reply = await Orchestrator(llm=fake).handle_user_message(
        session, user_id, "muéstrame una imagen", "t", "T"
    )
    assert not reply.images
    assert "aquí tienes" not in reply.text.lower()
    envs = _image_tool_results(fake)
    assert envs and envs[0].get("ok") is False
    assert (envs[0].get("data") or {}).get("reason") == "file_missing"
    await prop_repo.delete_property(session, prop.id)
    await session.commit()


# ── Caso 4: la imagen pertenece a la propiedad solicitada ───────────
async def test_case4_image_belongs_to_requested_property(session, user_id):
    pid8 = await _prop_id(session, "PROP-0008")
    pid1 = await _prop_id(session, "PROP-0001")
    await _setup_single_result_state(session, user_id, "PROP-0008")

    def agent(messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            return tool_round(tc("get_property_images", {"property_id": pid8, "limit": 1}, call_id="g1"))
        return send_response_round(
            "Te comparto la fotografía de PROP-0008.",
            intent="PROPERTY_IMAGES", images=[pid8],
        )

    fake = FakeLLMV2([agent])
    reply = await Orchestrator(llm=fake).handle_user_message(
        session, user_id, "Quiero una imagen de PROP-0008", "t", "T"
    )
    assert len(reply.images) == 1
    # El path real vive bajo storage_test/properties/<uuid-propiedad>/
    assert pid8 in reply.images[0], f"la foto debe pertenecer a PROP-0008: {reply.images[0]}"
    assert pid1 not in reply.images[0]
    assert Path(reply.images[0]).is_file()


# ── Caso 5: varias fotos ────────────────────────────────────────────
async def test_case5_multiple_photos(session, user_id):
    pid = await _prop_id(session, "PROP-0008")
    await _setup_single_result_state(session, user_id, "PROP-0008")

    def agent(messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            return tool_round(tc("get_property_images", {"property_id": pid}, call_id="g1"))
        return send_response_round(
            "Te comparto las fotografías de la propiedad.",
            intent="PROPERTY_IMAGES", images=[pid],
        )

    fake = FakeLLMV2([agent])
    reply = await Orchestrator(llm=fake).handle_user_message(
        session, user_id, "Muéstrame fotos de PROP-0008", "t", "T"
    )
    assert len(reply.images) >= 2, f"plural debe enviar varias, got {reply.images}"
    for p in reply.images:
        assert Path(p).is_file(), f"no es archivo real: {p}"


# ── Caso 6: contexto («quiero una imagen» sin código) ───────────────
async def test_case6_contextual_reference_resolves_previous(session, user_id):
    pid = await _prop_id(session, "PROP-0008")
    await _setup_single_result_state(session, user_id, "PROP-0008")

    def agent(messages, tools):
        # Sin property_id: «la casa» debe resolverse por contexto (last_results).
        if not any(m.get("role") == "tool" for m in messages):
            return tool_round(tc("get_property_images", {"limit": 1}, call_id="g1"))
        envs = [json.loads(m["content"]) for m in messages if m.get("role") == "tool"]
        img = next((e for e in envs if e.get("tool") == "get_property_images" and e.get("ok")), None)
        assert img is not None, f"la referencia contextual debió resolver, envs={envs}"
        got = (img.get("data") or {}).get("property_id")
        assert got == pid, f"debió resolver PROP-0008, got {got}"
        return send_response_round(
            "Te comparto la fotografía de la casa.",
            intent="PROPERTY_IMAGES", images=[got],
        )

    fake = FakeLLMV2([agent])
    reply = await Orchestrator(llm=fake).handle_user_message(
        session, user_id, "Bueno entonces deseo ver una imagen de la casa", "t", "T"
    )
    assert len(reply.images) == 1
    assert Path(reply.images[0]).is_file()


# ── Caso 6b: referencia genérica literal («la casa» como property_id) ─
async def test_case6b_generic_literal_ref_resolves(session, user_id):
    await _setup_single_result_state(session, user_id, "PROP-0008")

    def agent(messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            return tool_round(tc("get_property_images", {"property_id": "la casa", "limit": 1}, call_id="g1"))
        envs = [json.loads(m["content"]) for m in messages if m.get("role") == "tool"]
        img = next((e for e in envs if e.get("tool") == "get_property_images" and e.get("ok")), None)
        assert img is not None, f"«la casa» literal debió resolverse por contexto: {envs}"
        return send_response_round(
            "Te comparto la fotografía de la casa.",
            intent="PROPERTY_IMAGES", images=[(img.get("data") or {}).get("property_id")],
        )

    fake = FakeLLMV2([agent])
    reply = await Orchestrator(llm=fake).handle_user_message(
        session, user_id, "deseo ver una imagen de la casa", "t", "T"
    )
    assert len(reply.images) == 1
    assert Path(reply.images[0]).is_file()


# ── Caso 7: error Telegram → aviso visible, sin mentir ──────────────
async def test_case7_telegram_send_failure_is_visible(session, user_id):
    from app.bot import handlers

    pid = await _prop_id(session, "PROP-0008")
    await _setup_single_result_state(session, user_id, "PROP-0008")

    def agent(messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            return tool_round(tc("get_property_images", {"property_id": pid, "limit": 1}, call_id="g1"))
        return send_response_round(
            "Te comparto la fotografía.",
            intent="PROPERTY_IMAGES", images=[pid],
        )

    fake = FakeLLMV2([agent])
    reply = await Orchestrator(llm=fake).handle_user_message(
        session, user_id, "Quiero una imagen", "t", "T"
    )
    assert len(reply.images) == 1 and Path(reply.images[0]).is_file()

    update = MagicMock()
    update.effective_chat.id = 12345
    update.effective_message.reply_text = AsyncMock()
    update.effective_message.reply_photo = AsyncMock(side_effect=RuntimeError("telegram down"))
    await handlers._reply_with(update, reply)
    # Texto inicial + aviso visible de fallo (2 llamadas), nunca traceback al usuario
    assert update.effective_message.reply_text.await_count >= 2
    sent_texts = [
        str(c.args[0] if c.args else c.kwargs.get("text", ""))
        for c in update.effective_message.reply_text.await_args_list
    ]
    assert any("No pude enviar las fotos" in t for t in sent_texts)
    assert not any("Traceback" in t or "reply_photo" in t for t in sent_texts)


# ── Caso 8: texto libre que alucina → bloqueado, sin envío falso ────
async def test_case8_plain_text_image_claim_blocked(session, user_id):
    await _setup_single_result_state(session, user_id, "PROP-0008")
    fake = FakeLLMV2([plain_text("Aquí tienes una imagen de la casa:")])
    reply = await Orchestrator(llm=fake).handle_user_message(
        session, user_id, "deseo ver una imagen de la casa", "t", "T"
    )
    assert not reply.images, f"texto libre no puede adjuntar fotos: {reply.images}"
    assert "aquí tienes una imagen" not in reply.text.lower()
    # El runtime debió pedir corrección con tools (≥2 llamadas al LLM)
    assert len(fake.calls) >= 2


# ── E2E: buscar arriendo → pedir imagen → foto real ─────────────────
async def test_e2e_search_rent_then_single_image(session, user_id):
    from app.agents.orchestrator import Orchestrator as _Orch

    calls = {"n": 0}

    def agent(messages, tools):
        calls["n"] += 1
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if not tool_msgs:
            # Turno de búsqueda o de imagen según el último mensaje de usuario
            user_texts = [m.get("content", "") for m in messages if m.get("role") == "user"]
            last_user = (user_texts[-1] if user_texts else "").lower()
            if "imagen" in last_user or "foto" in last_user:
                return tool_round(tc("get_property_images", {"limit": 1}, call_id="g1"))
            return tool_round(
                tc("update_conversation_state", {
                    "intent": "SEARCH_PROPERTY", "operation": "RENT",
                    "property_type": "casa", "phase": "PROPERTY_SELECTION",
                }, call_id="st"),
                tc("search_properties", {
                    "filters": {"operation": "RENT", "property_type": "casa", "bedrooms": 3},
                    "semantic_query": "casa arrendada 3 habitaciones",
                }, call_id="sp"),
            )
        envs = [json.loads(m["content"]) for m in tool_msgs]
        search = next((e for e in envs if e.get("tool") == "search_properties" and e.get("ok")), None)
        if search is not None:
            props = (search.get("data") or {}).get("properties") or []
            assert len(props) == 1, f"RENT+casa debe dar 1 resultado (PROP-0009), got {len(props)}"
            code = props[0].get("code")
            return send_response_round(
                f"Encontré una casa en arriendo {code} que coincide con tu búsqueda. "
                "¿Te gustaría ver fotos, más detalles o agendar una visita?",
                intent="SEARCH_PROPERTY",
            )
        img = next((e for e in envs if e.get("tool") == "get_property_images" and e.get("ok")), None)
        assert img is not None, f"la imagen debió resolverse del contexto: {envs}"
        got = (img.get("data") or {}).get("property_id")
        code = (img.get("data") or {}).get("property_code")
        return send_response_round(
            f"Te comparto la fotografía de la casa {code}.",
            intent="PROPERTY_IMAGES", images=[got],
        )

    fake = FakeLLMV2([agent])
    orch = _Orch(llm=fake)
    reply1 = await orch.handle_user_message(session, user_id, "Quiero una casa arrendada", "t", "T")
    assert "arriendo" in reply1.text.lower() or "encontré" in reply1.text.lower()
    reply2 = await orch.handle_user_message(
        session, user_id, "Bueno entonces deseo ver una imagen de la casa", "t", "T"
    )
    assert len(reply2.images) == 1, f"E2E debe enviar 1 foto real, got {reply2.images}"
    assert Path(reply2.images[0]).is_file()
    assert Path(reply2.images[0]).stat().st_size > 0
    assert "aquí tienes una imagen de la casa:" not in reply2.text.lower() or reply2.images
