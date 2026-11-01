"""Public (widget) API. Authenticated by publishable key in the path + Origin allowlist (middleware)."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from trustdesk_ai.api.sse import sse_response
from trustdesk_ai.chat.service import ChatTurn, stream_turn
from trustdesk_ai.config.settings import get_settings
from trustdesk_ai.db.models import Feedback, Message
from trustdesk_ai.db.session import tenant_session
from trustdesk_ai.providers.ratelimit.postgres import PostgresRateLimitStore, bucket_key
from trustdesk_ai.rag.language import text_direction
from trustdesk_ai.tenancy.public import PublicTenant

router = APIRouter(prefix="/v1/public/{public_key}", tags=["public"])
_limiter = PostgresRateLimitStore()

# Handoff settings safe to expose to browsers (secrets such as webhook URLs never leave the server).
PUBLIC_HANDOFF_FIELDS = {"email": ["enabled"], "whatsapp": ["enabled", "number"], "booking": ["enabled", "url"]}


def public_tenant(request: Request) -> PublicTenant:
    tenant: PublicTenant | None = getattr(request.state, "public_tenant", None)
    if tenant is None:  # middleware always sets it for this prefix; defensive
        raise HTTPException(404, "unknown assistant")
    return tenant


Tenant = Annotated[PublicTenant, Depends(public_tenant)]


def client_ip(request: Request) -> str:
    # Behind a proxy, uvicorn rewrites request.client from X-Forwarded-For only for FORWARDED_ALLOW_IPS.
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(request: Request, tenant: PublicTenant, route: str, limit: int, window: int) -> None:
    key = bucket_key(str(tenant.tenant_id), client_ip(request), route)
    if not await _limiter.hit(key, limit, window):
        raise HTTPException(429, "too many requests, please wait a moment")


class CaptchaConfig(BaseModel):
    provider: Literal["turnstile", "hcaptcha"]
    site_key: str


class WidgetConfig(BaseModel):
    organization: str
    greeting: str | None
    default_language: str
    enabled_languages: list[str]
    direction: Literal["ltr", "rtl"]
    theme: dict[str, Any]
    handoff: dict[str, dict[str, Any]]
    ready: bool
    captcha: CaptchaConfig | None = None


@router.get("/config", response_model=WidgetConfig)
async def widget_config(tenant: Tenant) -> WidgetConfig:
    handoff = {
        name: {k: cfg.get(k) for k in fields}
        for name, fields in PUBLIC_HANDOFF_FIELDS.items()
        if isinstance(cfg := tenant.handoff_channels.get(name), dict) and cfg.get("enabled")
    }
    s = get_settings()
    captcha = None
    if s.captcha_provider == "turnstile" and s.turnstile_site_key:
        captcha = CaptchaConfig(provider="turnstile", site_key=s.turnstile_site_key)
    elif s.captcha_provider == "hcaptcha" and s.hcaptcha_site_key:
        captcha = CaptchaConfig(provider="hcaptcha", site_key=s.hcaptcha_site_key)
    return WidgetConfig(
        organization=tenant.organization,
        greeting=tenant.greeting,
        default_language=tenant.default_language,
        enabled_languages=list(tenant.enabled_languages),
        direction="rtl" if text_direction(tenant.default_language) == "rtl" else "ltr",
        theme=tenant.widget_theme,
        handoff=handoff,
        ready=tenant.setup_complete,
        captcha=captcha,
    )


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    visitor_id: UUID
    conversation_id: UUID | None = None
    page_url: str | None = Field(default=None, max_length=2048)
    page_title: str | None = Field(default=None, max_length=300)

    @field_validator("message")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.replace("\x00", "").strip()
        if not v:
            raise ValueError("message is empty")
        return v


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request, tenant: Tenant) -> Any:
    await enforce_rate_limit(request, tenant, "chat", limit=20, window=60)
    turn = ChatTurn(
        tenant_id=tenant.tenant_id,
        visitor_id=body.visitor_id,
        message=body.message,
        conversation_id=body.conversation_id,
        channel="widget",
        request_id=request.state.request_id,
        page_url=body.page_url,
        page_title=body.page_title,
    )
    return sse_response(stream_turn(turn))


class FeedbackRequest(BaseModel):
    message_id: UUID
    visitor_id: UUID
    rating: Literal["helpful", "not_helpful"]
    comment: str | None = Field(default=None, max_length=2000)


@router.post("/feedback", status_code=204)
async def feedback(body: FeedbackRequest, request: Request, tenant: Tenant) -> None:
    await enforce_rate_limit(request, tenant, "feedback", limit=30, window=60)
    from trustdesk_ai.db.models import Conversation

    async with tenant_session(tenant.tenant_id) as db:
        # The visitor may only rate assistant messages in their own conversation.
        message = (
            await db.execute(
                select(Message)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Message.id == body.message_id,
                    Message.role == "assistant",
                    Conversation.visitor_id == body.visitor_id,
                )
            )
        ).scalar_one_or_none()
        if message is None:
            raise HTTPException(404, "message not found")
        existing = (await db.execute(select(Feedback).where(Feedback.message_id == message.id))).scalar_one_or_none()
        if existing:
            existing.rating, existing.comment = body.rating, body.comment
        else:
            db.add(
                Feedback(tenant_id=tenant.tenant_id, message_id=message.id, rating=body.rating, comment=body.comment)
            )
