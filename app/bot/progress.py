"""Telegram progress tracking: editable status messages with throttling.

Provides a safe, application-generated progress representation without exposing
any private chain-of-thought or internal model reasoning.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum

from telegram import Message
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from app.core.logging import get_logger

log = get_logger(__name__)


class ProgressState(Enum):
    """Internal progress states — mapped to safe user-facing messages."""

    STARTING = "starting"
    ANALYZING = "analyzing"
    SEARCHING = "searching"
    CALLING_TOOL = "calling_tool"
    PROCESSING_TOOL_RESULT = "processing_tool_result"
    COMPOSING = "composing"
    FINALIZING = "finalizing"
    DONE = "done"
    ERROR = "error"


# Safe user-facing messages for each state (no chain-of-thought exposure)
STATE_MESSAGES = {
    ProgressState.STARTING: "⏳ Iniciando...",
    ProgressState.ANALYZING: "🧠 Analizando tu solicitud...",
    ProgressState.SEARCHING: "🔎 Buscando información...",
    ProgressState.CALLING_TOOL: "🛠️ Ejecutando consulta...",
    ProgressState.PROCESSING_TOOL_RESULT: "📊 Revisando resultados...",
    ProgressState.COMPOSING: "✍️ Preparando la respuesta...",
    ProgressState.FINALIZING: "✅ Terminando...",
    ProgressState.DONE: "✅ Listo",
    ProgressState.ERROR: "⚠️ Ocurrió un problema. Estoy intentando completar la solicitud...",
}

# Tool-specific progress messages (safe, no internal data)
TOOL_MESSAGES = {
    "search_properties": "🔎 Buscando propiedades...",
    "get_property": "📋 Consultando ficha de propiedad...",
    "compare_properties": "⚖️ Comparando propiedades...",
    "search_documents": "📄 Buscando en documentos...",
    "get_property_images": "📷 Obteniendo imágenes...",
    "list_available_slots": "📅 Consultando horarios disponibles...",
    "schedule_visit": "📅 Agendando visita...",
    "save_property": "⭐ Guardando en favoritos...",
    "remove_saved_property": "🗑️ Quitando de favoritos...",
    "save_search": "💾 Guardando búsqueda...",
    "list_saved_searches": "📋 Listando búsquedas guardadas...",
    "create_alert": "🔔 Creando alerta...",
    "list_alerts": "📋 Listando alertas...",
    "get_alert": "🔍 Consultando alerta...",
    "update_alert": "✏️ Actualizando alerta...",
    "pause_alert": "⏸️ Pausando alerta...",
    "resume_alert": "▶️ Reactivando alerta...",
    "delete_alert": "🗑️ Cancelando alerta...",
    "get_notification_history": "📜 Consultando historial...",
    "create_lead": "👤 Actualizando perfil...",
    "get_customer_profile": "👤 Consultando perfil...",
    "cancel_appointment": "❌ Cancelando cita...",
    "recommend_similar": "🔄 Buscando propiedades similares...",
    "reschedule_appointment": "🔄 Reprogramando cita...",
    "list_appointments": "📅 Consultando citas...",
    "update_conversation_state": "📝 Actualizando contexto...",
    "web_search": "🌐 Buscando en la web...",
}

TOOL_COMPLETED_MESSAGES = {
    "search_properties": "✅ Búsqueda completada",
    "get_property": "✅ Ficha consultada",
    "compare_properties": "✅ Comparación completada",
    "search_documents": "✅ Documentos consultados",
    "get_property_images": "✅ Imágenes obtenidas",
    "list_available_slots": "✅ Horarios consultados",
    "schedule_visit": "✅ Visita agendada",
    "save_property": "✅ Guardado en favoritos",
    "remove_saved_property": "✅ Quitado de favoritos",
    "save_search": "✅ Búsqueda guardada",
    "list_saved_searches": "✅ Listado completado",
    "create_alert": "✅ Alerta creada",
    "list_alerts": "✅ Listado completado",
    "get_alert": "✅ Alerta consultada",
    "update_alert": "✅ Alerta actualizada",
    "pause_alert": "✅ Alerta pausada",
    "resume_alert": "✅ Alerta reactivada",
    "delete_alert": "✅ Alerta cancelada",
    "get_notification_history": "✅ Historial consultado",
    "create_lead": "✅ Perfil actualizado",
    "get_customer_profile": "✅ Perfil consultado",
    "cancel_appointment": "✅ Cita cancelada",
    "recommend_similar": "✅ Recomendaciones listas",
    "reschedule_appointment": "✅ Cita reprogramada",
    "list_appointments": "✅ Citas consultadas",
    "update_conversation_state": "✅ Contexto actualizado",
    "web_search": "✅ Búsqueda web completada",
}


@dataclass
class ProgressConfig:
    """Configuration for progress tracking behavior."""

    # Minimum interval between Telegram edits (seconds)
    min_edit_interval: float = 1.5
    # Maximum message length for Telegram
    max_message_length: int = 4000
    # Timeout for edit operations
    edit_timeout: float = 10.0
    # Whether to show tool-specific messages
    show_tool_details: bool = True


@dataclass
class ProgressContext:
    """Runtime context for a single progress tracking session."""

    chat_id: int
    message_id: int | None = None
    current_state: ProgressState = ProgressState.STARTING
    current_tool: str | None = None
    tool_completed: bool = False
    last_edit_time: float = 0.0
    pending_update: bool = False
    last_message_text: str = ""
    edit_task: asyncio.Task | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class TelegramProgressRenderer:
    """Manages editable progress messages for a single chat session.

    Features:
    - Single message edited in place (no message spam)
    - Throttled edits to respect Telegram limits
    - Safe state messages (no chain-of-thought exposure)
    - Tool-aware progress updates
    - Robust error handling (RetryAfter, BadRequest, etc.)
    - Automatic cleanup on completion/error
    """

    def __init__(
        self,
        bot,
        chat_id: int,
        config: ProgressConfig | None = None,
        on_error: Callable[[Exception], Awaitable[None]] | None = None,
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.config = config or ProgressConfig()
        self.on_error = on_error
        self.ctx = ProgressContext(chat_id=chat_id)
        self._closed = False

    async def start(self, initial_state: ProgressState = ProgressState.STARTING) -> Message | None:
        """Send the initial progress message."""
        if self._closed:
            return None
        text = self._format_message(initial_state)
        try:
            msg = await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                disable_notification=True,
            )
            self.ctx.message_id = msg.message_id
            self.ctx.current_state = initial_state
            self.ctx.last_message_text = text
            self.ctx.last_edit_time = asyncio.get_event_loop().time()
            log.debug("progress_started chat_id=%s message_id=%s state=%s", self.chat_id, msg.message_id, initial_state.value)
            return msg
        except Exception as e:
            log.warning("progress_start_failed chat_id=%s error=%s", self.chat_id, e)
            if self.on_error:
                await self.on_error(e)
            return None

    async def update_state(self, state: ProgressState) -> None:
        """Update to a new progress state."""
        if self._closed:
            return
        async with self.ctx._lock:
            if self.ctx.current_state == state:
                return
            self.ctx.current_state = state
            self.ctx.current_tool = None
            self.ctx.tool_completed = False
            await self._schedule_edit()

    async def update_tool_start(self, tool_name: str) -> None:
        """Update to show a tool is being called."""
        if self._closed:
            return
        async with self.ctx._lock:
            self.ctx.current_state = ProgressState.CALLING_TOOL
            self.ctx.current_tool = tool_name
            self.ctx.tool_completed = False
            await self._schedule_edit()

    async def update_tool_complete(self, tool_name: str) -> None:
        """Update to show a tool has completed."""
        if self._closed:
            return
        async with self.ctx._lock:
            self.ctx.current_state = ProgressState.PROCESSING_TOOL_RESULT
            self.ctx.current_tool = tool_name
            self.ctx.tool_completed = True
            await self._schedule_edit()

    async def finish(self, final_text: str | None = None, delete_progress: bool = True) -> bool:
        """Finish progress tracking. Optionally replace with final text or delete."""
        if self._closed:
            return False
        self._closed = True

        # Cancel any pending edit
        if self.ctx.edit_task and not self.ctx.edit_task.done():
            self.ctx.edit_task.cancel()
            try:
                await self.ctx.edit_task
            except asyncio.CancelledError:
                pass

        if self.ctx.message_id is None:
            return False

        try:
            if delete_progress:
                await self.bot.delete_message(chat_id=self.chat_id, message_id=self.ctx.message_id)
                log.debug("progress_deleted chat_id=%s message_id=%s", self.chat_id, self.ctx.message_id)
            elif final_text:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.ctx.message_id,
                    text=final_text[:self.config.max_message_length],
                )
                log.debug("progress_replaced chat_id=%s message_id=%s", self.chat_id, self.ctx.message_id)
            return True
        except Exception as e:
            log.warning("progress_finish_failed chat_id=%s error=%s", self.chat_id, e)
            if self.on_error:
                await self.on_error(e)
            return False

    async def error(self, error_text: str | None = None) -> None:
        """Show error state. Does not close the renderer - allows finish() to clean up."""
        if self._closed:
            return
        if self.ctx.edit_task and not self.ctx.edit_task.done():
            self.ctx.edit_task.cancel()
            try:
                await self.ctx.edit_task
            except asyncio.CancelledError:
                pass

        text = error_text or STATE_MESSAGES[ProgressState.ERROR]
        try:
            if self.ctx.message_id:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.ctx.message_id,
                    text=text[:self.config.max_message_length],
                )
                self.ctx.last_message_text = text
                self.ctx.last_edit_time = asyncio.get_event_loop().time()
        except Exception as e:
            log.warning("progress_error_failed chat_id=%s error=%s", self.chat_id, e)

    def _format_message(self, state: ProgressState) -> str:
        """Format the message text for the current state."""
        if state == ProgressState.CALLING_TOOL and self.ctx.current_tool:
            if self.config.show_tool_details:
                return TOOL_MESSAGES.get(self.ctx.current_tool, STATE_MESSAGES[state])
        if state == ProgressState.PROCESSING_TOOL_RESULT and self.ctx.current_tool and self.ctx.tool_completed:
            if self.config.show_tool_details:
                return TOOL_COMPLETED_MESSAGES.get(self.ctx.current_tool, STATE_MESSAGES[state])
        return STATE_MESSAGES.get(state, STATE_MESSAGES[ProgressState.STARTING])

    async def _schedule_edit(self) -> None:
        """Schedule a throttled edit."""
        if self._closed or self.ctx.message_id is None:
            return

        now = asyncio.get_event_loop().time()
        time_since_last = now - self.ctx.last_edit_time

        if time_since_last >= self.config.min_edit_interval:
            # Execute immediately
            if self.ctx.edit_task and not self.ctx.edit_task.done():
                self.ctx.edit_task.cancel()
            self.ctx.edit_task = asyncio.create_task(self._do_edit())
        else:
            # Schedule for later
            self.ctx.pending_update = True
            if self.ctx.edit_task is None or self.ctx.edit_task.done():
                delay = self.config.min_edit_interval - time_since_last
                self.ctx.edit_task = asyncio.create_task(self._delayed_edit(delay))

    async def _delayed_edit(self, delay: float) -> None:
        """Execute edit after delay."""
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        await self._do_edit()

    async def _do_edit(self) -> None:
        """Perform the actual Telegram edit with error handling."""
        if self._closed or self.ctx.message_id is None:
            return

        async with self.ctx._lock:
            if not self.ctx.pending_update and self.ctx.last_edit_time > 0:
                # Check if enough time passed since last edit
                now = asyncio.get_event_loop().time()
                if now - self.ctx.last_edit_time < self.config.min_edit_interval:
                    self.ctx.pending_update = True
                    return

            text = self._format_message(self.ctx.current_state)
            if text == self.ctx.last_message_text:
                self.ctx.pending_update = False
                return

            self.ctx.pending_update = False

        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.ctx.message_id,
                text=text[:self.config.max_message_length],
            )
            self.ctx.last_message_text = text
            self.ctx.last_edit_time = asyncio.get_event_loop().time()
            log.debug("progress_updated chat_id=%s message_id=%s state=%s",
                      self.chat_id, self.ctx.message_id, self.ctx.current_state.value)
        except RetryAfter as e:
            # Telegram flood control - wait and retry once
            retry_after = min(e.retry_after, 30)
            log.warning("progress_retry_after chat_id=%s retry_after=%s", self.chat_id, retry_after)
            await asyncio.sleep(retry_after)
            try:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.ctx.message_id,
                    text=text[:self.config.max_message_length],
                )
                self.ctx.last_message_text = text
                self.ctx.last_edit_time = asyncio.get_event_loop().time()
            except Exception as e2:
                log.warning("progress_retry_failed chat_id=%s error=%s", self.chat_id, e2)
                if self.on_error:
                    await self.on_error(e2)
        except BadRequest as e:
            reason = (e.message or "").lower()
            if "message is not modified" in reason:
                # Content unchanged, just update timestamp
                self.ctx.last_edit_time = asyncio.get_event_loop().time()
                log.debug("progress_not_modified chat_id=%s", self.chat_id)
            elif "message to edit not found" in reason or "message can't be edited" in reason:
                # Message deleted or too old - stop tracking
                log.info("progress_message_unavailable chat_id=%s message_id=%s",
                         self.chat_id, self.ctx.message_id)
                self._closed = True
            else:
                log.warning("progress_edit_bad_request chat_id=%s reason=%s", self.chat_id, reason)
                if self.on_error:
                    await self.on_error(e)
        except (Forbidden, TimedOut, NetworkError) as e:
            log.warning("progress_edit_network_error chat_id=%s error=%s", self.chat_id, e)
            if self.on_error:
                await self.on_error(e)
        except Exception as e:
            log.warning("progress_edit_failed chat_id=%s error=%s", self.chat_id, e)
            if self.on_error:
                await self.on_error(e)


async def create_progress_renderer(
    bot,
    chat_id: int,
    config: ProgressConfig | None = None,
) -> TelegramProgressRenderer:
    """Factory function to create a progress renderer."""
    return TelegramProgressRenderer(bot, chat_id, config)