"""Appointments: slot generation, double-booking prevention, cancellation."""
from __future__ import annotations

import datetime as dt
import re
import uuid as uuid_mod

import pytest

from app.appointments import service as appts
from app.crm import service as crm
from app.memory import service as memory_service
from sqlalchemy import select

from app.database.models import Appointment, Property


async def _ensure_user(session, user_id: int) -> int:
    await memory_service.get_or_create_user(session, user_id, "appt", "APPT")
    return user_id


async def _property(session) -> Property:
    return (await session.execute(
        select(Property).where(Property.code == "PROP-0001")
    )).scalar_one()


def _next_weekday_slot() -> dt.datetime:
    """Next available business slot (tomorrow onwards, 9-17h, never Sunday)."""
    now = dt.datetime.now(dt.timezone.utc)
    for offset in range(1, 8):
        day = (now + dt.timedelta(days=offset)).date()
        if day.weekday() >= 6:
            continue
        for hour in appts.SLOT_HOURS:
            start = dt.datetime(day.year, day.month, day.day, hour, 0, tzinfo=dt.timezone.utc)
            if start > now + dt.timedelta(hours=2):
                return start
    raise AssertionError("no slot found in 7 days")


async def test_slots_exclude_occupied_and_past(session, user_id):
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)
    slot = _next_weekday_slot()
    await appts.create_appointment(session, property_id=prop.id, lead_id=lead.id, scheduled_at=slot)

    slots = await appts.list_available_slots(session, prop.id)
    labels = {s["datetime"] for s in slots}
    assert slot.isoformat() not in labels  # occupied slot hidden
    now = dt.datetime.now(dt.timezone.utc)
    for s in slots:
        assert dt.datetime.fromisoformat(s["datetime"]) > now + dt.timedelta(hours=2)


async def test_double_booking_is_rejected(session, user_id):
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)
    slot = _next_weekday_slot()
    await appts.create_appointment(session, property_id=prop.id, lead_id=lead.id, scheduled_at=slot)
    with pytest.raises(appts.SlotUnavailable):
        await appts.create_appointment(session, property_id=prop.id, lead_id=lead.id, scheduled_at=slot)


async def test_double_booking_allowed_after_cancellation(session, user_id):
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)
    slot = _next_weekday_slot()
    appt = await appts.create_appointment(session, property_id=prop.id, lead_id=lead.id, scheduled_at=slot)
    assert await appts.cancel_appointment(session, appt.id) is True
    second = await appts.create_appointment(session, property_id=prop.id, lead_id=lead.id, scheduled_at=slot)
    assert second.status.value == "REQUESTED"


async def test_cancel_appointment_idempotent_and_unknown(session, user_id):
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)
    appt = await appts.create_appointment(
        session, property_id=prop.id, lead_id=lead.id, scheduled_at=_next_weekday_slot()
    )
    assert await appts.cancel_appointment(session, appt.id) is True
    assert await appts.cancel_appointment(session, appt.id) is False  # already cancelled
    assert await appts.cancel_appointment(session, uuid_mod.uuid4()) is False  # unknown


async def test_naive_datetime_is_interpreted_as_business_time(session, user_id):
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)

    local_time = dt.datetime(2026, 9, 21, 14, 0)
    appt = await appts.create_appointment(
        session,
        property_id=prop.id,
        lead_id=lead.id,
        scheduled_at=local_time,
    )

    assert appt.scheduled_at.tzinfo is not None
    assert appt.scheduled_at == dt.datetime(
        2026, 9, 21, 19, 0, tzinfo=dt.timezone.utc
    )


async def test_slots_include_local_datetime_for_callbacks(session, user_id):
    """book_slot callbacks encode business-local naive datetimes (<=64 bytes)."""
    prop = await _property(session)
    slots = await appts.list_available_slots(session, prop.id)
    assert slots
    for s in slots:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", s["datetime_local"])
        local = appts.to_business_time(dt.datetime.fromisoformat(s["datetime"]))
        assert s["datetime_local"] == local.strftime("%Y-%m-%dT%H:%M")
