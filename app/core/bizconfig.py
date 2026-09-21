"""Business settings stored in DB (app_settings) with env fallback + short TTL cache.

Consumers: appointments (hours, timezone), uploads (max size), assistant
(contact info). Admin writes go through PUT /settings which invalidates the
cache; reads fall back to the .env defaults when a key is not set in the DB.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.database.base import AsyncSessionLocal
from app.database.models import AppSetting

log = get_logger(__name__)

TTL_SECONDS = 30
_cache: dict[str, tuple[float, Any]] = {}

# Default business hours by weekday (0=Monday, 6=Sunday)
# Mon-Fri: 08:00-18:00, Sat: 09:00-15:00, Sun: closed
DEFAULT_APPOINTMENT_HOURS_BY_WEEKDAY: dict[int, list[int]] = {
    0: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17],  # Monday
    1: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17],  # Tuesday
    2: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17],  # Wednesday
    3: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17],  # Thursday
    4: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17],  # Friday
    5: [9, 10, 11, 12, 13, 14],                  # Saturday (09:00-15:00)
    6: [],                                        # Sunday (closed)
}

# Legacy flat list for backward compatibility (Mon-Fri hours)
DEFAULT_APPOINTMENT_HOURS_LEGACY = [9, 10, 11, 14, 15, 16, 17]

SETTING_DEFAULTS: dict[str, Any] = {
    "company_name": "epresedi Inmobiliaria",
    "contact_phone": "",
    "contact_email": "",
    "contact_address": "",
    "appointment_hours_by_weekday": DEFAULT_APPOINTMENT_HOURS_BY_WEEKDAY,
    "appointment_hours": DEFAULT_APPOINTMENT_HOURS_LEGACY,  # legacy, kept for compat
    "timezone": "America/Bogota",
    "max_upload_mb": 15,
}

SETTING_DESCRIPTIONS: dict[str, str] = {
    "company_name": "Nombre comercial de la empresa (branding)",
    "contact_phone": "Teléfono de contacto comercial (usado por el asistente)",
    "contact_email": "Email de contacto comercial",
    "contact_address": "Dirección de la oficina comercial",
    "appointment_hours_by_weekday": "Horas hábiles por día de la semana (0=lunes..6=domingo)",
    "appointment_hours": "Horas hábiles legacy (compatibilidad)",
    "timezone": "Zona horaria del negocio (agenda y fechas)",
    "max_upload_mb": "Tamaño máximo de subida de archivos (MB)",
}


async def get_value(key: str) -> Any:
    """Reads a business setting: DB → env fallback, cached for TTL_SECONDS."""
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and now - hit[0] < TTL_SECONDS:
        return hit[1]
    default = SETTING_DEFAULTS.get(key)
    try:
        async with AsyncSessionLocal() as session:
            row = await session.get(AppSetting, key)
        value = row.value if row is not None else default
    except Exception as e:  # pragma: no cover - DB down → env fallback
        log.warning("bizconfig_read_failed key=%s error=%s", key, e)
        value = default
    _cache[key] = (now, value)
    return value


async def get_business_timezone() -> str:
    return str(await get_value("timezone") or "America/Bogota")


async def get_appointment_hours_by_weekday() -> dict[int, list[int]]:
    """Returns business hours mapped by weekday (0=Monday..6=Sunday)."""
    raw = await get_value("appointment_hours_by_weekday")
    if isinstance(raw, dict):
        result: dict[int, list[int]] = {}
        for k, v in raw.items():
            try:
                weekday = int(k)
                if 0 <= weekday <= 6 and isinstance(v, list):
                    hours = [h for h in v if isinstance(h, int) and 0 <= h <= 23]
                    if hours:
                        result[weekday] = sorted(hours)
            except (ValueError, TypeError):
                continue
        if result:
            return result
    return dict(SETTING_DEFAULTS["appointment_hours_by_weekday"])


async def get_appointment_hours_for_weekday(weekday: int) -> list[int]:
    """Returns business hours for a specific weekday (0=Monday..6=Sunday)."""
    hours_map = await get_appointment_hours_by_weekday()
    return hours_map.get(weekday, [])


async def is_business_day(weekday: int) -> bool:
    """Returns True if the weekday has business hours (not closed)."""
    hours = await get_appointment_hours_for_weekday(weekday)
    return len(hours) > 0


async def is_within_business_hours(dt_utc: dt.datetime) -> tuple[bool, str]:
    """Checks if a UTC datetime falls within business hours in the business timezone.
    
    Returns (is_within, reason). Reason explains why if not within.
    """
    from app.appointments.service import to_business_time
    
    local_dt = await to_business_time(dt_utc)
    weekday = local_dt.weekday()
    hour = local_dt.hour
    minute = local_dt.minute
    
    if not await is_business_day(weekday):
        day_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        return False, f"No hay atención los {day_names[weekday]}s."
    
    hours = await get_appointment_hours_for_weekday(weekday)
    if hour not in hours:
        # Check if it's before opening or after closing
        if hour < hours[0] or (hour == hours[0] and minute > 0):
            return False, f"Horario fuera de rango. Atención desde las {hours[0]:02d}:00."
        if hour > hours[-1] or (hour == hours[-1] and minute > 0):
            return False, f"Horario fuera de rango. Último horario a las {hours[-1]:02d}:00."
        return False, "Horario no disponible en el rango de atención."
    
    return True, ""


# Backward compatibility
async def get_appointment_hours() -> list[int]:
    """Legacy: returns flat list of hours (Mon-Fri default)."""
    raw = await get_value("appointment_hours")
    if isinstance(raw, list):
        hours = [h for h in raw if isinstance(h, int) and 0 <= h <= 23]
        if hours:
            return sorted(hours)
    return list(SETTING_DEFAULTS["appointment_hours"])


async def get_max_upload_mb() -> int:
    raw = await get_value("max_upload_mb")
    if isinstance(raw, int) and 1 <= raw <= 200:
        return raw
    return get_settings().MAX_UPLOAD_MB


def invalidate() -> None:
    """Called after PUT /settings so changes take effect immediately."""
    _cache.clear()
