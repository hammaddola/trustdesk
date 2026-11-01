"""SSRF-safe outbound HTTP.

Two layers:
1. `validate_url` — scheme, port, credentials, IP literals and domain allowlist, checked before any I/O.
2. `SafeNetworkBackend` — resolves DNS *inside the connect call*, rejects the connection if any
   resolved address is non-public, and connects to the address it just validated. Validation and
   connection use the same resolution, which defeats DNS rebinding. TLS still verifies the hostname
   because httpcore passes the original host as SNI.

Redirects are followed manually so each hop is re-validated against the allowlist.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import anyio
import httpcore
import httpx

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443}
MAX_REDIRECTS = 5

# Ranges that `is_global` misses or that we block explicitly for clarity.
_EXTRA_BLOCKED = [
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
    ipaddress.ip_network("fd00:ec2::254/128"),  # AWS IMDS over IPv6
]


class BlockedURLError(ValueError):
    """The URL or its resolved address is not allowed. Message is safe to show to admins."""


def is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv6Address) and ip.sixtofour is not None:
        ip = ip.sixtofour
    if not ip.is_global or ip.is_multicast or ip.is_reserved:
        return False
    return not any(ip in net for net in _EXTRA_BLOCKED)


def normalize_host(host: str) -> str:
    host = host.strip().rstrip(".").lower()
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise BlockedURLError("invalid hostname") from exc


def host_allowed(host: str, allowed_domains: Iterable[str]) -> bool:
    host = normalize_host(host)
    for domain in allowed_domains:
        d = normalize_host(domain.removeprefix("*."))
        if host == d or host.endswith("." + d):
            return True
    return False


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        # Legacy numeric forms like "2130706433" or "0x7f.1" are resolved by getaddrinfo to IPs.
        return host.replace(".", "").replace("x", "").isalnum() and all(
            p.isdigit() or p.startswith("0x") for p in host.split(".")
        )


@dataclass(frozen=True)
class CheckedURL:
    url: str
    host: str


def validate_url(url: str, allowed_domains: Iterable[str] | None) -> CheckedURL:
    """Static checks. `allowed_domains=None` means "any public host" (used for webhooks)."""
    if len(url) > 2048:
        raise BlockedURLError("URL too long")
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedURLError("only http and https URLs are allowed")
    if parts.username or parts.password:
        raise BlockedURLError("URLs with credentials are not allowed")
    if not parts.hostname:
        raise BlockedURLError("URL has no host")
    try:
        port = parts.port
    except ValueError as exc:
        raise BlockedURLError("invalid port") from exc
    if port not in ALLOWED_PORTS:
        raise BlockedURLError("only ports 80 and 443 are allowed")
    host = normalize_host(parts.hostname)
    if _is_ip_literal(host):
        raise BlockedURLError("IP-address URLs are not allowed; use the site's domain name")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise BlockedURLError("local hostnames are not allowed")
    if allowed_domains is not None and not host_allowed(host, allowed_domains):
        raise BlockedURLError(f"{host} is not in this organization's allowed domains")
    return CheckedURL(url=parts.geturl(), host=host)


async def resolve_public(host: str, port: int) -> list[str]:
    """Resolve and require that every address is public (mixed public/private answers are rejected)."""
    try:
        infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise BlockedURLError(f"could not resolve {host}") from exc
    addresses = list(dict.fromkeys(str(info[4][0]) for info in infos))
    if not addresses:
        raise BlockedURLError(f"could not resolve {host}")
    for addr in addresses:
        if not is_public_ip(ipaddress.ip_address(addr.split("%")[0])):
            raise BlockedURLError(f"{host} resolves to a non-public address")
    return addresses


class SafeNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - signature defined by httpcore
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = await resolve_public(host, port)
        last_exc: Exception | None = None
        for addr in addresses:
            try:
                return await self._inner.connect_tcp(addr, port, timeout, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_exc = exc
        raise httpcore.ConnectError(str(last_exc))

    async def connect_unix_socket(self, *args: Any, **kwargs: Any) -> httpcore.AsyncNetworkStream:
        raise BlockedURLError("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def safe_client(timeout: float = 15.0) -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(retries=0)
    # httpx exposes no public hook for the network backend; this attribute is stable across httpx 0.2x.
    transport._pool._network_backend = SafeNetworkBackend()
    return httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,  # environment proxies would bypass the address checks
        headers={"User-Agent": "TrustDeskBot/0.1 (+https://github.com/trustdesk)"},
    )


@dataclass(frozen=True)
class FetchResult:
    url: str  # final URL after redirects
    status_code: int
    content_type: str
    body: bytes
    last_modified: str | None


async def safe_fetch(
    url: str,
    allowed_domains: Iterable[str] | None,
    *,
    max_bytes: int = 5 * 1024 * 1024,
    client: httpx.AsyncClient | None = None,
) -> FetchResult:
    domains = list(allowed_domains) if allowed_domains is not None else None
    own = client is None
    http = client or safe_client()
    try:
        current = validate_url(url, domains).url
        for _ in range(MAX_REDIRECTS + 1):
            async with http.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise BlockedURLError("redirect without location")
                    current = validate_url(urljoin(current, location), domains).url
                    continue
                declared = int(resp.headers.get("content-length") or 0)
                if declared > max_bytes:
                    raise BlockedURLError("response too large")
                body = bytearray()
                async for part in resp.aiter_bytes():
                    body.extend(part)
                    if len(body) > max_bytes:
                        raise BlockedURLError("response too large")
                return FetchResult(
                    url=current,
                    status_code=resp.status_code,
                    content_type=resp.headers.get("content-type", "").split(";")[0].strip().lower(),
                    body=bytes(body),
                    last_modified=resp.headers.get("last-modified"),
                )
        raise BlockedURLError("too many redirects")
    finally:
        if own:
            await http.aclose()
