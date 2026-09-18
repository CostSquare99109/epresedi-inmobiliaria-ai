"""Property images: local storage only (storage/properties/PROPERTY_ID/...)."""
from __future__ import annotations

import os
import re
import uuid as uuid_mod
from pathlib import Path

from app.core.settings import get_settings

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def property_images_dir(property_id: str) -> Path:
    return get_settings().storage_dir / "properties" / str(property_id)


def list_property_images(property_id: str) -> list[str]:
    """Returns ordered filenames (cover first, then 001.., numeric sort)."""
    base = property_images_dir(property_id)
    if not base.is_dir():
        return []

    def sort_key(name: str):
        if name.startswith("cover"):
            return (0, name)
        m = re.match(r"^(\d+)", name)
        return (1, int(m.group(1)) if m else 9999, name)

    return sorted(
        (f for f in os.listdir(base) if Path(f).suffix.lower() in ALLOWED_IMAGE_EXT),
        key=sort_key,
    )


def save_property_image(property_id: str, data: bytes, original_name: str) -> str:
    """Safe upload: extension whitelist, size cap, uuid-safe filename."""
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise ValueError(f"Extensión de imagen no permitida: {ext}")
    if len(data) > get_settings().MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError("Imagen demasiado grande")
    base = property_images_dir(property_id)
    base.mkdir(parents=True, exist_ok=True)
    existing = list_property_images(property_id)
    if not existing:
        name = "cover.jpg" if ext == ".jpg" else f"cover{ext}"
    else:
        n = len(existing) + 1
        name = f"{n:03d}{ext}"
    path = base / name
    with open(path, "wb") as fh:
        fh.write(data)
    return str(path)


def image_path_or_none(property_id: str, filename: str) -> Path | None:
    """Path traversal-proof: resolve inside the property dir only."""
    if not _SAFE_NAME.match(filename):
        return None
    base = property_images_dir(property_id).resolve()
    candidate = (base / filename).resolve()
    if base != candidate and base not in candidate.parents:
        return None
    return candidate if candidate.exists() else None
