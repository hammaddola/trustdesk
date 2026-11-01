"""Server-Sent Events encoding. Heartbeats are SSE comments (ignored by clients' event handlers)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from starlette.responses import StreamingResponse

from trustdesk_ai.chat.service import Event

EVENT_TYPES = frozenset(
    {
        "conversation_started",
        "searching",
        "reranking",
        "token",
        "citation",
        "confidence",
        "handoff",
        "completed",
        "error",
    }
)


def encode(event_id: int, event: Event) -> str:
    if event.name == "heartbeat":
        return ": ping\n\n"
    if event.name not in EVENT_TYPES:
        raise ValueError(f"unknown SSE event {event.name}")
    data = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event.name}\ndata: {data}\n\n"


async def _encode_all(events: AsyncIterator[Event]) -> AsyncIterator[str]:
    yield "retry: 5000\n\n"
    n = 0
    async for event in events:
        if event.name != "heartbeat":
            n += 1
        yield encode(n, event)


def sse_response(events: AsyncIterator[Event]) -> StreamingResponse:
    return StreamingResponse(
        _encode_all(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
