"""Provider interfaces. Adding a provider = one file implementing one Protocol + one registry line
(see docs/providers.md)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMStream:
    """Async text deltas; `usage` is filled in once the stream is exhausted."""

    deltas: AsyncIterator[str]
    usage: LLMUsage = field(default_factory=LLMUsage)


class ProviderError(Exception):
    """Upstream provider failed. Message is sanitized (no keys, no prompt text)."""


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(self, system: str, messages: Sequence[ChatMessage], max_tokens: int) -> tuple[str, LLMUsage]: ...

    def stream(self, system: str, messages: Sequence[ChatMessage], max_tokens: int) -> LLMStream: ...


EmbedKind = Literal["query", "document"]


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimension: int

    async def embed(self, texts: Sequence[str], kind: EmbedKind) -> list[list[float]]: ...


class RerankerProvider(Protocol):
    name: str
    model: str

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        """Relevance per document, normalized to 0..1, in input order."""
        ...


class EmailProvider(Protocol):
    name: str

    async def send(self, to: str, subject: str, body: str, reply_to: str | None = None) -> None: ...


class CaptchaProvider(Protocol):
    name: str

    async def verify(self, token: str | None, remote_ip: str | None) -> bool: ...


class FileStorageProvider(Protocol):
    name: str

    async def put(self, key: str, data: bytes) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


class RateLimitStore(Protocol):
    name: str

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Count one hit; return False when the limit for the current window is exceeded."""
        ...
