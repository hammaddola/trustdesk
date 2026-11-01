"""HTML -> typed blocks. Removes boilerplate (navigation, scripts, cookie banners) and keeps structure.

Fetched HTML is untrusted: it is only parsed, never executed, and its text is stored as data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup, Tag

from trustdesk_ai.ingestion.types import Block, ParsedDocument

_DROP_TAGS = [
    "script",
    "style",
    "noscript",
    "template",
    "iframe",
    "svg",
    "canvas",
    "form",
    "button",
    "nav",
    "footer",
    "header",
    "aside",
    "dialog",
]
_BOILERPLATE = re.compile(r"cookie|consent|gdpr|newsletter|popup|modal|breadcrumb|skip-link|share", re.I)
_WS = re.compile(r"\s+")


def _text(el: Tag) -> str:
    return _WS.sub(" ", el.get_text(" ", strip=True)).strip()


def _table_markdown(table: Tag) -> str:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [_text(c).replace("|", "/") for c in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


@dataclass
class ParsedPage:
    document: ParsedDocument
    canonical_url: str | None
    links: list[str]


def parse_html(html: str | bytes, base_url: str) -> ParsedPage:
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("meta", attrs={"property": "og:title"})
    og_title = title_tag.get("content") if isinstance(title_tag, Tag) else None
    title = (str(og_title) if og_title else None) or (soup.title.get_text(strip=True) if soup.title else None)
    html_tag = soup.find("html")
    lang = html_tag.get("lang") if isinstance(html_tag, Tag) else None
    canonical = soup.find("link", rel="canonical")
    canonical_url = (
        urljoin(base_url, str(canonical["href"])) if isinstance(canonical, Tag) and canonical.get("href") else None
    )

    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urldefrag(urljoin(base_url, str(a["href"]))).url
        if href.startswith(("http://", "https://")):
            links.append(href)

    for tag in soup(_DROP_TAGS):
        tag.decompose()
    for el in soup.find_all(True, attrs={"aria-hidden": "true"}):
        el.decompose()
    for el in soup.find_all(True):
        if el.decomposed or el.attrs is None:
            continue
        marker = " ".join([str(el.get("id") or ""), *[str(c) for c in (el.get("class") or [])]])
        if marker.strip() and _BOILERPLATE.search(marker) and el.name not in ("html", "body", "main", "article"):
            el.decompose()

    root = soup.find("main") or soup.find("article") or soup.body or soup
    blocks: list[Block] = []
    for el in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "table", "pre"]):
        if el.find_parent(["table", "ul", "ol", "pre"]):
            continue  # already emitted as part of its container
        if el.name in ("ul", "ol"):
            items = [_text(li) for li in el.find_all("li", recursive=False)]
            text = "\n".join(f"- {i}" for i in items if i)
            if text:
                blocks.append(Block("list", text))
        elif el.name == "table":
            if md := _table_markdown(el):
                blocks.append(Block("table", md))
        elif el.name == "pre":
            if code := el.get_text().strip():
                blocks.append(Block("code", code))
        elif el.name.startswith("h"):
            if t := _text(el):
                blocks.append(Block("heading", t, level=int(el.name[1])))
        elif t := _text(el):
            blocks.append(Block("paragraph", t))

    return ParsedPage(
        document=ParsedDocument(blocks=blocks, title=title, language=str(lang).split("-")[0].lower() if lang else None),
        canonical_url=canonical_url,
        links=list(dict.fromkeys(links)),
    )
