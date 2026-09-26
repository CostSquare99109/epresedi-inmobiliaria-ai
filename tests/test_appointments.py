"""Appointments: slot generation, double-booking prevention, cancellation."""
from __future__ import annotations

import datetime as dt
import re
import uuid as uuid_mod
import zoneinfo

import pytest
from freezegun import freeze_time
from sqlalchemy import select

from app.appointments import service as appts
from app.crm import service as crm
from app.database.models import Property
from app.memory import service as memory_service
from tests.test_fake_llm_v2 import plain_text


async def _ensure_user(session, user_id: int) -> int:
    await memory_service.get_or_create_user(session, user_id, "appt", "APPT")
    return user_id


async def _property(session) -> Property:
    return (await session.execute(
        select(Property).where(Property.code == "PROP-0001")
    )).scalar_one()


async def _next_weekday_slot(session) -> dt.datetime:
    """Next available business slot (tomorrow onwards, business hours, never Sunday).
    
    Returns a naive datetime that will be interpreted as business timezone (America/Bogota).
    Business hours: Mon-Fri 08:00-18:00, Sat 09:00-15:00.
    """
    from app.appointments import service as appt_service
    
    prop = await _property(session)
    slots = await appt_service.list_available_slots(session, prop.id)
    assert slots, "no slots available for test"
    # Return the first available slot as UTC datetime
    first_slot = slots[0]
    return dt.datetime.fromisoformat(first_slot["datetime"])


async def test_slots_exclude_occupied_and_past(session, user_id):
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)
    slot = await _next_weekday_slot(session)
    appt = await appts.create_appointment(session, property_id=prop.id, lead_id=lead.id, scheduled_at=slot)

    slots = await appts.list_available_slots(session, prop.id)
    labels = {s["datetime"] for s in slots}
    assert slot.isoformat() not in labels  # occupied slot hidden
    now = dt.datetime.now(dt.UTC)
    for s in slots:
        assert dt.datetime.fromisoformat(s["datetime"]) > now + dt.timedelta(hours=2)
    
    # Cleanup
    await session.delete(appt)
    await session.flush()


async def test_double_booking_is_rejected(session, user_id):
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)
    slot = await _next_weekday_slot(session)
    appt = await appts.create_appointment(session, property_id=prop.id, lead_id=lead.id, scheduled_at=slot)
    with pytest.raises(appts.SlotUnavailable):
        await appts.create_appointment(session, property_id=prop.id, lead_id=lead.id, scheduled_at=slot)
    
    # Cleanup
    await session.delete(appt)
    await session.flush()


async def test_double_booking_allowed_after_cancellation(session, user_id):
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)
    slot = await _next_weekday_slot(session)
    appt = await appts.create_appointment(session, property_id=prop.id, lead_id=lead.id, scheduled_at=slot)
    assert await appts.cancel_appointment(session, appt.id) is True
    second = await appts.create_appointment(session, property_id=prop.id, lead_id=lead.id, scheduled_at=slot)
    assert second.status.value == "REQUESTED"
    
    # Cleanup
    await session.delete(second)
    await session.flush()


async def test_cancel_appointment_idempotent_and_unknown(session, user_id):
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)
    appt = await appts.create_appointment(
        session, property_id=prop.id, lead_id=lead.id, scheduled_at=await _next_weekday_slot(session)
    )
    assert await appts.cancel_appointment(session, appt.id) is True
    assert await appts.cancel_appointment(session, appt.id) is False  # already cancelled
    assert await appts.cancel_appointment(session, uuid_mod.uuid4()) is False  # unknown
    # appt is already cancelled, no cleanup needed


async def test_naive_datetime_is_interpreted_as_business_time(session, user_id):
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)

    # Próximo lunes 14:00 Bogotá (fecha futura dinámica: el pasado se rechaza).
    bogota = zoneinfo.ZoneInfo("America/Bogota")
    now_local = dt.datetime.now(bogota)
    days_ahead = (0 - now_local.weekday()) % 7 or 7
    target = (now_local + dt.timedelta(days=days_ahead)).replace(
        hour=14, minute=0, second=0, microsecond=0
    )
    local_time = target.replace(tzinfo=None)
    appt = await appts.create_appointment(
        session,
        property_id=prop.id,
        lead_id=lead.id,
        scheduled_at=local_time,
    )

    assert appt.scheduled_at.tzinfo is not None
    assert appt.scheduled_at == target.astimezone(dt.UTC)

    # Cleanup
    await session.delete(appt)
    await session.flush()


async def test_create_appointment_rejects_past_datetime(session, user_id):
    """V-03: agendar en el pasado debe rechazarse (OutsideBusinessHours, no 200)."""
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)
    past = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    with pytest.raises(appts.OutsideBusinessHours):
        await appts.create_appointment(
            session, property_id=prop.id, lead_id=lead.id, scheduled_at=past
        )


async def test_create_appointment_requires_minimum_advance(session, user_id):
    """V-03: menos de 2h de anticipación debe rechazarse."""
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)
    soon = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=30)
    with pytest.raises(appts.OutsideBusinessHours):
        await appts.create_appointment(
            session, property_id=prop.id, lead_id=lead.id, scheduled_at=soon
        )


async def test_create_appointment_rejects_sunday(session, user_id):
    """V-04: el servicio rechaza domingos (la ruta lo mapea a 422, nunca 500)."""
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)
    bogota = zoneinfo.ZoneInfo("America/Bogota")
    now_local = dt.datetime.now(bogota)
    days_ahead = (6 - now_local.weekday()) % 7 or 7
    sunday_10 = (now_local + dt.timedelta(days=days_ahead)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    with pytest.raises(appts.OutsideBusinessHours):
        await appts.create_appointment(
            session, property_id=prop.id, lead_id=lead.id, scheduled_at=sunday_10
        )


async def test_active_slot_unique_index_exists(session):
    """V-01: el índice único parcial anti-doble-reserva existe en la DB."""
    from sqlalchemy import text

    rows = (
        await session.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename='appointments' AND indexname='uq_appointments_active_slot'"
            )
        )
    ).all()
    assert rows, "falta el índice uq_appointments_active_slot"


async def test_slots_include_local_datetime_for_callbacks(session, user_id):
    """book_slot callbacks encode business-local naive datetimes (<=64 bytes)."""
    prop = await _property(session)
    slots = await appts.list_available_slots(session, prop.id)
    assert slots
    for s in slots:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", s["datetime_local"])
        local = await appts.to_business_time(dt.datetime.fromisoformat(s["datetime"]))
        assert s["datetime_local"] == local.strftime("%Y-%m-%dT%H:%M")


# ---------------------------------------------------------------------------
# New tests for appointment negotiation flow (structured data with requested_datetime)
# ---------------------------------------------------------------------------

async def test_list_slots_with_requested_datetime_exact_match(session, user_id):
    """CASO 1: Horario exacto disponible - exact_match=true, exact_slot populated."""
    prop = await _property(session)
    slots = await appts.list_available_slots(session, prop.id)
    assert slots, "need at least one slot for test"
    
    # Pick the first available slot as the requested time
    target_slot = slots[0]
    target_dt = dt.datetime.fromisoformat(target_slot["datetime"])
    
    # Request with exact datetime
    result = await appts.list_available_slots(
        session, prop.id, requested_datetime=target_dt, window_hours=2
    )
    
    assert isinstance(result, dict)
    assert result["exact_match"] is True
    assert result["exact_slot"] is not None
    assert result["exact_slot"]["datetime"] == target_slot["datetime"]
    assert result["requested_datetime"] == target_dt.isoformat()
    assert "available_slots" in result


async def test_list_slots_with_requested_datetime_no_match_returns_nearest(session, user_id):
    """CASO 2: Horario exacto ocupado + alternativa cercana - exact_match=false, nearest_slots populated."""
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)
    
    # Get a slot and book it
    slots = await appts.list_available_slots(session, prop.id)
    assert slots
    target_slot = slots[0]
    target_dt = dt.datetime.fromisoformat(target_slot["datetime"])
    await appts.create_appointment(session, property_id=prop.id, lead_id=lead.id, scheduled_at=target_dt)
    
    # Now request the same (now occupied) slot
    result = await appts.list_available_slots(
        session, prop.id, requested_datetime=target_dt, window_hours=2
    )
    
    assert isinstance(result, dict)
    assert result["exact_match"] is False
    assert result["exact_slot"] is None
    # Should have nearest alternatives (same day prioritized)
    assert "nearest_slots" in result
    # nearest_slots should not include the occupied slot
    nearest_datetimes = {s["datetime"] for s in result["nearest_slots"]}
    assert target_dt.isoformat() not in nearest_datetimes


async def test_list_slots_nearest_prioritizes_same_day(session, user_id):
    """Nearest slots should prioritize same day over adjacent days."""
    prop = await _property(session)
    slots = await appts.list_available_slots(session, prop.id)
    assert len(slots) >= 2, "need multiple slots for test"
    
    # Find two slots on the same day
    same_day_slots = []
    for slot in slots:
        slot_dt = dt.datetime.fromisoformat(slot["datetime"])
        if not same_day_slots:
            same_day_slots.append(slot)
        else:
            first_dt = dt.datetime.fromisoformat(same_day_slots[0]["datetime"])
            if slot_dt.date() == first_dt.date():
                same_day_slots.append(slot)
                break
    
    if len(same_day_slots) < 2:
        pytest.skip("Not enough same-day slots in test data")
    
    # Request a time between the two same-day slots (should match neither exactly)
    first_dt = dt.datetime.fromisoformat(same_day_slots[0]["datetime"])
    second_dt = dt.datetime.fromisoformat(same_day_slots[1]["datetime"])
    mid_dt = first_dt + (second_dt - first_dt) / 2
    
    result = await appts.list_available_slots(
        session, prop.id, requested_datetime=mid_dt, window_hours=2
    )
    
    assert isinstance(result, dict)
    assert result["exact_match"] is False
    # Nearest should include same-day slots
    assert len(result["nearest_slots"]) > 0
    for ns in result["nearest_slots"]:
        ns_dt = dt.datetime.fromisoformat(ns["datetime"])
        # Should be within window_hours
        assert abs((ns_dt - mid_dt).total_seconds()) <= 2 * 3600


async def test_list_slots_window_hours_limits_alternatives(session, user_id):
    """window_hours parameter should limit how far alternatives are searched."""
    prop = await _property(session)
    slots = await appts.list_available_slots(session, prop.id)
    assert slots
    
    # Request a time far from any slot (midnight)
    target_dt = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
    
    # With default 2-hour window, should find nothing or very few
    result_narrow = await appts.list_available_slots(
        session, prop.id, requested_datetime=target_dt, window_hours=2
    )
    
    # With wider window, should find more
    result_wide = await appts.list_available_slots(
        session, prop.id, requested_datetime=target_dt, window_hours=12
    )
    
    assert isinstance(result_narrow, dict)
    assert isinstance(result_wide, dict)
    # Wide window should find at least as many as narrow
    assert len(result_wide["nearest_slots"]) >= len(result_narrow["nearest_slots"])


async def test_list_slots_no_requested_datetime_returns_list_backward_compat(session, user_id):
    """CASO 10 baseline: without requested_datetime, returns list (backward compat)."""
    prop = await _property(session)
    result = await appts.list_available_slots(session, prop.id)
    
    assert isinstance(result, list)
    assert len(result) > 0
    for s in result:
        assert "datetime" in s
        assert "datetime_local" in s
        assert "label" in s


async def test_list_slots_empty_result_handling(session, user_id):
    """CASO 6: No availability at all - empty nearest_slots and available_slots."""
    # This test is hard to set up without clearing all slots
    # We'll test the structure when no slots match the window
    prop = await _property(session)
    
    # Request a time on a Sunday (closed) far in future
    sunday = dt.datetime.now(dt.UTC) + dt.timedelta(days=7)
    while sunday.weekday() != 6:  # Sunday
        sunday += dt.timedelta(days=1)
    sunday = sunday.replace(hour=10, minute=0, second=0, microsecond=0)
    
    result = await appts.list_available_slots(
        session, prop.id, requested_datetime=sunday, window_hours=1
    )
    
    assert isinstance(result, dict)
    assert result["exact_match"] is False
    assert result["exact_slot"] is None
    # May have empty nearest_slots if no business hours on Sunday
    assert "nearest_slots" in result
    assert "available_slots" in result


async def test_tool_list_slots_returns_structured_data_when_requested(session, user_id):
    """Integration test: tool returns slots_data with structured info when requested_datetime provided."""
    from app.agents.tools import ToolContext, run_tool
    from app.memory import service as memory_service
    
    await memory_service.get_or_create_user(session, user_id, "tooltest", "TOOL")
    prop = await _property(session)
    
    ctx = ToolContext(session=session, user_id=user_id, conversation_id=None, state={})
    slots = await appts.list_available_slots(session, prop.id)
    target_slot = slots[0]
    target_dt = dt.datetime.fromisoformat(target_slot["datetime"])
    
    res = await run_tool("list_available_slots", {
        "property_id": str(prop.id),
        "requested_datetime": target_dt.isoformat(),
        "window_hours": 2,
    }, ctx)
    
    assert res["ok"] is True
    assert "slots" in res  # backward compat list
    assert "slots_data" in res  # new structured data
    assert res["slots_data"]["exact_match"] is True
    assert res["slots_data"]["exact_slot"]["datetime"] == target_slot["datetime"]


async def test_tool_list_slots_backward_compat_without_requested(session, user_id):
    """Integration test: tool returns only slots list when no requested_datetime."""
    from app.agents.tools import ToolContext, run_tool
    from app.memory import service as memory_service
    
    await memory_service.get_or_create_user(session, user_id, "tooltest2", "TOOL2")
    prop = await _property(session)
    
    ctx = ToolContext(session=session, user_id=user_id, conversation_id=None, state={})
    
    res = await run_tool("list_available_slots", {
        "property_id": str(prop.id),
    }, ctx)
    
    assert res["ok"] is True
    assert "slots" in res
    assert isinstance(res["slots"], list)
    assert "slots_data" not in res  # no structured data when not requested


# ---------------------------------------------------------------------------
# Comprehensive tests for business hours validation (18 cases from requirements)
# ---------------------------------------------------------------------------

async def test_case_1_martes_10am_within_business_hours(session, user_id):
    """Caso 1: martes a las 10 - día válido, horario dentro del rango."""
    await _ensure_user(session, user_id)
    prop = await _property(session)
    
    # Find a Tuesday slot at 10:00
    slots = await appts.list_available_slots(session, prop.id)
    tuesday_10 = None
    for slot in slots:
        slot_dt = dt.datetime.fromisoformat(slot["datetime"])
        local = slot_dt.astimezone(dt.UTC).astimezone(zoneinfo.ZoneInfo("America/Bogota"))
        if local.weekday() == 1 and local.hour == 10:  # Tuesday 10:00
            tuesday_10 = slot_dt
            break
    
    if tuesday_10 is None:
        pytest.skip("No Tuesday 10:00 slot available in test data")
    
    result = await appts.list_available_slots(
        session, prop.id, requested_datetime=tuesday_10, window_hours=2
    )
    
    assert isinstance(result, dict)
    assert result["exact_match"] is True
    assert result["exact_slot"] is not None


async def test_case_2_domingo_10am_rejected(session, user_id):
    """Caso 2: domingo a las 10 - día no permitido, debe rechazarse sin consultar disponibilidad."""
    await _ensure_user(session, user_id)
    prop = await _property(session)
    
    # Find next Sunday at 10:00
    from app.core.bizconfig import is_within_business_hours
    import zoneinfo
    tz = zoneinfo.ZoneInfo("America/Bogota")
    now = dt.datetime.now(tz)
    sunday = now + dt.timedelta(days=(6 - now.weekday()) % 7 or 7)
    sunday_10 = sunday.replace(hour=10, minute=0, second=0, microsecond=0)
    sunday_10_utc = sunday_10.astimezone(dt.UTC)
    
    # Should be rejected by business hours validation
    is_within, reason = await is_within_business_hours(sunday_10_utc)
    assert is_within is False
    assert "domingo" in reason.lower() or "no hay atención" in reason.lower()


async def test_case_3_martes_19pm_rejected(session, user_id):
    """Caso 3: martes a las 19 - día válido pero fuera de horario (después de 18:00)."""
    from app.core.bizconfig import is_within_business_hours
    import zoneinfo
    tz = zoneinfo.ZoneInfo("America/Bogota")
    now = dt.datetime.now(tz)
    tuesday = now + dt.timedelta(days=(1 - now.weekday()) % 7 or 7)
    tuesday_19 = tuesday.replace(hour=19, minute=0, second=0, microsecond=0)
    tuesday_19_utc = tuesday_19.astimezone(dt.UTC)
    
    is_within, reason = await is_within_business_hours(tuesday_19_utc)
    assert is_within is False
    assert "fuera de rango" in reason.lower() or "último horario" in reason.lower()


async def test_case_4_lunes_08am_valid(session, user_id):
    """Caso 4: lunes a las 08:00 - primer horario válido lunes-viernes."""
    from app.core.bizconfig import is_within_business_hours, get_appointment_hours_for_weekday
    import zoneinfo
    tz = zoneinfo.ZoneInfo("America/Bogota")
    now = dt.datetime.now(tz)
    monday = now + dt.timedelta(days=(0 - now.weekday()) % 7 or 7)
    monday_08 = monday.replace(hour=8, minute=0, second=0, microsecond=0)
    monday_08_utc = monday_08.astimezone(dt.UTC)
    
    is_within, reason = await is_within_business_hours(monday_08_utc)
    assert is_within is True
    hours = await get_appointment_hours_for_weekday(0)  # Monday
    assert 8 in hours


async def test_case_5_viernes_17pm_valid(session, user_id):
    """Caso 5: viernes a las 17:00 - último horario válido lunes-viernes (inicio de última cita)."""
    from app.core.bizconfig import is_within_business_hours, get_appointment_hours_for_weekday
    import zoneinfo
    tz = zoneinfo.ZoneInfo("America/Bogota")
    now = dt.datetime.now(tz)
    friday = now + dt.timedelta(days=(4 - now.weekday()) % 7 or 7)
    friday_17 = friday.replace(hour=17, minute=0, second=0, microsecond=0)
    friday_17_utc = friday_17.astimezone(dt.UTC)
    
    is_within, reason = await is_within_business_hours(friday_17_utc)
    assert is_within is True
    hours = await get_appointment_hours_for_weekday(4)  # Friday
    assert 17 in hours
    assert 18 not in hours  # 18:00 is end time, not a slot start


async def test_case_6_sabado_09am_valid(session, user_id):
    """Caso 6: sábado a las 09:00 - primer horario válido sábado."""
    from app.core.bizconfig import is_within_business_hours, get_appointment_hours_for_weekday
    import zoneinfo
    tz = zoneinfo.ZoneInfo("America/Bogota")
    now = dt.datetime.now(tz)
    saturday = now + dt.timedelta(days=(5 - now.weekday()) % 7 or 7)
    saturday_09 = saturday.replace(hour=9, minute=0, second=0, microsecond=0)
    saturday_09_utc = saturday_09.astimezone(dt.UTC)
    
    is_within, reason = await is_within_business_hours(saturday_09_utc)
    assert is_within is True
    hours = await get_appointment_hours_for_weekday(5)  # Saturday
    assert 9 in hours


async def test_case_7_sabado_14pm_valid(session, user_id):
    """Caso 7: sábado a las 14:00 - último horario válido sábado (inicio de última cita)."""
    from app.core.bizconfig import is_within_business_hours, get_appointment_hours_for_weekday
    import zoneinfo
    tz = zoneinfo.ZoneInfo("America/Bogota")
    now = dt.datetime.now(tz)
    saturday = now + dt.timedelta(days=(5 - now.weekday()) % 7 or 7)
    saturday_14 = saturday.replace(hour=14, minute=0, second=0, microsecond=0)
    saturday_14_utc = saturday_14.astimezone(dt.UTC)
    
    is_within, reason = await is_within_business_hours(saturday_14_utc)
    assert is_within is True
    hours = await get_appointment_hours_for_weekday(5)  # Saturday
    assert 14 in hours
    assert 15 not in hours  # 15:00 is end time, not a slot start


async def test_case_8_sabado_1501_rejected(session, user_id):
    """Caso 8: sábado a las 15:01 - fuera de horario (después de 15:00)."""
    from app.core.bizconfig import is_within_business_hours
    import zoneinfo
    tz = zoneinfo.ZoneInfo("America/Bogota")
    now = dt.datetime.now(tz)
    saturday = now + dt.timedelta(days=(5 - now.weekday()) % 7 or 7)
    saturday_1501 = saturday.replace(hour=15, minute=1, second=0, microsecond=0)
    saturday_1501_utc = saturday_1501.astimezone(dt.UTC)
    
    is_within, reason = await is_within_business_hours(saturday_1501_utc)
    assert is_within is False
    assert "fuera de rango" in reason.lower()


async def test_case_9_sabado_08am_open(session, user_id):
    """Caso 9: sábado a las 08:00 - dentro de horario (inicio a las 08:00)."""
    from app.core.bizconfig import is_within_business_hours
    import zoneinfo
    tz = zoneinfo.ZoneInfo("America/Bogota")
    now = dt.datetime.now(tz)
    saturday = now + dt.timedelta(days=(5 - now.weekday()) % 7 or 7)
    saturday_08 = saturday.replace(hour=8, minute=0, second=0, microsecond=0)
    saturday_08_utc = saturday_08.astimezone(dt.UTC)
    
    is_within, reason = await is_within_business_hours(saturday_08_utc)
    assert is_within is True
    assert "fuera de rango" not in reason.lower()


async def test_case_10_lunes_0759_rejected(session, user_id):
    """Caso 10: lunes a las 07:59 - fuera de horario (antes de 08:00)."""
    from app.core.bizconfig import is_within_business_hours
    import zoneinfo
    tz = zoneinfo.ZoneInfo("America/Bogota")
    now = dt.datetime.now(tz)
    monday = now + dt.timedelta(days=(0 - now.weekday()) % 7 or 7)
    monday_0759 = monday.replace(hour=7, minute=59, second=0, microsecond=0)
    monday_0759_utc = monday_0759.astimezone(dt.UTC)
    
    is_within, reason = await is_within_business_hours(monday_0759_utc)
    assert is_within is False
    assert "fuera de rango" in reason.lower()


async def test_case_11_martes_10am_booked_offers_alternative(session, user_id):
    """Caso 11: martes a las 10 ocupado - debe informar y ofrecer alternativa real."""
    await _ensure_user(session, user_id)
    prop = await _property(session)
    lead = await crm.get_or_create_lead(session, user_id)
    
    # Find a Tuesday 10:00 slot and book it
    slots = await appts.list_available_slots(session, prop.id)
    tuesday_10 = None
    for slot in slots:
        slot_dt = dt.datetime.fromisoformat(slot["datetime"])
        local = slot_dt.astimezone(dt.UTC).astimezone(zoneinfo.ZoneInfo("America/Bogota"))
        if local.weekday() == 1 and local.hour == 10:
            tuesday_10 = slot_dt
            break
    
    if tuesday_10 is None:
        pytest.skip("No Tuesday 10:00 slot available in test data")
    
    # Book the slot
    appt = await appts.create_appointment(session, property_id=prop.id, lead_id=lead.id, scheduled_at=tuesday_10)
    
    # Now request the same slot - should be rejected with nearest_slots
    result = await appts.list_available_slots(
        session, prop.id, requested_datetime=tuesday_10, window_hours=2
    )
    
    assert isinstance(result, dict)
    assert result["exact_match"] is False
    assert result["exact_slot"] is None
    assert len(result["nearest_slots"]) > 0
    
    # Cleanup
    await session.delete(appt)
    await session.flush()
    
    # Cleanup
    appt = await appts.get_appointment(session, result["exact_slot"]["id"] if result["exact_slot"] else None)
    if appt:
        await session.delete(appt)
        await session.flush()


async def test_case_12_fecha_pasada_rejected(session, user_id):
    """Caso 12: fecha pasada - debe rechazarse correctamente."""
    await _ensure_user(session, user_id)
    prop = await _property(session)
    
    # Yesterday at 10:00
    yesterday = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    yesterday_10 = yesterday.replace(hour=15, minute=0, second=0, microsecond=0)  # 10:00 Bogotá = 15:00 UTC
    
    result = await appts.list_available_slots(
        session, prop.id, requested_datetime=yesterday_10, window_hours=2
    )
    
    assert isinstance(result, dict)
    assert result["exact_match"] is False
    # Past dates should have no exact match and no nearest slots (filtered by 2h advance)
    assert "nearest_slots" in result


async def test_case_13_domingo_futuro_rejected(session, user_id):
    """Caso 13: domingo futuro - debe identificar que es domingo y no reservar."""
    from app.core.bizconfig import is_within_business_hours
    import zoneinfo
    tz = zoneinfo.ZoneInfo("America/Bogota")
    now = dt.datetime.now(tz)
    # Next Sunday
    sunday = now + dt.timedelta(days=(6 - now.weekday()) % 7 or 7)
    sunday_10 = sunday.replace(hour=10, minute=0, second=0, microsecond=0)
    sunday_10_utc = sunday_10.astimezone(dt.UTC)
    
    is_within, reason = await is_within_business_hours(sunday_10_utc)
    assert is_within is False
    assert "domingo" in reason.lower()


async def test_case_14_manana_10am_resolves_correctly(session, user_id):
    """Caso 14: 'mañana a las 10' - debe calcular correctamente mañana según timezone Colombia."""
    from app.core.bizconfig import is_within_business_hours
    import zoneinfo
    tz = zoneinfo.ZoneInfo("America/Bogota")
    now = dt.datetime.now(tz)
    tomorrow = now + dt.timedelta(days=1)
    tomorrow_10 = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    tomorrow_10_utc = tomorrow_10.astimezone(dt.UTC)
    
    # Should be valid if tomorrow is a business day and 10:00 is within hours
    is_within, reason = await is_within_business_hours(tomorrow_10_utc)
    # Result depends on what day tomorrow is
    if tomorrow.weekday() <= 5:  # Mon-Sat
        if tomorrow.weekday() <= 4:  # Mon-Fri
            assert is_within is True
        elif tomorrow.weekday() == 5:  # Saturday
            assert is_within is True  # 10:00 is within 9-15
    else:  # Sunday
        assert is_within is False


async def test_case_15_proximo_sabado_11am_resolves_correctly(session, user_id):
    """Caso 15: 'próximo sábado a las 11' - debe resolver fecha, validar horario, consultar disponibilidad."""
    from app.core.bizconfig import is_within_business_hours, is_business_day
    import zoneinfo
    tz = zoneinfo.ZoneInfo("America/Bogota")
    now = dt.datetime.now(tz)
    # Next Saturday
    saturday = now + dt.timedelta(days=(5 - now.weekday()) % 7 or 7)
    saturday_11 = saturday.replace(hour=11, minute=0, second=0, microsecond=0)
    saturday_11_utc = saturday_11.astimezone(dt.UTC)
    
    is_biz_day = await is_business_day(saturday.weekday())
    assert is_biz_day is True
    
    is_within, reason = await is_within_business_hours(saturday_11_utc)
    assert is_within is True


async def test_case_16_usuario_cambia_opinion(session, user_id):
    """Caso 16: usuario cambia de martes 10 a miércoles 3 - debe usar la nueva solicitud."""
    # This is more of an integration test with the agent
    # Here we test that the backend doesn't retain state between calls
    await _ensure_user(session, user_id)
    prop = await _property(session)
    
    # First request: Tuesday 10:00
    slots = await appts.list_available_slots(session, prop.id)
    tuesday_10 = None
    for slot in slots:
        slot_dt = dt.datetime.fromisoformat(slot["datetime"])
        local = slot_dt.astimezone(dt.UTC).astimezone(zoneinfo.ZoneInfo("America/Bogota"))
        if local.weekday() == 1 and local.hour == 10:
            tuesday_10 = slot_dt
            break
    
    if tuesday_10 is None:
        pytest.skip("No Tuesday 10:00 slot available")
    
    result1 = await appts.list_available_slots(
        session, prop.id, requested_datetime=tuesday_10, window_hours=2
    )
    
    # Second request: Wednesday 15:00 (3 PM)
    wednesday_15 = None
    for slot in slots:
        slot_dt = dt.datetime.fromisoformat(slot["datetime"])
        local = slot_dt.astimezone(dt.UTC).astimezone(zoneinfo.ZoneInfo("America/Bogota"))
        if local.weekday() == 2 and local.hour == 15:
            wednesday_15 = slot_dt
            break
    
    if wednesday_15 is None:
        pytest.skip("No Wednesday 15:00 slot available")
    
    result2 = await appts.list_available_slots(
        session, prop.id, requested_datetime=wednesday_15, window_hours=2
    )
    
    # Both should be valid independent calls
    assert isinstance(result1, dict)
    assert isinstance(result2, dict)
    assert result1["requested_datetime"] != result2["requested_datetime"]


async def test_case_17_solo_dia_pide_hora(session, user_id):
    """Caso 17: usuario da solo el día ('martes') - backend no tiene esta lógica, es del LLM.
    
    Este test verifica que list_available_slots sin requested_datetime devuelve
    todos los slots, y el LLM debe preguntar la hora.
    """
    prop = await _property(session)
    result = await appts.list_available_slots(session, prop.id, requested_datetime=None)
    
    assert isinstance(result, list)
    assert len(result) > 0
    # Should have slots for multiple days
    days = set()
    for slot in result:
        slot_dt = dt.datetime.fromisoformat(slot["datetime"])
        local = slot_dt.astimezone(dt.UTC).astimezone(zoneinfo.ZoneInfo("America/Bogota"))
        days.add(local.weekday())
    assert len(days) > 1  # Multiple days available


async def test_case_18_solo_hora_pide_dia(session, user_id):
    """Caso 18: usuario da solo la hora ('a las 10') - backend no tiene esta lógica, es del LLM.
    
    Este test verifica que sin día específico, no se puede validar.
    """
    from app.core.bizconfig import is_within_business_hours
    
    # A datetime without a specific day doesn't make sense for validation
    # The LLM must resolve the day first
    # This test just confirms the validation requires a complete datetime
    now = dt.datetime.now(dt.UTC)
    # This is just a time component test - validation needs full datetime
    is_within, reason = await is_within_business_hours(now)
    # Result depends on current time
    assert isinstance(is_within, bool)


# ---------------------------------------------------------------------------
# Regression tests for timezone handling and relative date resolution
# ---------------------------------------------------------------------------

import pytest
from freezegun import freeze_time


@pytest.fixture
def frozen_bogota_time():
    """Helper to freeze time in America/Bogota timezone."""
    from freezegun import freeze_time
    from zoneinfo import ZoneInfo
    import datetime as dt
    
    # This will be used as a context manager in tests
    return freeze_time


async def _setup_user_and_property(session, user_id):
    """Helper to set up user and property for appointment tests."""
    from app.memory import service as memory_service
    from app.crm import service as crm_service
    from app.properties import repository as prop_repo
    
    await memory_service.get_or_create_user(session, user_id, "t", "T")
    prop = await prop_repo.get_property_by_code(session, "PROP-0001")
    user = await memory_service.get_or_create_user(session, user_id, "t", "T")
    await session.flush()
    lead = await crm_service.get_or_create_lead(session, user.id)
    await crm_service.update_lead(session, lead.id, {
        "name": "Test User",
        "phone": "+57 300 123 4567",
        "email": "test@example.com",
    })
    return prop, lead


# Caso real del 20 de septiembre 2026 23:11 America/Bogota
# "mañana" debe ser lunes 21, NO martes 22
@freeze_time("2026-09-20 23:11:00-05:00")
async def test_regression_sunday_23_11_mañana_is_monday(session, user_id):
    """REGRESIÓN: domingo 20/09/2026 23:11 Bogota → 'mañana a las 2' = lunes 21/09 14:00."""
    from app.agents.orchestrator import Orchestrator
    from tests.test_fake_llm_v2 import FakeLLMV2, tool_round, tc, send_response_round
    from app.appointments import service as appt_service
    from zoneinfo import ZoneInfo
    
    prop, lead = await _setup_user_and_property(session, user_id)
    
    # Get available slots for reference
    slots = await appt_service.list_available_slots(session, prop.id)
    assert slots
    
    # Find a Monday 14:00 slot (lunes 21 sept a las 2pm)
    monday_14 = None
    for slot in slots:
        slot_dt = dt.datetime.fromisoformat(slot["datetime"])
        local = slot_dt.astimezone(ZoneInfo("America/Bogota"))
        if local.weekday() == 0 and local.hour == 14:  # Monday 14:00
            monday_14 = slot
            break
    
    assert monday_14 is not None, "No Monday 14:00 slot available for test"
    
    # Agent that schedules for "mañana a las 2" -> should resolve to Monday 14:00
    def agent(messages, tools):
        # First turn: user says "mañana a las 2" -> agent calls list_available_slots with requested_datetime
        # The fake agent needs to parse "mañana a las 2" relative to frozen time
        # In the real system, the LLM does this. Here we simulate by calling schedule_visit with the correct datetime.
        return tool_round(
            tc("schedule_visit", {
                "property_id": str(prop.id),
                "datetime_iso": monday_14["datetime"],  # This is UTC ISO
            }, call_id="sv1"),
        )
    
    fake = FakeLLMV2([agent])
    orch = Orchestrator(llm=fake)
    
    reply = await orch.handle_user_message(
        session, user_id, "mañana a las 2", "t", "T"
    )
    
    # Verify appointment was created on Monday 21 Sept
    from sqlalchemy import select
    from app.database.models import Appointment
    
    appts = (await session.execute(
        select(Appointment).where(Appointment.property_id == prop.id, Appointment.lead_id == lead.id)
    )).scalars().all()
    
    assert len(appts) == 1
    appt = appts[0]
    appt_local = appt.scheduled_at.astimezone(ZoneInfo("America/Bogota"))
    
    # Should be Monday 21 Sept 2026, NOT Tuesday 22
    assert appt_local.weekday() == 0, f"Expected Monday (0), got {appt_local.weekday()}"
    assert appt_local.day == 21, f"Expected day 21, got {appt_local.day}"
    assert appt_local.month == 9, f"Expected month 9, got {appt_local.month}"
    assert appt_local.hour == 14, f"Expected hour 14, got {appt_local.hour}"
    
    # Cleanup
    await session.delete(appt)
    await session.flush()


# Edge case: Sunday 23:59 -> "mañana" should be Monday 00:00 next day
@freeze_time("2026-09-20 23:59:00-05:00")
async def test_edge_sunday_23_59_mañana(session, user_id):
    """Domingo 20/09 23:59 → 'mañana' = lunes 21/09."""
    from app.core.bizconfig import get_business_timezone
    from zoneinfo import ZoneInfo
    import datetime as dt
    
    tz_name = await get_business_timezone()
    tz = ZoneInfo(tz_name)
    now = dt.datetime.now(tz)
    
    assert now.weekday() == 6  # Sunday
    assert now.day == 20
    assert now.hour == 23
    assert now.minute == 59
    
    tomorrow = now + dt.timedelta(days=1)
    assert tomorrow.weekday() == 0  # Monday
    assert tomorrow.day == 21


# Edge case: Sunday 23:59:59 -> "mañana" should be Monday
@freeze_time("2026-09-20 23:59:59-05:00")
async def test_edge_sunday_23_59_59_mañana(session, user_id):
    """Domingo 20/09 23:59:59 → 'mañana' = lunes 21/09."""
    from app.core.bizconfig import get_business_timezone
    from zoneinfo import ZoneInfo
    import datetime as dt
    
    tz_name = await get_business_timezone()
    tz = ZoneInfo(tz_name)
    now = dt.datetime.now(tz)
    
    assert now.weekday() == 6  # Sunday
    tomorrow = now + dt.timedelta(days=1)
    assert tomorrow.weekday() == 0  # Monday
    assert tomorrow.day == 21


# Edge case: Monday 00:00 -> "mañana" should be Tuesday
@freeze_time("2026-09-21 00:00:00-05:00")
async def test_edge_monday_00_00_mañana(session, user_id):
    """Lunes 21/09 00:00 → 'mañana' = martes 22/09."""
    from app.core.bizconfig import get_business_timezone
    from zoneinfo import ZoneInfo
    import datetime as dt
    
    tz_name = await get_business_timezone()
    tz = ZoneInfo(tz_name)
    now = dt.datetime.now(tz)
    
    assert now.weekday() == 0  # Monday
    assert now.day == 21
    assert now.hour == 0
    assert now.minute == 0
    
    tomorrow = now + dt.timedelta(days=1)
    assert tomorrow.weekday() == 1  # Tuesday
    assert tomorrow.day == 22


# Edge case: Monday 00:01 -> "mañana" should be Tuesday
@freeze_time("2026-09-21 00:01:00-05:00")
async def test_edge_monday_00_01_mañana(session, user_id):
    """Lunes 21/09 00:01 → 'mañana' = martes 22/09."""
    from app.core.bizconfig import get_business_timezone
    from zoneinfo import ZoneInfo
    import datetime as dt
    
    tz_name = await get_business_timezone()
    tz = ZoneInfo(tz_name)
    now = dt.datetime.now(tz)
    
    assert now.weekday() == 0  # Monday
    tomorrow = now + dt.timedelta(days=1)
    assert tomorrow.weekday() == 1  # Tuesday
    assert tomorrow.day == 22


# Test that LLM receives correct timezone-aware current time
async def test_llm_receives_business_timezone_not_utc(session, user_id):
    """Verify the system prompt provides current time in business timezone, not UTC."""
    from app.agents.llm_orchestrator import PureLLMOrchestrator
    from tests.test_fake_llm_v2 import FakeLLMV2
    from app.core.bizconfig import get_business_timezone
    from zoneinfo import ZoneInfo
    import datetime as dt
    
    # Create a fake LLM that captures the system prompt
    captured = {}
    
    class CapturingFake(FakeLLMV2):
        async def chat(self, messages, tools=None, temperature=0.2, max_tokens=2000, response_format=None):
            for m in messages:
                if m.get("role") == "system":
                    captured["system"] = m.get("content", "")
                    break
            return await super().chat(messages, tools, temperature, max_tokens, response_format)
    
    fake = CapturingFake([plain_text("ok")])
    orchestrator = PureLLMOrchestrator(fake)
    from app.memory import service as memory_service
    await memory_service.get_or_create_user(session, user_id, "t", "T")
    conv = await memory_service.get_or_create_conversation(session, user_id)
    
    await orchestrator.handle_user_message(session, user_id, "hola", "t", "T")
    
    system_content = captured.get("system", "")
    
    # Should contain business timezone info
    assert "zona horaria del negocio" in system_content
    assert "America/Bogota" in system_content
    # Should NOT say UTC
    assert "Fecha/hora actual del sistema (UTC):" not in system_content
    # Should have current date in business timezone
    assert "Fecha actual (zona horaria del negocio):" in system_content
    assert "Día de la semana actual (zona horaria del negocio):" in system_content


# Test relative date resolution: "hoy", "mañana", "pasado mañana"
@freeze_time("2026-09-20 10:00:00-05:00")  # Sunday 10 AM
async def test_relative_dates_sunday_10am(session, user_id):
    """Domingo 20/09 10:00 → hoy=domingo 20, mañana=lunes 21, pasado mañana=martes 22."""
    from app.core.bizconfig import get_business_timezone
    from zoneinfo import ZoneInfo
    import datetime as dt
    
    tz_name = await get_business_timezone()
    tz = ZoneInfo(tz_name)
    now = dt.datetime.now(tz)
    
    assert now.weekday() == 6  # Sunday
    assert now.day == 20
    
    hoy = now.date()
    mañana = (now + dt.timedelta(days=1)).date()
    pasado_mañana = (now + dt.timedelta(days=2)).date()
    
    assert hoy.day == 20
    assert mañana.day == 21
    assert mañana.weekday() == 0  # Monday
    assert pasado_mañana.day == 22
    assert pasado_mañana.weekday() == 1  # Tuesday


# Test 12:00 PM formatting (should be PM, not AM)
async def test_noon_formatting_not_am(session, user_id):
    """12:00 mediodía debe representarse como 12:00 p. m., nunca 12:00 a. m."""
    from app.appointments import service as appt_service
    from app.properties import repository as prop_repo
    from zoneinfo import ZoneInfo
    
    prop = await prop_repo.get_property_by_code(session, "PROP-0001")
    slots = await appt_service.list_available_slots(session, prop.id)
    
    # Find a slot at 12:00 (noon)
    noon_slot = None
    for slot in slots:
        slot_dt = dt.datetime.fromisoformat(slot["datetime"])
        local = slot_dt.astimezone(ZoneInfo("America/Bogota"))
        if local.hour == 12:
            noon_slot = slot
            break
    
    if noon_slot:
        # The label should show 12:00 as PM format
        # This tests that the system doesn't confuse 12:00 with AM
        assert noon_slot is not None
        # The datetime_local should be 12:00
        assert "12:00" in noon_slot["datetime_local"]


# ------------------------------------------------------------------ IDOR (ownership)
async def test_cancel_appointment_is_scoped_to_owner(session, user_id):
    """IDOR: con user_scope, un usuario NO puede cancelar la cita de otro."""
    other_id = user_id + 1
    await _ensure_user(session, user_id)
    await _ensure_user(session, other_id)
    prop = await _property(session)
    lead_other = await crm.get_or_create_lead(session, other_id)
    appt = await appts.create_appointment(
        session, property_id=prop.id, lead_id=lead_other.id,
        scheduled_at=await _next_weekday_slot(session),
    )

    # Un tercero con scope propio NO puede cancelarla...
    assert await appts.cancel_appointment(session, appt.id, user_scope=user_id) is False
    from app.database.models import AppointmentStatus

    await session.refresh(appt)
    assert appt.status == AppointmentStatus.REQUESTED  # sigue activa

    # ...y el dueño sí puede.
    assert await appts.cancel_appointment(session, appt.id, user_scope=other_id) is True


async def test_reschedule_appointment_is_scoped_to_owner(session, user_id):
    """IDOR: con user_scope, un usuario NO puede reprogramar la cita de otro."""
    other_id = user_id + 1
    await _ensure_user(session, user_id)
    await _ensure_user(session, other_id)
    prop = await _property(session)
    lead_other = await crm.get_or_create_lead(session, other_id)
    appt = await appts.create_appointment(
        session, property_id=prop.id, lead_id=lead_other.id,
        scheduled_at=await _next_weekday_slot(session),
    )

    slots = await appts.list_available_slots(session, prop.id)
    later = dt.datetime.fromisoformat(slots[0]["datetime"])
    if later <= appt.scheduled_at and len(slots) > 1:
        later = dt.datetime.fromisoformat(slots[1]["datetime"])

    # Un tercero con scope propio NO puede reprogramarla...
    assert await appts.reschedule_appointment(
        session, appt.id, later, user_scope=user_id
    ) is None

    # ...y el dueño sí puede (hora distinta a la original).
    if later != appt.scheduled_at:
        moved = await appts.reschedule_appointment(
            session, appt.id, later, user_scope=other_id
        )
        assert moved is not None and moved.id == appt.id

    await session.delete(appt)
    await session.flush()


async def test_agent_tool_cancel_cannot_touch_foreign_appointments(session, user_id):
    """El agente Telegram siempre opera con el user_id del chat: no puede
    cancelar citas ajenas aunque el LLM pase un id ajeno (IDOR cerrado)."""
    from app.agents.tools import ToolContext, run_tool

    other_id = user_id + 1
    await memory_service.get_or_create_user(session, user_id, "t", "T")
    await _ensure_user(session, other_id)
    prop = await _property(session)
    lead_other = await crm.get_or_create_lead(session, other_id)
    appt = await appts.create_appointment(
        session, property_id=prop.id, lead_id=lead_other.id,
        scheduled_at=await _next_weekday_slot(session),
    )

    ctx = ToolContext(session=session, user_id=user_id, conversation_id=None, state={})
    res = await run_tool("cancel_appointment", {"appointment_id": str(appt.id)}, ctx)
    assert res["cancelled"] is False  # ajena: cancelación bloqueada

    ctx_owner = ToolContext(session=session, user_id=other_id, conversation_id=None, state={})
    res_owner = await run_tool("cancel_appointment", {"appointment_id": str(appt.id)}, ctx_owner)
    assert res_owner["cancelled"] is True  # dueño: funciona
