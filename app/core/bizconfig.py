"""Business settings stored in DB (app_settings) with env fallback + short TTL cache.

Consumers: appointments (hours, timezone), uploads (max size), assistant
(contact info). Admin writes go through PUT /settings which invalidates the
cache; reads fall back to the .env defaults when a key is not set in the DB.
"""
from __future__ import annotations

import time
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.database.base import AsyncSessionLocal
from app.database.models import AppSetting

log = get_logger(__name__)

TTL_SECONDS = 30
_cache: dict[str, tuple[float, Any]] = {}

SETTING_DEFAULTS: dict[str, Any] = {
    "company_name": "EXPRESEDI Inmobiliaria",
    "contact_phone": "",
    "contact_email": "",
    "contact_address": "",
    "appointment_hours": [9, 10, 11, 14, 15, 16, 17],
    "timezone": "America/Bogota",
    "max_upload_mb": 15,
}

SETTING_DESCRIPTIONS: dict[str, str] = {
    "company_name": "Nombre comercial de la empresa (branding)",
    "contact_phone": "Teléfono de contacto comercial (usado por el asistente)",
    "contact_email": "Email de contacto comercial",
    "contact_address": "Dirección de la oficina comercial",
    "appointment_hours": "Horas hábiles para agendar visitas (slots de cita)",
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


async def get_appointment_hours() -> list[int]:
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
