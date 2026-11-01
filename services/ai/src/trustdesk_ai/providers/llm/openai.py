"""OpenAI chat completions; also any OpenAI-compatible endpoint (Groq, Together, vLLM, LM Studio)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import openai

from trustdesk_ai.providers.base import ChatMessage, LLMStream, LLMUsage, ProviderError
from trustdesk_ai.providers.llm._util import empty_stream


class OpenAILLM:
    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str | None = None,
        name: str = "openai",
        reasoning_effort: str | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._extra: dict[str, Any] = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
        # Compatible local servers often accept any key.
        self._client = openai.AsyncOpenAI(api_key=api_key or "not-needed", base_url=base_url, max_retries=2)

    @staticmethod
    def _messages(system: str, messages: Sequence[ChatMessage]) -> Any:
        return [{"role": "system", "content": system}] + [{"role": m.role, "content": m.content} for m in messages]

    async def complete(self, system: str, messages: Sequence[ChatMessage], max_tokens: int) -> tuple[str, LLMUsage]:
        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=self._messages(system, messages),
                max_tokens=max_tokens,
                temperature=0,
                **self._extra,
            )
        except openai.APIError as exc:
            raise ProviderError(f"{self.name} request failed: {type(exc).__name__}") from exc
        u = resp.usage
        usage = LLMUsage(u.prompt_tokens, u.completion_tokens) if u else LLMUsage()
        return resp.choices[0].message.content or "", usage

    def stream(self, system: str, messages: Sequence[ChatMessage], max_tokens: int) -> LLMStream:
        out = LLMStream(deltas=empty_stream())
        out.deltas = self._iter(system, messages, max_tokens, out)
        return out

    async def _iter(
        self, system: str, messages: Sequence[ChatMessage], max_tokens: int, out: LLMStream
    ) -> AsyncIterator[str]:
        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=self._messages(system, messages),
                max_tokens=max_tokens,
                temperature=0,
                **self._extra,
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                if chunk.usage:
                    out.usage = LLMUsage(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
                if chunk.choices and (delta := chunk.choices[0].delta.content):
                    yield delta
        except openai.APIError as exc:
            raise ProviderError(f"{self.name} request failed: {type(exc).__name__}") from exc
