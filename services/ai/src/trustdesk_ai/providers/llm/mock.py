"""Deterministic development/test LLM. Refused in production by settings validation.

It does not invent content: it quotes the first evidence passage's first sentence verbatim with its
marker, so the whole pipeline (verification, citations, streaming) runs without a real model.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence

from trustdesk_ai.providers.base import ChatMessage, LLMStream, LLMUsage

_EVIDENCE = re.compile(r'<evidence id="E(\d+)"[^>]*>\s*(.*?)\s*</evidence>', re.DOTALL)
_SENTENCE = re.compile(r"(?<=[.!?۔؟])\s+")


class MockLLM:
    name = "mock"
    model = "mock-quote-v1"

    def _answer(self, messages: Sequence[ChatMessage]) -> str:
        last = messages[-1].content if messages else ""
        if "<evidence" not in last:  # rewrite request: return the latest question unchanged
            return last.rsplit("Follow-up question:", 1)[-1].strip()
        found = _EVIDENCE.findall(last)
        if not found:
            return "I don't have information about that in the available sources."
        num, body = found[0]
        sentence = _SENTENCE.split(body.strip())[0].rstrip(".")
        return f"{sentence} [E{num}]."

    async def complete(self, system: str, messages: Sequence[ChatMessage], max_tokens: int) -> tuple[str, LLMUsage]:
        text = self._answer(messages)
        return text, LLMUsage(len(system.split()), len(text.split()))

    def stream(self, system: str, messages: Sequence[ChatMessage], max_tokens: int) -> LLMStream:
        text = self._answer(messages)
        return LLMStream(deltas=self._iter(text), usage=LLMUsage(len(system.split()), len(text.split())))

    async def _iter(self, text: str) -> AsyncIterator[str]:
        for word in re.findall(r"\S+\s*", text):
            yield word
