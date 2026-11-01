"""Sitemap discovery and parsing (urlset + sitemapindex), bounded and SSRF-safe."""

from __future__ import annotations

import gzip
import io
from collections.abc import Iterable
from urllib.parse import urljoin

from lxml import etree

from trustdesk_ai.security.ssrf import BlockedURLError, safe_fetch

_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
MAX_SITEMAP_BYTES = 50 * 1024 * 1024
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False)


def parse_sitemap(xml: bytes) -> tuple[list[str], list[str]]:
    """Returns (page_urls, child_sitemap_urls)."""
    if xml[:2] == b"\x1f\x8b":
        # Bounded read: never inflate more than MAX_SITEMAP_BYTES (decompression-bomb guard).
        with gzip.GzipFile(fileobj=io.BytesIO(xml)) as gz:
            xml = gz.read(MAX_SITEMAP_BYTES + 1)
        if len(xml) > MAX_SITEMAP_BYTES:
            return [], []
    try:
        root = etree.fromstring(xml, parser=_PARSER)
    except etree.XMLSyntaxError:
        return [], []
    locs = [(el.text or "").strip() for el in root.iter(f"{_NS}loc", "loc")]
    locs = [loc for loc in locs if loc]
    if root.tag.endswith("sitemapindex"):
        return [], locs
    return locs, []


async def discover_urls(
    root_url: str, allowed_domains: Iterable[str], max_pages: int, sitemap_url: str | None = None
) -> list[str]:
    """Collect page URLs from the sitemap (explicit, robots.txt-declared, or /sitemap.xml)."""
    domains = list(allowed_domains)
    queue = [sitemap_url] if sitemap_url else []
    if not queue:
        try:
            robots = await safe_fetch(urljoin(root_url, "/robots.txt"), domains, max_bytes=512 * 1024)
            if robots.status_code == 200:
                for line in robots.body.decode("utf-8", "replace").splitlines():
                    if line.lower().startswith("sitemap:"):
                        queue.append(line.split(":", 1)[1].strip())
        except BlockedURLError:
            pass  # robots.txt unavailable or off-domain: fall back to the default location
        queue = queue or [urljoin(root_url, "/sitemap.xml")]

    pages: list[str] = []
    seen: set[str] = set()
    while queue and len(seen) < 50 and len(pages) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = await safe_fetch(url, domains, max_bytes=20 * 1024 * 1024)
        except BlockedURLError:
            continue
        if resp.status_code != 200:
            continue
        found, children = parse_sitemap(resp.body)
        pages.extend(found)
        queue.extend(children)
    return list(dict.fromkeys(pages))[:max_pages]
