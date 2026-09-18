"""Telegram handlers (python-telegram-bot). Presentation layer only:
no SQL here — everything goes through the orchestrator and services."""
from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from app.agents.orchestrator import AgentReply, Orchestrator
from app.appointments.service import to_business_time
from app.bot.keyboards import build_keyboard, parse_callback
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.database.base import AsyncSessionLocal
from app.security.ratelimit import RateLimited, check_rate_limit

log = get_logger(__name__)

# Telegram BadRequest reasons that a degraded retry can actually fix.
_MARKUP_ERROR_HINTS = ("button_data_invalid",)
_PARSE_ERROR_HINTS = ("can't parse entities", "unsupported start tag")

_ORCHESTRATOR_HOLDER: dict = {}


def register_orchestrator(orchestrator: Orchestrator) -> None:
    _ORCHESTRATOR_HOLDER["orchestrator"] = orchestrator


def get_orchestrator() -> Orchestrator:
    return _ORCHESTRATOR_HOLDER["orchestrator"]


WELCOME = (
    "👋 ¡Hola! Soy tu asesor inmobiliario inteligente.\n\n"
    "Cuéntame qué buscas con palabras naturales, por ejemplo:\n"
    "«Busco una casa en Carepa de máximo 300 millones, tres habitaciones, garaje y cerca del centro»\n\n"
    "También puedo mostrarte fichas, fotos, comparar opciones, consultar documentos "
    "(reglamentos) y agendar visitas.\n\nEscribe /help para ver los comandos."
)

HELP = (
    "Comandos:\n"
    "• /buscar — iniciar una búsqueda\n"
    "• /propiedades — ver el inventario disponible\n"
    "• /favoritos — tus propiedades guardadas\n"
    "• /busquedas — tus alertas guardadas\n"
    "• /citas — tus visitas agendadas\n"
    "• /perfil — tu perfil y preferencias\n\n"
    "El lenguaje natural es el mecanismo principal: solo escribe lo que necesitas."
)


def _user_ids(update: Update) -> tuple[int, str, str]:
    user = update.effective_user
    return user.id, (user.username or ""), (user.first_name or "")


def _describe_markup(markup) -> str:
    """Diagnostic summary of a reply_markup (button text, callback, length)."""
    if markup is None:
        return "none"
    try:
        parts = []
        for row in markup.inline_keyboard:
            for b in row:
                size = len((b.callback_data or "").encode("utf-8", errors="replace"))
                parts.append(f"{b.text!r}->{(b.callback_data or '')!r}({size}B)")
        return ";".join(parts)
    except Exception:
        return "unavailable"


async def _send_text(
    message, text: str, *, parse_mode: str | None = None, reply_markup=None,
) -> None:
    """Sends text with graceful degradation; no recovery loops.

    - Markup/callback errors (BUTTON_DATA_INVALID): log and retry WITHOUT the
      keyboard (the same keyboard is never re-sent).
    - Parse-entity errors: log and retry WITHOUT parse_mode.
    - Any other error is re-raised: never hidden behind a fallback.
    """
    try:
        await message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except BadRequest as e:
        reason = (e.message or "").lower()
        if reply_markup is not None and any(h in reason for h in _MARKUP_ERROR_HINTS):
            log.warning(
                "reply_markup_rejected reason=%r keyboard=%s -> retrying without markup",
                reason, _describe_markup(reply_markup),
            )
            await _send_text(message, text, parse_mode=parse_mode)
            return
        if parse_mode is not None and any(h in reason for h in _PARSE_ERROR_HINTS):
            log.warning(
                "reply_parse_rejected reason=%r parse_mode=%s -> retrying as plain text",
                reason, parse_mode,
            )
            await _send_text(message, text, reply_markup=reply_markup)
            return
        raise


async def _reply_with(update: Update, reply: AgentReply) -> None:
    keyboard = build_keyboard(reply.actions)
    message = update.effective_message
    if reply.images:
        from telegram.helpers import escape_markdown

        try:
            await _send_text(
                message, escape_markdown(reply.text, version=2), parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception:
            log.warning("reply_text_failed with_images -> retrying as plain text")
            try:
                await message.reply_text(reply.text)
            except Exception:
                log.exception("reply_text_failed with_images plain")
        for path in reply.images[:10]:
            try:
                with open(path, "rb") as fh:
                    await update.effective_message.reply_photo(photo=fh)
            except Exception as e:
                log.warning("send_photo_failed path=%s error=%s", path, e)
        return
    log.debug("reply_keyboard buttons=%d", 0 if keyboard is None else len(keyboard.inline_keyboard))
    await _send_text(message, reply.text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def _run_orchestrator(update: Update, text: str) -> None:
    settings = get_settings()
    user_id, username, first_name = _user_ids(update)
    try:
        await check_rate_limit(f"tg:{user_id}", settings.RATE_LIMIT_PER_MINUTE)
    except RateLimited:
        await update.effective_message.reply_text(
            "⏳ Demasiados mensajes seguidos. Espera unos segundos e inténtalo de nuevo."
        )
        return
    async with AsyncSessionLocal() as session:
        reply = await get_orchestrator().handle_user_message(session, user_id, text, username, first_name)
    await _reply_with(update, reply)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(WELCOME)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP)


async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "🔍 Cuéntame qué buscas: tipo, ciudad, presupuesto, habitaciones…\n"
        "Ej: «apartamento en Carepa de 2 habitaciones hasta 150 millones»"
    )

async def cmd_propiedades(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id, username, first_name = _user_ids(update)
    async with AsyncSessionLocal() as session:
        reply = await get_orchestrator().handle_user_message(
            session, user_id, "muéstrame las propiedades disponibles", username, first_name
        )
    await _reply_with(update, reply)


async def cmd_favoritos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id, _, _ = _user_ids(update)
    from app.crm import service as crm
    from app.memory import service as memory_service

    async with AsyncSessionLocal() as session:
        user = await memory_service.get_or_create_user(session, user_id)
        props = await crm.list_favorites(session, user.id)
    if not props:
        await update.effective_message.reply_text(
            "Aún no tienes favoritos. Toca ⭐ Guardar en una ficha o dime «guarda esta»."
        )
        return
    lines = ["Tus favoritos:"]
    for i, p in enumerate(props, start=1):
        lines.append(f"{i}. {p.title} — ${float(p.price):,.0f} {p.currency} · {p.code} ({p.status.value})")
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_busquedas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id, _, _ = _user_ids(update)
    async with AsyncSessionLocal() as session:
        reply = await get_orchestrator().handle_action(session, user_id, "list_saved", None)
    await update.effective_message.reply_text(reply.text)


async def cmd_citas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id, _, _ = _user_ids(update)
    from app.appointments import service as appts
    from app.crm import service as crm
    from app.memory import service as memory_service

    async with AsyncSessionLocal() as session:
        user = await memory_service.get_or_create_user(session, user_id)
        lead = await crm.get_or_create_lead(session, user.id)
        items = await appts.list_appointments(session, lead.id, limit=10)
    if not items:
        await update.effective_message.reply_text("No tienes citas. Pide «agendar visita» en una ficha.")
        return
    lines = ["Tus citas:"]
    for a in items:
        local_time = await to_business_time(a.scheduled_at)
        lines.append(f"• {local_time:%a %d %b %H:%M} — {a.status.value}")
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id, _, _ = _user_ids(update)
    from app.crm import service as crm
    from app.memory import service as memory_service

    async with AsyncSessionLocal() as session:
        user = await memory_service.get_or_create_user(session, user_id)
        prefs = await memory_service.get_preferences(session, user.id)
        lead = await crm.get_or_create_lead(session, user.id)
    lines = ["Tu perfil:"]
    if prefs:
        lines += [
            f"• Ciudad: {prefs.city or '—'}", f"• Tipo: {prefs.property_type or '—'}",
            f"• Operación: {prefs.operation or '—'}",
            f"• Presupuesto: {prefs.min_budget or '—'} – {prefs.max_budget or '—'}",
            f"• Habitaciones: {prefs.bedrooms or '—'}",
        ]
    lines.append(f"• Lead: {lead.status.value}")
    await update.effective_message.reply_text("\n".join(lines))


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    await _run_orchestrator(update, update.message.text)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("telegram_handler_error update=%s", update)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action, payload = parse_callback(query.data or "")
    user_id, _, _ = _user_ids(update)
    async with AsyncSessionLocal() as session:
        reply = await get_orchestrator().handle_action(session, user_id, action, payload)
    if reply.images:
        for path in reply.images[:10]:
            try:
                with open(path, "rb") as fh:
                    await query.message.reply_photo(photo=fh)
            except Exception as e:
                log.warning("send_photo_failed path=%s error=%s", path, e)
        if reply.text:
            await query.message.reply_text(reply.text)
        return
    keyboard = build_keyboard(reply.actions)
    log.debug("reply_keyboard buttons=%d", 0 if keyboard is None else len(keyboard.inline_keyboard))
    await _send_text(query.message, reply.text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


def build_application():
    """Builds the PTB Application (no run_polling: main.py controls the loop)."""
    from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters

    settings = get_settings()
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN no configurado en .env")
    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("buscar", cmd_buscar))
    app.add_handler(CommandHandler("propiedades", cmd_propiedades))
    app.add_handler(CommandHandler("favoritos", cmd_favoritos))
    app.add_handler(CommandHandler("busquedas", cmd_busquedas))
    app.add_handler(CommandHandler("citas", cmd_citas))
    app.add_handler(CommandHandler("perfil", cmd_perfil))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app

