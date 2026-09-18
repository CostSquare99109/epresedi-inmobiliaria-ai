"""CRM: favorites, saved searches, leads. All queries scoped per user_id."""
from __future__ import annotations

import uuid as uuid_mod

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Favorite, Lead, LeadStatus, Property, SavedSearch

VALID_LEAD_STATUSES = {s.value for s in LeadStatus}


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


async def save_search(session: AsyncSession, user_id: int, name: str, filters: dict) -> SavedSearch:
    ss = SavedSearch(user_id=user_id, name=name or "Búsqueda guardada", filters=filters, active=True)
    session.add(ss)
    await session.flush()
    return ss


async def list_saved_searches(session: AsyncSession, user_id: int) -> list[SavedSearch]:
    return (await session.execute(
        select(SavedSearch).where(SavedSearch.user_id == user_id, SavedSearch.active.is_(True))
        .order_by(SavedSearch.created_at.desc())
    )).scalars().all()


async def deactivate_saved_search(session: AsyncSession, user_id: int, search_id: uuid_mod.UUID) -> bool:
    res = await session.execute(
        update(SavedSearch).where(SavedSearch.user_id == user_id, SavedSearch.id == search_id)
        .values(active=False)
    )
    return res.rowcount > 0


async def all_active_saved_searches(session: AsyncSession) -> list[SavedSearch]:
    return (await session.execute(
        select(SavedSearch).where(SavedSearch.active.is_(True))
    )).scalars().all()


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
    from app.database.models import Appointment, AppointmentStatus
    lead = await get_or_create_lead(session, user_id)
    appts = (await session.execute(
        select(Appointment).where(Appointment.lead_id == lead.id)
        .order_by(Appointment.scheduled_at.desc()).limit(10)
    )).scalars().all()
    return {
        "lead_id": str(lead.id),
        "name": lead.name,
        "phone": lead.phone,
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
