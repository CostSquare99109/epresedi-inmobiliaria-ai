"""RAG ingestion: validation, dedupe, versioning, parse → chunk → embed → store."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import uuid as uuid_mod

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import embedding_version, get_embedding_provider
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.database.models import Document, DocumentChunk, DocumentStatus

log = get_logger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


class DocumentValidationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_document(filename: str, data: bytes, max_mb: int | None = None) -> None:
    s = get_settings()
    max_bytes = (max_mb or s.MAX_UPLOAD_MB) * 1024 * 1024
    if not filename or "/" in filename or ".." in filename or "\\" in filename:
        raise DocumentValidationError("bad_name", "Nombre de archivo inválido.")
    ext = "." + filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise DocumentValidationError(
            "bad_extension", f"Extensión no permitida. Permitidas: {sorted(ALLOWED_EXTENSIONS)}"
        )
    if len(data) == 0:
        raise DocumentValidationError("empty", "El archivo está vacío.")
    if len(data) > max_bytes:
        raise DocumentValidationError("too_large", f"El archivo supera {max_mb} MB.")


def safe_document_path(original_filename: str, doc_id: uuid_mod.UUID) -> str:
    """Never trust user filenames for paths: uuid-based, extension validated first."""
    ext = original_filename.rsplit(".", 1)[-1].lower()
    return str(get_settings().storage_dir / "documents" / f"{doc_id}.{ext}")


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def save_document(
    session: AsyncSession,
    *,
    filename: str,
    data: bytes,
    title: str = "",
    document_type: str = "general",
    property_id: uuid_mod.UUID | None = None,
    project_id: uuid_mod.UUID | None = None,
) -> tuple[Document, bool]:
    """Stores a document. Returns (document, changed).

    `changed` is True when the file is NEW or has become a NEW VERSION, i.e.
    when it must be (re)processed. It is False for a byte-identical duplicate,
    whose existing chunks are still valid (dedupe by content hash).
    """
    validate_document(filename, data)
    sha = file_sha256(data)

    existing_same_hash = (
        await session.execute(select(Document).where(Document.file_hash == sha))
    ).scalar_one_or_none()
    if existing_same_hash:
        return existing_same_hash, False

    existing_by_name = (
        (
            await session.execute(
                select(Document)
                .where(Document.filename == filename)
                .order_by(Document.created_at.desc())
            )
        )
        .scalars()
        .first()
    )

    doc_id = uuid_mod.uuid4()
    path = safe_document_path(filename, doc_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)

    if existing_by_name:
        old_path = existing_by_name.file_path
        existing_by_name.filename = filename
        existing_by_name.file_hash = sha
        existing_by_name.file_path = path
        existing_by_name.size_bytes = len(data)
        existing_by_name.title = title or existing_by_name.title
        existing_by_name.document_type = document_type
        if property_id:
            existing_by_name.property_id = property_id
        if project_id:
            existing_by_name.project_id = project_id
        existing_by_name.version += 1
        existing_by_name.status = DocumentStatus.PENDING
        existing_by_name.error = ""
        existing_by_name.processed_at = None
        if old_path and os.path.exists(old_path) and old_path != path:
            try:
                os.remove(old_path)
            except OSError:
                pass
        return existing_by_name, True

    doc = Document(
        id=doc_id,
        title=title or filename,
        filename=filename,
        file_hash=sha,
        file_path=path,
        size_bytes=len(data),
        document_type=document_type,
        property_id=property_id,
        project_id=project_id,
        status=DocumentStatus.PENDING,
    )
    session.add(doc)
    await session.flush()
    return doc, True


async def process_document(session: AsyncSession, document_id: uuid_mod.UUID) -> Document:
    """Parses + chunks + embeds a document. Called by API, CLI and worker."""
    doc = (
        await session.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if doc is None:
        raise LookupError(f"document {document_id} not found")

    doc.status = DocumentStatus.PROCESSING
    await session.flush()
    try:
        from app.rag.chunking import split_into_chunks
        from app.rag.parsing import ParseError, parse_document

        with open(doc.file_path, "rb") as fh:
            data = fh.read()
        parsed = parse_document(doc.filename, data)

        paragraphs: list[tuple[str, int | None]] = []
        if parsed.pages and parsed.pages[0].page is not None:
            for p in parsed.pages:
                for para in re.split(r"\n\s*\n", p.text):
                    paragraphs.append((para, p.page))
        else:
            for para in re.split(r"\n\s*\n", parsed.text):
                paragraphs.append((para, None))

        chunks = split_into_chunks(paragraphs)
        if not chunks:
            raise ParseError("no chunks produced")

        provider = get_embedding_provider()
        vectors = await provider.embed([c.content for c in chunks])

        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        for chunk, vec in zip(chunks, vectors):
            session.add(
                DocumentChunk(
                    document_id=doc.id,
                    property_id=doc.property_id,
                    project_id=doc.project_id,
                    document_type=doc.document_type,
                    filename=doc.filename,
                    page=chunk.page,
                    section=chunk.section,
                    content=chunk.content,
                    embedding=vec,
                    chunk_hash=chunk.chunk_hash,
                )
            )
        doc.status = DocumentStatus.READY
        doc.error = ""
        doc.chunk_count = len(chunks)
        doc.embedding_version = embedding_version()
        doc.processed_at = dt.datetime.now(dt.UTC)
        await session.flush()
        log.info("rag_process doc=%s chunks=%s version=%s", doc.id, len(chunks), doc.version)
    except Exception as e:
        doc.status = DocumentStatus.FAILED
        doc.error = str(e)[:900]
        await session.flush()
        log.error("rag_process_failed doc=%s error=%s", doc.id, e)
        raise
    return doc


async def ingest_directory(session: AsyncSession, directory: str | None = None) -> list[dict]:
    """Scans DOCUMENTS_PATH/inbox, ingests new files, processes them. Returns report."""
    from app.rag.parsing import guess_mime_from_extension

    s = get_settings()
    target = directory or str(s.documents_dir / "inbox")
    report: list[dict] = []
    if not os.path.isdir(target):
        return report
    for name in sorted(os.listdir(target)):
        if name.startswith("."):
            continue  # hidden files (.gitkeep etc.)
        path = os.path.join(target, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            report.append({"file": name, "ok": False, "error": "extensión no permitida"})
            continue
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            title = os.path.splitext(name)[0].replace("_", " ").replace("-", " ").strip()
            doc, created = await save_document(
                session, filename=name, data=data, title=title,
                document_type="general",
            )
            if not created and doc.status == DocumentStatus.READY:
                report.append({"file": name, "ok": True, "skipped": "duplicado (hash igual)"})
                continue
            await process_document(session, doc.id)
            report.append({
                "file": name, "ok": True, "document_id": str(doc.id),
                "chunks": doc.chunk_count, "version": doc.version,
                "mime": guess_mime_from_extension(name),
            })
        except Exception as e:
            await session.rollback()
            report.append({"file": name, "ok": False, "error": str(e)[:300]})
    await session.commit()
    return report
