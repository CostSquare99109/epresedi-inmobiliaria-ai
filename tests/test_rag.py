"""RAG: parsing, chunking, validation, ingestion, versioning, retrieval, citations."""
from __future__ import annotations

import uuid as uuid_mod

import pytest
from sqlalchemy import delete

from app.rag import retrieval as rag_retrieval
from app.rag.chunking import split_into_chunks
from app.rag.ingest import (
    DocumentValidationError,
    file_sha256,
    ingest_directory,
    process_document,
    safe_document_path,
    save_document,
    validate_document,
)
from app.rag.parsing import ParseError, parse_document, write_simple_docx, write_simple_pdf


# ---------------------------------------------------------------------- parsing
def test_parse_txt_and_md(tmp_path):
    txt = tmp_path / "a.txt"
    txt.write_text("Linea uno.\n\nLinea dos.", encoding="utf-8")
    parsed = parse_document("a.txt", txt.read_bytes())
    assert "Linea uno." in parsed.text and "Linea dos." in parsed.text


def test_parse_pdf_preserves_page_numbers(tmp_path):
    pdf = tmp_path / "doc.pdf"
    write_simple_pdf([f"Linea {i} de la pagina" for i in range(45)], str(pdf))
    parsed = parse_document("doc.pdf", pdf.read_bytes())
    assert [p.page for p in parsed.pages] == [1, 2]
    assert "Linea 44" in parsed.pages[1].text


def test_parse_docx_extracts_paragraphs(tmp_path):
    docx = tmp_path / "doc.docx"
    write_simple_docx(["Titulo del documento", "Parrafo con contenido real."], str(docx))
    parsed = parse_document("doc.docx", docx.read_bytes())
    assert "Titulo del documento" in parsed.text
    assert "Parrafo con contenido real." in parsed.text


def test_parse_rejects_unsupported_extension():
    with pytest.raises(ParseError):
        parse_document("file.xyz", b"data")


def test_parse_rejects_corrupt_pdf():
    with pytest.raises(ParseError):
        parse_document("broken.pdf", b"%PDF-1.4 this is not really a pdf")


def test_parse_rejects_empty_text():
    with pytest.raises(ParseError):
        parse_document("empty.txt", b"   ")


def test_parse_survives_latin1_encoding():
    parsed = parse_document("l.txt", "Casa en Carepa \xf1".encode("latin-1"))
    assert "Carepa" in parsed.text


# --------------------------------------------------------------------- chunking
def test_chunking_respects_max_size_and_overlap():
    paragraphs = [("x" * 400, 1), ("y" * 400, 1), ("z" * 400, 2)]
    chunks = split_into_chunks(paragraphs, max_chars=900)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.content) <= 1000


def test_chunking_tracks_section_and_page():
    paragraphs = [("Articulo 5 Sobre mascotas", 3), ("Se permiten mascotas hasta 15 kg.", 3)]
    chunks = split_into_chunks(paragraphs)
    assert chunks
    assert chunks[0].page == 3
    assert chunks[0].section.lower().startswith("articulo 5")


def test_chunk_hash_is_stable_and_content_addressed():
    chunks_a = split_into_chunks([("contenido estable", None)])
    chunks_b = split_into_chunks([("contenido estable", None)])
    assert chunks_a[0].chunk_hash == chunks_b[0].chunk_hash
    chunks_c = split_into_chunks([("contenido distinto", None)])
    assert chunks_a[0].chunk_hash != chunks_c[0].chunk_hash


def test_chunking_ignores_blank_paragraphs():
    assert split_into_chunks([("", None), ("   ", None)]) == []


# ------------------------------------------------------------ file validation
def test_validate_document_accepts_allowed_types():
    validate_document("ok.pdf", b"%PDF-1.4 data")
    validate_document("ok.txt", b"data")
    validate_document("ok.md", b"data")
    validate_document("ok.docx", b"data")


def test_validate_document_rejects_bad_extension():
    with pytest.raises(DocumentValidationError) as exc:
        validate_document("malware.exe", b"data")
    assert exc.value.code == "bad_extension"


def test_validate_document_rejects_path_traversal():
    with pytest.raises(DocumentValidationError) as exc:
        validate_document("../../etc/passwd.txt", b"data")
    assert exc.value.code == "bad_name"
    with pytest.raises(DocumentValidationError):
        validate_document("sub/dir/file.txt", b"data")
    with pytest.raises(DocumentValidationError):
        validate_document("..\\windows\\evil.txt", b"data")


def test_validate_document_rejects_empty_and_oversized():
    with pytest.raises(DocumentValidationError) as exc:
        validate_document("empty.txt", b"")
    assert exc.value.code == "empty"
    from app.core.settings import get_settings

    too_big = b"x" * ((get_settings().MAX_UPLOAD_MB + 1) * 1024 * 1024)
    with pytest.raises(DocumentValidationError) as exc:
        validate_document("big.txt", too_big)
    assert exc.value.code == "too_large"


def test_safe_document_path_never_uses_client_name():
    doc_id = uuid_mod.uuid4()
    path = safe_document_path("reglamento.pdf", doc_id)
    assert str(doc_id) in path
    assert "reglamento" not in path
    assert path.endswith(".pdf")


def test_file_sha256_is_content_addressed():
    assert file_sha256(b"a") == file_sha256(b"a")
    assert file_sha256(b"a") != file_sha256(b"b")


# ------------------------------------------------------------------ ingestion
async def test_save_document_persists_metadata_and_file(session, tmp_path):
    content = f"Documento de prueba {uuid_mod.uuid4()}\n\nContenido con datos.".encode()
    doc, created = await save_document(
        session, filename=f"prueba_{uuid_mod.uuid4().hex[:8]}.txt", data=content,
        title="Documento de prueba", document_type="general",
    )
    assert created is True
    assert doc.status.value == "PENDING"
    assert doc.file_hash == file_sha256(content)
    assert doc.version == 1
    import os

    assert os.path.exists(doc.file_path)
    await session.rollback()


async def test_duplicate_content_is_not_reprocessed(session):
    content = f"Contenido unico {uuid_mod.uuid4()}".encode()
    name = f"dup_{uuid_mod.uuid4().hex[:8]}.txt"
    first, created_first = await save_document(session, filename=name, data=content)
    assert created_first is True
    second, created_second = await save_document(session, filename=name, data=content)
    assert created_second is False
    assert second.id == first.id
    await session.rollback()


async def test_changed_content_creates_new_version(session):
    name = f"version_{uuid_mod.uuid4().hex[:8]}.txt"
    first, changed = await save_document(session, filename=name, data=b"version uno")
    assert changed is True
    await process_document(session, first.id)
    assert first.version == 1

    # same filename, new content → same row, version bumped, needs reprocess
    second, changed_again = await save_document(session, filename=name, data=b"version dos")
    assert changed_again is True
    assert second.id == first.id
    assert second.version == 2
    assert second.file_hash == file_sha256(b"version dos")
    assert second.status.value == "PENDING"
    assert second.processed_at is None

    # byte-identical content is a no-op (dedupe by hash)
    _, changed_same = await save_document(session, filename=name, data=b"version dos")
    assert changed_same is False
    assert second.version == 2
    await session.rollback()


async def test_process_document_builds_traceable_chunks(session):
    doc, _ = await save_document(
        session,
        filename=f"trace_{uuid_mod.uuid4().hex[:8]}.txt",
        data=b"Parrafo uno con suficiente contenido para generar un chunk util.\n\nParrafo dos igualmente extenso.",
        title="Trazabilidad",
        document_type="reglamento",
    )
    await process_document(session, doc.id)
    assert doc.status.value == "READY"
    assert doc.chunk_count >= 1
    assert doc.processed_at is not None
    assert doc.embedding_version

    from sqlalchemy import select

    from app.database.models import DocumentChunk

    chunks = (
        await session.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    ).scalars().all()
    assert chunks
    for chunk in chunks:
        assert chunk.document_id == doc.id
        assert chunk.filename == doc.filename
        assert chunk.document_type == "reglamento"
        assert chunk.content
        assert chunk.chunk_hash
        assert chunk.embedding is not None
    await session.rollback()


async def test_ingest_directory_is_idempotent(tmp_path, session):
    from app.core.settings import get_settings

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    marker = uuid_mod.uuid4().hex[:10]
    (inbox / f"doc_{marker}.txt").write_text(
        f"Documento {marker}.\n\nEl Proyecto Zeta cuenta con 42 apartamentos.", encoding="utf-8"
    )
    (inbox / ".hidden").write_text("ignorado", encoding="utf-8")
    (inbox / "notas.exe").write_bytes(b"binary")

    report = await ingest_directory(session, str(inbox))
    by_name = {r["file"]: r for r in report}
    assert by_name[f"doc_{marker}.txt"]["ok"] is True
    assert by_name[f"doc_{marker}.txt"]["chunks"] >= 1
    assert by_name["notas.exe"]["ok"] is False
    assert ".hidden" not in by_name

    # re-ingest: same hash → skipped, never duplicated
    second = await ingest_directory(session, str(inbox))
    reused = {r["file"]: r for r in second}
    assert reused[f"doc_{marker}.txt"].get("skipped") or reused[f"doc_{marker}.txt"]["ok"]

    from sqlalchemy import func, select

    from app.database.models import Document

    count = (
        await session.execute(
            select(func.count()).select_from(Document).where(Document.filename == f"doc_{marker}.txt")
        )
    ).scalar()
    assert count == 1
    assert get_settings().DOCUMENTS_PATH.endswith("documents_test")

    # ingest_directory commitea el doc en la BD compartida de sesión: borrarlo
    # evita que el chunk "Proyecto Zeta … 42 apartamentos" contamine el corpus
    # de RAG de OTROS tests (flakiness determinista en test_e2e full_journey).
    await session.execute(delete(Document).where(Document.filename == f"doc_{marker}.txt"))
    await session.commit()


# ------------------------------------------------------------------ retrieval
async def test_retrieval_finds_seeded_project_fact(session):
    chunks = await rag_retrieval.retrieve_chunks(session, "cuantos apartamentos tiene el Proyecto X", k=5)
    assert chunks, "RAG must retrieve the seeded reglamento"
    joined = " ".join(c.content for c in chunks)
    assert "120" in joined
    top = chunks[0]
    assert top.filename
    assert top.document_title
    assert top.score > 0


async def test_retrieval_returns_page_and_metadata_for_citation(session):
    chunks = await rag_retrieval.retrieve_chunks(session, "reglamento proyecto X", k=3)
    assert chunks
    assert any(c.page for c in chunks), "PDF chunks must keep their page for citations"


async def test_retrieval_empty_query_returns_nothing(session):
    assert await rag_retrieval.retrieve_chunks(session, "   ") == []


async def test_retrieval_respects_k(session):
    chunks = await rag_retrieval.retrieve_chunks(session, "proyecto", k=2)
    assert len(chunks) <= 2


async def test_retrieval_only_returns_ready_documents(session, tmp_path):
    """A PENDING document must never be retrievable."""
    doc, _ = await save_document(
        session, filename=f"pending_{uuid_mod.uuid4().hex[:8]}.txt",
        data=b"Palabraunicaequis busca el secreto marmolado.",
    )
    assert doc.status.value == "PENDING"
    chunks = await rag_retrieval.retrieve_chunks(session, "marmolado", k=5)
    assert all(c.document_id != doc.id for c in chunks)
    await session.rollback()

