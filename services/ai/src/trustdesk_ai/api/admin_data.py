"""Admin: overview metrics, conversations, leads. All queries run under the principal's tenant (RLS)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, case, exists, func, or_, select, text

from trustdesk_ai.api.deps import AdminPrincipal, TenantDB
from trustdesk_ai.audit import audit
from trustdesk_ai.db.models import Citation, Conversation, Document, Feedback, IndexingJob, Lead, Message

router = APIRouter(prefix="/v1/admin", tags=["admin-data"])


# ---------------- overview ----------------


class Overview(BaseModel):
    period_days: int
    conversations: int
    questions: int
    answered: int
    handoffs: int
    citation_coverage: float | None  # share of answered messages with >= 1 verified citation
    helpful_rate: float | None
    feedback_count: int
    indexed_documents: int
    failed_jobs: int
    recent: list[dict[str, Any]]


@router.get("/overview", response_model=Overview)
async def overview(principal: AdminPrincipal, db: TenantDB, days: int = Query(30, ge=1, le=365)) -> Overview:
    since = datetime.now(UTC) - timedelta(days=days)
    conversations = (
        await db.execute(select(func.count()).where(Conversation.started_at >= since, Conversation.channel == "widget"))
    ).scalar_one()
    m = (
        await db.execute(
            select(
                func.count().filter(Message.role == "user"),
                func.count().filter(Message.answer_status.in_(["answered", "partial"])),
                func.count().filter(Message.handoff_required),
                func.count().filter(
                    and_(
                        Message.answer_status.in_(["answered", "partial"]),
                        exists().where(Citation.message_id == Message.id),
                    )
                ),
            )
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.created_at >= since, Conversation.channel == "widget")
        )
    ).one()
    questions, answered, handoffs, cited = m
    fb = (
        await db.execute(
            select(func.count(), func.count().filter(Feedback.rating == "helpful")).where(Feedback.created_at >= since)
        )
    ).one()
    indexed = (await db.execute(select(func.count()).where(Document.status == "indexed"))).scalar_one()
    failed = (
        await db.execute(select(func.count()).where(IndexingJob.status == "failed", IndexingJob.created_at >= since))
    ).scalar_one()
    recent = (
        await db.execute(
            select(
                Message.id,
                Message.conversation_id,
                Message.content,
                Message.answer_status,
                Message.confidence,
                Message.created_at,
            )
            .where(Message.role == "assistant")
            .order_by(Message.created_at.desc())
            .limit(8)
        )
    ).all()
    return Overview(
        period_days=days,
        conversations=conversations,
        questions=questions,
        answered=answered,
        handoffs=handoffs,
        citation_coverage=(cited / answered) if answered else None,
        helpful_rate=(fb[1] / fb[0]) if fb[0] else None,
        feedback_count=fb[0],
        indexed_documents=indexed,
        failed_jobs=failed,
        recent=[
            {
                "message_id": str(r.id),
                "conversation_id": str(r.conversation_id),
                "status": r.answer_status,
                "confidence": r.confidence,
                "preview": r.content[:140],
                "created_at": r.created_at.isoformat(),
            }
            for r in recent
        ],
    )


# ---------------- conversations ----------------


class ConversationRow(BaseModel):
    id: UUID
    channel: str
    status: str
    language: str | None
    message_count: int
    started_at: datetime
    last_message_at: datetime
    first_question: str | None
    lowest_confidence: str | None
    handoff: bool


@router.get("/conversations", response_model=list[ConversationRow])
async def list_conversations(
    principal: AdminPrincipal,
    db: TenantDB,
    q: str | None = Query(None, max_length=200),
    since: datetime | None = None,
    until: datetime | None = None,
    confidence: Literal["high", "medium", "low"] | None = None,
    handoff: bool | None = None,
    channel: Literal["widget", "playground"] = "widget",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ConversationRow]:
    rank = case({"low": 0, "medium": 1, "high": 2}, value=Message.confidence)
    first_q = (
        select(Message.content)
        .where(Message.conversation_id == Conversation.id, Message.role == "user")
        .order_by(Message.created_at)
        .limit(1)
        .scalar_subquery()
    )
    lowest = (
        select(Message.confidence)
        .where(Message.conversation_id == Conversation.id, Message.confidence.is_not(None))
        .order_by(rank)
        .limit(1)
        .scalar_subquery()
    )
    stmt = select(Conversation, first_q.label("first_q"), lowest.label("lowest")).where(Conversation.channel == channel)
    if since:
        stmt = stmt.where(Conversation.last_message_at >= since)
    if until:
        stmt = stmt.where(Conversation.started_at <= until)
    if handoff is not None:
        stmt = stmt.where((Conversation.status == "handed_off") if handoff else (Conversation.status != "handed_off"))
    if confidence:
        stmt = stmt.where(exists().where(Message.conversation_id == Conversation.id, Message.confidence == confidence))
    if q:
        stmt = stmt.where(
            exists().where(
                Message.conversation_id == Conversation.id,
                text("messages.tsv @@ plainto_tsquery('simple', :q)").bindparams(q=q),
            )
        )
    rows = (await db.execute(stmt.order_by(Conversation.last_message_at.desc()).limit(limit).offset(offset))).all()
    return [
        ConversationRow(
            id=c.id,
            channel=c.channel,
            status=c.status,
            language=c.language,
            message_count=c.message_count,
            started_at=c.started_at,
            last_message_at=c.last_message_at,
            first_question=(fq or "")[:200] or None,
            lowest_confidence=low,
            handoff=c.status == "handed_off",
        )
        for c, fq, low in rows
    ]


class CitationOut(BaseModel):
    marker: int
    title: str | None
    url: str | None
    section: str | None
    supporting_span: str | None
    evidence_snapshot: str
    support_score: float | None
    source_updated_at: datetime | None


class MessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime
    answer_status: str | None
    confidence: str | None
    handoff_required: bool
    rewritten_query: str | None
    language: str | None
    citations: list[CitationOut]
    feedback: dict[str, Any] | None
    retrieval_trace: dict[str, Any] | None


class ConversationDetail(BaseModel):
    conversation: ConversationRow
    messages: list[MessageOut]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def conversation_detail(conversation_id: UUID, principal: AdminPrincipal, db: TenantDB) -> ConversationDetail:
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    messages = (
        (
            await db.execute(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )
    ids = [m.id for m in messages]
    cites: dict[UUID, list[CitationOut]] = {}
    for c in (
        await db.execute(select(Citation).where(Citation.message_id.in_(ids)).order_by(Citation.marker))
    ).scalars():
        cites.setdefault(c.message_id, []).append(
            CitationOut(
                marker=c.marker,
                title=c.page_title,
                url=c.source_url,
                section=c.section,
                supporting_span=c.supporting_span,
                evidence_snapshot=c.evidence_snapshot,
                support_score=c.support_score,
                source_updated_at=c.source_updated_at,
            )
        )
    feedback = {
        f.message_id: {"rating": f.rating, "comment": f.comment}
        for f in (await db.execute(select(Feedback).where(Feedback.message_id.in_(ids)))).scalars()
    }
    first = next((m.content for m in messages if m.role == "user"), None)
    order = {"low": 0, "medium": 1, "high": 2}
    confs = [m.confidence for m in messages if m.confidence]
    return ConversationDetail(
        conversation=ConversationRow(
            id=conv.id,
            channel=conv.channel,
            status=conv.status,
            language=conv.language,
            message_count=conv.message_count,
            started_at=conv.started_at,
            last_message_at=conv.last_message_at,
            first_question=first,
            lowest_confidence=min(confs, key=order.__getitem__) if confs else None,
            handoff=conv.status == "handed_off",
        ),
        messages=[
            MessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
                answer_status=m.answer_status,
                confidence=m.confidence,
                handoff_required=m.handoff_required,
                rewritten_query=m.rewritten_query,
                language=m.language,
                citations=cites.get(m.id, []),
                feedback=feedback.get(m.id),
                retrieval_trace=m.retrieval_trace,
            )
            for m in messages
        ],
    )


# ---------------- leads ----------------

LeadStatus = Literal["new", "contacted", "qualified", "closed", "spam"]


class LeadOut(BaseModel):
    id: UUID
    conversation_id: UUID | None
    channel: str
    name: str | None
    email: str | None
    phone: str | None
    message: str | None
    summary: str | None
    source: str
    status: str
    created_at: datetime


def _lead_query(q: str | None, status: LeadStatus | None) -> Any:
    stmt = select(Lead)
    if status:
        stmt = stmt.where(Lead.status == status)
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        stmt = stmt.where(
            or_(Lead.name.ilike(like), Lead.email.ilike(like), Lead.summary.ilike(like), Lead.message.ilike(like))
        )
    return stmt.order_by(Lead.created_at.desc())


def _lead_out(lead: Lead) -> LeadOut:
    return LeadOut(
        id=lead.id,
        conversation_id=lead.conversation_id,
        channel=lead.channel,
        name=lead.name,
        email=lead.email,
        phone=lead.phone,
        message=lead.message,
        summary=lead.summary,
        source=lead.source,
        status=lead.status,
        created_at=lead.created_at,
    )


@router.get("/leads", response_model=list[LeadOut])
async def list_leads(
    principal: AdminPrincipal,
    db: TenantDB,
    q: str | None = Query(None, max_length=200),
    status: LeadStatus | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[LeadOut]:
    rows = (await db.execute(_lead_query(q, status).limit(limit).offset(offset))).scalars().all()
    return [_lead_out(lead) for lead in rows]


class LeadPatch(BaseModel):
    status: LeadStatus


@router.patch("/leads/{lead_id}", response_model=LeadOut)
async def update_lead(
    lead_id: UUID, body: LeadPatch, principal: AdminPrincipal, db: TenantDB, request: Request
) -> LeadOut:
    lead = await db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "lead not found")
    lead.status, lead.updated_at = body.status, datetime.now(UTC)
    await audit(
        principal.tenant_id,
        principal.user_id,
        "lead.status_changed",
        target_type="lead",
        target_id=lead_id,
        request=request,
        status=body.status,
    )
    return _lead_out(lead)


def _csv_cell(value: object) -> str:
    """Neutralize spreadsheet formula injection (cells starting with = + - @ tab CR)."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@router.get("/leads.csv")
async def export_leads(
    principal: AdminPrincipal,
    db: TenantDB,
    request: Request,
    q: str | None = Query(None, max_length=200),
    status: LeadStatus | None = None,
) -> StreamingResponse:
    rows = (await db.execute(_lead_query(q, status).limit(10000))).scalars().all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["created_at", "status", "channel", "name", "email", "phone", "summary", "message", "conversation_id"]
    )
    for lead in rows:
        writer.writerow(
            [
                _csv_cell(v)
                for v in (
                    lead.created_at.isoformat(),
                    lead.status,
                    lead.channel,
                    lead.name,
                    lead.email,
                    lead.phone,
                    lead.summary,
                    lead.message,
                    lead.conversation_id,
                )
            ]
        )
    await audit(principal.tenant_id, principal.user_id, "lead.exported", request=request, count=len(rows))
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="leads.csv"'},
    )
