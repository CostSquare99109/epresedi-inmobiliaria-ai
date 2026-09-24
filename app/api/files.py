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

_SAFE_NAME = re.compile(r"^[\w.\-]+$", re.UNICODE)
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_STEM_LEN = 80


def sanitize_image_stem(raw: str | None) -> str:
    """Limpia un nombre dado por el usuario para usarlo como nombre de archivo.

    - Conserva letras unicode (ñ, tildes), dígitos, guion y punto.
    - Los espacios se convierten en guiones: "Piso 2" -> "Piso-2".
    - Devuelve "" si no queda nada aprovechable (el llamador usa el esquema
      legacy cover/NNN en ese caso).
    """
    if not raw:
        return ""
    import unicodedata

    stem = unicodedata.normalize("NFC", raw.strip())
    stem = re.sub(r"\s+", "-", stem)
    stem = re.sub(r"[^\w.\-]", "", stem, flags=re.UNICODE)
    stem = stem.strip(".-")
    if len(stem) > MAX_IMAGE_STEM_LEN:
        stem = stem[:MAX_IMAGE_STEM_LEN].rstrip(".-")
    if not _SAFE_NAME.match(stem) or not stem:
        return ""
    return stem


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
    property_id: str, data: bytes, original_name: str, max_mb: int | None = None,
    preferred_name: str | None = None,
) -> str:
    """Safe upload: extension whitelist, size cap, uuid-safe filename.

    Si `preferred_name` trae un nombre útil (p. ej. "Baño"), el archivo se
    guarda como "<Nombre>.<ext>" ("Baño.jpg"); ante colisiones se sufija
    ("Baño2.jpg", "Baño3.jpg"). Sin nombre útil se conserva el esquema legacy: la primera
    imagen es cover.{ext} y las siguientes toman el siguiente slot numerado
    libre (max+1, así los borrados nunca causan sobrescrituras).
    """
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise ValueError(f"Extensión de imagen no permitida: {ext}")
    limit = max_mb if max_mb is not None else get_settings().MAX_UPLOAD_MB
    if len(data) > limit * 1024 * 1024:
        raise ValueError(f"Imagen demasiado grande (máximo {limit} MB)")
    base = property_images_dir(property_id)
    base.mkdir(parents=True, exist_ok=True)
    stem = sanitize_image_stem(preferred_name)
    if stem:
        # No pisar cover/NNN del esquema legacy ni otras fotos con nombre.
        if stem.lower() == "cover" or re.match(r"^\d+$", stem):
            stem = f"{stem}-foto"
        name = f"{stem}{ext}"
        n = 2
        while (base / name).exists():
            name = f"{stem}{n}{ext}"
            n += 1
    elif not list_property_images(property_id):
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


def delete_property_image(property_id: str, filename: str) -> tuple[list[str], dict[str, str]]:
    """Deletes one image. If it was the cover, promotes the first remaining.

    Returns ``(remaining, renames)`` where ``renames`` maps old disk names to
    new ones. Callers MUST apply the mapping to the database (the promoted
    file keeps its DB row under a new filename) or served URLs break (404).
    """
    path = _valid_existing_name(property_id, filename)
    if path is None:
        raise ValueError("Imagen no encontrada")
    was_cover = path.name.startswith("cover")
    path.unlink()
    renames: dict[str, str] = {}
    remaining = list_property_images(property_id)
    if was_cover and remaining:
        first = property_images_dir(property_id) / remaining[0]
        old_name = first.name
        target = property_images_dir(property_id) / f"cover{first.suffix.lower()}"
        first.rename(target)
        renames[old_name] = target.name
        remaining = list_property_images(property_id)
    return remaining, renames


def set_property_cover(property_id: str, filename: str) -> tuple[list[str], dict[str, str]]:
    """Promotes `filename` to cover; the previous cover gets a free number.

    Returns ``(images, renames)`` (see :func:`delete_property_image`): the
    promoted file becomes ``cover.ext`` on disk and the caller must update the
    database filenames, otherwise the DB keeps pointing at the old name (404).
    """
    path = _valid_existing_name(property_id, filename)
    if path is None:
        raise ValueError("Imagen no encontrada")
    base = property_images_dir(property_id)
    if path.name.startswith("cover"):
        return list_property_images(property_id), {}
    old_cover = next(
        (base / f for f in os.listdir(base) if f.startswith("cover")), None
    )
    old_name = path.name
    target = base / f"cover{path.suffix.lower()}"
    renames: dict[str, str] = {}
    if old_cover is not None:
        old_cover_name = old_cover.name
        new_old = base / f"{_next_number(base):03d}{old_cover.suffix.lower()}"
        old_cover.rename(new_old)
        renames[old_cover_name] = new_old.name
    path.rename(target)
    renames[old_name] = target.name
    return list_property_images(property_id), renames


def reorder_property_images(property_id: str, order: list[str]) -> tuple[list[str], dict[str, str]]:
    """Renames files to match `order` (two-phase to avoid clobbering).

    The first filename in `order` becomes the cover; the rest are renumbered
    sequentially. Filenames not present in `order` keep their relative order
    at the end. This preserves the cover-first + numeric convention used by
    list_property_images and every consumer (dashboard, listado, asistente).

    Returns ``(images, renames)`` (see :func:`delete_property_image`): every
    file gets a new disk name and the caller must update the database.
    """
    base = property_images_dir(property_id)
    current = list_property_images(property_id)
    if not current:
        raise ValueError("La propiedad no tiene imágenes")
    known = [f for f in order if f in set(current)]
    ordered = known + [f for f in current if f not in set(known)]
    renames = {}
    for i, name in enumerate(ordered):
        ext = Path(name).suffix.lower()
        renames[name] = f"cover{ext}" if i == 0 else f"{i:03d}{ext}"
    # Fase 1: cada archivo a un nombre temporal único (__staging_NNN.ext).
    for i, name in enumerate(ordered):
        (base / name).rename(base / f"__staging_{i:03d}{Path(name).suffix.lower()}")
    # Fase 2: temporal → nombre final (portada primera, resto numerado).
    for i, name in enumerate(ordered):
        ext = Path(name).suffix.lower()
        final = base / (f"cover{ext}" if i == 0 else f"{i:03d}{ext}")
        (base / f"__staging_{i:03d}{ext}").rename(final)
    return list_property_images(property_id), renames


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
