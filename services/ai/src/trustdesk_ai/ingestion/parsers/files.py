"""PDF and DOCX -> typed blocks."""

from __future__ import annotations

import io
import re
import zipfile

from trustdesk_ai.ingestion.types import Block, ParsedDocument

_WS = re.compile(r"[ \t]+")


class UnsupportedFileError(ValueError):
    """File is not a valid PDF/DOCX or cannot be read. Message is admin-safe."""


def parse_pdf(data: bytes) -> ParsedDocument:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise UnsupportedFileError("encrypted PDFs are not supported")
        blocks: list[Block] = []
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            # PDF text has no reliable structure: paragraphs are separated by blank lines.
            for para in re.split(r"\n\s*\n", text):
                cleaned = _WS.sub(" ", para.replace("\n", " ")).strip()
                if cleaned:
                    blocks.append(Block("paragraph", cleaned, page_number=number))
        meta = reader.metadata
        title = str(meta.title) if meta and meta.title else None
    except PdfReadError as exc:
        raise UnsupportedFileError("the PDF could not be read") from exc
    if not blocks:
        raise UnsupportedFileError("no text found in the PDF (scanned PDFs need OCR, which is not supported)")
    return ParsedDocument(blocks=blocks, title=title, metadata={"pages": str(len(reader.pages))})


def parse_docx(data: bytes) -> ParsedDocument:
    import docx
    from docx.opc.exceptions import PackageNotFoundError
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(io.BytesIO(data))
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise UnsupportedFileError("the DOCX file could not be read") from exc

    blocks: list[Block] = []
    list_items: list[str] = []

    def flush_list() -> None:
        if list_items:
            blocks.append(Block("list", "\n".join(f"- {i}" for i in list_items)))
            list_items.clear()

    for item in document.iter_inner_content():
        if isinstance(item, Table):
            flush_list()
            rows = [[c.text.strip().replace("|", "/") for c in r.cells] for r in item.rows]
            if rows:
                width = max(len(r) for r in rows)
                lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
                lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                blocks.append(Block("table", "\n".join(lines)))
            continue
        assert isinstance(item, Paragraph)
        text = item.text.strip()
        style = (item.style.name if item.style is not None else "") or ""
        if not text:
            continue
        if style.startswith("Heading") or style == "Title":
            flush_list()
            level = int(style.split()[-1]) if style.split()[-1].isdigit() else 1
            blocks.append(Block("heading", text, level=level))
        elif "List" in style:
            list_items.append(text)
        else:
            flush_list()
            blocks.append(Block("paragraph", text))
    flush_list()
    title = document.core_properties.title or None
    if not blocks:
        raise UnsupportedFileError("no text found in the DOCX file")
    return ParsedDocument(blocks=blocks, title=title)


PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"


def sniff_file_type(filename: str, data: bytes) -> str:
    """Trust content, not the client-supplied name or MIME type."""
    name = filename.lower()
    if name.endswith(".pdf") and data.startswith(PDF_MAGIC):
        return "pdf"
    if name.endswith(".docx") and data.startswith(ZIP_MAGIC):
        return "docx"
    raise UnsupportedFileError("only .pdf and .docx files are accepted")
