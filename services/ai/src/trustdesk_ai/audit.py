"""Append-only audit log. Never records credentials or message content."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from starlette.requests import Request

from trustdesk_ai.auth.service import ip_hash
from trustdesk_ai.db.models import AuditLog
from trustdesk_ai.db.session import tenant_session

log = logging.getLogger(__name__)


async def audit(
    tenant_id: UUID,
    actor: UUID | None,
    action: str,
    *,
    target_type: str | None = None,
    target_id: object = None,
    request: Request | None = None,
    **metadata: Any,
) -> None:
    try:
        async with tenant_session(tenant_id) as db:
            db.add(
                AuditLog(
                    tenant_id=tenant_id,
                    actor_user_id=actor,
                    action=action,
                    target_type=target_type,
                    target_id=str(target_id) if target_id is not None else None,
                    request_id=getattr(request.state, "request_id", None) if request else None,
                    ip_hash=ip_hash(request.client.host) if request and request.client else None,
                    metadata_=metadata,
                )
            )
    except Exception:
        # Audit failure must be visible but must not break the user's action after it succeeded.
        log.exception("audit write failed action=%s tenant=%s", action, tenant_id)
