import io
import zipfile

import pytest

from trustdesk_ai.ingestion.parsers import files
from trustdesk_ai.ingestion.parsers.files import UnsupportedFileError, parse_docx


def test_docx_zip_bomb_rejected_before_parsing():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"\0" * (30 * 1024 * 1024))  # 30 MB of zeros compresses to ~30 KB
    data = buf.getvalue()
    assert len(data) < 200_000
    with pytest.raises(UnsupportedFileError, match="unsafe size"):
        parse_docx(data)


def test_pdf_page_cap(monkeypatch):
    class FakeReader:
        is_encrypted = False
        pages = [object()] * (files.MAX_PDF_PAGES + 1)
        metadata = None

        def __init__(self, _):
            pass

    import pypdf

    monkeypatch.setattr(pypdf, "PdfReader", FakeReader)
    with pytest.raises(UnsupportedFileError, match="pages"):
        files.parse_pdf(b"%PDF-1.7")
