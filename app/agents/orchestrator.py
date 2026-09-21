"""Fachada del orquestador (compatibilidad main.py / bot / API).

Todo el trabajo real está en:
- app/agents/runtime.py        → loop agentic (LLM → tools → LLM → ...).
- app/agents/llm_orchestrator.py → bootstrap del turno, persistencia, auditoría.

Esta fachada solo mantiene la interfaz pública y adapta los callbacks de
botones de Telegram a texto semántico (capa de presentación, NO razonamiento).
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.intents import Intent
from app.agents.llm_orchestrator import create_orchestrator
from app.agents.prompts_v2 import PROMPT_VERSION
from app.agents.reply import AgentReply
from app.agents.runtime import ProgressCallback
from app.ai.llm import LLMProvider
from app.core.logging import get_logger, new_request_id

log = get_logger(__name__)


class Orchestrator:
    """Fachada delgada: delega cada turno al orquestador agent-loop."""

    def __init__(self, llm: LLMProvider | None = None):
        self._llm = llm
        self._pure_orchestrator = None
        self._initialized = False

    async def _ensure_initialized(self):
        if self._initialized:
            return
        self._pure_orchestrator = await create_orchestrator(self._llm)
        self._initialized = True

    @property
    def uses_llm(self) -> bool:
        return self._llm is not None

    @property
    def llm(self) -> LLMProvider | None:
        return self._llm

    # ─────────────────────────────────────────────────────── mensaje de texto
    async def handle_user_message(
        self,
        session: AsyncSession,
        user_id: int,
        text: str,
        username: str = "",
        first_name: str = "",
        on_progress: ProgressCallback | None = None,
    ) -> AgentReply:
        await self._ensure_initialized()
        # Use the cached orchestrator but pass the progress callback for this request
        return await self._pure_orchestrator.handle_user_message(
            session, user_id, text, username, first_name, on_progress=on_progress
        )

    # ──────────────────────────────────────────────────── callback de botón
    async def handle_action(
        self,
        session: AsyncSession,
        user_id: int,
        action: str,
        payload: Any,
        on_progress: ProgressCallback | None = None,
    ) -> AgentReply:
        """Traduce un botón de Telegram a texto semántico y delega el turno.

        La persistencia/auditoría la hace handle_user_message (una sola vez);
        duplicarla aquí creaba mensajes de asistente duplicados.
        """
        await self._ensure_initialized()
        action_text = self._action_to_user_text(action, payload)
        log.info(
            "telegram_action action=%s user=%s request_id=%s",
            action, user_id, new_request_id(),
        )
        started = time.monotonic()
        try:
            return await self._pure_orchestrator.handle_user_message(
                session, user_id, action_text, "", "", on_progress=on_progress
            )
        except Exception as e:
            log.exception(
                "action_error action=%s user=%s latency_ms=%s",
                action, user_id, int((time.monotonic() - started) * 1000),
            )
            return AgentReply(
                text="⚠️ Error procesando la acción. Intenta de nuevo.",
                intent=Intent.UNKNOWN,
                error=str(e),
            )

    def _action_to_user_text(self, action: str, payload: Any) -> str:
        """Botón → mensaje que el USUARIO habría enviado (el LLM interpreta)."""
        if not isinstance(payload, dict):
            payload = {"ref": payload}
        p = {k: v for k, v in payload.items() if isinstance(v, (str, int, float, bool))}
        action_map = {
            "details": "Quiero ver los detalles de la propiedad {ref}",
            "images": "Muéstrame las imágenes de la propiedad {ref}",
            "save": "Guarda la propiedad {ref} en mis favoritos",
            "compare": "Compara la propiedad {ref} con las otras que me mostraste",
            "slots": "Quiero ver horarios disponibles para visitar la propiedad {ref}",
            "book_slot": (
                "Quiero reservar la visita a la propiedad {property_id} "
                "el {datetime_iso}"
            ),
            "confirm_booking": (
                "Sí, confirmo la visita a la propiedad {property_id} el {datetime_iso}. "
                "Agéndala con mis datos de esta conversación."
            ),
            "cancel_booking": "No, cancela ese agendamiento de la propiedad {property_id}",
            "ver_mas_dias": "Muéstrame más días disponibles para la propiedad {property_id}",
            "contact_agent": "Quiero hablar con un asesor humano sobre la propiedad {ref}",
            "docs": "Muéstrame los documentos de la propiedad {ref}",
            "save_search": "Guárdame esta búsqueda como alerta",
            "list_saved": "Muéstrame mis búsquedas guardadas",
            "cancel_appt": "Cancela mi cita {ref}",
        }
        template = action_map.get(action, "Acción: {action} {ref}")
        text = template.format(action=action, **{"ref": "", **p})
        return f"[el usuario presionó el botón «{action}»] {text}".strip()


__all__ = ["PROMPT_VERSION", "Orchestrator"]
