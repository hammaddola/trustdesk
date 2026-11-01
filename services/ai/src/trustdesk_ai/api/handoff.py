"""Public handoff: lead capture (email form) and recorded WhatsApp / booking intents.

The lead row is committed BEFORE the visitor is told it was received. The notification email to the
team is sent after commit; if that fails the lead still exists (visible in admin) and the failure is
logged — success is never reported for a lead that wasn't saved.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from trustdesk_ai.api.public import Tenant, client_ip, enforce_rate_limit
from trustdesk_ai.config.settings import get_settings
from trustdesk_ai.db.models import Conversation, Lead
from trustdesk_ai.db.session import tenant_session
from trustdesk_ai.providers.captcha.providers import build_captcha
from trustdesk_ai.providers.email.providers import build_email

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/public/{public_key}", tags=["public-handoff"])

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    v = _CONTROL.sub("", v).strip()
    return v or None


class LeadIn(BaseModel):
    channel: Literal["email", "whatsapp", "booking"]
    visitor_id: UUID
    conversation_id: UUID | None = None
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40, pattern=r"^[0-9+()\- ]{6,40}$")
    message: str | None = Field(default=None, max_length=2000)
    consent: bool = False
    captcha_token: str | None = Field(default=None, max_length=4096)

    _clean = field_validator("name", "message")(classmethod(lambda cls, v: _clean(v)))

    @model_validator(mode="after")
    def _email_form_requirements(self) -> LeadIn:
        if self.channel == "email":
            if not self.email:
                raise ValueError("email is required")
            if not self.consent:
                raise ValueError("consent is required to be contacted")
        return self


class LeadReceipt(BaseModel):
    lead_id: UUID
    status: Literal["received"]


async def _summary(tenant_id: UUID, conversation_id: UUID | None, visitor_id: UUID) -> tuple[UUID | None, str | None]:
    """Conversation must belong to this visitor; summary = the visitor's own recent questions (no inference)."""
    if conversation_id is None:
        return None, None
    from trustdesk_ai.db.models import Message

    async with tenant_session(tenant_id) as db:
        conv = (
            await db.execute(
                select(Conversation).where(Conversation.id == conversation_id, Conversation.visitor_id == visitor_id)
            )
        ).scalar_one_or_none()
        if conv is None:
            return None, None
        questions = (
            (
                await db.execute(
                    select(Message.content)
                    .where(Message.conversation_id == conv.id, Message.role == "user")
                    .order_by(Message.created_at.desc())
                    .limit(3)
                )
            )
            .scalars()
            .all()
        )
    lines = [f"- {q[:300]}" for q in reversed(questions)]
    return conv.id, ("Visitor asked:\n" + "\n".join(lines)) if lines else None


@router.post("/leads", response_model=LeadReceipt, status_code=201)
async def create_lead(body: LeadIn, request: Request, tenant: Tenant) -> LeadReceipt:
    await enforce_rate_limit(request, tenant, "leads", limit=5, window=600)
    channel_cfg = tenant.handoff_channels.get(body.channel)
    if not isinstance(channel_cfg, dict) or not channel_cfg.get("enabled"):
        raise HTTPException(404, "this contact option is not available")
    if body.channel == "email" and not await build_captcha(get_settings()).verify(
        body.captcha_token, client_ip(request)
    ):
        raise HTTPException(400, "verification failed, please try again")

    conversation_id, summary = await _summary(tenant.tenant_id, body.conversation_id, body.visitor_id)
    try:
        async with tenant_session(tenant.tenant_id) as db:
            existing = (
                await db.execute(select(Lead).where(Lead.idempotency_key == body.idempotency_key))
            ).scalar_one_or_none()
            if existing is not None:  # duplicate submit (double click / retry): same receipt, no new row
                return LeadReceipt(lead_id=existing.id, status="received")
            lead = Lead(
                tenant_id=tenant.tenant_id,
                conversation_id=conversation_id,
                channel=body.channel,
                name=body.name,
                email=str(body.email) if body.email else None,
                phone=body.phone,
                message=body.message,
                summary=summary,
                source="widget",
                idempotency_key=body.idempotency_key,
                consented_at=datetime.now(UTC) if body.consent else None,
            )
            db.add(lead)
            await db.flush()
            lead_id = lead.id
    except IntegrityError:  # concurrent duplicate with the same key
        async with tenant_session(tenant.tenant_id) as db:
            lead_id = (
                await db.execute(select(Lead.id).where(Lead.idempotency_key == body.idempotency_key))
            ).scalar_one()
        return LeadReceipt(lead_id=lead_id, status="received")

    if body.channel == "email":
        await _notify_team(tenant.organization, channel_cfg.get("to"), body, summary)
    return LeadReceipt(lead_id=lead_id, status="received")


async def _notify_team(organization: str, to: object, body: LeadIn, summary: str | None) -> None:
    email = build_email(get_settings())
    if email is None or not isinstance(to, str) or "@" not in to:
        log.warning("lead saved but no team email is configured for delivery")
        return
    text = "\n".join(
        filter(
            None,
            [
                f"New contact request from the {organization} website assistant.",
                f"Name: {body.name}" if body.name else None,
                f"Email: {body.email}",
                f"Phone: {body.phone}" if body.phone else None,
                f"Message: {body.message}" if body.message else None,
                summary,
            ],
        )
    )
    try:
        await email.send(to, f"New website enquiry — {organization}", text, reply_to=str(body.email))
    except Exception:
        log.exception("lead notification email failed (lead is saved)")
