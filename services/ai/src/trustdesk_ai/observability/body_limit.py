"""Enforce request-body limits on the bytes actually received (chunked bodies have no Content-Length).

When the limit is crossed, the app's receive call fails (so no handler ever processes the body) and whatever
response the app then produces is replaced with a 413.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_BODY = json.dumps({"error": "request too large"}).encode()


class _TooLargeError(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, limit_for: Callable[[str], int]) -> None:
        self.app = app
        self.limit_for = limit_for

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope["path"])
        state = {"received": 0, "exceeded": False, "replaced": False}

        async def limited_receive() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                state["received"] += len(message.get("body", b""))
                if state["received"] > limit:
                    state["exceeded"] = True
                    raise _TooLargeError
            return message

        async def guarded_send(message: Message) -> None:
            if not state["exceeded"]:
                await send(message)
                return
            if not state["replaced"] and message["type"] == "http.response.start":
                state["replaced"] = True
                await _send_413(send)
            # any later messages of the app's own error response are dropped

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _TooLargeError:
            if not state["replaced"]:
                state["replaced"] = True
                await _send_413(send)


async def _send_413(send: Send) -> None:
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(_BODY)).encode())]
    await send({"type": "http.response.start", "status": 413, "headers": headers})
    await send({"type": "http.response.body", "body": _BODY})
