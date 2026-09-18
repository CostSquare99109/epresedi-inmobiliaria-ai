"""Appointments: slot generation, double-booking prevention, cancellation."""
from __future__ import annotations

import datetime as dt
import uuid as uuid_mod
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.database.models import Appointment, AppointmentStatus

log = get_logger(__name__)


class SlotUnavailable(Exception):
    pass


SLOT_HOURS = (9, 10, 11, 14, 15, 16, 17)


def _business_timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().TZ)


def _to_utc(value: dt.datetime) -> dt.datetime:
    tz = _business_timezone()
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    return value.astimezone(dt.timezone.utc)


def to_business_time(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(_business_timezone())


def _to_local(value: dt.datetime) -> dt.datetime:
    return to_business_time(value)


async def list_available_slots(session: AsyncSession, property_id, days: int = 7) -> list[dict]:
    """Next `days` days, hour slots between 9-17, skipping occupied slots."""
    prop_uuid = property_id if isinstance(property_id, uuid_mod.UUID) else uuid_mod.UUID(str(property_id))
    now = dt.datetime.now(dt.timezone.utc)
    now_local = _to_local(now)
    occupied = set(
        (
            await session.execute(
                select(Appointment.scheduled_at).where(
                    Appointment.property_id == prop_uuid,
                    Appointment.status.in_([AppointmentStatus.REQUESTED, AppointmentStatus.CONFIRMED]),
                    Appointment.scheduled_at >= now,
                )
            )
        ).scalars().all()
    )
    slots: list[dict] = []
    for day_offset in range(1, days + 1):
        day = (now_local + dt.timedelta(days=day_offset)).date()
        if day.weekday() >= 6:  # Sundays closed
            continue
        for hour in SLOT_HOURS:
            local_start = dt.datetime(
                day.year,
                day.month,
                day.day,
                hour,
                0,
                tzinfo=_business_timezone(),
            )
            start = local_start.astimezone(dt.timezone.utc)
            if start <= now + dt.timedelta(hours=2):
                continue
            if any(abs((start - occ).total_seconds()) < 60 for occ in occupied):
                continue
            slots.append({
                "datetime": start.isoformat(),
                "label": local_start.strftime("%a %d %b %H:%M"),
                "datetime_local": local_start.strftime("%Y-%m-%dT%H:%M"),
            })
    return slots


async def create_appointment(
    session: AsyncSession,
    *,
    property_id,
    lead_id: uuid_mod.UUID | None,
    scheduled_at: dt.datetime,
    notes: str = "",
) -> Appointment:
    """Atomic double-booking prevention: check + insert in one transaction."""
    prop_uuid = property_id if isinstance(property_id, uuid_mod.UUID) else uuid_mod.UUID(str(property_id))
    scheduled_at = _to_utc(scheduled_at)
    clash = (await session.execute(
        select(Appointment).where(
            Appointment.property_id == prop_uuid,
            Appointment.scheduled_at == scheduled_at,
            Appointment.status.in_([AppointmentStatus.REQUESTED, AppointmentStatus.CONFIRMED]),
        )
    )).scalar_one_or_none()
    if clash is not None:
        raise SlotUnavailable(f"El horario {scheduled_at:%a %d %b %H:%M} ya está reservado.")

    appt = Appointment(
        property_id=prop_uuid,
        lead_id=lead_id,
        scheduled_at=scheduled_at,
        status=AppointmentStatus.REQUESTED,
        notes=notes[:1000],
    )
    session.add(appt)
    await session.flush()
    log.info("appointment_created id=%s prop=%s at=%s", appt.id, prop_uuid, scheduled_at.isoformat())
    return appt


async def cancel_appointment(session: AsyncSession, appointment_id, user_scope: int | None = None) -> bool:
    appt = (await session.execute(
        select(Appointment).where(Appointment.id == appointment_id)
    )).scalar_one_or_none()
    if appt is None:
        return False
    if appt.status in (AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED):
        return False
    appt.status = AppointmentStatus.CANCELLED
    await session.flush()
    return True


async def list_appointments(session: AsyncSession, lead_id: uuid_mod.UUID | None = None, limit: int = 20):
    stmt = select(Appointment).order_by(Appointment.scheduled_at.desc()).limit(limit)
    if lead_id:
        stmt = stmt.where(Appointment.lead_id == lead_id)
    return (await session.execute(stmt)).scalars().all()


async def get_appointment(session: AsyncSession, appointment_id) -> Appointment | None:
    return (await session.execute(
        select(Appointment).where(Appointment.id == appointment_id)
    )).scalar_one_or_none()
