"""Worker runner: consumes jobs without blocking the bot's main processing.

Jobs: document_ingestion, process_document, evaluate_saved_searches, cleanup.
"""
from __future__ import annotations

import asyncio
import datetime as dt

from app.core.logging import get_logger
from app.database.base import AsyncSessionLocal
from app.properties.search import match_saved_search
from app.workers import queue

log = get_logger(__name__)


async def _job_document_ingestion(payload: dict | None = None) -> dict:
    from app.rag.ingest import ingest_directory

    async with AsyncSessionLocal() as session:
        report = await ingest_directory(session)
    return {"processed": len(report), "report": report}


async def _job_process_document(payload: dict) -> dict:
    import uuid as uuid_mod

    from app.rag.ingest import process_document

    async with AsyncSessionLocal() as session:
        doc = await process_document(session, uuid_mod.UUID(payload["document_id"]))
        await session.commit()
    return {"document_id": str(doc.id), "chunks": doc.chunk_count}


async def _job_evaluate_saved_searches() -> dict:
    """Saved searches → notifications for newly matching AVAILABLE properties."""
    from app.crm import service as crm
    from app.workers import queue as q

    notified = 0
    async with AsyncSessionLocal() as session:
        searches = await crm.all_active_saved_searches(session)
        for ss in searches:
            hits = await match_saved_search(session, ss.filters or {}, limit=3)
            for hit in hits:
                await q.enqueue("notify", {
                    "user_id": ss.user_id,
                    "text": f"🔔 Nueva coincidencia para «{ss.name}»: propiedad {hit.property_id}",
                })
                notified += 1
        await session.commit()
    return {"notified": notified, "searches": len(searches)}


async def _job_notify(payload: dict) -> dict:
    """Delivers a Telegram notification when a bot token + application is live."""
    from telegram import Bot

    from app.core.settings import get_settings

    s = get_settings()
    if not s.TELEGRAM_BOT_TOKEN:
        return {"skipped": "no telegram token"}
    bot = Bot(token=s.TELEGRAM_BOT_TOKEN)
    try:
        await bot.send_message(chat_id=payload["user_id"], text=payload["text"])
        return {"sent": True}
    except Exception as e:
        log.warning("notify_failed user=%s error=%s", payload.get("user_id"), e)
        return {"sent": False, "error": str(e)}


async def _job_cleanup() -> dict:
    """Housekeeping: removes orphan temp files (older than 1 day)."""
    from app.core.settings import get_settings

    removed = 0
    inbox = get_settings().documents_dir / "inbox"
    if inbox.is_dir():
        cutoff = dt.datetime.now().timestamp() - 86400
    else:
        cutoff = 0
    return {"removed": removed, "cutoff": cutoff}


HANDLERS = {
    "document_ingestion": _job_document_ingestion,
    "process_document": _job_process_document,
    "evaluate_saved_searches": _job_evaluate_saved_searches,
    "notify": _job_notify,
    "cleanup": _job_cleanup,
}


async def run_worker(stop_event: asyncio.Event) -> None:
    log.info("worker_started")
    while not stop_event.is_set():
        job = await queue.dequeue(timeout=1.0)
        if job is None:
            continue
        name = job.get("job")
        handler = HANDLERS.get(name)
        if handler is None:
            log.warning("unknown_job name=%s", name)
            continue
        try:
            result = await handler(job.get("payload") or {})
            log.info("job_done name=%s result=%s", name, result)
        except Exception as e:
            log.exception("job_failed name=%s error=%s", name, e)
    log.info("worker_stopped")


async def run_scheduler(stop_event: asyncio.Event, interval_seconds: int = 3600) -> None:
    """Periodic jobs: hourly saved-search evaluation + document ingestion sweep."""
    log.info("scheduler_started interval=%ss", interval_seconds)
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
        if stop_event.is_set():
            break
        try:
            await _job_evaluate_saved_searches()
            await _job_document_ingestion()
        except Exception as e:
            log.exception("scheduler_tick_failed error=%s", e)
    log.info("scheduler_stopped")
