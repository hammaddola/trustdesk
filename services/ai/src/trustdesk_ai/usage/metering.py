"""Usage recording, cost estimation and monthly budgets.

Prices are NOT hard-coded for cloud models (they change and we will not guess them). Operators set
them in MODEL_PRICES_JSON, e.g. {"openai/gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.6}}.
Local providers (ollama, local, mock) cost 0. A cloud model without a configured price is recorded with
cost 0 and logged once, and budgets cannot protect against it — the admin Settings page shows this.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from functools import cache
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trustdesk_ai.db.models import TenantSettings, UsageRecord
from trustdesk_ai.providers.base import LLMUsage

log = logging.getLogger(__name__)
FREE_PROVIDERS = frozenset({"ollama", "local", "mock", "none"})


@cache
def _prices() -> dict[str, dict[str, float]]:
    raw = os.environ.get("MODEL_PRICES_JSON")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): {str(f): float(v) for f, v in d.items()} for k, d in data.items()}
    except (ValueError, AttributeError):
        log.error("MODEL_PRICES_JSON is not valid JSON of {model: {field: number}}; ignoring it")
        return {}


_warned: set[str] = set()


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int, units: int) -> Decimal:
    if provider in FREE_PROVIDERS:
        return Decimal(0)
    price = _prices().get(f"{provider}/{model}")
    if price is None:
        if f"{provider}/{model}" not in _warned:
            _warned.add(f"{provider}/{model}")
            log.warning("no price configured for %s/%s; cost recorded as 0", provider, model)
        return Decimal(0)
    cost = (
        input_tokens * price.get("input_per_1m", 0) / 1e6
        + output_tokens * price.get("output_per_1m", 0) / 1e6
        + units * price.get("per_1k_units", 0) / 1e3
    )
    return Decimal(str(round(cost, 6)))


@dataclass(frozen=True)
class UsageItem:
    kind: str  # llm | embedding | rerank
    provider: str
    model: str
    usage: LLMUsage | int


def record_usage(
    db: AsyncSession, tenant_id: UUID, items: list[UsageItem], message_id: UUID | None, request_id: str | None
) -> None:
    for item in items:
        tokens = item.usage if isinstance(item.usage, LLMUsage) else LLMUsage()
        units = item.usage if isinstance(item.usage, int) else 0
        db.add(
            UsageRecord(
                tenant_id=tenant_id,
                kind=item.kind,
                provider=item.provider,
                model=item.model,
                input_tokens=tokens.input_tokens,
                output_tokens=tokens.output_tokens,
                units=units,
                estimated_cost_usd=estimate_cost(
                    item.provider, item.model, tokens.input_tokens, tokens.output_tokens, units
                ),
                message_id=message_id,
                request_id=request_id,
            )
        )


@dataclass(frozen=True)
class BudgetStatus:
    spent_usd: Decimal
    budget_usd: Decimal | None
    warning: bool
    blocked: bool


async def budget_status(db: AsyncSession, tenant_id: UUID) -> BudgetStatus:
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spent = (
        await db.execute(
            select(func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0)).where(
                UsageRecord.tenant_id == tenant_id, UsageRecord.occurred_at >= month_start
            )
        )
    ).scalar_one()
    settings = await db.get(TenantSettings, tenant_id)
    budget = settings.monthly_budget_usd if settings else None
    if not budget:
        return BudgetStatus(Decimal(spent), None, False, False)
    warn_at = budget * Decimal(settings.budget_warning_pct) / 100 if settings else budget
    return BudgetStatus(
        Decimal(spent), budget, spent >= warn_at, bool(settings and settings.budget_hard_limit and spent >= budget)
    )
