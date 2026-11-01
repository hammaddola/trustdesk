"""Login, sessions and principal resolution. Tokens are random; only their SHA-256 is stored."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from trustdesk_ai.auth.passwords import hash_password, needs_rehash, verify_password
from trustdesk_ai.db.models import Session, User

Role = Literal["owner", "admin"]
ROLE_RANK: dict[str, int] = {"admin": 1, "owner": 2}


@dataclass(frozen=True)
class Membership:
    tenant_id: UUID
    tenant_name: str
    role: Role


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    email: str
    session_id: UUID
    tenant_id: UUID
    role: Role
    memberships: tuple[Membership, ...]

    def has_role(self, minimum: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[minimum]


class AuthError(Exception):
    """Generic authentication failure; never says which part was wrong."""


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def ip_hash(ip: str | None) -> bytes | None:
    return hashlib.sha256(ip.encode()).digest() if ip else None


async def memberships(db: AsyncSession, user_id: UUID) -> tuple[Membership, ...]:
    rows = await db.execute(text("SELECT tenant_id, tenant_name, role FROM user_memberships(:u)"), {"u": user_id})
    return tuple(Membership(r.tenant_id, r.tenant_name, r.role) for r in rows)


async def login(
    db: AsyncSession, email: str, password: str, *, ttl_hours: int, ip: str | None, user_agent: str | None
) -> tuple[str, Principal]:
    user = (await db.execute(select(User).where(User.email == email.strip().lower()))).scalar_one_or_none()
    if not verify_password(user.password_hash if user else None, password) or user is None or not user.is_active:
        raise AuthError("invalid email or password")
    mems = await memberships(db, user.id)
    if not mems:
        raise AuthError("invalid email or password")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    session = Session(
        user_id=user.id,
        token_hash=token_hash(token),
        active_tenant_id=mems[0].tenant_id,
        expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
        ip_hash=ip_hash(ip),
        user_agent=(user_agent or "")[:300],
    )
    db.add(session)
    await db.flush()
    return token, Principal(user.id, user.email, session.id, mems[0].tenant_id, mems[0].role, mems)


async def resolve(db: AsyncSession, token: str) -> Principal:
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(Session, User)
            .join(User, User.id == Session.user_id)
            .where(Session.token_hash == token_hash(token), Session.expires_at > now, User.is_active.is_(True))
        )
    ).first()
    if row is None:
        raise AuthError("session expired")
    session, user = row
    mems = await memberships(db, user.id)
    active = next((m for m in mems if m.tenant_id == session.active_tenant_id), None)
    if active is None:  # membership revoked since login
        raise AuthError("session expired")
    if (now - session.last_seen_at) > timedelta(minutes=5):
        session.last_seen_at = now
    return Principal(user.id, user.email, session.id, active.tenant_id, active.role, mems)


async def switch_tenant(db: AsyncSession, principal: Principal, tenant_id: UUID) -> None:
    if not any(m.tenant_id == tenant_id for m in principal.memberships):
        raise AuthError("not a member of this organization")
    await db.execute(update(Session).where(Session.id == principal.session_id).values(active_tenant_id=tenant_id))


async def logout(db: AsyncSession, token: str) -> None:
    await db.execute(delete(Session).where(Session.token_hash == token_hash(token)))


async def purge_expired(db: AsyncSession) -> None:
    await db.execute(delete(Session).where(Session.expires_at <= datetime.now(UTC)))
