"""Agent runtime: the LLM tool-calling loop. Pure infrastructure.

Este módulo implementa el loop agentic REAL:

    user message → LLM (con tools)
        → tool_calls[] → runtime ejecuta → envelopes (con call_id)
        → LLM inspecciona resultados → (más tools | send_response | texto final)
        → respuesta

El runtime NUNCA decide semántica inmobiliaria. Solo: ejecutar tools, validar
argumentos, reintentos técnicos, idempotencia, límites anti-loop, correlación
de IDs y observabilidad estructurada. La decisión de qué hacer con cada
resultado pertenece al LLM.

Referencias del patrón (documentación oficial OpenAI, function calling):
- el loop continúa "for as many tool calls as the task requires";
- cada tool result debe referenciar su call_id;
- las respuestas pueden traer 0, 1 o N tool calls (lote del modelo).
"""
from __future__ import annotations

import itertools
import json
import time
import uuid as uuid_mod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.agents.intents import Intent
from app.agents.metrics import METRICS
from app.agents.tools import ToolContext, run_tool, tool_envelope
from app.ai.llm import LLMError, LLMProvider, ToolCall
from app.core.logging import get_logger
from app.core.retry import (
    ErrorCategory,
    OperationType,
    RetryPolicy,
    classify_tool_error,
    execute_with_retry,
    generate_idempotency_key,
    is_idempotent_tool,
    requires_idempotency_key,
)
from app.core.settings import get_settings

log = get_logger(__name__)

# Progress callback type for optional Telegram progress tracking
ProgressCallback = Callable[[str, dict], Awaitable[None]]

# ──────────────────────────────────────────────────────────────────────────
# Límites técnicos del runtime (NO son flujo de negocio: son protección)
# ──────────────────────────────────────────────────────────────────────────
MAX_IDENTICAL_TOOL_CALLS = 2          # misma tool+args consecutivas → forzar final
MAX_CONSECUTIVE_ZERO_SEARCHES = 2     # búsquedas sin resultados consecutivas
MAX_MESSAGES_IN_CONTEXT = 60          # techo absoluto del contexto del turno
MAX_TOOL_CALLS_PER_TURN = 8           # presupuesto de tools por turno
EMPTY_CONTENT_NUDGES = 1               # reintentos cuando el LLM responde vacío
MAX_REPLY_CHARS = 6000                # techo Telegram
SEND_RESPONSE_TOOL = "send_response"

# Acciones de teclado válidas (contrato de presentación, validado en runtime)
KNOWN_KEYBOARD_ACTIONS = frozenset({
    "details", "images", "save", "compare", "slots", "book_slot", "confirm_booking",
    "cancel_booking", "contact_agent", "docs", "save_search", "list_saved",
    "cancel_appt", "ver_mas_dias",
})


@dataclass
class TurnOutcome:
    """Resultado observable de un turno del agente."""
    reply_text: str = ""
    intent: Intent = Intent.UNKNOWN
    images: list[str] = field(default_factory=list)
    actions: list[tuple] = field(default_factory=list)
    tool_trace: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)  # envelopes crudos (audit/degraded)
    rounds: int = 0
    llm_calls: int = 0
    status: str = "ok"            # ok | forced_final | llm_error:<kind> | empty
    finish: str = ""              # send_response | plain_text | forced_final | none
    error: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.reply_text.strip()) and self.status in ("ok", "forced_final")


def _tool_signature(tc: ToolCall) -> str:
    return f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True, ensure_ascii=False)}"


def _tool_message_content(envelope: dict, max_chars: int) -> str:
    """Serializa el envelope GARANTIZANDO JSON válido dentro de max_chars.

    Un slice ciego ``json.dumps(...)[:max]`` corta a mitad de JSON y alimenta
    al modelo con basura sintáctica. Aquí: si cabe → tal cual; si no → versión
    compacta (sin datos largos) SIEMPRE parseable, con la cuenta en metadata.
    """
    payload = json.dumps(envelope, ensure_ascii=False, default=str)
    if len(payload) <= max_chars:
        return payload
    slim = {k: v for k, v in envelope.items() if k not in ("data", "data_truncated")}
    slim["data_omitted"] = True
    slim["note"] = "El resultado completo excede el límite de contexto; usa la cuenta de metadata y refina la consulta si necesitas el detalle."
    slim_payload = json.dumps(slim, ensure_ascii=False, default=str)
    if len(slim_payload) <= max_chars:
        return slim_payload
    minimal = {
        "tool": envelope.get("tool"), "ok": envelope.get("ok"),
        "data_omitted": True,
        "note": "resultado demasiado grande para el contexto",
    }
    return json.dumps(minimal, ensure_ascii=False)


def _looks_like_broken_tool_attempt(content: str) -> bool:
    """Heuristica: el LLM parece haber intentado un tool-call en texto plano
    (JSON truncado/invalido) en vez de responder al usuario o usar send_response."""
    c = content.strip()
    if not c.startswith(("{", "[")):
        return False
    try:
        import json as _json
        _json.loads(c)
        return False  # JSON valido: no es "roto", se deja pasar como texto normal
    except Exception:  # noqa: BLE001 - any JSON parsing error means broken tool attempt
        return True


class AgentRuntime:
    """Ejecuta turnos del agente: LLM → tools → LLM → ... → respuesta final."""

    def __init__(
        self,
        provider: LLMProvider,
    ):
        self.provider = provider
        self.settings = get_settings()

    async def _emit_progress(self, on_progress: ProgressCallback | None, event: str, data: dict | None = None) -> None:
        """Emit a progress event if callback is registered."""
        if on_progress:
            try:
                await on_progress(event, data or {})
            except Exception:
                # Progress callbacks must never break the agent loop
                log.debug("progress_callback_failed event=%s", event, exc_info=True)

    # ------------------------------------------------------------------ turno
    async def run_turn(
        self,
        ctx: ToolContext,
        user_text: str,
        messages: list[dict],
        on_progress: ProgressCallback | None = None,
    ) -> TurnOutcome:
        """Corre el loop agentic para un turno completo.

        ``messages`` llega ya construido (system + historial + mensaje actual).
        El runtime puede añadir: mensajes de tools y correcciones de sistema.
        Nunca reordena ni reconstruye el historial.
        """
        s = self.settings
        max_rounds = max(1, s.LLM_MAX_TOOL_ROUNDS)
        outcome = TurnOutcome()

        run_id = getattr(ctx, "request_id", None) or uuid_mod.uuid4().hex[:16]
        log.info(
            "agent_turn_started run_id=%s user=%s conversation_id=%s",
            run_id, ctx.user_id, ctx.conversation_id,
        )
        await self._emit_progress(on_progress, "turn_started", {"run_id": run_id, "user_id": ctx.user_id})
        started = time.monotonic()

        # estado de protecciones (contadores técnicos, no flujo de negocio)
        last_signature: str | None = None
        identical_count = 0
        zero_search_streak = 0
        empty_content_nudges = 0
        tool_budget = MAX_TOOL_CALLS_PER_TURN
        images_by_property: dict[str, list[str]] = {}
        # BUG-3: rastrear tools que fallaron y luego tuvieron éxito en el mismo turno
        failed_tools_this_turn: set[str] = set()
        succeeded_tools_this_turn: set[str] = set()
        # traza del último turno (introspección para tests/debug)
        self._last_trace = outcome.tool_trace

        for round_num in range(1, max_rounds + 1):
            if len(messages) > MAX_MESSAGES_IN_CONTEXT:
                METRICS.inc("loop_protections")
                log.warning("loop_protection_triggered reason=message_limit run_id=%s", run_id)
                await self._emit_progress(on_progress, "turn_error", {"run_id": run_id, "reason": "message_limit"})
                return await self._forced_final(ctx, messages, outcome, reason="message_limit", on_progress=on_progress)

            outcome.rounds = round_num
            METRICS.inc("llm_rounds")
            log.info("llm_round_started round=%s run_id=%s", round_num, run_id)
            await self._emit_progress(on_progress, "llm_round_started", {"run_id": run_id, "round": round_num})
            t0 = time.monotonic()

            try:
                resp = await self._call_llm(messages, with_tools=True)
            except LLMError as e:
                METRICS.inc("llm_errors")
                outcome.llm_calls += 1
                outcome.status = f"llm_error:{e.kind}"
                outcome.error = f"{e.kind}: {e}"
                log.error(
                    "llm_round_failed round=%s kind=%s run_id=%s rounds=%s",
                    round_num, e.kind, run_id, round_num,
                )
                await self._emit_progress(on_progress, "llm_error", {"run_id": run_id, "round": round_num, "kind": e.kind})
                return outcome
            outcome.llm_calls += 1

            latency_ms = int((time.monotonic() - t0) * 1000)
            log.info(
                "llm_round_completed round=%s latency_ms=%s finish=%s tool_calls=%s run_id=%s",
                round_num, latency_ms, resp.finish_reason, len(resp.tool_calls), run_id,
            )

            # ── caso 1: el LLM pidió tools → ejecutar y continuar el loop ──
            if resp.tool_calls:
                await self._emit_progress(on_progress, "tools_planned", {"run_id": run_id, "round": round_num, "tool_count": len(resp.tool_calls), "tools": [tc.name for tc in resp.tool_calls]})
                messages.append(self._assistant_tool_message(resp))
                if len(resp.tool_calls) > 1:
                    METRICS.inc("tool_call_batches")

                send_calls = [c for c in resp.tool_calls if c.name == SEND_RESPONSE_TOOL]
                other_calls = [c for c in resp.tool_calls if c.name != SEND_RESPONSE_TOOL]

                for tc in other_calls:
                    if tool_budget <= 0:
                        log.warning(
                            "loop_protection_triggered reason=tool_budget tool=%s run_id=%s",
                            tc.name, run_id,
                        )
                        METRICS.inc("loop_protections")
                        await self._emit_progress(on_progress, "turn_error", {"run_id": run_id, "reason": "tool_budget", "tool": tc.name})
                        return await self._forced_final(ctx, messages, outcome, reason="tool_budget", on_progress=on_progress)
                    tool_budget -= 1

                    signature = _tool_signature(tc)
                    if signature == last_signature:
                        identical_count += 1
                    else:
                        identical_count = 1
                        last_signature = signature
                    if identical_count > MAX_IDENTICAL_TOOL_CALLS:
                        METRICS.inc("loop_protections")
                        log.warning(
                            "loop_protection_triggered reason=identical_calls tool=%s count=%s run_id=%s",
                            tc.name, identical_count, run_id,
                        )
                        return await self._forced_final(ctx, messages, outcome, reason="identical_calls", on_progress=on_progress)

                    await self._emit_progress(on_progress, "tool_started", {"run_id": run_id, "round": round_num, "tool": tc.name, "call_id": tc.id})
                    envelope, trace = await self._execute_tool(
                        tc, ctx, round_num, run_id, images_by_property
                    )
                    outcome.tool_trace.append(trace)
                    outcome.evidence.append(envelope)
                    await self._emit_progress(on_progress, "tool_completed", {"run_id": run_id, "round": round_num, "tool": tc.name, "call_id": tc.id, "ok": envelope.get("ok", False)})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": _tool_message_content(
                            envelope, s.LLM_TOOL_RESULT_MAX_CHARS
                        ),
                    })

                    # BUG-3: track tool failures and subsequent successes for silent retry detection
                    tool_ok = envelope.get("ok", False)
                    if not tool_ok:
                        failed_tools_this_turn.add(tc.name)
                    elif tool_ok and tc.name in failed_tools_this_turn:
                        # Tool falló antes y ahora tuvo éxito en el mismo turno
                        # Verificar si el LLM narró la corrección en la respuesta final
                        # (esto se verifica al final del turno en send_response)
                        succeeded_tools_this_turn.add(tc.name)

                    if tc.name == "search_properties" and envelope.get("ok"):
                        if (envelope.get("data", {}) or {}).get("count", 0) == 0:
                            zero_search_streak += 1
                            if zero_search_streak >= MAX_CONSECUTIVE_ZERO_SEARCHES:
                                METRICS.inc("loop_protections")
                                log.warning(
                                    "loop_protection_triggered reason=zero_result_searches count=%s run_id=%s",
                                    zero_search_streak, run_id,
                                )
                                return await self._forced_final(
                                    ctx, messages, outcome, reason="zero_result_searches", on_progress=on_progress
                                )
                        else:
                            zero_search_streak = 0

                # send_response en lote con otras tools: se ejecuta después y se
                # pide al modelo que decida DE NUEVO con los resultados reales.
                for tc in send_calls:
                    if other_calls:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps({
                                "tool": SEND_RESPONSE_TOOL, "ok": False,
                                "error": {
                                    "code": "BATCHED_TERMINAL_CALL",
                                    "message": (
                                        "Llamaste send_response junto con otras herramientas. "
                                        "Ya tienes sus resultados reales. Decide de nuevo: "
                                        "envía send_response SOLO (actualizando el texto si hace "
                                        "falta) o llama otras tools primero."
                                    ),
                                    "retryable": False,
                                },
                            }, ensure_ascii=False),
                        })
                        continue
                    # send_response solo → validar y capturar (fin del turno)
                    error = self._validate_send_response(tc, ctx, images_by_property)
                    if error:
                        outcome.tool_trace.append({
                            "tool": SEND_RESPONSE_TOOL, "call_id": tc.id, "round": round_num,
                            "ok": False, "error": error,
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps({
                                "tool": SEND_RESPONSE_TOOL, "ok": False,
                                "error": {"code": "BAD_ARGUMENTS", "message": error, "retryable": False},
                            }, ensure_ascii=False),
                        })
                        continue
                    METRICS.inc("send_response_calls")
                    args = tc.arguments
                    resolved, _missing = self._resolve_images(
                        args.get("images") or [], ctx, images_by_property
                    )
                    outcome.reply_text = str(args.get("text", ""))[:MAX_REPLY_CHARS]
                    if args.get("intent"):
                        try:
                            outcome.intent = Intent(str(args["intent"]))
                        except ValueError:
                            outcome.intent = Intent.UNKNOWN
                    outcome.images = resolved
                    outcome.actions = [
                        (btn["action"], btn.get("payload"))
                        for btn in (args.get("keyboard") or [])
                    ]
                    outcome.status = "ok"
                    outcome.finish = "send_response"

                    # BUG-3: detectar reintentos silenciosos (tool falló y luego tuvo éxito sin narrar corrección)
                    # Comparamos tools que fallaron y luego tuvieron éxito en este turno
                    silent_retries = failed_tools_this_turn & succeeded_tools_this_turn
                    if silent_retries:
                        # Verificar si el texto de la respuesta menciona la corrección
                        reply_text_lower = outcome.reply_text.lower()
                        correction_keywords = [
                            "falló", "fallo", "error", "correg", "primer intento",
                            "intento anterior", "id inválid", "incorrect", "cambié",
                            "arreglé", "solucion", "problema", "ahora sí"
                        ]
                        narrated_correction = any(kw in reply_text_lower for kw in correction_keywords)
                        if not narrated_correction:
                            METRICS.inc("silent_retry_after_tool_error")
                            log.warning(
                                "silent_retry_detected tools=%s reply=%s",
                                silent_retries, outcome.reply_text[:100]
                            )

                    outcome.tool_trace.append({
                        "tool": SEND_RESPONSE_TOOL, "call_id": tc.id, "round": round_num, "ok": True,
                    })
                    await self._emit_progress(on_progress, "turn_completed", {"run_id": run_id, "rounds": round_num, "finish": "send_response", "latency_ms": int((time.monotonic() - started) * 1000)})
                    log.info(
                        "agent_turn_completed status=ok finish=send_response rounds=%s "
                        "tool_calls=%s latency_ms=%s run_id=%s",
                        round_num, len(outcome.tool_trace),
                        int((time.monotonic() - started) * 1000), run_id,
                    )
                    return outcome

                # Tools ejecutadas y resultados appended → el loop CONTINÚA:
                # la siguiente decisión es del LLM viendo la evidencia. En
                # tool-calling el content de esta respuesta suele estar VACÍO
                # y eso es normal: NUNCA se evalúa como respuesta final aquí
                # (patrón oficial: assistant.tool_calls → role:tool → model).
                continue

            # ── caso 2: sin tool_calls → respuesta final ──
            content = (resp.content or "").strip()
            if content and _looks_like_broken_tool_attempt(content):
                content = ""
            if content:
                outcome.reply_text = content[:MAX_REPLY_CHARS]
                outcome.finish = "plain_text"
                outcome.status = "ok"
                await self._emit_progress(on_progress, "turn_completed", {"run_id": run_id, "rounds": round_num, "finish": "plain_text", "latency_ms": int((time.monotonic() - started) * 1000)})
                log.info(
                    "agent_turn_completed status=ok finish=plain_text rounds=%s "
                    "tool_calls=%s latency_ms=%s run_id=%s",
                    round_num, len(outcome.tool_trace), int((time.monotonic() - started) * 1000), run_id,
                )
                return outcome

            # contenido vacío: un nudge técnico y continuar
            if empty_content_nudges < EMPTY_CONTENT_NUDGES:
                empty_content_nudges += 1
                log.warning("llm_empty_content round=%s nudging run_id=%s", round_num, run_id)
                messages.append({
                    "role": "user",
                    "content": (
                        "Tu respuesta anterior quedó vacía. Responde al usuario con texto "
                        "útil o llama a send_response."
                    ),
                })
                continue
            return await self._forced_final(ctx, messages, outcome, reason="empty_content", on_progress=on_progress)

        # rondas agotadas → una última llamada sin tools para forzar respuesta
        return await self._forced_final(ctx, messages, outcome, reason="max_rounds", on_progress=on_progress)

    # ─────────────────────────────────────────────────────────── forced final
    async def _forced_final(
        self, ctx, messages: list[dict], outcome: TurnOutcome, *, reason: str, on_progress: ProgressCallback | None = None
    ) -> TurnOutcome:
        """Límite técnico alcanzado: una llamada SIN tools para cerrar el turno.

        Es infraestructura: el modelo sigue decidiendo QUÉ decir; el runtime
        solo retira la opción de más tools porque detectó un patrón de loop.
        """
        run_id = getattr(ctx, "request_id", "")
        METRICS.inc("forced_finals")
        await self._emit_progress(on_progress, "turn_composing", {"run_id": run_id, "reason": reason, "rounds": outcome.rounds})
        log.info("agent_forced_final reason=%s rounds=%s run_id=%s",
                 reason, outcome.rounds, run_id)
        messages.append({
            "role": "user",
            "content": (
                f"[aviso del sistema] Se alcanzó un límite técnico de ejecución ({reason}). "
                "Responde AHORA al usuario con texto final. NO llames más herramientas: "
                "usa solo lo confirmado hasta ahora y aclara qué quedó pendiente si hace falta."
            ),
        })
        try:
            resp = await self._call_llm(messages, with_tools=False)
            outcome.llm_calls += 1
        except LLMError as e:
            METRICS.inc("llm_errors")
            outcome.status = f"llm_error:{e.kind}"
            outcome.error = str(e)
            await self._emit_progress(on_progress, "turn_error", {"run_id": run_id, "reason": f"llm_error:{e.kind}"})
            return outcome
        content = (resp.content or "").strip()
        if content and _looks_like_broken_tool_attempt(content):
            content = ""
        if not content:
            outcome.status = "empty"
            await self._emit_progress(on_progress, "turn_error", {"run_id": run_id, "reason": "empty_content"})
            return outcome
        if resp.tool_calls:  # contra contrato: sin tools no debería haber tool_calls
            log.warning("forced_final_returned_tool_calls n=%s", len(resp.tool_calls))
        outcome.reply_text = content[:MAX_REPLY_CHARS]
        outcome.finish = "forced_final"
        outcome.status = "forced_final"
        await self._emit_progress(on_progress, "turn_completed", {"run_id": run_id, "rounds": outcome.rounds, "finish": "forced_final", "latency_ms": 0})
        return outcome

    # ─────────────────────────────────────────────────────────── llm plumbing
    async def _call_llm(self, messages: list[dict], *, with_tools: bool):
        """Una llamada al proveedor. Los reintentos técnicos los maneja el
        provider (backoff ante 429/5xx/timeout): el runtime no duplica capas.
        Un LLMError definitivo termina el turno con estado honesto (el
        orquestador decide la respuesta degradada)."""
        from app.agents.tool_specs import TOOL_SPECS

        s = self.settings
        resp = await self.provider.chat(
            messages,
            tools=TOOL_SPECS if with_tools else None,
            temperature=s.LLM_TEMPERATURE,
            max_tokens=s.LLM_MAX_TOKENS,
        )
        METRICS.inc("llm_success")
        return resp

    # ─────────────────────────────────────────────────────────── tool plumbing
    async def _execute_tool(
        self, tc: ToolCall, ctx: ToolContext, round_num: int, run_id: str,
        images_by_property: dict[str, list[str]],
    ) -> tuple[dict, dict]:
        """Ejecuta UNA tool con reintentos técnicos + idempotencia.

        Devuelve (envelope para el LLM, trace para auditoría). Los errores se
        convierten en envelopes estructurados: el AGENTE decide qué hacer con
        ellos (continuar, reintentar con otros argumentos, responder parcial).
        """
        s = self.settings
        t0 = time.monotonic()

        if tc.arguments_error:
            envelope = {
                "tool": tc.name, "ok": False,
                "error": {"code": "BAD_ARGUMENTS", "message": tc.arguments_error, "retryable": False},
            }
            trace = {"tool": tc.name, "call_id": tc.id, "round": round_num, "ok": False,
                     "error": tc.arguments_error, "attempts": 1,
                     "duration_ms": int((time.monotonic() - t0) * 1000)}
            METRICS.inc("tool_errors")
            log.info("tool_call_failed tool=%s call_id=%s code=BAD_ARGUMENTS run_id=%s",
                     tc.name, tc.id, run_id)
            return envelope, trace

        log.info("tool_call_started tool=%s call_id=%s run_id=%s", tc.name, tc.id, run_id)

        idempotency_key = None
        if requires_idempotency_key(tc.name):
            idempotency_key = generate_idempotency_key(
                tc.name, tc.arguments, str(ctx.conversation_id), ctx.user_id
            )
            if idempotency_key in ctx.idempotency_keys:
                log.info(
                    "tool_idempotent_skip tool=%s key=%s run_id=%s",
                    tc.name, idempotency_key[:8], run_id,
                )
                envelope = {
                    "tool": tc.name, "ok": True,
                    "data": {"idempotent_skip": True, "note": "operación ya ejecutada en este turno"},
                }
                trace = {"tool": tc.name, "call_id": tc.id, "round": round_num, "ok": True,
                         "idempotent_skip": True, "attempts": 1,
                         "duration_ms": int((time.monotonic() - t0) * 1000)}
                return envelope, trace

        op_type = (
            OperationType.READ if is_idempotent_tool(tc.name)
            else OperationType.TOOL_EXEC
        )
        policy = RetryPolicy(
            max_attempts=s.RETRY_TOOL_EXEC_MAX_ATTEMPTS,
            base_delay=s.RETRY_BASE_DELAY,
            max_delay=s.RETRY_MAX_DELAY,
            jitter_factor=s.RETRY_JITTER_FACTOR,
            timeout=s.TOOL_TIMEOUT,
        )
        # Empieza en 1: cada intento ejecutado deja el contador en n_intentos.
        # (count() desde 0 provocaba un off-by-one: un retry de 2 intentos
        # nunca registraba la métrica tool_retries.)
        attempts = itertools.count(1)

        async def _run():
            next(attempts)
            return await run_tool(tc.name, tc.arguments, ctx)

        try:
            raw = await execute_with_retry(
                _run, policy=policy,
                operation_type=op_type,
                operation_name=f"tool:{tc.name}",
                correlation_id=run_id,
            )
            n_attempts = next(attempts) - 1
            if n_attempts > 0:
                METRICS.inc("tool_retries", n_attempts)
        except Exception as e:  # noqa: BLE001 - tool execution errors are converted to envelopes
            n_attempts = next(attempts) - 1
            if n_attempts > 0:
                METRICS.inc("tool_retries", n_attempts)
            category = classify_exception_quiet(e)
            retryable = category in {
                ErrorCategory.TRANSIENT_NETWORK, ErrorCategory.TRANSIENT_HTTP_5XX,
                ErrorCategory.TRANSIENT_RATE_LIMIT, ErrorCategory.TRANSIENT_DB,
                ErrorCategory.TRANSIENT_PROVIDER,
            }
            duration_ms = int((time.monotonic() - t0) * 1000)
            envelope = {
                "tool": tc.name, "ok": False,
                "error": {"code": "TOOL_EXECUTION_ERROR", "message": str(e)[:200],
                          "retryable": retryable, "category": category.value},
            }
            trace = {"tool": tc.name, "call_id": tc.id, "round": round_num, "ok": False,
                     "error": f"{category.value}: {str(e)[:200]}", "attempts": max(1, n_attempts),
                     "duration_ms": duration_ms}
            METRICS.inc("tool_errors")
            log.info(
                "tool_call_failed tool=%s call_id=%s category=%s duration_ms=%s run_id=%s",
                tc.name, tc.id, category.value, duration_ms, run_id,
            )
            return envelope, trace

        duration_ms = int((time.monotonic() - t0) * 1000)
        envelope = tool_envelope(tc.name, raw, max_chars=s.LLM_TOOL_RESULT_MAX_CHARS)
        if tc.name == "get_property_images":
            data = envelope.get("data") or {}
            pid = data.get("property_id")
            if pid:
                images_by_property[str(pid)] = list(data.get("images") or [])
        if raw.get("ok", True):
            if idempotency_key:
                ctx.idempotency_keys[idempotency_key] = tc.name
        else:
            METRICS.inc("tool_errors")
            error_category = classify_tool_error(envelope)
            envelope["error"]["category"] = error_category.value
        trace = {
            "tool": tc.name, "call_id": tc.id, "round": round_num,
            "ok": bool(raw.get("ok", True)), "args": tc.arguments,
            "duration_ms": duration_ms,
        }
        if not trace["ok"]:
            trace["error"] = (envelope.get("error") or {}).get("message", "")[:200]
        log.info(
            "tool_call_completed tool=%s call_id=%s ok=%s duration_ms=%s run_id=%s",
            tc.name, tc.id, trace["ok"], duration_ms, run_id,
        )
        return envelope, trace

    # ─────────────────────────────────────────────────────────── send_response
    def _validate_send_response(
        self, tc: ToolCall, ctx: ToolContext, images_by_property: dict[str, list[str]]
    ) -> str | None:
        """Valida argumentos de la tool terminal. Devuelve None si son válidos."""
        args = tc.arguments or {}
        if tc.arguments_error:
            return tc.arguments_error
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            return "send_response.text es obligatorio y no puede estar vacío."
        if len(text) > MAX_REPLY_CHARS:
            return f"send_response.text supera el máximo de {MAX_REPLY_CHARS} caracteres."
        intent = args.get("intent")
        if intent is not None:
            try:
                Intent(str(intent))
            except ValueError:
                return f"send_response.intent={intent!r} no es una intención válida."
        keyboard = args.get("keyboard")
        if keyboard is not None:
            if not isinstance(keyboard, list) or len(keyboard) > 8:
                return "send_response.keyboard debe ser una lista de máximo 8 botones."
            for btn in keyboard:
                if not isinstance(btn, dict):
                    return "cada botón de keyboard debe ser un objeto {text, action, payload}."
                label = btn.get("text")
                action = btn.get("action")
                if not isinstance(label, str) or not label.strip() or len(label) > 64:
                    return "botón sin texto válido (máx. 64 caracteres)."
                if action not in KNOWN_KEYBOARD_ACTIONS:
                    return (
                        f"acción de botón {action!r} no permitida. Usa una de: "
                        f"{sorted(KNOWN_KEYBOARD_ACTIONS)}."
                    )
                if not isinstance(btn.get("payload"), (dict, str, int, float, type(None))):
                    return "payload del botón debe ser objeto o valor simple."
        images = args.get("images")
        if images is not None:
            if not isinstance(images, list) or len(images) > 10:
                return "send_response.images debe ser una lista de máximo 10 referencias."
            _, missing = self._resolve_images(images, ctx, images_by_property)
            if missing:
                return (
                    "no tengo imágenes obtenidas este turno para: "
                    f"{', '.join(missing)}. Llama get_property_images primero."
                )

        # Anti-alucinación: detectar si el texto afirma enviar imágenes pero no hay images[]
        # Frases típicas que implican envío de imágenes
        text_lower = text.lower()
        claims_images = any(phrase in text_lower for phrase in [
            "adjunto las", "adjuntan las", "se adjuntan", "te envío las", "te mando las",
            "aquí tienes las", "aquí están las", "las imágenes se", "las fotos se",
            "envío las imágenes", "envío las fotos", "mando las imágenes", "mando las fotos",
            "adjunto imágenes", "adjunto fotos", "comparto las imágenes", "comparto las fotos",
        ])
        if claims_images:
            resolved_images = args.get("images") or []
            if not resolved_images:
                METRICS.inc("reply_claims_images_but_empty")
                return (
                    "Tu texto afirma que envías imágenes pero send_response.images está vacío. "
                    "Si tienes imágenes reales, llama get_property_images y pon los property_ids en images[]. "
                    "Si no hay imágenes, no digas que las envías."
                )
            # Si hay images[] pero están vacías tras resolución, _resolve_images ya lo detectó arriba

        # BUG-4: detectar promesas de notificar a vendedor/propietario
        seller_notify_phrases = [
            "notificaré al", "notificar al", "avisar al", "avisaré al",
            "registraré tu interés con el", "registrar tu interés con el",
            "contactaré al", "contactar al", "comunicaré al",
            "el vendedor recibir", "el propietario recibir", "el dueño recibir",
            "ya tengo registrada tu solicitud con el", "solicitud registrada con el",
        ]
        if any(phrase in text_lower for phrase in seller_notify_phrases):
            METRICS.inc("seller_notification_claimed")
            # No bloqueamos, solo métrica - el system prompt debería prevenirlo

        # BUG-5: detectar "confirmada" cuando el estado de cita es REQUESTED
        # El metadata de schedule_visit advierte sobre esto; si el LLM lo ignora, métrica
        if any(w in text_lower for w in ["confirmada", "queda todo confirmado", "cita agendada", "cita confirmada"]):
            # Verificar si en este turno se creó una cita con status REQUESTED
            for trace_item in ctx.executed:
                if trace_item.get("tool") == "schedule_visit" and trace_item.get("ok"):
                    # El resultado está en el trace, pero necesitamos verificar el status
                    # Por simplicidad, si hay schedule_visit exitoso en este turno, métrica
                    METRICS.inc("appointment_status_mismatch")
                    break

        return None

    def _resolve_images(
        self, refs: list, ctx: ToolContext, images_by_property: dict[str, list[str]]
    ) -> tuple[list[str], list[str]]:
        """Resuelve referencias de propiedades a rutas reales obtenidas este turno.

        Solo usa evidencia del turno (images_by_property): el runtime nunca
        inventa rutas ni consulta el disco por su cuenta.
        """
        resolved: list[str] = []
        missing: list[str] = []
        alias: dict[str, list[str]] = {}
        for item in (ctx.state.get("last_results") or []):
            for key in ("id", "code"):
                val = item.get(key)
                if val:
                    alias.setdefault(str(val), []).append(str(item.get("id")))
        for ref in refs:
            ref = str(ref)
            paths = images_by_property.get(ref)
            if not paths:
                for target in alias.get(ref, []):
                    paths = images_by_property.get(target)
                    if paths:
                        break
            if paths:
                resolved.extend(paths)
            else:
                missing.append(ref)
        return resolved, missing

    @staticmethod
    def _assistant_tool_message(resp) -> dict:
        return {
            "role": "assistant",
            "content": resp.content or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in resp.tool_calls
            ],
        }


def classify_exception_quiet(exc: Exception) -> ErrorCategory:
    """Clasifica una excepción para el envelope (sin re-lanzar)."""
    from app.core.retry import classify_exception

    try:
        return classify_exception(exc)
    except Exception:  # pragma: no cover - clasificación nunca debe fallar
        return ErrorCategory.UNKNOWN
