import gzip
import io

import pytest

from trustdesk_ai.ingestion.parsers.files import UnsupportedFileError, parse_docx, sniff_file_type
from trustdesk_ai.ingestion.parsers.html import parse_html
from trustdesk_ai.ingestion.sitemap import parse_sitemap

HTML = """<!doctype html><html lang="en-GB"><head><title>Services | Acme</title>
<link rel="canonical" href="/services"></head><body>
<nav><a href="/about">About</a></nav>
<div class="cookie-banner"><p>We use cookies</p></div>
<main>
  <h1>Services</h1><p>We design websites.</p>
  <h2>Packages</h2>
  <ul><li>Starter <p>nested</p></li><li>Growth</li></ul>
  <table><tr><th>Plan</th><th>Price</th></tr><tr><td>Starter</td><td>$1,500</td></tr></table>
  <script>alert('x')</script>
  <a href="https://acme.example/contact#form">Contact</a>
</main><footer><p>Copyright</p></footer></body></html>"""


def test_html_structure_and_boilerplate_removed():
    page = parse_html(HTML, "https://acme.example/services?x=1")
    doc = page.document
    kinds = [(b.kind, b.text) for b in doc.blocks]
    assert ("heading", "Services") in kinds and ("paragraph", "We design websites.") in kinds
    assert ("list", "- Starter nested\n- Growth") in kinds
    assert any(k == "table" and "| Starter | $1,500 |" in t for k, t in kinds)
    flat = " ".join(t for _, t in kinds)
    assert "cookies" not in flat and "Copyright" not in flat and "alert" not in flat
    assert sum(1 for _, t in kinds if "nested" in t) == 1  # no duplicate emission of nested elements
    assert doc.title == "Services | Acme" and doc.language == "en"
    assert page.canonical_url == "https://acme.example/services"
    assert "https://acme.example/contact" in page.links  # fragment stripped


def test_sitemap_urlset_index_and_gzip():
    urlset = b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://a.example/x</loc></url></urlset>'
    assert parse_sitemap(urlset) == (["https://a.example/x"], [])
    index = b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://a.example/s2.xml</loc></sitemap></sitemapindex>'
    assert parse_sitemap(index) == ([], ["https://a.example/s2.xml"])
    assert parse_sitemap(gzip.compress(urlset))[0] == ["https://a.example/x"]
    assert parse_sitemap(b"not xml") == ([], [])


def test_sitemap_entities_not_expanded():
    xxe = b'<?xml version="1.0"?><!DOCTYPE u [<!ENTITY x SYSTEM "file:///etc/passwd">]><urlset><url><loc>&x;</loc></url></urlset>'
    pages, _ = parse_sitemap(xxe)
    assert all("root:" not in p for p in pages)


def test_file_sniffing_rejects_mismatched_content():
    with pytest.raises(UnsupportedFileError):
        sniff_file_type("evil.pdf", b"<html>not a pdf</html>")
    with pytest.raises(UnsupportedFileError):
        sniff_file_type("payload.exe", b"MZ...")
    assert sniff_file_type("a.PDF", b"%PDF-1.7 ...") == "pdf"


def test_docx_headings_lists_tables():
    import docx

    d = docx.Document()
    d.add_heading("Pricing", level=1)
    d.add_paragraph("Our plans are below.")
    d.add_paragraph("Starter", style="List Bullet")
    d.add_paragraph("Growth", style="List Bullet")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text, t.cell(1, 0).text, t.cell(1, 1).text = "Plan", "Price", "Starter", "$1,500"
    buf = io.BytesIO()
    d.save(buf)
    doc = parse_docx(buf.getvalue())
    kinds = [(b.kind, b.text) for b in doc.blocks]
    assert kinds[0] == ("heading", "Pricing")
    assert ("list", "- Starter\n- Growth") in kinds
    assert any(k == "table" and "| Starter | $1,500 |" in t for k, t in kinds)


def test_corrupt_docx_rejected():
    with pytest.raises(UnsupportedFileError):
        parse_docx(b"PK\x03\x04garbage")
