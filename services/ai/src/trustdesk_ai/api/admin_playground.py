"""Admin Playground: internal testing tool. Runs the same pipeline as the widget (channel=playground,
excluded from visitor metrics) and returns the full retrieval trace: chunks, scores, gate decision,
verification verdicts and citations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from trustdesk_ai.api.deps import AdminPrincipal
from trustdesk_ai.chat.service import ChatTurn, stream_turn
from trustdesk_ai.db.models import Citation, Message
from trustdesk_ai.db.session import tenant_session

router = APIRouter(prefix="/v1/admin", tags=["admin-playground"])


class PlaygroundIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: UUID | None = None


class PlaygroundOut(BaseModel):
    conversation_id: UUID | None
    message_id: UUID | None
    answer: str
    status: str | None
    confidence: str | None
    handoff_required: bool
    events: list[dict[str, Any]]
    trace: dict[str, Any] | None
    citations: list[dict[str, Any]]
    error: str | None


@router.post("/playground", response_model=PlaygroundOut)
async def playground(body: PlaygroundIn, principal: AdminPrincipal, request: Request) -> PlaygroundOut:
    # The admin's user id doubles as the playground "visitor" so they can continue their own test chats.
    turn = ChatTurn(
        tenant_id=principal.tenant_id,
        visitor_id=principal.user_id,
        message=body.message.strip(),
        conversation_id=body.conversation_id,
        channel="playground",
        request_id=request.state.request_id,
    )
    events: list[dict[str, Any]] = []
    answer, error, completed = [], None, {}
    async for event in stream_turn(turn):
        if event.name == "heartbeat":
            continue
        events.append({"event": event.name, "data": event.data})
        if event.name == "token":
            answer.append(event.data["text"])
        elif event.name == "error":
            error = event.data["message"]
        elif event.name == "completed":
            completed = event.data
    trace, citations = None, []
    if completed.get("message_id"):
        async with tenant_session(principal.tenant_id) as db:
            msg = await db.get(Message, UUID(completed["message_id"]))
            if msg is None:
                raise HTTPException(404, "message not found")
            trace = msg.retrieval_trace
            citations = [
                {
                    "marker": c.marker,
                    "title": c.page_title,
                    "url": c.source_url,
                    "section": c.section,
                    "supporting_span": c.supporting_span,
                    "support_score": c.support_score,
                    "evidence": c.evidence_snapshot,
                }
                for c in (
                    await db.execute(select(Citation).where(Citation.message_id == msg.id).order_by(Citation.marker))
                ).scalars()
            ]
    confidence = next((e["data"]["level"] for e in events if e["event"] == "confidence"), None)
    return PlaygroundOut(
        conversation_id=UUID(completed["conversation_id"]) if completed.get("conversation_id") else None,
        message_id=UUID(completed["message_id"]) if completed.get("message_id") else None,
        answer="".join(answer).strip(),
        status=completed.get("status"),
        confidence=confidence,
        handoff_required=bool(completed.get("handoff_required")),
        events=events,
        trace=trace,
        citations=citations,
        error=error,
    )
