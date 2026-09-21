"""Property images: local storage only (storage/properties/PROPERTY_ID/...).

Operations: upload (safe naming, whitelist, size cap), delete (with cover
promotion), cover selection, reorder (two-phase rename) and full storage
cleanup when a property is removed.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from app.core.settings import get_settings

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def property_images_dir(property_id: str) -> Path:
    return get_settings().storage_dir / "properties" / str(property_id)


def _sort_key(name: str):
    if name.startswith("cover"):
        return (0, name)
    m = re.match(r"^(\d+)", name)
    return (1, int(m.group(1)) if m else 9999, name)


def list_property_images(property_id: str) -> list[str]:
    """Returns ordered filenames (cover first, then 001.., numeric sort)."""
    base = property_images_dir(property_id)
    if not base.is_dir():
        return []
    return sorted(
        (f for f in os.listdir(base) if Path(f).suffix.lower() in ALLOWED_IMAGE_EXT),
        key=_sort_key,
    )


def _next_number(base: Path) -> int:
    """Highest existing numbered prefix + 1 (collision-safe after deletes)."""
    highest = 0
    if base.is_dir():
        for f in os.listdir(base):
            m = re.match(r"^(\d+)", f)
            if m:
                highest = max(highest, int(m.group(1)))
    return highest + 1


def save_property_image(
    property_id: str, data: bytes, original_name: str, max_mb: int | None = None
) -> str:
    """Safe upload: extension whitelist, size cap, uuid-safe filename.

    The first image becomes cover.{ext}; subsequent ones take the next free
    numbered slot (max+1, so deletes never cause overwrites).
    """
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise ValueError(f"Extensión de imagen no permitida: {ext}")
    limit = max_mb if max_mb is not None else get_settings().MAX_UPLOAD_MB
    if len(data) > limit * 1024 * 1024:
        raise ValueError(f"Imagen demasiado grande (máximo {limit} MB)")
    base = property_images_dir(property_id)
    base.mkdir(parents=True, exist_ok=True)
    if not list_property_images(property_id):
        name = "cover.jpg" if ext == ".jpg" else f"cover{ext}"
    else:
        name = f"{_next_number(base):03d}{ext}"
    path = base / name
    with open(path, "wb") as fh:
        fh.write(data)
    return str(path)


def _valid_existing_name(property_id: str, filename: str) -> Path | None:
    """Validates the filename against the whitelist AND the stored files."""
    if not _SAFE_NAME.match(filename):
        return None
    if Path(filename).suffix.lower() not in ALLOWED_IMAGE_EXT:
        return None
    path = property_images_dir(property_id) / filename
    return path if path.is_file() else None


def delete_property_image(property_id: str, filename: str) -> list[str]:
    """Deletes one image. If it was the cover, promotes the first remaining."""
    path = _valid_existing_name(property_id, filename)
    if path is None:
        raise ValueError("Imagen no encontrada")
    was_cover = path.name.startswith("cover")
    path.unlink()
    remaining = list_property_images(property_id)
    if was_cover and remaining:
        first = property_images_dir(property_id) / remaining[0]
        target = property_images_dir(property_id) / f"cover{first.suffix.lower()}"
        first.rename(target)
        remaining = list_property_images(property_id)
    return remaining


def set_property_cover(property_id: str, filename: str) -> list[str]:
    """Promotes `filename` to cover; the previous cover gets a free number."""
    path = _valid_existing_name(property_id, filename)
    if path is None:
        raise ValueError("Imagen no encontrada")
    if path.name.startswith("cover"):
        return list_property_images(property_id)
    base = property_images_dir(property_id)
    old_cover = next(
        (base / f for f in os.listdir(base) if f.startswith("cover")), None
    )
    target = base / f"cover{path.suffix.lower()}"
    if old_cover is not None:
        old_cover.rename(base / f"{_next_number(base):03d}{old_cover.suffix.lower()}")
    path.rename(target)
    return list_property_images(property_id)


def reorder_property_images(property_id: str, order: list[str]) -> list[str]:
    """Renames files to match `order` (two-phase to avoid clobbering).

    The first filename in `order` becomes the cover; the rest are renumbered
    sequentially. Filenames not present in `order` keep their relative order
    at the end. This preserves the cover-first + numeric convention used by
    list_property_images and every consumer (dashboard, listado, asistente).
    """
    base = property_images_dir(property_id)
    current = list_property_images(property_id)
    if not current:
        raise ValueError("La propiedad no tiene imágenes")
    known = [f for f in order if f in set(current)]
    ordered = known + [f for f in current if f not in set(known)]
    # Fase 1: cada archivo a un nombre temporal único (__staging_NNN.ext).
    for i, name in enumerate(ordered):
        (base / name).rename(base / f"__staging_{i:03d}{Path(name).suffix.lower()}")
    # Fase 2: temporal → nombre final (portada primera, resto numerado).
    for i, name in enumerate(ordered):
        ext = Path(name).suffix.lower()
        final = base / (f"cover{ext}" if i == 0 else f"{i:03d}{ext}")
        (base / f"__staging_{i:03d}{ext}").rename(final)
    return list_property_images(property_id)


def delete_property_storage(property_id: str) -> int:
    """Removes the whole property image directory (orphan cleanup on delete)."""
    base = property_images_dir(property_id)
    if not base.is_dir():
        return 0
    count = len([f for f in os.listdir(base) if Path(f).suffix.lower() in ALLOWED_IMAGE_EXT])
    import shutil

    shutil.rmtree(base, ignore_errors=True)
    return count


def property_has_images(property_id: str) -> bool:
    base = property_images_dir(property_id)
    if not base.is_dir():
        return False
    return any(Path(f).suffix.lower() in ALLOWED_IMAGE_EXT for f in os.listdir(base))


def image_path_or_none(property_id: str, filename: str) -> Path | None:
    """Path traversal-proof: resolve inside the property dir only."""
    if not _SAFE_NAME.match(filename):
        return None
    base = property_images_dir(property_id).resolve()
    candidate = (base / filename).resolve()
    if base != candidate and base not in candidate.parents:
        return None
    return candidate if candidate.exists() else None
