"""Appointments: slot generation, double-booking prevention, cancellation."""
from __future__ import annotations

import datetime as dt
import uuid as uuid_mod
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.bizconfig import (
    get_appointment_hours_for_weekday,
    get_business_timezone,
    is_business_day,
    is_within_business_hours,
)
from app.core.logging import get_logger
from app.database.models import Appointment, AppointmentStatus, Lead

log = get_logger(__name__)


class SlotUnavailable(Exception):
    pass


class OutsideBusinessHours(Exception):
    """Raised when a requested datetime is outside business hours."""
    def __init__(self, message: str, reason: str = ""):
        super().__init__(message)
        self.reason = reason


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
    return value.astimezone(dt.UTC)


async def to_business_time(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(await _business_timezone())


def _find_nearest_slots(
    slots: list[dict],
    target: dt.datetime,
    tz: ZoneInfo,
    window_hours: int = 2,
    max_alternatives: int = 3,
) -> list[dict]:
    """Find the nearest available slots to a target datetime.
    
    Prioritizes:
    1. Same day slots (closest by time)
    2. Adjacent days (previous/next business day)
    3. Within window_hours if specified
    
    Returns up to max_alternatives slots sorted by proximity.
    """
    if not slots:
        return []
    
    target_utc = target
    if target_utc.tzinfo is None:
        target_utc = target_utc.replace(tzinfo=dt.UTC)
    
    target_local = target_utc.astimezone(tz)
    target_date = target_local.date()
    
    # Calculate time difference for each slot
    scored_slots = []
    for slot in slots:
        slot_utc = dt.datetime.fromisoformat(slot["datetime"])
        diff_seconds = abs((slot_utc - target_utc).total_seconds())
        slot_local = slot_utc.astimezone(tz)
        same_day = slot_local.date() == target_date
        scored_slots.append((slot, diff_seconds, same_day, slot_utc))
    
    # Sort by: same day first, then by absolute time difference
    scored_slots.sort(key=lambda x: (not x[2], x[1]))
    
    # Filter by window_hours
    result = []
    for slot, diff_seconds, same_day, slot_utc in scored_slots:
        if diff_seconds <= window_hours * 3600:
            result.append(slot)
        if len(result) >= max_alternatives:
            break
    
    return result


async def list_available_slots(
    session: AsyncSession,
    property_id,
    days: int = 7,
    requested_datetime: dt.datetime | None = None,
    window_hours: int = 2,
) -> list[dict] | dict:
    """Next `days` days, hour slots between business hours, skipping occupied slots.
    
    If `requested_datetime` is None (default), returns a list of slots (backward compatible).
    
    If `requested_datetime` is provided, returns structured data with:
    - requested_datetime: the requested datetime (ISO)
    - exact_match: whether the exact slot is available
    - exact_slot: the matching slot if available
    - nearest_slots: closest alternative slots (prioritizing same day)
    - available_slots: all available slots (for fallback display)
    """
    prop_uuid = property_id if isinstance(property_id, uuid_mod.UUID) else uuid_mod.UUID(str(property_id))
    now = dt.datetime.now(dt.UTC)
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
        weekday = day.weekday()
        if not await is_business_day(weekday):
            continue
        slot_hours = await get_appointment_hours_for_weekday(weekday)
        for hour in slot_hours:
            local_start = dt.datetime(
                day.year,
                day.month,
                day.day,
                hour,
                0,
                tzinfo=tz,
            )
            start = local_start.astimezone(dt.UTC)
            if start <= now + dt.timedelta(hours=2):
                continue
            if any(abs((start - occ).total_seconds()) < 60 for occ in occupied):
                continue
            slots.append({
                "datetime": start.isoformat(),
                "label": local_start.strftime("%a %d %b %H:%M"),
                "datetime_local": local_start.strftime("%Y-%m-%dT%H:%M"),
            })
    
    # If no requested_datetime, return all slots (backward compatible)
    if requested_datetime is None:
        return slots
    
    # Normalize requested_datetime to UTC
    req_utc = await _to_utc(requested_datetime)
    
    # Check for exact match (within 1 minute tolerance)
    exact_slot = None
    for slot in slots:
        slot_utc = dt.datetime.fromisoformat(slot["datetime"])
        if abs((slot_utc - req_utc).total_seconds()) < 60:
            exact_slot = slot
            break
    
    # Find nearest alternatives
    tz = await _business_timezone()
    nearest = _find_nearest_slots(slots, req_utc, tz, window_hours)
    
    return {
        "requested_datetime": req_utc.isoformat(),
        "exact_match": exact_slot is not None,
        "exact_slot": exact_slot,
        "nearest_slots": nearest,
        "available_slots": slots,
    }


MIN_ADVANCE_HOURS = 2


async def validate_business_hours(scheduled_at: dt.datetime) -> None:
    """Validates that a datetime is bookable: future, minimum advance, business hours.

    Raises OutsideBusinessHours if not bookable (reason: past | too_soon | outside).
    """
    scheduled_at_utc = await _to_utc(scheduled_at)
    now_utc = dt.datetime.now(dt.UTC)
    if scheduled_at_utc <= now_utc:
        raise OutsideBusinessHours(
            "No se puede agendar en el pasado.",
            reason="past",
        )
    if scheduled_at_utc <= now_utc + dt.timedelta(hours=MIN_ADVANCE_HOURS):
        raise OutsideBusinessHours(
            f"Se requiere al menos {MIN_ADVANCE_HOURS} horas de anticipación.",
            reason="too_soon",
        )
    is_within, reason = await is_within_business_hours(scheduled_at_utc)
    if not is_within:
        raise OutsideBusinessHours(
            f"El horario solicitado está fuera del horario de atención. {reason}",
            reason=reason
        )


async def create_appointment(
    session: AsyncSession,
    *,
    property_id,
    lead_id: uuid_mod.UUID | None,
    scheduled_at: dt.datetime,
    notes: str = "",
) -> Appointment:
    """Atomic double-booking prevention: check + insert in one transaction."""
    # Validate business hours first (defense in depth)
    await validate_business_hours(scheduled_at)
    
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


async def get_appointment(session: AsyncSession, appointment_id) -> Appointment | None:
    return (await session.execute(
        select(Appointment).where(Appointment.id == appointment_id)
    )).scalar_one_or_none()


async def get_appointment_for_user(
    session: AsyncSession, appointment_id, user_scope: int | None = None
) -> Appointment | None:
    """Cita por id; con ``user_scope`` solo si pertenece a ese usuario (vía su lead).

    Los endpoints admin llaman sin scope (RBAC ya aplicado); el agente Telegram
    SIEMPRE pasa el user_id del chat: un usuario no puede tocar citas ajenas.
    """
    stmt = select(Appointment).where(Appointment.id == appointment_id)
    if user_scope is not None:
        stmt = stmt.join(Lead, Appointment.lead_id == Lead.id).where(Lead.user_id == user_scope)
    return (await session.execute(stmt)).scalar_one_or_none()


async def cancel_appointment(session: AsyncSession, appointment_id, user_scope: int | None = None) -> bool:
    appt = await get_appointment_for_user(session, appointment_id, user_scope=user_scope)
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
    session: AsyncSession, appointment_id, scheduled_at: dt.datetime,
    user_scope: int | None = None,
) -> Appointment | None:
    """Reprograma una cita activa validando choque de horario (excluyéndose a sí misma).

    Con ``user_scope`` la cita debe pertenecer a ese usuario (vía su lead).
    """
    # Validate business hours first (defense in depth)
    await validate_business_hours(scheduled_at)

    appt = await get_appointment_for_user(session, appointment_id, user_scope=user_scope)
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
