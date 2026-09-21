"""CRM: favorites, saved searches, leads, alerts. All queries scoped per user_id."""
from __future__ import annotations

import uuid as uuid_mod

from sqlalchemy import delete, select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    AlertStatus,
    Favorite,
    Lead,
    LeadStatus,
    NotificationHistory,
    Property,
    SavedSearch,
)

VALID_LEAD_STATUSES = {s.value for s in LeadStatus}
VALID_ALERT_STATUSES = {s.value for s in AlertStatus}


async def add_favorite(session: AsyncSession, user_id: int, property_id: uuid_mod.UUID) -> bool:
    exists = (await session.execute(
        select(Favorite).where(Favorite.user_id == user_id, Favorite.property_id == property_id)
    )).scalar_one_or_none()
    if exists:
        return False
    session.add(Favorite(user_id=user_id, property_id=property_id))
    await session.flush()
    return True


async def remove_favorite(session: AsyncSession, user_id: int, property_id: uuid_mod.UUID) -> bool:
    res = await session.execute(
        delete(Favorite).where(Favorite.user_id == user_id, Favorite.property_id == property_id)
    )
    return res.rowcount > 0


async def list_favorites(session: AsyncSession, user_id: int) -> list[Property]:
    stmt = (
        select(Property).join(Favorite, Favorite.property_id == Property.id)
        .where(Favorite.user_id == user_id).order_by(Favorite.created_at.desc())
    )
    return (await session.execute(stmt)).scalars().all()


async def is_favorite(session: AsyncSession, user_id: int, property_id: uuid_mod.UUID) -> bool:
    return (await session.execute(
        select(Favorite.id).where(Favorite.user_id == user_id, Favorite.property_id == property_id)
    )).scalar_one_or_none() is not None


# ------------------------------------------------------------------ saved searches / alerts
async def create_alert(
    session: AsyncSession,
    user_id: int,
    telegram_user_id: int,
    telegram_chat_id: int,
    user_name: str,
    name: str,
    filters: dict,
    frequency_hours: int = 1,
) -> SavedSearch:
    """Create a new property alert (saved search)."""
    ss = SavedSearch(
        user_id=user_id,
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_chat_id,
        user_name=user_name or "Usuario",
        name=name or "Alerta de propiedades",
        filters=filters,
        status=AlertStatus.ACTIVE,
        frequency_hours=frequency_hours,
    )
    session.add(ss)
    await session.flush()
    return ss


async def get_alert(session: AsyncSession, user_id: int, alert_id: uuid_mod.UUID) -> SavedSearch | None:
    """Get a specific alert by ID for a user."""
    return (await session.execute(
        select(SavedSearch).where(
            SavedSearch.user_id == user_id,
            SavedSearch.id == alert_id
        )
    )).scalar_one_or_none()


async def list_alerts(session: AsyncSession, user_id: int, status: str | None = None) -> list[SavedSearch]:
    """List alerts for a user, optionally filtered by status."""
    stmt = select(SavedSearch).where(SavedSearch.user_id == user_id)
    if status:
        stmt = stmt.where(SavedSearch.status == status)
    stmt = stmt.order_by(SavedSearch.created_at.desc())
    return (await session.execute(stmt)).scalars().all()


async def update_alert(
    session: AsyncSession,
    user_id: int,
    alert_id: uuid_mod.UUID,
    data: dict,
) -> SavedSearch | None:
    """Update an alert's fields."""
    alert = await get_alert(session, user_id, alert_id)
    if alert is None:
        return None

    if data.get("name") is not None:
        alert.name = str(data["name"])[:160]
    if data.get("filters") is not None and isinstance(data["filters"], dict):
        alert.filters = data["filters"]
    if data.get("frequency_hours") is not None:
        freq = int(data["frequency_hours"])
        if freq < 1:
            freq = 1
        if freq > 168:  # max 1 week
            freq = 168
        alert.frequency_hours = freq
    if data.get("status") is not None:
        new_status = data["status"]
        if new_status not in VALID_ALERT_STATUSES:
            raise ValueError(f"Estado inválido: {new_status}. Válidos: {', '.join(VALID_ALERT_STATUSES)}")
        alert.status = AlertStatus(new_status)

    await session.flush()
    return alert


async def pause_alert(session: AsyncSession, user_id: int, alert_id: uuid_mod.UUID) -> bool:
    """Pause an alert (set status to paused)."""
    res = await session.execute(
        update(SavedSearch)
        .where(SavedSearch.user_id == user_id, SavedSearch.id == alert_id)
        .values(status=AlertStatus.PAUSED)
    )
    return res.rowcount > 0


async def resume_alert(session: AsyncSession, user_id: int, alert_id: uuid_mod.UUID) -> bool:
    """Resume a paused alert (set status to active)."""
    res = await session.execute(
        update(SavedSearch)
        .where(SavedSearch.user_id == user_id, SavedSearch.id == alert_id)
        .values(status=AlertStatus.ACTIVE)
    )
    return res.rowcount > 0


async def delete_alert(session: AsyncSession, user_id: int, alert_id: uuid_mod.UUID) -> bool:
    """Delete (cancel) an alert by setting status to cancelled."""
    res = await session.execute(
        update(SavedSearch)
        .where(SavedSearch.user_id == user_id, SavedSearch.id == alert_id)
        .values(status=AlertStatus.CANCELLED)
    )
    return res.rowcount > 0


async def all_active_alerts(session: AsyncSession) -> list[SavedSearch]:
    """Get all active alerts for the scheduler to evaluate."""
    return (await session.execute(
        select(SavedSearch).where(SavedSearch.status == AlertStatus.ACTIVE)
    )).scalars().all()


# ------------------------------------------------------------------ backward compatibility (old saved_search API)
async def save_search(session: AsyncSession, user_id: int, name: str, filters: dict) -> SavedSearch:
    """Backward compatible: creates an active alert with default values."""
    return await create_alert(
        session=session,
        user_id=user_id,
        telegram_user_id=user_id,  # default to user_id for backward compat
        telegram_chat_id=user_id,
        user_name="Usuario",
        name=name,
        filters=filters,
        frequency_hours=1,
    )


async def list_saved_searches(session: AsyncSession, user_id: int) -> list[SavedSearch]:
    """Backward compatible: lists active alerts only."""
    return await list_alerts(session, user_id, status=AlertStatus.ACTIVE.value)


async def deactivate_saved_search(session: AsyncSession, user_id: int, search_id: uuid_mod.UUID) -> bool:
    """Backward compatible: cancels the alert."""
    return await delete_alert(session, user_id, search_id)


async def all_active_saved_searches(session: AsyncSession) -> list[SavedSearch]:
    """Backward compatible: returns all active alerts."""
    return await all_active_alerts(session)


async def update_alert_last_checked(session: AsyncSession, alert_id: uuid_mod.UUID) -> None:
    """Update the last_checked_at timestamp for an alert."""
    from datetime import UTC, datetime
    await session.execute(
        update(SavedSearch)
        .where(SavedSearch.id == alert_id)
        .values(last_checked_at=datetime.now(UTC))
    )


# ------------------------------------------------------------------ notification history
async def check_notification_exists(
    session: AsyncSession,
    saved_search_id: uuid_mod.UUID,
    property_id: uuid_mod.UUID,
) -> bool:
    """Check if a notification was already sent for this alert+property combo."""
    return (await session.execute(
        select(NotificationHistory.id).where(
            NotificationHistory.saved_search_id == saved_search_id,
            NotificationHistory.property_id == property_id,
        )
    )).scalar_one_or_none() is not None


async def create_notification_record(
    session: AsyncSession,
    saved_search_id: uuid_mod.UUID,
    property_id: uuid_mod.UUID,
    channel: str = "telegram",
    payload: dict | None = None,
) -> NotificationHistory:
    """Create a pending notification record."""
    nh = NotificationHistory(
        saved_search_id=saved_search_id,
        property_id=property_id,
        channel=channel,
        status="pending",
        payload=payload or {},
    )
    session.add(nh)
    await session.flush()
    return nh


async def mark_notification_sent(
    session: AsyncSession,
    notification_id: uuid_mod.UUID,
    payload: dict | None = None,
) -> bool:
    """Mark a notification as successfully sent."""
    from datetime import UTC, datetime
    values = {"status": "sent", "sent_at": datetime.now(UTC)}
    if payload is not None:
        values["payload"] = payload
    res = await session.execute(
        update(NotificationHistory)
        .where(NotificationHistory.id == notification_id)
        .values(**values)
    )
    return res.rowcount > 0


async def mark_notification_failed(
    session: AsyncSession,
    notification_id: uuid_mod.UUID,
    error: str,
) -> bool:
    """Mark a notification as failed."""
    res = await session.execute(
        update(NotificationHistory)
        .where(NotificationHistory.id == notification_id)
        .values(status="failed", error=error)
    )
    return res.rowcount > 0


async def get_notification_history(
    session: AsyncSession,
    user_id: int,
    alert_id: uuid_mod.UUID | None = None,
    limit: int = 50,
) -> list[NotificationHistory]:
    """Get notification history for a user's alerts."""
    from sqlalchemy.orm import joinedload

    stmt = (
        select(NotificationHistory)
        .join(SavedSearch, NotificationHistory.saved_search_id == SavedSearch.id)
        .where(SavedSearch.user_id == user_id)
    )
    if alert_id:
        stmt = stmt.where(NotificationHistory.saved_search_id == alert_id)
    stmt = stmt.order_by(NotificationHistory.created_at.desc()).limit(limit)
    return (await session.execute(stmt)).scalars().all()


# ------------------------------------------------------------------ leads
async def get_or_create_lead(session: AsyncSession, user_id: int) -> Lead:
    lead = (await session.execute(
        select(Lead).where(Lead.user_id == user_id).order_by(Lead.updated_at.desc())
    )).scalars().first()
    if lead is None:
        lead = Lead(user_id=user_id, status=LeadStatus.NEW)
        session.add(lead)
        await session.flush()
    return lead


async def update_lead(session: AsyncSession, lead_id: uuid_mod.UUID, data: dict) -> Lead | None:
    lead = (await session.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if lead is None:
        return None
    if data.get("name") is not None:
        lead.name = str(data["name"])[:160]
    if data.get("phone") is not None:
        lead.phone = str(data["phone"])[:40]
    if data.get("email") is not None:
        lead.email = str(data["email"])[:160]
    if data.get("budget") is not None:
        lead.budget = float(data["budget"])
    if data.get("notes") is not None:
        lead.notes = str(data["notes"])[:2000]
    if data.get("status") in VALID_LEAD_STATUSES:
        lead.status = LeadStatus(data["status"])
    if data.get("preferences") is not None and isinstance(data["preferences"], dict):
        lead.preferences = {**(lead.preferences or {}), **data["preferences"]}
    if "assigned_admin_id" in data:
        raw = data["assigned_admin_id"]
        if raw is None or raw == "":
            lead.assigned_admin_id = None
        else:
            from app.database.models import AdminUser

            admin = await session.get(AdminUser, uuid_mod.UUID(str(raw)))
            if admin is None:
                raise ValueError("Asesor no encontrado")
            lead.assigned_admin_id = admin.id
    await session.flush()
    return lead


async def set_lead_status_from_appointment(session: AsyncSession, lead_id: uuid_mod.UUID | None) -> None:
    if lead_id is None:
        return
    await session.execute(
        update(Lead).where(Lead.id == lead_id).values(status=LeadStatus.VISIT_SCHEDULED)
    )


async def get_customer_profile(session: AsyncSession, user_id: int) -> dict:
    from app.database.models import Appointment
    lead = await get_or_create_lead(session, user_id)
    appts = (await session.execute(
        select(Appointment).where(Appointment.lead_id == lead.id)
        .order_by(Appointment.scheduled_at.desc()).limit(10)
    )).scalars().all()
    return {
        "lead_id": str(lead.id),
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "status": lead.status.value,
        "budget": float(lead.budget) if lead.budget else None,
        "notes": lead.notes,
        "appointments": [
            {"id": str(a.id), "scheduled_at": a.scheduled_at.isoformat(), "status": a.status.value}
            for a in appts
        ],
    }


async def list_leads(session: AsyncSession, limit: int = 100):
    return (await session.execute(
        select(Lead).order_by(Lead.updated_at.desc()).limit(limit)
    )).scalars().all()