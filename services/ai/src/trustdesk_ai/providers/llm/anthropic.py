"""Anthropic Claude Messages API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import anthropic

from trustdesk_ai.providers.base import ChatMessage, LLMStream, LLMUsage, ProviderError
from trustdesk_ai.providers.llm._util import empty_stream


class AnthropicLLM:
    name = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=2)

    @staticmethod
    def _messages(messages: Sequence[ChatMessage]) -> Any:
        return [{"role": m.role, "content": m.content} for m in messages]

    async def complete(self, system: str, messages: Sequence[ChatMessage], max_tokens: int) -> tuple[str, LLMUsage]:
        try:
            resp = await self._client.messages.create(
                model=self.model, system=system, max_tokens=max_tokens, messages=self._messages(messages)
            )
        except anthropic.APIError as exc:
            raise ProviderError(f"anthropic request failed: {type(exc).__name__}") from exc
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text, LLMUsage(resp.usage.input_tokens, resp.usage.output_tokens)

    def stream(self, system: str, messages: Sequence[ChatMessage], max_tokens: int) -> LLMStream:
        out = LLMStream(deltas=empty_stream())
        out.deltas = self._iter(system, messages, max_tokens, out)
        return out

    async def _iter(
        self, system: str, messages: Sequence[ChatMessage], max_tokens: int, out: LLMStream
    ) -> AsyncIterator[str]:
        try:
            async with self._client.messages.stream(
                model=self.model, system=system, max_tokens=max_tokens, messages=self._messages(messages)
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
                out.usage = LLMUsage(final.usage.input_tokens, final.usage.output_tokens)
        except anthropic.APIError as exc:
            raise ProviderError(f"anthropic request failed: {type(exc).__name__}") from exc
