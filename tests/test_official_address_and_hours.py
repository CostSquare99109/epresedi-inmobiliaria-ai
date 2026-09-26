"""Tests for official address and business hours configuration."""
from __future__ import annotations

import datetime as dt
import zoneinfo

import httpx
import pytest
from sqlalchemy import select

from app.api import routes
from app.core.bizconfig import (
    get_appointment_hours_by_weekday,
    get_appointment_hours_for_weekday,
    get_business_timezone,
    is_business_day,
    is_within_business_hours,
)
from app.database.models import Branch


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=routes.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestOfficialAddress:
    """Tests for the official office address."""

    async def test_branch_has_correct_street(self, session):
        """La sede debe tener la calle correcta: Calle 70."""
        branch = (await session.execute(
            select(Branch).where(Branch.name == "Sede Principal")
        )).scalar_one_or_none()
        
        assert branch is not None, "Debe existir la sede 'Sede Principal'"
        assert branch.street == "Calle 70", f"Calle esperada 'Calle 70', obtenida '{branch.street}'"

    async def test_branch_has_correct_street_number(self, session):
        """La sede debe tener el número correcto: # 68A - 11."""
        branch = (await session.execute(
            select(Branch).where(Branch.name == "Sede Principal")
        )).scalar_one_or_none()
        
        assert branch is not None
        assert branch.street_number == "# 68A - 11", f"Número esperado '# 68A - 11', obtenido '{branch.street_number}'"

    async def test_branch_has_correct_neighborhood(self, session):
        """La sede debe estar en el barrio Calazans."""
        branch = (await session.execute(
            select(Branch).where(Branch.name == "Sede Principal")
        )).scalar_one_or_none()
        
        assert branch is not None
        assert branch.neighborhood == "Calazans", f"Barrio esperado 'Calazans', obtenido '{branch.neighborhood}'"

    async def test_branch_has_correct_floor_in_descriptive_location(self, session):
        """La ubicación descriptiva debe mencionar '1er piso'."""
        branch = (await session.execute(
            select(Branch).where(Branch.name == "Sede Principal")
        )).scalar_one_or_none()
        
        assert branch is not None
        assert "1er piso" in branch.descriptive_location, f"Descriptive location debe contener '1er piso', obtuvo '{branch.descriptive_location}'"

    async def test_branch_has_correct_city(self, session):
        """La sede debe estar en Carepa."""
        branch = (await session.execute(
            select(Branch).where(Branch.name == "Sede Principal")
        )).scalar_one_or_none()
        
        assert branch is not None
        assert branch.city == "Carepa", f"Ciudad esperada 'Carepa', obtenida '{branch.city}'"

    async def test_branch_has_reference_in_descriptive_location(self, session):
        """La ubicación descriptiva debe mencionar la referencia 'Diagonal a Tiendas Ara'."""
        branch = (await session.execute(
            select(Branch).where(Branch.name == "Sede Principal")
        )).scalar_one_or_none()
        
        assert branch is not None
        assert "Diagonal a Tiendas Ara" in branch.descriptive_location, f"Descriptive location debe contener 'Diagonal a Tiendas Ara', obtuvo '{branch.descriptive_location}'"

    async def test_full_address_format(self, session):
        """La dirección completa debe tener el formato correcto."""
        branch = (await session.execute(
            select(Branch).where(Branch.name == "Sede Principal")
        )).scalar_one_or_none()
        
        assert branch is not None
        full = branch._build_full_address()
        assert "Calle 70" in full
        assert "# 68A - 11" in full
        assert "Calazans" in full
        assert "Carepa" in full


class TestBusinessHours:
    """Tests for official business hours configuration."""

    async def test_timezone_is_america_bogota(self):
        """La zona horaria debe ser America/Bogota."""
        tz = await get_business_timezone()
        assert tz == "America/Bogota", f"Zona horaria esperada 'America/Bogota', obtenida '{tz}'"

    async def test_monday_hours(self):
        """Lunes: 08:00-12:00 y 14:00-18:00."""
        hours = await get_appointment_hours_for_weekday(0)
        assert hours == [8, 9, 10, 11, 14, 15, 16, 17], f"Lunes: esperado [8,9,10,11,14,15,16,17], obtenido {hours}"

    async def test_tuesday_hours(self):
        """Martes: 08:00-12:00 y 14:00-18:00."""
        hours = await get_appointment_hours_for_weekday(1)
        assert hours == [8, 9, 10, 11, 14, 15, 16, 17], f"Martes: esperado [8,9,10,11,14,15,16,17], obtenido {hours}"

    async def test_wednesday_hours(self):
        """Miércoles: 08:00-12:00 y 14:00-18:00."""
        hours = await get_appointment_hours_for_weekday(2)
        assert hours == [8, 9, 10, 11, 14, 15, 16, 17], f"Miércoles: esperado [8,9,10,11,14,15,16,17], obtenido {hours}"

    async def test_thursday_hours(self):
        """Jueves: 08:00-12:00 y 14:00-18:00."""
        hours = await get_appointment_hours_for_weekday(3)
        assert hours == [8, 9, 10, 11, 14, 15, 16, 17], f"Jueves: esperado [8,9,10,11,14,15,16,17], obtenido {hours}"

    async def test_friday_hours(self):
        """Viernes: 08:00-12:00 y 14:00-18:00."""
        hours = await get_appointment_hours_for_weekday(4)
        assert hours == [8, 9, 10, 11, 14, 15, 16, 17], f"Viernes: esperado [8,9,10,11,14,15,16,17], obtenido {hours}"

    async def test_saturday_hours(self):
        """Sábado: 08:00-15:00."""
        hours = await get_appointment_hours_for_weekday(5)
        assert hours == [8, 9, 10, 11, 12, 13, 14], f"Sábado: esperado [8,9,10,11,12,13,14], obtenido {hours}"

    async def test_sunday_closed(self):
        """Domingo: cerrado (sin horarios)."""
        hours = await get_appointment_hours_for_weekday(6)
        assert hours == [], f"Domingo: esperado [], obtenido {hours}"

    async def test_sunday_is_not_business_day(self):
        """Domingo no es día hábil."""
        is_biz = await is_business_day(6)
        assert is_biz is False, "Domingo no debe ser día hábil"

    async def test_saturday_is_business_day(self):
        """Sábado es día hábil."""
        is_biz = await is_business_day(5)
        assert is_biz is True, "Sábado debe ser día hábil"

    async def test_monday_is_business_day(self):
        """Lunes es día hábil."""
        is_biz = await is_business_day(0)
        assert is_biz is True, "Lunes debe ser día hábil"

    async def test_lunch_break_monday_12pm_closed(self):
        """Lunes 12:00 debe estar cerrado (pausa de almuerzo)."""
        tz = zoneinfo.ZoneInfo("America/Bogota")
        monday_12 = dt.datetime(2026, 9, 21, 12, 0, tzinfo=tz).astimezone(dt.UTC)
        is_within, reason = await is_within_business_hours(monday_12)
        assert is_within is False, f"Lunes 12:00 debe estar cerrado (pausa), razón: {reason}"
        assert "fuera de rango" in reason.lower() or "horario" in reason.lower()

    async def test_lunch_break_monday_13pm_closed(self):
        """Lunes 13:00 debe estar cerrado (pausa de almuerzo)."""
        tz = zoneinfo.ZoneInfo("America/Bogota")
        monday_13 = dt.datetime(2026, 9, 21, 13, 0, tzinfo=tz).astimezone(dt.UTC)
        is_within, reason = await is_within_business_hours(monday_13)
        assert is_within is False, f"Lunes 13:00 debe estar cerrado (pausa), razón: {reason}"

    async def test_monday_14pm_open(self):
        """Lunes 14:00 debe estar abierto (inicio tarde)."""
        tz = zoneinfo.ZoneInfo("America/Bogota")
        monday_14 = dt.datetime(2026, 9, 21, 14, 0, tzinfo=tz).astimezone(dt.UTC)
        is_within, reason = await is_within_business_hours(monday_14)
        assert is_within is True, f"Lunes 14:00 debe estar abierto, razón: {reason}"

    async def test_monday_10am_open(self):
        """Lunes 10:00 debe estar abierto (mañana)."""
        tz = zoneinfo.ZoneInfo("America/Bogota")
        monday_10 = dt.datetime(2026, 9, 21, 10, 0, tzinfo=tz).astimezone(dt.UTC)
        is_within, reason = await is_within_business_hours(monday_10)
        assert is_within is True, f"Lunes 10:00 debe estar abierto, razón: {reason}"

    async def test_monday_17pm_open(self):
        """Lunes 17:00 debe estar abierto (último horario)."""
        tz = zoneinfo.ZoneInfo("America/Bogota")
        monday_17 = dt.datetime(2026, 9, 21, 17, 0, tzinfo=tz).astimezone(dt.UTC)
        is_within, reason = await is_within_business_hours(monday_17)
        assert is_within is True, f"Lunes 17:00 debe estar abierto, razón: {reason}"

    async def test_monday_18pm_closed(self):
        """Lunes 18:00 debe estar cerrado (después del último horario)."""
        tz = zoneinfo.ZoneInfo("America/Bogota")
        monday_18 = dt.datetime(2026, 9, 21, 18, 0, tzinfo=tz).astimezone(dt.UTC)
        is_within, reason = await is_within_business_hours(monday_18)
        assert is_within is False, f"Lunes 18:00 debe estar cerrado, razón: {reason}"

    async def test_saturday_10am_open(self):
        """Sábado 10:00 debe estar abierto."""
        tz = zoneinfo.ZoneInfo("America/Bogota")
        saturday_10 = dt.datetime(2026, 9, 26, 10, 0, tzinfo=tz).astimezone(dt.UTC)
        is_within, reason = await is_within_business_hours(saturday_10)
        assert is_within is True, f"Sábado 10:00 debe estar abierto, razón: {reason}"

    async def test_saturday_14pm_open(self):
        """Sábado 14:30 debe estar abierto."""
        tz = zoneinfo.ZoneInfo("America/Bogota")
        saturday_1430 = dt.datetime(2026, 9, 26, 14, 30, tzinfo=tz).astimezone(dt.UTC)
        is_within, reason = await is_within_business_hours(saturday_1430)
        assert is_within is True, f"Sábado 14:30 debe estar abierto, razón: {reason}"

    async def test_saturday_15pm_closed(self):
        """Sábado 15:00 debe estar cerrado (fin de horario)."""
        tz = zoneinfo.ZoneInfo("America/Bogota")
        saturday_15 = dt.datetime(2026, 9, 26, 15, 0, tzinfo=tz).astimezone(dt.UTC)
        is_within, reason = await is_within_business_hours(saturday_15)
        assert is_within is False, f"Sábado 15:00 debe estar cerrado, razón: {reason}"

    async def test_saturday_08am_open(self):
        """Sábado 08:00 debe estar abierto (inicio)."""
        tz = zoneinfo.ZoneInfo("America/Bogota")
        saturday_08 = dt.datetime(2026, 9, 26, 8, 0, tzinfo=tz).astimezone(dt.UTC)
        is_within, reason = await is_within_business_hours(saturday_08)
        assert is_within is True, f"Sábado 08:00 debe estar abierto, razón: {reason}"

    async def test_saturday_07am_closed(self):
        """Sábado 07:00 debe estar cerrado (antes de inicio)."""
        tz = zoneinfo.ZoneInfo("America/Bogota")
        saturday_07 = dt.datetime(2026, 9, 26, 7, 0, tzinfo=tz).astimezone(dt.UTC)
        is_within, reason = await is_within_business_hours(saturday_07)
        assert is_within is False, f"Sábado 07:00 debe estar cerrado, razón: {reason}"

    async def test_sunday_11am_closed(self):
        """Domingo 11:00 debe estar cerrado."""
        tz = zoneinfo.ZoneInfo("America/Bogota")
        sunday_11 = dt.datetime(2026, 9, 27, 11, 0, tzinfo=tz).astimezone(dt.UTC)
        is_within, reason = await is_within_business_hours(sunday_11)
        assert is_within is False, f"Domingo 11:00 debe estar cerrado, razón: {reason}"
        assert "domingo" in reason.lower() or "no hay atención" in reason.lower()

    async def test_all_weekdays_hours_map(self):
        """Verificar el mapa completo de horarios por día.
        
        Nota: get_appointment_hours_by_weekday solo devuelve días con horarios.
        Para obtener horarios de un día específico (incluyendo días cerrados),
        use get_appointment_hours_for_weekday().
        """
        hours_map = await get_appointment_hours_by_weekday()
        
        # Verificar días con horarios
        expected_with_hours = {
            0: [8, 9, 10, 11, 14, 15, 16, 17],  # Lunes
            1: [8, 9, 10, 11, 14, 15, 16, 17],  # Martes
            2: [8, 9, 10, 11, 14, 15, 16, 17],  # Miércoles
            3: [8, 9, 10, 11, 14, 15, 16, 17],  # Jueves
            4: [8, 9, 10, 11, 14, 15, 16, 17],  # Viernes
            5: [8, 9, 10, 11, 12, 13, 14],       # Sábado
        }
        
        assert hours_map == expected_with_hours, f"Mapa de horarios no coincide:\nEsperado: {expected_with_hours}\nObtenido: {hours_map}"
        
        # Verificar que domingo devuelve lista vacía vía get_appointment_hours_for_weekday
        sunday_hours = await get_appointment_hours_for_weekday(6)
        assert sunday_hours == [], f"Domingo debe devolver [] vía get_appointment_hours_for_weekday, obtuvo {sunday_hours}"

    async def test_monday_0759_closed(self):
        """Lunes 07:59 debe estar cerrado (antes de apertura)."""
        tz = zoneinfo.ZoneInfo("America/Bogota")
        monday_0759 = dt.datetime(2026, 9, 21, 7, 59, tzinfo=tz).astimezone(dt.UTC)
        is_within, reason = await is_within_business_hours(monday_0759)
        assert is_within is False, f"Lunes 07:59 debe estar cerrado, razón: {reason}"

    async def test_friday_17pm_last_slot(self):
        """Viernes 17:00 es el último horario de inicio (termina a las 18:00)."""
        tz = zoneinfo.ZoneInfo("America/Bogota")
        friday_17 = dt.datetime(2026, 9, 25, 17, 0, tzinfo=tz).astimezone(dt.UTC)
        is_within, reason = await is_within_business_hours(friday_17)
        assert is_within is True, f"Viernes 17:00 debe estar abierto, razón: {reason}"

    async def test_no_12pm_slot_monday_thru_friday(self):
        """Verificar que no existe slot a las 12:00 de lunes a viernes (es hora de cierre de mañana)."""
        for day in range(5):  # Mon-Fri
            hours = await get_appointment_hours_for_weekday(day)
            assert 12 not in hours, f"Día {day} no debe tener slot a las 12:00 (es cierre de mañana)"

    async def test_no_13pm_slot_monday_thru_friday(self):
        """Verificar que no existe slot a las 13:00 de lunes a viernes (es hora de almuerzo)."""
        for day in range(5):  # Mon-Fri
            hours = await get_appointment_hours_for_weekday(day)
            assert 13 not in hours, f"Día {day} no debe tener slot a las 13:00 (es almuerzo)"


class TestContactEndpoint:
    """Tests for the public /contact endpoint."""

    async def test_contact_endpoint_returns_correct_structure(self, client):
        """El endpoint /contact debe devolver la estructura correcta."""
        response = await client.get("/contact")
        assert response.status_code == 200
        
        data = response.json()
        
        # Company info
        assert "company" in data
        assert data["company"]["name"] == "epresedi Inmobiliaria"
        
        # Address
        assert "address" in data
        addr = data["address"]
        assert addr["street"] == "Calle 70"
        assert addr["street_number"] == "# 68A - 11"
        assert addr["neighborhood"] == "Calazans"
        assert addr["floor"] == "1er piso"
        assert addr["city"] == "Carepa"
        assert addr["department"] == "Antioquia"
        assert addr["country"] == "Colombia"
        assert addr["reference"] == "Diagonal a Tiendas Ara"
        assert "Calle 70 # 68A - 11" in addr["full_address"]
        assert "Calazans" in addr["full_address"]
        assert "Carepa" in addr["full_address"]
        assert "Antioquia" in addr["full_address"]
        
        # Timezone
        assert "timezone" in data
        assert data["timezone"] == "America/Bogota"
        
        # Business hours
        assert "business_hours" in data
        hours = data["business_hours"]
        assert "Lunes" in hours
        assert "Domingo" in hours
        assert hours["Domingo"].get("closed") is True
        
        # Lunes should have morning and afternoon intervals
        lunes = hours["Lunes"]
        assert "intervals" in lunes
        assert len(lunes["intervals"]) == 2
        assert lunes["intervals"][0]["open"] == "08:00"
        assert lunes["intervals"][0]["close"] == "12:00"
        assert lunes["intervals"][1]["open"] == "14:00"
        assert lunes["intervals"][1]["close"] == "18:00"
        
        # Sábado should have one interval
        sabado = hours["Sábado"]
        assert "intervals" in sabado
        assert len(sabado["intervals"]) == 1
        assert sabado["intervals"][0]["open"] == "08:00"
        assert sabado["intervals"][0]["close"] == "15:00"


class TestNoOldConflictingData:
    """Tests to ensure no old conflicting data exists."""

    async def test_no_old_address_in_bizconfig_defaults(self):
        """Verificar que SETTING_DEFAULTS no tiene direcciones antiguas."""
        from app.core.bizconfig import SETTING_DEFAULTS
        
        # contact_address default should be empty (set via DB/branch)
        assert SETTING_DEFAULTS.get("contact_address", "") == ""

    async def test_branch_not_using_el_centro(self, session):
        """La sede principal no debe usar 'El Centro' como barrio."""
        branch = (await session.execute(
            select(Branch).where(Branch.name == "Sede Principal")
        )).scalar_one_or_none()
        
        assert branch is not None
        assert branch.neighborhood != "El Centro", "Barrio no debe ser 'El Centro' (dato antiguo)"
        assert branch.neighborhood == "Calazans"

    async def test_branch_not_using_sede_principal_en_centro(self, session):
        """La ubicación descriptiva no debe decir 'centro de Carepa'."""
        branch = (await session.execute(
            select(Branch).where(Branch.name == "Sede Principal")
        )).scalar_one_or_none()
        
        assert branch is not None
        assert "centro de Carepa" not in branch.descriptive_location.lower(), \
            "Descriptive location no debe contener 'centro de Carepa' (dato antiguo)"