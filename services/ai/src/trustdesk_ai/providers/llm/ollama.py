"""Ollama chat (local, zero API cost)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence

import httpx

from trustdesk_ai.providers.base import ChatMessage, LLMStream, LLMUsage, ProviderError
from trustdesk_ai.providers.llm._util import empty_stream


class OllamaLLM:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self.model = model
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def _body(self, system: str, messages: Sequence[ChatMessage], max_tokens: int, stream: bool) -> dict[str, object]:
        return {
            "model": self.model,
            "stream": stream,
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
            "options": {"num_predict": max_tokens, "temperature": 0},
        }

    async def complete(self, system: str, messages: Sequence[ChatMessage], max_tokens: int) -> tuple[str, LLMUsage]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                resp = await http.post(f"{self._base}/api/chat", json=self._body(system, messages, max_tokens, False))
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama unreachable: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise ProviderError(f"ollama returned HTTP {resp.status_code}")
        data = resp.json()
        return data["message"]["content"], LLMUsage(data.get("prompt_eval_count", 0), data.get("eval_count", 0))

    def stream(self, system: str, messages: Sequence[ChatMessage], max_tokens: int) -> LLMStream:
        out = LLMStream(deltas=empty_stream())
        out.deltas = self._iter(system, messages, max_tokens, out)
        return out

    async def _iter(
        self, system: str, messages: Sequence[ChatMessage], max_tokens: int, out: LLMStream
    ) -> AsyncIterator[str]:
        body = self._body(system, messages, max_tokens, True)
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout) as http,
                http.stream("POST", f"{self._base}/api/chat", json=body) as resp,
            ):
                if resp.status_code != 200:
                    raise ProviderError(f"ollama returned HTTP {resp.status_code}")
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    if delta := event.get("message", {}).get("content"):
                        yield delta
                    if event.get("done"):
                        out.usage = LLMUsage(event.get("prompt_eval_count", 0), event.get("eval_count", 0))
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama unreachable: {type(exc).__name__}") from exc
