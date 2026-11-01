"""Admin: organization settings (owners edit; admins read)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator

from trustdesk_ai.api.deps import AdminPrincipal, OwnerPrincipal, TenantDB
from trustdesk_ai.audit import audit
from trustdesk_ai.db.models import EmbeddingIndex, Tenant, TenantSettings
from trustdesk_ai.security.ssrf import BlockedURLError, normalize_host, validate_url
from trustdesk_ai.tenancy import public
from trustdesk_ai.usage.metering import budget_status

router = APIRouter(prefix="/v1/admin", tags=["admin-settings"])

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
LANGS = Literal["en", "ur", "ur-Latn"]


class WidgetTheme(BaseModel):
    primary: str | None = None
    accent: str | None = None
    mode: Literal["auto", "light", "dark"] = "auto"
    position: Literal["right", "left"] = "right"
    launcher_text: str | None = Field(default=None, max_length=40)

    @field_validator("primary", "accent")
    @classmethod
    def _hex(cls, v: str | None) -> str | None:
        if v is not None and not HEX.match(v):
            raise ValueError("colors must be #RRGGBB")
        return v


class EmailChannel(BaseModel):
    enabled: bool = False
    to: EmailStr | None = None  # where leads are delivered (server-side only)


class WhatsAppChannel(BaseModel):
    enabled: bool = False
    number: str | None = Field(default=None, pattern=r"^\+?[1-9]\d{6,14}$")


class BookingChannel(BaseModel):
    enabled: bool = False
    url: str | None = Field(default=None, max_length=500)


class HandoffChannels(BaseModel):
    email: EmailChannel = EmailChannel()
    whatsapp: WhatsAppChannel = WhatsAppChannel()
    booking: BookingChannel = BookingChannel()


class SettingsOut(BaseModel):
    organization_name: str
    description: str | None
    industry: str | None
    audience: str | None
    website_urls: list[str]
    allowed_domains: list[str]
    allowed_origins: list[str]
    founder_name: str | None
    founder_role: str | None
    default_language: str
    enabled_languages: list[str]
    timezone: str
    llm_provider: str | None
    llm_model: str | None
    reranker_provider: str | None
    confidence_threshold: float
    max_answer_tokens: int
    monthly_budget_usd: float | None
    budget_warning_pct: int
    budget_hard_limit: bool
    greeting: str | None
    widget_theme: dict[str, Any]
    handoff_channels: dict[str, Any]
    setup_completed: bool
    public_key: str
    embedding_index: dict[str, Any] | None
    spend_this_month_usd: float
    budget_warning: bool


class SettingsPatch(BaseModel):
    organization_name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    industry: str | None = Field(default=None, max_length=100)
    audience: str | None = Field(default=None, max_length=200)
    website_urls: list[str] | None = Field(default=None, max_length=20)
    allowed_domains: list[str] | None = Field(default=None, max_length=20)
    allowed_origins: list[str] | None = Field(default=None, max_length=20)
    founder_name: str | None = Field(default=None, max_length=200)
    founder_role: str | None = Field(default=None, max_length=200)
    default_language: LANGS | None = None
    enabled_languages: list[LANGS] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    llm_provider: Literal["ollama", "openai", "anthropic", "openai_compat"] | None = None
    llm_model: str | None = Field(default=None, max_length=100)
    reranker_provider: Literal["local", "cohere", "none"] | None = None
    confidence_threshold: float | None = Field(default=None, ge=0.05, le=0.95)
    max_answer_tokens: int | None = Field(default=None, ge=50, le=4000)
    monthly_budget_usd: float | None = Field(default=None, ge=0)
    budget_warning_pct: int | None = Field(default=None, ge=1, le=100)
    budget_hard_limit: bool | None = None
    greeting: str | None = Field(default=None, max_length=300)
    widget_theme: WidgetTheme | None = None
    handoff_channels: HandoffChannels | None = None
    mark_setup_complete: bool | None = None

    @field_validator("allowed_domains")
    @classmethod
    def _domains(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        out = []
        for d in v:
            host = normalize_host(d.removeprefix("https://").removeprefix("http://").split("/")[0])
            if not DOMAIN.match(host):
                raise ValueError(f"invalid domain: {d}")
            out.append(host)
        return sorted(set(out))

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        out = []
        for o in v:
            norm = public.normalize_origin(o)
            if o.strip() == "*" or norm is None or "*" in o:
                raise ValueError(f"invalid origin {o!r}: use exact origins like https://www.example.com")
            out.append(norm)
        return sorted(set(out))

    @field_validator("website_urls")
    @classmethod
    def _urls(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        try:
            return [validate_url(u, None).url for u in v]
        except BlockedURLError as exc:
            raise ValueError(str(exc)) from exc


async def _out(db: TenantDB, tenant_id: UUID) -> SettingsOut:
    s = await db.get(TenantSettings, tenant_id)
    tenant = await db.get(Tenant, tenant_id)
    if s is None or tenant is None:
        raise HTTPException(404, "organization not found")
    from sqlalchemy import select

    index = (
        await db.execute(
            select(EmbeddingIndex).where(EmbeddingIndex.tenant_id == tenant_id, EmbeddingIndex.status == "active")
        )
    ).scalar_one_or_none()
    budget = await budget_status(db, tenant_id)
    return SettingsOut(
        organization_name=s.organization_name,
        description=s.description,
        industry=s.industry,
        audience=s.audience,
        website_urls=list(s.website_urls),
        allowed_domains=list(s.allowed_domains),
        allowed_origins=list(s.allowed_origins),
        founder_name=s.founder_name,
        founder_role=s.founder_role,
        default_language=s.default_language,
        enabled_languages=list(s.enabled_languages),
        timezone=s.timezone,
        llm_provider=s.llm_provider,
        llm_model=s.llm_model,
        reranker_provider=s.reranker_provider,
        confidence_threshold=float(s.confidence_threshold),
        max_answer_tokens=s.max_answer_tokens,
        monthly_budget_usd=float(s.monthly_budget_usd) if s.monthly_budget_usd is not None else None,
        budget_warning_pct=s.budget_warning_pct,
        budget_hard_limit=s.budget_hard_limit,
        greeting=s.greeting,
        widget_theme=dict(s.widget_theme),
        handoff_channels=dict(s.handoff_channels),
        setup_completed=s.setup_completed_at is not None,
        public_key=tenant.public_key,
        embedding_index={"provider": index.provider, "model": index.model, "dimension": index.dimension}
        if index
        else None,
        spend_this_month_usd=float(budget.spent_usd),
        budget_warning=budget.warning,
    )


@router.get("/settings", response_model=SettingsOut)
async def get_settings_(principal: AdminPrincipal, db: TenantDB) -> SettingsOut:
    return await _out(db, principal.tenant_id)


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(
    body: SettingsPatch, principal: OwnerPrincipal, db: TenantDB, request: Request
) -> SettingsOut:
    s = await db.get(TenantSettings, principal.tenant_id)
    if s is None:
        raise HTTPException(404, "organization not found")
    changes = body.model_dump(exclude_unset=True)
    mark = changes.pop("mark_setup_complete", None)
    for key, value in changes.items():
        if key == "monthly_budget_usd" and value is not None:
            value = Decimal(str(value))
        if key == "confidence_threshold" and value is not None:
            value = Decimal(str(value))
        setattr(s, key, value)
    if mark:
        s.setup_completed_at = s.setup_completed_at or datetime.now(UTC)
    s.updated_at = datetime.now(UTC)
    await db.flush()
    public.clear_cache()  # widget config/origins take effect immediately in this process
    await audit(
        principal.tenant_id, principal.user_id, "settings.updated", request=request, fields=sorted(changes)
    )  # field names only, never values
    return await _out(db, principal.tenant_id)
