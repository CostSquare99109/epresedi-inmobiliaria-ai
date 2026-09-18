"""Document parsing for PDF / DOCX / TXT / MD — pure Python, no lxml.

Includes minimal PDF/DOCX *writers* used by the seed script to generate real
test documents without external binaries.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


@dataclass
class ParsedPage:
    page: int | None
    text: str


@dataclass
class ParsedDocument:
    text: str
    pages: list[ParsedPage]


class ParseError(Exception):
    pass


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_pdf(data: bytes) -> ParsedDocument:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages: list[ParsedPage] = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                content = page.extract_text() or ""
            except Exception:
                content = ""
            if content.strip():
                pages.append(ParsedPage(page=i, text=_clean(content)))
        if not pages:
            raise ParseError("PDF has no extractable text (scanned image?)")
        return ParsedDocument(text="\n\n".join(p.text for p in pages), pages=pages)
    except ParseError:
        raise
    except Exception as e:
        raise ParseError(f"invalid PDF: {e}") from e


_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def parse_docx(data: bytes) -> ParsedDocument:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read("word/document.xml")
        root = ET.fromstring(xml)
        paragraphs: list[str] = []
        for p in root.iter(f"{{{ _DOCX_NS['w'] }}}p"):
            texts = [t.text or "" for t in p.iter(f"{{{ _DOCX_NS['w'] }}}t")]
            line = "".join(texts).strip()
            if line:
                paragraphs.append(line)
        if not paragraphs:
            raise ParseError("DOCX has no text paragraphs")
        full = _clean("\n".join(paragraphs))
        return ParsedDocument(text=full, pages=[ParsedPage(page=None, text=full)])
    except ParseError:
        raise
    except Exception as e:
        raise ParseError(f"invalid DOCX: {e}") from e


def parse_text(data: bytes) -> ParsedDocument:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1", errors="replace")
    if not text.strip():
        raise ParseError("text file is empty")
    text = _clean(text)
    return ParsedDocument(text=text, pages=[ParsedPage(page=None, text=text)])


def parse_document(filename: str, data: bytes) -> ParsedDocument:
    """Dispatch by extension. Caller must validate the extension first."""
    name = filename.lower()
    if name.endswith(".pdf"):
        return parse_pdf(data)
    if name.endswith(".docx"):
        return parse_docx(data)
    if name.endswith((".txt", ".md")):
        return parse_text(data)
    raise ParseError(f"unsupported extension for {filename!r}")


def detect_mime(data: bytes, filename: str) -> str:
    """Sniff magic bytes; do not trust the client-provided name alone."""
    head = data[:8]
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head.startswith(b"PK\x03\x04"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext in (".txt", ".md"):
        return "text/markdown" if ext == ".md" else "text/plain"
    return "application/octet-stream"


def guess_mime_from_extension(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    return {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain",
        "md": "text/markdown",
    }.get(ext, "application/octet-stream")


# ------------------------------------------------------------- minimal writers
def _pdf_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def write_simple_pdf(lines: list[str], out_path: str) -> None:
    """Writes a valid PDF (Helvetica 11, correct xref offsets) — no deps."""
    per_page = 40
    chunks = [lines[i:i + per_page] for i in range(0, len(lines), per_page)] or [[]]
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    pages_id = add(b"<< /Type /Pages /Kids [] /Count 0 >>")
    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    for chunk in chunks:
        content = io.BytesIO()
        content.write(b"BT /F1 11 Tf 56 760 Td 16 TL\n")
        for line in chunk:
            safe = _pdf_escape(line)[:95]
            content.write(f"({safe}) Tj T*\n".encode("latin-1", errors="replace"))
        content.write(b"ET\n")
        stream = content.getvalue()
        cid = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream")
        pid = add(
            b"<< /Type /Page /Parent " + str(pages_id).encode() + b" 0 R /MediaBox [0 0 612 792]"
            b" /Contents " + str(cid).encode() + b" 0 R /Resources << /Font << /F1 "
            + str(font_id).encode() + b" 0 R >> >> >>"
        )
        page_ids.append(pid)
    kids = b" ".join(f"{pid} 0 R".encode() for pid in page_ids)
    objects[pages_id - 1] = (
        b"<< /Type /Pages /Kids [ " + kids + b" ] /Count " + str(len(page_ids)).encode() + b" >>"
    )
    catalog_id = add(b"<< /Type /Catalog /Pages " + str(pages_id).encode() + b" 0 R >>")

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(buf.tell())
        buf.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref_pos = buf.tell()
    buf.write(f"xref\n0 {len(objects) + 1}\n".encode())
    buf.write(b"0000000000 65535 f \n")
    for off in offsets:
        buf.write(f"{off:010d} 00000 n \n".encode())
    buf.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    with open(out_path, "wb") as fh:
        fh.write(buf.getvalue())


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_simple_docx(paragraphs: list[str], out_path: str) -> None:
    """Writes a minimal valid DOCX (WordprocessingML) via zipfile — no lxml."""
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{_xml_escape(p)}</w:t></w:r></w:p>'
        for p in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{w}"><w:body>{body}<w:sectPr/></w:body></w:document>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)

