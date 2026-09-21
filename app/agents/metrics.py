"""Métricas del agente: ¿el LLM está actuando realmente como cerebro?

Contadores en proceso (sin dependencias, sin secretos) que permiten responder:
- ¿qué porcentaje de turnos resolvió el LLM?
- ¿cuántas llamadas a herramientas hace por turno?
- ¿cuántas veces cayó al fallback determinista?
- ¿cuánto se usó RAG?

Se exponen vía ``GET /agent/metrics`` y se registran en logs estructurados.
"""
from __future__ import annotations

import threading

_COUNTERS = (
    "agent_turns",
    "llm_first_attempts",
    "llm_success",
    "llm_errors",
    "llm_fallbacks",
    "deterministic_turns",
    "llm_rounds",
    "tool_calls",
    "tool_errors",
    "tool_retries",
    "tool_call_batches",
    "loop_protections",
    "forced_finals",
    "degraded_replies",
    "send_response_calls",
    "web_search_calls",
    "property_search",
    "rag_retrieval",
    "appointment_created",
    "state_updates",
    "state_update_rejections",
    "reply_guards_triggered",
    # Bug-pattern detectors (added for production monitoring):
    "reply_claims_images_but_empty",      # BUG-1: texto dice que envía imágenes pero images=[]
    "appointment_status_mismatch",         # BUG-5: estado REQUESTED pero texto dice "confirmada"
    "seller_notification_claimed",         # BUG-4: texto promete notificar a vendedor sin tool
    "silent_retry_after_tool_error",       # BUG-3: tool falla, luego éxito, sin mención en texto
)


class AgentMetrics:
    """Thread-safe counters. Cheap enough to call on every turn."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {name: 0 for name in _COUNTERS}
        self._lock = threading.Lock()

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counts[name] = self._counts.get(name, 0) + value

    def snapshot(self) -> dict:
        with self._lock:
            counts = dict(self._counts)

        def rate(num: int, den: int) -> float:
            return round(num / den, 4) if den else 0.0

        turns = counts.get("agent_turns", 0)
        tool_calls = counts.get("tool_calls", 0)
        llm_requests = counts.get("llm_success", 0) + counts.get("llm_errors", 0)
        return {
            "counters": counts,
            "rates": {
                "llm_usage_rate": rate(counts.get("llm_success", 0), turns),
                "llm_success_rate": rate(counts.get("llm_success", 0), llm_requests),
                "tool_call_rate": rate(tool_calls, turns),
                "tool_error_rate": rate(counts.get("tool_errors", 0), tool_calls),
                "tool_retry_rate": rate(counts.get("tool_retries", 0), tool_calls),
                "fallback_rate": rate(counts.get("llm_fallbacks", 0), turns),
                "rag_usage_rate": rate(counts.get("rag_retrieval", 0), turns),
                "web_search_usage_rate": rate(counts.get("web_search_calls", 0), turns),
                "average_tool_calls_per_turn": rate(tool_calls, turns),
                "loop_protection_rate": rate(counts.get("loop_protections", 0), turns),
                "degraded_reply_rate": rate(counts.get("degraded_replies", 0), turns),
                "state_update_rejection_rate": rate(
                    counts.get("state_update_rejections", 0), counts.get("state_updates", 0)
                ),
            },
        }

    def reset(self) -> None:
        with self._lock:
            self._counts = {name: 0 for name in _COUNTERS}


METRICS = AgentMetrics()