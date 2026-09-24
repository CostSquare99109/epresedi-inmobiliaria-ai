"""Worker runner: consumes jobs without blocking the bot's main processing.

Jobs: document_ingestion, process_document, evaluate_alerts, notify, cleanup.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid as uuid_mod

from app.core.logging import get_logger
from app.database.base import AsyncSessionLocal
from app.properties.repository import get_properties
from app.properties.search import match_saved_search, SearchFilters
from app.workers import queue
from app.crm import service as crm_service
from app.database.models import Property, SavedSearch, AlertStatus, NotificationHistory

log = get_logger(__name__)


async def _job_document_ingestion(payload: dict | None = None) -> dict:
    from app.rag.ingest import ingest_directory

    async with AsyncSessionLocal() as session:
        report = await ingest_directory(session)
    return {"processed": len(report), "report": report}


async def _job_process_document(payload: dict) -> dict:
    from app.rag.ingest import process_document

    async with AsyncSessionLocal() as session:
        doc = await process_document(session, uuid_mod.UUID(payload["document_id"]))
        await session.commit()
    return {"document_id": str(doc.id), "chunks": doc.chunk_count}


def _build_property_message(property_data: dict, alert: SavedSearch) -> str:
    """Build a rich notification message for a matching property."""
    lines = [
        "🔔 *Encontré una propiedad que coincide con tu alerta*",
        "",
        f"*{property_data.get('title', 'Propiedad')}*", 
        f"📍 {property_data.get('city', '—')}",
        f"🏠 {property_data.get('property_type', '—').capitalize()} · {property_data.get('operation', '—').capitalize()}",
    ]
    
    price = property_data.get('price')
    if price is not None:
        lines.append(f"💰 ${float(price):,.0f} {property_data.get('currency', 'COP')}")
    
    bedrooms = property_data.get('bedrooms')
    if bedrooms is not None:
        lines.append(f"🛏️ {bedrooms} habitaciones")
    
    bathrooms = property_data.get('bathrooms')
    if bathrooms is not None:
        lines.append(f"🛁 {bathrooms} baños")
    
    parking = property_data.get('parking_spaces')
    if parking is not None and parking > 0:
        lines.append(f"🚗 {parking} parqueadero{'s' if parking > 1 else ''}")
    
    area = property_data.get('area_m2')
    if area is not None:
        lines.append(f"📐 {area:,.0f} m²")
    
    neighborhood = property_data.get('neighborhood')
    if neighborhood:
        lines.append(f"📍 Barrio: {neighborhood}")
    
    code = property_data.get('code')
    if code:
        lines.append(f"\nCódigo: `{code}`")
    
    return "\n".join(lines)


async def _job_notify(payload: dict) -> dict:
    """Delivers a rich Telegram notification for a property match."""
    from telegram import Bot
    from telegram.error import RetryAfter, TimedOut, NetworkError

    from app.core.settings import get_settings
    from app.database.models import Property

    notification_id = uuid_mod.UUID(payload.get("notification_id"))
    s = get_settings()
    
    if not s.TELEGRAM_BOT_TOKEN:
        return {"skipped": "no telegram token"}
    
    bot = Bot(token=s.TELEGRAM_BOT_TOKEN)
    
    async with AsyncSessionLocal() as session:
        # Load notification record
        notification = await session.get(NotificationHistory, notification_id)
        if notification is None:
            return {"sent": False, "error": "notification_not_found"}
        
        if notification.status == "sent":
            return {"sent": True, "skipped": "already_sent"}
        
        # Load property and alert
        property_obj = await session.get(Property, notification.property_id)
        alert = await session.get(SavedSearch, notification.saved_search_id)
        
        if property_obj is None or alert is None:
            await crm_service.mark_notification_failed(session, notification_id, "property_or_alert_not_found")
            await session.commit()
            return {"sent": False, "error": "property_or_alert_not_found"}
        
        # Build message
        property_data = property_obj.to_dict()
        message_text = _build_property_message(property_data, alert)
        
        # Add alert name context
        message_text = f"🔔 *Alerta: {alert.name}*\n\n{message_text}"
        
        # Try to send with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Send text message
                await bot.send_message(
                    chat_id=alert.telegram_chat_id or alert.telegram_user_id,
                    text=message_text,
                    parse_mode="Markdown",
                )
                
                # Send images if available (solo archivos reales y verificados)
                from app.api.files import image_path_or_none, list_property_images
                try:
                    filenames = list_property_images(str(property_obj.id))
                    if filenames:
                        sent_photos = 0
                        for fname in filenames[:3]:  # Limit to 3 images
                            resolved = image_path_or_none(str(property_obj.id), fname)
                            if resolved is None:
                                log.warning(
                                    "telegram_photo_send status=filtered property=%s file=%s",
                                    property_obj.id, fname,
                                )
                                continue
                            try:
                                if resolved.stat().st_size == 0:
                                    continue
                                with open(resolved, "rb") as fh:
                                    await bot.send_photo(
                                        chat_id=alert.telegram_chat_id or alert.telegram_user_id,
                                        photo=fh,
                                        disable_notification=True,
                                    )
                                sent_photos += 1
                            except Exception as e:
                                log.warning("send_photo_failed property=%s error=%s", property_obj.id, e)
                        log.info(
                            "telegram_photo_send status=%s property=%s sent=%s",
                            "success" if sent_photos else "none",
                            property_obj.id, sent_photos,
                        )
                except Exception as e:
                    log.warning("image_send_failed property=%s error=%s", property_obj.id, e)
                
                # Mark as sent
                await crm_service.mark_notification_sent(
                    session, 
                    notification_id, 
                    {"message_text": message_text, "property_code": property_obj.code}
                )
                await session.commit()
                
                log.info("notification_sent alert=%s property=%s user=%s", alert.id, property_obj.id, alert.user_id)
                return {"sent": True}
                
            except RetryAfter as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(min(e.retry_after, 30))
                    continue
                await crm_service.mark_notification_failed(session, notification_id, f"RetryAfter: {e.retry_after}s")
                await session.commit()
                return {"sent": False, "error": f"RetryAfter: {e.retry_after}s"}
                
            except (TimedOut, NetworkError) as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # exponential backoff
                    continue
                await crm_service.mark_notification_failed(session, notification_id, f"Network error: {e}")
                await session.commit()
                return {"sent": False, "error": f"Network error: {e}"}
                
            except Exception as e:
                log.warning("notify_failed alert=%s user=%s error=%s", alert.id, alert.user_id, e)
                await crm_service.mark_notification_failed(session, notification_id, str(e))
                await session.commit()
                return {"sent": False, "error": str(e)}
        
        return {"sent": False, "error": "max_retries_exceeded"}


async def _job_evaluate_alerts() -> dict:
    """Evaluate all active alerts and create notification records for new matches."""
    notified = 0
    evaluated = 0
    skipped_duplicates = 0
    
    async with AsyncSessionLocal() as session:
        alerts = await crm_service.all_active_alerts(session)
        log.info("evaluating_alerts count=%d", len(alerts))
        
        for alert in alerts:
            # Check frequency - skip if not enough time has passed
            if alert.last_checked_at:
                from datetime import UTC, datetime, timedelta
                elapsed = datetime.now(UTC) - alert.last_checked_at
                if elapsed < timedelta(hours=alert.frequency_hours):
                    skipped_duplicates += 1
                    continue
            
            evaluated += 1
            
            # Search for matching properties
            hits = await match_saved_search(session, alert.filters or {}, limit=10)
            
            for hit in hits:
                # Check if already notified (idempotency)
                exists = await crm_service.check_notification_exists(session, alert.id, hit.property_id)
                if exists:
                    continue
                
                # Create notification record atomically
                notification = await crm_service.create_notification_record(
                    session, alert.id, hit.property_id, "telegram", 
                    {"property_code": hit.property_id}  # will be enriched with property data
                )
                
                # Enqueue notification job
                await queue.enqueue("notify", {"notification_id": str(notification.id)})
                notified += 1
            
            # Update last_checked_at
            await crm_service.update_alert_last_checked(session, alert.id)
        
        await session.commit()
    
    return {
        "notified": notified, 
        "alerts_evaluated": evaluated, 
        "alerts_skipped_frequency": skipped_duplicates,
        "total_alerts": len(alerts)
    }


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
    "evaluate_alerts": _job_evaluate_alerts,
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
    """Periodic jobs: hourly alert evaluation + document ingestion sweep."""
    log.info("scheduler_started interval=%ss", interval_seconds)
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
        if stop_event.is_set():
            break
        try:
            await _job_evaluate_alerts()
            await _job_document_ingestion()
        except Exception as e:
            log.exception("scheduler_tick_failed error=%s", e)
    log.info("scheduler_stopped")