"""Appointments: slot generation, double-booking prevention, cancellation."""
from __future__ import annotations

import datetime as dt
import uuid as uuid_mod
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.bizconfig import get_appointment_hours, get_business_timezone
from app.core.logging import get_logger
from app.database.models import Appointment, AppointmentStatus

log = get_logger(__name__)


class SlotUnavailable(Exception):
    pass


async def _business_timezone() -> ZoneInfo:
    tz_name = await get_business_timezone()
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):  # pragma: no cover - config inválida
        log.warning("invalid_business_timezone fallback=UTC tz=%s", tz_name)
        return ZoneInfo("UTC")


async def _to_utc(value: dt.datetime) -> dt.datetime:
    tz = await _business_timezone()
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    return value.astimezone(dt.timezone.utc)


async def to_business_time(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(await _business_timezone())


async def list_available_slots(session: AsyncSession, property_id, days: int = 7) -> list[dict]:
    """Next `days` days, hour slots between business hours, skipping occupied slots."""
    prop_uuid = property_id if isinstance(property_id, uuid_mod.UUID) else uuid_mod.UUID(str(property_id))
    slot_hours = await get_appointment_hours()
    now = dt.datetime.now(dt.timezone.utc)
    now_local = await to_business_time(now)
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
    tz = await _business_timezone()
    for day_offset in range(1, days + 1):
        day = (now_local + dt.timedelta(days=day_offset)).date()
        if day.weekday() >= 6:  # Sundays closed
            continue
        for hour in slot_hours:
            local_start = dt.datetime(
                day.year,
                day.month,
                day.day,
                hour,
                0,
                tzinfo=tz,
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
    scheduled_at = await _to_utc(scheduled_at)
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


# Transiciones válidas de estado de cita (REQUESTED → CONFIRMED → COMPLETED;
# cancelación desde REQUESTED o CONFIRMED). CANCELLED/COMPLETED son terminales.
APPOINTMENT_TRANSITIONS: dict[AppointmentStatus, set[AppointmentStatus]] = {
    AppointmentStatus.REQUESTED: {AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED},
    AppointmentStatus.CONFIRMED: {AppointmentStatus.COMPLETED, AppointmentStatus.CANCELLED},
    AppointmentStatus.CANCELLED: set(),
    AppointmentStatus.COMPLETED: set(),
}


async def reschedule_appointment(
    session: AsyncSession, appointment_id, scheduled_at: dt.datetime
) -> Appointment | None:
    """Reprograma una cita activa validando choque de horario (excluyéndose a sí misma)."""
    appt = (await session.execute(
        select(Appointment).where(Appointment.id == appointment_id)
    )).scalar_one_or_none()
    if appt is None:
        return None
    if appt.status in (AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED):
        raise SlotUnavailable("La cita ya está cancelada o realizada; no se puede reprogramar.")
    scheduled_at = await _to_utc(scheduled_at)
    clash = (await session.execute(
        select(Appointment).where(
            Appointment.property_id == appt.property_id,
            Appointment.scheduled_at == scheduled_at,
            Appointment.status.in_([AppointmentStatus.REQUESTED, AppointmentStatus.CONFIRMED]),
            Appointment.id != appt.id,
        )
    )).scalar_one_or_none()
    if clash is not None:
        raise SlotUnavailable(f"El horario {scheduled_at:%a %d %b %H:%M} ya está reservado.")
    appt.scheduled_at = scheduled_at
    await session.flush()
    log.info("appointment_rescheduled id=%s at=%s", appt.id, scheduled_at.isoformat())
    return appt


async def list_appointments(session: AsyncSession, lead_id: uuid_mod.UUID | None = None, limit: int = 20):
    stmt = select(Appointment).order_by(Appointment.scheduled_at.desc()).limit(limit)
    if lead_id:
        stmt = stmt.where(Appointment.lead_id == lead_id)
    return (await session.execute(stmt)).scalars().all()


async def get_appointment(session: AsyncSession, appointment_id) -> Appointment | None:
    return (await session.execute(
        select(Appointment).where(Appointment.id == appointment_id)
    )).scalar_one_or_none()
