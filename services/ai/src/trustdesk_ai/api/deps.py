"""Admin authentication dependencies. Every admin route checks the session server-side."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from trustdesk_ai.auth.service import AuthError, Principal, Role, resolve
from trustdesk_ai.db.session import global_session, tenant_session


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 128:
        raise HTTPException(401, "authentication required")
    return token


async def current_principal(request: Request, token: Annotated[str, Depends(bearer_token)]) -> Principal:
    try:
        async with global_session() as db:
            principal = await resolve(db, token)
    except AuthError as exc:
        raise HTTPException(401, "session expired, please sign in again") from exc
    request.state.principal = principal
    return principal


def require(role: Role) -> Callable[..., Coroutine[Any, Any, Principal]]:
    async def dep(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if not principal.has_role(role):
            raise HTTPException(403, "you do not have permission for this action")
        return principal

    return dep


AdminPrincipal = Annotated[Principal, Depends(require("admin"))]
OwnerPrincipal = Annotated[Principal, Depends(require("owner"))]


async def tenant_db(principal: AdminPrincipal) -> AsyncIterator[AsyncSession]:
    """Tenant-scoped transaction for the principal's active organization (RLS applies)."""
    async with tenant_session(principal.tenant_id, principal.user_id) as db:
        yield db


TenantDB = Annotated[AsyncSession, Depends(tenant_db)]
