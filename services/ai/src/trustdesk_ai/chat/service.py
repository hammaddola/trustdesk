"""Runs one chat turn: persistence, budgets, the RAG graph and the SSE event stream.

The graph runs in a task that pushes events onto a queue; the HTTP generator drains the queue and sends
heartbeats. If the client disconnects, the generator is closed and the task is cancelled (no further
model tokens are paid for).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select, update

from trustdesk_ai.config.settings import get_settings
from trustdesk_ai.db.models import Citation, Conversation, EmbeddingIndex, Message, TenantSettings
from trustdesk_ai.db.session import tenant_session
from trustdesk_ai.providers import registry
from trustdesk_ai.providers.base import ChatMessage, ProviderError
from trustdesk_ai.rag import prompts
from trustdesk_ai.rag.answerability import AnswerabilityPolicy
from trustdesk_ai.rag.graph import RAGContext, RAGState, run
from trustdesk_ai.retrieval.hybrid import RetrievalConfig, RetrievalResult, hybrid_retrieve
from trustdesk_ai.usage.metering import budget_status, record_usage

log = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 15.0
Channel = Literal["widget", "playground"]


@dataclass(frozen=True)
class ChatTurn:
    tenant_id: UUID
    visitor_id: UUID
    message: str
    conversation_id: UUID | None
    channel: Channel
    request_id: str
    page_url: str | None = None
    page_title: str | None = None


class ChatUnavailableError(Exception):
    """Turn cannot run (no knowledge indexed, budget exhausted). Message is visitor-safe."""


@dataclass(frozen=True)
class Event:
    name: str
    data: dict[str, Any]


async def _prepare(turn: ChatTurn) -> tuple[TenantSettings, EmbeddingIndex, UUID, list[ChatMessage]]:
    async with tenant_session(turn.tenant_id) as db:
        settings = await db.get(TenantSettings, turn.tenant_id)
        if settings is None:
            raise ChatUnavailableError("This assistant is not set up yet.")
        index = (
            await db.execute(
                select(EmbeddingIndex).where(
                    EmbeddingIndex.tenant_id == turn.tenant_id, EmbeddingIndex.status == "active"
                )
            )
        ).scalar_one_or_none()
        if index is None:
            raise ChatUnavailableError("This assistant has no indexed knowledge yet.")
        budget = await budget_status(db, turn.tenant_id)
        if budget.blocked:
            raise ChatUnavailableError("The assistant is temporarily unavailable. Please contact the team directly.")

        conversation = None
        if turn.conversation_id:
            conversation = (
                await db.execute(
                    select(Conversation).where(
                        Conversation.id == turn.conversation_id,
                        Conversation.tenant_id == turn.tenant_id,
                        Conversation.visitor_id == turn.visitor_id,
                    )
                )
            ).scalar_one_or_none()
        if conversation is None:
            conversation = Conversation(
                tenant_id=turn.tenant_id,
                visitor_id=turn.visitor_id,
                channel=turn.channel,
                page_url=turn.page_url,
                page_title=turn.page_title,
            )
            db.add(conversation)
            await db.flush()
        history_rows = (
            (
                await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation.id)
                    .order_by(Message.created_at.desc())
                    .limit(6)
                )
            )
            .scalars()
            .all()
        )
        history = [ChatMessage("user" if m.role == "user" else "assistant", m.content) for m in reversed(history_rows)]
        db.add(
            Message(
                tenant_id=turn.tenant_id,
                conversation_id=conversation.id,
                role="user",
                content=turn.message,
                request_id=turn.request_id,
            )
        )
        conversation.message_count += 1
        conversation.last_message_at = datetime.now(UTC)
        return settings, index, conversation.id, history


def _context(turn: ChatTurn, settings: TenantSettings, index: EmbeddingIndex, emit: Any) -> RAGContext:
    s = get_settings()
    embedder = registry.embeddings()
    if (embedder.name, embedder.model, embedder.dimension) != (index.provider, index.model, index.dimension):
        raise ChatUnavailableError("The assistant is being re-indexed. Please try again shortly.")
    llm = (
        registry.build_llm(s, settings.llm_provider, settings.llm_model)
        if settings.llm_provider
        else registry.default_llm()
    )
    reranker = (
        registry.build_reranker(s, settings.reranker_provider)
        if settings.reranker_provider
        else registry.default_reranker()
    )
    retrieval = RetrievalConfig()

    async def retrieve(query: str, vector: list[float]) -> RetrievalResult:
        async with tenant_session(turn.tenant_id) as db:
            return await hybrid_retrieve(
                db,
                tenant_id=turn.tenant_id,
                query=query,
                query_vector=vector,
                index_id=index.id,
                dimension=index.dimension,
                config=retrieval,
            )

    return RAGContext(
        tenant_id=turn.tenant_id,
        organization=settings.organization_name,
        llm=llm,
        embedder=embedder,
        reranker=reranker,
        retrieve=retrieve,
        emit=emit,
        retrieval=retrieval,
        policy=AnswerabilityPolicy(min_relevance=float(settings.confidence_threshold)),
        max_answer_tokens=min(settings.max_answer_tokens, s.max_answer_tokens),
    )


def retrieval_trace(state: RAGState) -> dict[str, Any]:
    """Debug record for the Playground and gap reports: ids, titles and scores only (no full text)."""

    def brief(cands: Any) -> list[dict[str, Any]]:
        return [
            {
                "chunk_id": str(c.chunk_id),
                "title": c.page_title,
                "section": c.section,
                "url": c.source_url,
                "vector": c.vector_score,
                "fts": c.fts_score,
                "rrf": round(c.rrf_score, 6),
                "rerank": c.rerank_score,
                "preview": c.content[:240],
            }
            for c in cands or []
        ]

    gate = state.get("gate")
    verifier = state.get("verifier")
    return {
        "rewritten_query": state.get("rewritten_query"),
        "fused": brief(state.get("fused")),
        "top": brief(state.get("top")),
        "reranked": state.get("reranked"),
        "gate": {"answerable": gate.answerable, "reasons": list(gate.reasons), "signals": gate.signals}
        if gate
        else None,
        "verification": [{"sentence": v.original[:500], "kept": v.kept, "reason": v.reason} for v in verifier.verdicts]
        if verifier
        else [],
        "timings_ms": state.get("timings_ms", {}),
    }


async def _persist(
    turn: ChatTurn, conversation_id: UUID, state: RAGState, ctx: RAGContext, latency_ms: int, error: bool = False
) -> UUID:
    async with tenant_session(turn.tenant_id) as db:
        handoff = bool(state.get("handoff_required"))
        message = Message(
            tenant_id=turn.tenant_id,
            conversation_id=conversation_id,
            role="assistant",
            content=state.get("answer") or "",
            rewritten_query=state.get("rewritten_query"),
            language=state.get("language"),
            answer_status="error" if error else state.get("status", "handoff"),
            confidence=None if error else state.get("confidence", "low"),
            handoff_required=handoff,
            handoff_summary=state.get("handoff_summary"),
            prompt_version=prompts.ANSWER_PROMPT,
            llm_provider=ctx.llm.name,
            llm_model=ctx.llm.model,
            latency_ms=latency_ms,
            input_tokens=sum(
                u.usage.input_tokens for u in ctx.usage if u.kind == "llm" and not isinstance(u.usage, int)
            ),
            output_tokens=sum(
                u.usage.output_tokens for u in ctx.usage if u.kind == "llm" and not isinstance(u.usage, int)
            ),
            request_id=turn.request_id,
            retrieval_trace=retrieval_trace(state),
        )
        db.add(message)
        await db.flush()
        for c in state.get("citations") or []:
            cand = c.candidate
            db.add(
                Citation(
                    tenant_id=turn.tenant_id,
                    message_id=message.id,
                    marker=c.marker,
                    chunk_id=cand.chunk_id,
                    document_version_id=cand.document_version_id,
                    source_url=cand.source_url,
                    page_title=cand.page_title,
                    section=cand.section,
                    evidence_snapshot=cand.content,
                    supporting_span=c.supporting_span,
                    support_score=c.support_score,
                    source_updated_at=cand.source_updated_at,
                )
            )
        record_usage(db, turn.tenant_id, ctx.usage, message.id, turn.request_id)
        values: dict[str, Any] = {"last_message_at": datetime.now(UTC), "message_count": Conversation.message_count + 1}
        if state.get("language"):
            values["language"] = state["language"]
        if handoff:
            values["status"] = "handed_off"
        await db.execute(update(Conversation).where(Conversation.id == conversation_id).values(**values))
        return message.id


async def stream_turn(turn: ChatTurn) -> AsyncIterator[Event]:
    started = time.perf_counter()
    try:
        settings, index, conversation_id, history = await _prepare(turn)
    except ChatUnavailableError as exc:
        yield Event("error", {"message": str(exc), "request_id": turn.request_id})
        return
    yield Event("conversation_started", {"conversation_id": str(conversation_id)})

    queue: asyncio.Queue[Event | None] = asyncio.Queue()

    async def emit(name: str, data: dict[str, Any]) -> None:
        await queue.put(Event(name, data))

    try:
        ctx = _context(turn, settings, index, emit)
    except ChatUnavailableError as exc:
        yield Event("error", {"message": str(exc), "request_id": turn.request_id})
        return
    result: dict[str, Any] = {}

    async def runner() -> None:
        try:
            result["state"] = await run(ctx, turn.message, history)
        except ProviderError as exc:
            log.warning("provider error request_id=%s: %s", turn.request_id, exc)
            result["error"] = "The assistant could not answer right now. Please try again or contact the team."
        except Exception:
            log.exception("chat turn failed request_id=%s", turn.request_id)
            result["error"] = "Something went wrong. Please try again or contact the team."
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                yield Event("heartbeat", {})
                continue
            if event is None:
                break
            yield event
        latency = int((time.perf_counter() - started) * 1000)
        state: RAGState = result.get("state", {})
        message_id = await _persist(turn, conversation_id, state, ctx, latency, error="error" in result)
        if "error" in result:
            yield Event("error", {"message": result["error"], "request_id": turn.request_id})
            return
        yield Event("confidence", {"level": state.get("confidence", "low")})
        yield Event(
            "completed",
            {
                "message_id": str(message_id),
                "conversation_id": str(conversation_id),
                "status": state.get("status"),
                "handoff_required": bool(state.get("handoff_required")),
                "language": state.get("language"),
            },
        )
    finally:
        if not task.done():
            task.cancel()  # client disconnected: stop generation
