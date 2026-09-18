"""Chunking: paragraph-aware splitting with overlap and section tracking."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MAX_CHARS = 900
OVERLAP_CHARS = 120

_HEADING_RE = re.compile(
    r"^(#{1,3}\s+.*|\b(Sección|Seccion|Capítulo|Capitulo|Artículo|Articulo)\s+[\w\d]+.*)$"
)
# ALL-CAPS standalone lines are section markers too: "FINANCIACION:",
# "AREAS Y TIPOLOGIAS:", "REGLAMENTO DE PROPIEDAD HORIZONTAL - ..."
_ALLCAPS_RE = re.compile(r"^[A-ZÁÉÍÓÚÜÑ0-9][A-ZÁÉÍÓÚÜÑ0-9\s.,:;()%-]{3,}$")


@dataclass
class Chunk:
    content: str
    section: str
    page: int | None
    chunk_hash: str


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _mode_page(pages: list[int | None]) -> int | None:
    real = [p for p in pages if p is not None]
    if not real:
        return None
    return max(set(real), key=real.count)


def _clean(content: str) -> str:
    content = content.replace("\x00", " ")
    content = re.sub(r"[ \t]+", " ", content)
    return content.strip()


def split_into_chunks(paragraphs: list[tuple[str, int | None]], max_chars: int = MAX_CHARS) -> list[Chunk]:
    """paragraphs: list of (text, page). Produces stable, traceable chunks."""
    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_pages: list[int | None] = []
    section = ""

    def flush() -> None:
        if not buffer:
            return
        content = _clean(" ".join(buffer))
        if not content:
            return
        chunks.append(Chunk(content=content, section=section, page=_mode_page(buffer_pages), chunk_hash=_hash(content)))
        buffer.clear()
        buffer_pages.clear()

    for text, page in paragraphs:
        text = _clean(text)
        if not text:
            continue
        if _HEADING_RE.match(text) or (_ALLCAPS_RE.match(text) and any(c.isalpha() for c in text)):
            flush()
            section = re.sub(r"^#+\s*", "", text)[:200]
            continue
        if sum(len(t) + 1 for t in buffer) + len(text) > max_chars:
            tail = _clean(" ".join(buffer))[-OVERLAP_CHARS:] if buffer else ""
            flush()
            if tail:
                buffer.append(tail)
                buffer_pages.append(page)
        buffer.append(text)
        buffer_pages.append(page)
    flush()
    return chunks
