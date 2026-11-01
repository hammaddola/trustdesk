"""LangGraph workflow:

START -> rewrite -> hybrid_retrieve -> rerank -> answerability_gate
      -> (insufficient) handoff -> END
      -> (sufficient)   generate -> verify -> (ok) END | (insufficient) handoff -> END

`generate` streams the model and verifies each completed sentence before emitting it (decision D6);
`verify` makes the final whole-answer decision (sufficiency, confidence). Dependencies and the event
emitter are passed in `RAGContext` via the run config, not in state.
"""

from __future__ import annotations

import html
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from trustdesk_ai.providers.base import ChatMessage, EmbeddingProvider, LLMProvider, RerankerProvider
from trustdesk_ai.rag import prompts
from trustdesk_ai.rag.answerability import AnswerabilityPolicy, GateDecision, evaluate
from trustdesk_ai.rag.confidence import Confidence, confidence_level
from trustdesk_ai.rag.language import detect_language
from trustdesk_ai.rag.sentences import SentenceBuffer
from trustdesk_ai.rag.verification import CitationVerifier, VerifiedCitation
from trustdesk_ai.retrieval.hybrid import RetrievalConfig, RetrievalResult, rerank
from trustdesk_ai.retrieval.types import Candidate
from trustdesk_ai.usage.metering import UsageItem

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]
Retrieve = Callable[[str, list[float]], Awaitable[RetrievalResult]]
AnswerStatus = Literal["answered", "partial", "refused", "handoff", "error"]

HANDOFF_MESSAGES = {
    "en": "I couldn't find this in {org}'s published information, so I won't guess. A person from the team can help.",
    "ur": "مجھے {org} کی شائع شدہ "
    "معلومات میں یہ نہیں "
    "ملا، اس لیے میں اندازہ "
    "نہیں لگاؤں گا۔ ٹیم کا "
    "کوئی فرد آپ کی مدد کر "
    "سکتا ہے۔",
    "ur-Latn": "Mujhe yeh {org} ki published maloomat mein nahi mila, is liye main andaza nahi lagaunga. "
    "Team ka koi shakhs aap ki madad kar sakta hai.",
}


@dataclass
class RAGContext:
    tenant_id: UUID
    organization: str
    llm: LLMProvider
    embedder: EmbeddingProvider
    reranker: RerankerProvider | None
    retrieve: Retrieve
    emit: Emit
    policy: AnswerabilityPolicy = field(default_factory=AnswerabilityPolicy)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    max_answer_tokens: int = 600
    usage: list[UsageItem] = field(default_factory=list)


class RAGState(TypedDict, total=False):
    question: str
    history: list[ChatMessage]
    language: str
    rewritten_query: str
    vector_hits: list[Candidate]
    fulltext_hits: list[Candidate]
    fused: list[Candidate]
    top: list[Candidate]
    reranked: bool
    gate: GateDecision
    answer: str
    citations: list[VerifiedCitation]
    verifier: CitationVerifier
    confidence: Confidence
    status: AnswerStatus
    handoff_required: bool
    handoff_summary: str
    timings_ms: dict[str, int]


def _ctx(config: RunnableConfig) -> RAGContext:
    return config["configurable"]["ctx"]  # type: ignore[no-any-return]


def _timed(state: RAGState, name: str, started: float) -> dict[str, int]:
    return {**state.get("timings_ms", {}), name: int((time.perf_counter() - started) * 1000)}


async def rewrite_node(state: RAGState, config: RunnableConfig) -> RAGState:
    ctx, t0 = _ctx(config), time.perf_counter()
    question = state["question"]
    language = detect_language(question)
    history = state.get("history") or []
    rewritten = question
    if history:
        transcript = "\n".join(f"{m.role}: {m.content[:500]}" for m in history[-6:])
        text, usage = await ctx.llm.complete(
            prompts.load(prompts.REWRITE_PROMPT),
            [ChatMessage("user", f"Conversation:\n{transcript}\n\nFollow-up question: {question}")],
            max_tokens=120,
        )
        ctx.usage.append(UsageItem("llm", ctx.llm.name, ctx.llm.model, usage))
        candidate = text.strip().splitlines()[0][:500] if text.strip() else ""
        rewritten = candidate or question
    return {"language": language, "rewritten_query": rewritten, "timings_ms": _timed(state, "rewrite", t0)}


async def hybrid_retrieve_node(state: RAGState, config: RunnableConfig) -> RAGState:
    ctx, t0 = _ctx(config), time.perf_counter()
    await ctx.emit("searching", {})
    query = state["rewritten_query"]
    [vector] = await ctx.embedder.embed([query], "query")
    ctx.usage.append(UsageItem("embedding", ctx.embedder.name, ctx.embedder.model, 1))
    result = await ctx.retrieve(query, vector)
    return {
        "vector_hits": result.vector,
        "fulltext_hits": result.fulltext,
        "fused": result.fused,
        "timings_ms": _timed(state, "retrieve", t0),
    }


async def rerank_node(state: RAGState, config: RunnableConfig) -> RAGState:
    ctx, t0 = _ctx(config), time.perf_counter()
    fused = state.get("fused") or []
    if ctx.reranker is not None and fused:
        await ctx.emit("reranking", {})  # only emitted when a reranker actually runs
    top, reranked = await rerank(ctx.reranker, state["rewritten_query"], fused, ctx.retrieval.top_k)
    if ctx.reranker is not None and fused:
        ctx.usage.append(UsageItem("rerank", ctx.reranker.name, ctx.reranker.model, len(fused)))
    return {"top": top, "reranked": reranked, "timings_ms": _timed(state, "rerank", t0)}


async def answerability_node(state: RAGState, config: RunnableConfig) -> RAGState:
    ctx = _ctx(config)
    gate = evaluate(
        state["rewritten_query"],
        state.get("language"),
        state.get("top") or [],
        ctx.policy,
        reranked=state.get("reranked", False),
    )
    return {"gate": gate}


def route_after_gate(state: RAGState) -> str:
    return "generate" if state["gate"].answerable else "handoff"


async def generate_node(state: RAGState, config: RunnableConfig) -> RAGState:
    ctx, t0 = _ctx(config), time.perf_counter()
    evidence = list(state["gate"].supporting)
    verifier = CitationVerifier(
        tenant_id=ctx.tenant_id,
        evidence={i: c for i, c in enumerate(evidence, start=1)},
        # Retrieval only returns active versions; this re-asserts it for the verifier's own check.
        active_version_ids=frozenset(c.document_version_id for c in evidence),
    )
    history = (state.get("history") or [])[-6:]
    messages = [*history, ChatMessage("user", prompts.answer_user_turn(state["question"], evidence))]
    stream = ctx.llm.stream(
        prompts.answer_system_prompt(ctx.organization, state.get("language", "en")), messages, ctx.max_answer_tokens
    )
    verifier.semantic_scorer = _semantic_scorer(ctx)
    buffer, kept = SentenceBuffer(), []

    async def handle(sentence: str) -> None:
        verdict = await verifier.acheck(html.unescape(sentence))
        if not verdict.kept:
            return
        for c in verdict.new_citations:
            await ctx.emit("citation", citation_payload(c))
        trailing = sentence[len(sentence.rstrip()) :]
        text = verdict.text + trailing
        kept.append(text)
        await ctx.emit("token", {"text": text})

    async for delta in stream.deltas:
        for sentence in buffer.feed(delta):
            await handle(sentence)
    for sentence in buffer.flush():
        await handle(sentence)
    ctx.usage.append(UsageItem("llm", ctx.llm.name, ctx.llm.model, stream.usage))
    return {
        "answer": "".join(kept).strip(),
        "verifier": verifier,
        "citations": sorted(verifier.citations.values(), key=lambda c: c.marker),
        "timings_ms": _timed(state, "generate", t0),
    }


def _semantic_scorer(ctx: RAGContext) -> Callable[[str, list[str]], Awaitable[float]]:
    cache: dict[str, list[float]] = {}

    async def score(sentence: str, evidence: list[str]) -> float:
        missing = [t for t in evidence if t not in cache]
        vectors = await ctx.embedder.embed([sentence, *missing], "document")
        ctx.usage.append(UsageItem("embedding", ctx.embedder.name, ctx.embedder.model, len(vectors)))
        cache.update(zip(missing, vectors[1:], strict=True))
        return max(_cosine(vectors[0], cache[t]) for t in evidence)

    return score


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = sum(x * x for x in a) ** 0.5, sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


async def verify_node(state: RAGState, config: RunnableConfig) -> RAGState:
    verifier = state["verifier"]
    if not verifier.sufficient():
        return {"handoff_required": True}
    status: AnswerStatus = "answered" if verifier.dropped == 0 else "partial"
    return {
        "confidence": confidence_level(state["gate"], verifier.kept_ratio),
        "status": status,
        "handoff_required": False,
    }


def route_after_verify(state: RAGState) -> str:
    return "handoff" if state.get("handoff_required") else END


async def handoff_node(state: RAGState, config: RunnableConfig) -> RAGState:
    ctx = _ctx(config)
    language = state.get("language", "en")
    template = HANDOFF_MESSAGES.get(language, HANDOFF_MESSAGES["en"])
    message = template.format(org=ctx.organization)
    # Summary for the human team: the visitor's own question only (no inferred details).
    summary = f"Visitor asked: {state['question'][:400]}"
    await ctx.emit("handoff", {"message": message, "summary": summary})
    return {
        "handoff_required": True,
        "handoff_summary": summary,
        "confidence": "low",
        "status": "partial" if state.get("answer") else "handoff",
    }


def citation_payload(c: VerifiedCitation) -> dict[str, Any]:
    cand = c.candidate
    return {
        "marker": c.marker,
        "title": cand.page_title,
        "url": cand.source_url,
        "section": cand.section,
        "snippet": c.supporting_span[:300],
        "updated_at": cand.source_updated_at.isoformat() if cand.source_updated_at else None,
    }


def build_graph() -> Any:
    g = StateGraph(RAGState)
    g.add_node("rewrite", rewrite_node)
    g.add_node("hybrid_retrieve", hybrid_retrieve_node)
    g.add_node("rerank", rerank_node)
    g.add_node("answerability_gate", answerability_node)
    g.add_node("generate", generate_node)
    g.add_node("verify", verify_node)
    g.add_node("handoff", handoff_node)
    g.add_edge(START, "rewrite")
    g.add_edge("rewrite", "hybrid_retrieve")
    g.add_edge("hybrid_retrieve", "rerank")
    g.add_edge("rerank", "answerability_gate")
    g.add_conditional_edges("answerability_gate", route_after_gate, {"generate": "generate", "handoff": "handoff"})
    g.add_edge("generate", "verify")
    g.add_conditional_edges("verify", route_after_verify, {"handoff": "handoff", END: END})
    g.add_edge("handoff", END)
    return g.compile()


async def run(ctx: RAGContext, question: str, history: Sequence[ChatMessage]) -> RAGState:
    graph = build_graph()
    result: RAGState = await graph.ainvoke(
        {"question": question, "history": list(history)}, config={"configurable": {"ctx": ctx}}
    )
    return result
