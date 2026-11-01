import ipaddress

import httpx
import pytest

from trustdesk_ai.security import ssrf
from trustdesk_ai.security.ssrf import BlockedURLError, is_public_ip, safe_fetch, validate_url

ALLOW = ["example.com"]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://example.com/",
        "ftp://example.com/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://2130706433/",  # decimal 127.0.0.1
        "http://0x7f.1/",
        "http://localhost/",
        "http://foo.localhost/",
        "http://metadata.google.internal/",
        "http://user:pass@example.com/",
        "http://example.com:8080/",
        "http://evil.com/",
        "http://example.com.evil.com/",
        "http://notexample.com/",
    ],
)
def test_blocked_urls(url):
    with pytest.raises(BlockedURLError):
        validate_url(url, ALLOW)


@pytest.mark.parametrize("url", ["https://example.com/", "http://www.example.com/a?b=1", "https://EXAMPLE.com./x"])
def test_allowed_urls(url):
    assert validate_url(url, ALLOW).host.endswith("example.com")


@pytest.mark.parametrize(
    "ip,public",
    [
        ("8.8.8.8", True),
        ("10.0.0.1", False),
        ("172.16.0.1", False),
        ("192.168.1.1", False),
        ("127.0.0.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("0.0.0.0", False),
        ("::1", False),
        ("fe80::1", False),
        ("fc00::1", False),
        ("::ffff:127.0.0.1", False),  # IPv4-mapped loopback
        ("::ffff:8.8.8.8", True),
        ("fd00:ec2::254", False),
        ("2606:4700:4700::1111", True),
    ],
)
def test_is_public_ip(ip, public):
    assert is_public_ip(ipaddress.ip_address(ip)) is public


async def test_dns_rebinding_blocked_at_connect(monkeypatch):
    async def fake_getaddrinfo(host, port, type=0):
        return [(2, 1, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(ssrf.anyio, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(BlockedURLError, match="non-public"):
        await safe_fetch("http://example.com/", ALLOW)


async def test_mixed_public_private_answer_rejected(monkeypatch):
    async def fake_getaddrinfo(host, port, type=0):
        return [(2, 1, 6, "", ("93.184.216.34", port)), (2, 1, 6, "", ("10.0.0.5", port))]

    monkeypatch.setattr(ssrf.anyio, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(BlockedURLError):
        await ssrf.resolve_public("example.com", 80)


async def test_redirect_to_disallowed_target_is_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(BlockedURLError):
            await safe_fetch("https://example.com/", ALLOW, client=client)


async def test_redirect_within_allowlist_followed_and_size_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(301, headers={"location": "/home"})
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=b"x" * 100)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await safe_fetch("https://example.com/", ALLOW, client=client)
        assert result.url == "https://example.com/home" and result.content_type == "text/html"
        with pytest.raises(BlockedURLError, match="too large"):
            await safe_fetch("https://example.com/", ALLOW, client=client, max_bytes=10)
