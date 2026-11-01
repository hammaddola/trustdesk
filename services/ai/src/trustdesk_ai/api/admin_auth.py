"""Admin login/logout/session and first-run setup (owner + organization creation)."""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import re
import secrets
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from trustdesk_ai.api.deps import AdminPrincipal, bearer_token
from trustdesk_ai.api.public import client_ip
from trustdesk_ai.audit import audit
from trustdesk_ai.auth import service as auth
from trustdesk_ai.auth.passwords import hash_password, validate_new_password
from trustdesk_ai.config.settings import get_settings
from trustdesk_ai.db.models import TenantMembership, TenantSettings, User
from trustdesk_ai.db.session import global_session, tenant_session
from trustdesk_ai.providers.ratelimit.postgres import PostgresRateLimitStore, bucket_key

router = APIRouter(prefix="/v1/admin", tags=["admin-auth"])


def ip_network_key(ip: str) -> str:
    """IPv6 clients usually control a whole /64, so throttle per /64; IPv4 per address."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


_limiter = PostgresRateLimitStore()
LOGIN_WINDOW = 900  # seconds


class MembershipOut(BaseModel):
    tenant_id: UUID
    tenant_name: str
    role: Literal["owner", "admin"]


class SessionOut(BaseModel):
    user_id: UUID
    email: str
    tenant_id: UUID
    role: Literal["owner", "admin"]
    memberships: list[MembershipOut]
    mode: Literal["simple", "platform"]


class LoginOut(SessionOut):
    token: str
    expires_in_seconds: int


def _session_out(p: auth.Principal) -> SessionOut:
    return SessionOut(
        user_id=p.user_id,
        email=p.email,
        tenant_id=p.tenant_id,
        role=p.role,
        memberships=[
            MembershipOut(tenant_id=m.tenant_id, tenant_name=m.tenant_name, role=m.role) for m in p.memberships
        ],
        mode=get_settings().trustdesk_mode,
    )


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


@router.post("/auth/login", response_model=LoginOut)
async def login(body: LoginIn, request: Request) -> LoginOut:
    ip = client_ip(request)
    email = body.email.lower()
    # Throttling (all checks happen BEFORE the password is verified, atomically per key):
    #  - client network (IPv6 /64): every attempt counts, 30 / 15 min, never refunded - so a valid account
    #    cannot be used to "earn back" attempts for spraying other accounts.
    #  - (email, client network): 10 / 15 min; refunded on success (same window only), so only failures count.
    #  - email alone: no hard lockout (others could lock the owner out); after 20 failures from anywhere,
    #    every attempt is slowed down progressively.
    network = ip_network_key(ip)
    ok_ip = await _limiter.hit(bucket_key("login-ip", network), 30, LOGIN_WINDOW)
    pair_key = bucket_key("login-fail", email, network)
    ok_pair, pair_window = await _limiter.reserve(pair_key, 10, LOGIN_WINDOW)
    if not (ok_ip and ok_pair):
        raise HTTPException(429, "too many sign-in attempts, try again in 15 minutes")
    account_key = bucket_key("login-fail-account", email)
    account_failures = await _limiter.count(account_key, LOGIN_WINDOW)
    if account_failures >= 20:
        await asyncio.sleep(min(0.25 * (account_failures - 19), 5.0))
    settings = get_settings()
    try:
        async with global_session() as db:
            token, principal = await auth.login(
                db,
                body.email,
                body.password,
                ttl_hours=settings.session_ttl_hours,
                ip=ip,
                user_agent=request.headers.get("user-agent"),
            )
    except auth.AuthError as exc:
        await _limiter.hit(account_key, 1_000_000, LOGIN_WINDOW)  # counter only; never blocks on its own
        raise HTTPException(401, "invalid email or password") from exc
    await _limiter.refund(pair_key, pair_window)
    await audit(principal.tenant_id, principal.user_id, "auth.login", request=request)
    return LoginOut(
        **_session_out(principal).model_dump(), token=token, expires_in_seconds=settings.session_ttl_hours * 3600
    )


@router.post("/auth/logout", status_code=204)
async def logout(token: Annotated[str, Depends(bearer_token)]) -> None:
    async with global_session() as db:
        await auth.logout(db, token)


@router.get("/auth/session", response_model=SessionOut)
async def session(principal: AdminPrincipal) -> SessionOut:
    return _session_out(principal)


class SwitchIn(BaseModel):
    tenant_id: UUID


@router.post("/auth/switch-tenant", response_model=SessionOut)
async def switch_tenant(body: SwitchIn, principal: AdminPrincipal, request: Request) -> SessionOut:
    try:
        async with global_session() as db:
            await auth.switch_tenant(db, principal, body.tenant_id)
    except auth.AuthError as exc:
        raise HTTPException(403, str(exc)) from exc
    role = next(m.role for m in principal.memberships if m.tenant_id == body.tenant_id)
    return _session_out(
        auth.Principal(
            principal.user_id, principal.email, principal.session_id, body.tenant_id, role, principal.memberships
        )
    )


# ---------------- first-run setup ----------------


class SetupStatus(BaseModel):
    needs_setup: bool
    mode: Literal["simple", "platform"]


@router.get("/setup/status", response_model=SetupStatus)
async def setup_status() -> SetupStatus:
    async with global_session() as db:
        users = (await db.execute(text("SELECT count_users()"))).scalar_one()
    return SetupStatus(needs_setup=users == 0, mode=get_settings().trustdesk_mode)


class SetupIn(BaseModel):
    setup_token: str = Field(min_length=1, max_length=256)
    organization_name: str = Field(min_length=1, max_length=200)
    website_url: str = Field(min_length=4, max_length=2048)
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    display_name: str | None = Field(default=None, max_length=200)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "org"
    return slug if len(slug) >= 2 else f"{slug}-org"


async def create_tenant(db: AsyncSession, name: str, *, is_demo: bool = False) -> UUID:
    slug = _slugify(name) + "-" + secrets.token_hex(3)
    key = "td_pk_" + secrets.token_urlsafe(18)
    result = await db.execute(
        text("SELECT create_tenant(:s, :n, :k, :d)"), {"s": slug, "n": name, "k": key, "d": is_demo}
    )
    tenant_id: UUID = result.scalar_one()
    return tenant_id


@router.post("/setup", response_model=LoginOut)
async def setup(body: SetupIn, request: Request) -> LoginOut:
    """Creates the first owner and organization. Only works while no users exist and with the setup token."""
    from trustdesk_ai.security.ssrf import BlockedURLError, validate_url
    from trustdesk_ai.tenancy.public import normalize_origin

    expected = get_settings().trustdesk_setup_token
    if expected is None:
        raise HTTPException(409, "TRUSTDESK_SETUP_TOKEN is not configured on the server")
    if not await _limiter.hit(bucket_key("setup", client_ip(request)), 10, 900):
        raise HTTPException(429, "too many attempts")
    if not hmac.compare_digest(body.setup_token.encode(), expected.get_secret_value().encode()):
        raise HTTPException(403, "invalid setup token")
    try:
        validate_new_password(body.password)
        checked = validate_url(body.website_url, None)
    except (ValueError, BlockedURLError) as exc:
        raise HTTPException(422, str(exc)) from exc
    origin = normalize_origin(checked.url)
    domain = checked.host.removeprefix("www.")

    async with global_session() as db:
        await db.execute(text("SELECT pg_advisory_xact_lock(7243001)"))  # serialize concurrent setup attempts
        if (await db.execute(text("SELECT count_users()"))).scalar_one() != 0:
            raise HTTPException(409, "setup has already been completed")
        user = User(
            email=body.email.lower(), password_hash=hash_password(body.password), display_name=body.display_name
        )
        db.add(user)
        await db.flush()
        user_id = user.id
        tenant_id = await create_tenant(db, body.organization_name)

    async with tenant_session(tenant_id) as db:
        db.add(TenantMembership(tenant_id=tenant_id, user_id=user_id, role="owner"))
        db.add(
            TenantSettings(
                tenant_id=tenant_id,
                organization_name=body.organization_name,
                website_urls=[checked.url],
                allowed_domains=[domain],
                allowed_origins=[o for o in {origin, normalize_origin(f"https://www.{domain}")} if o],
            )
        )
    await audit(tenant_id, user_id, "setup.completed", request=request)
    return await login(LoginIn(email=body.email, password=body.password), request)
