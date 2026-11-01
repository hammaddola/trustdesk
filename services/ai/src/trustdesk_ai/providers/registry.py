"""Builds provider instances from settings. Adding a provider: one adapter file + one line here.

`RERANKER_PROVIDER=none` returns None: retrieval keeps RRF order and the answerability gate applies its
stricter no-reranker threshold.
"""

from __future__ import annotations

from functools import lru_cache

from trustdesk_ai.config.settings import Settings, get_settings
from trustdesk_ai.providers.base import EmbeddingProvider, LLMProvider, RerankerProvider


def _secret(value: object) -> str:
    return value.get_secret_value() if value is not None else ""  # type: ignore[attr-defined]


def build_llm(s: Settings, provider: str | None = None, model: str | None = None) -> LLMProvider:
    name, model = provider or s.llm_provider, model or s.llm_model
    if name == "ollama":
        from trustdesk_ai.providers.llm.ollama import OllamaLLM

        return OllamaLLM(s.ollama_base_url, model)
    if name in ("openai", "openai_compat"):
        from trustdesk_ai.providers.llm.openai import OpenAILLM

        base = s.openai_base_url if name == "openai_compat" else None
        return OpenAILLM(
            _secret(s.openai_api_key) or None, model, base_url=base, name=name, reasoning_effort=s.llm_reasoning_effort
        )
    if name == "anthropic":
        from trustdesk_ai.providers.llm.anthropic import AnthropicLLM

        return AnthropicLLM(_secret(s.anthropic_api_key), model)
    if name == "mock" and not s.is_production:
        from trustdesk_ai.providers.llm.mock import MockLLM

        return MockLLM()
    raise ValueError(f"unknown or disallowed LLM provider: {name}")


def build_embeddings(s: Settings) -> EmbeddingProvider:
    name, model, dim = s.embedding_provider, s.embedding_model, s.embedding_dimension
    if name == "ollama":
        from trustdesk_ai.providers.embeddings.ollama import OllamaEmbeddings

        return OllamaEmbeddings(s.ollama_base_url, model, dim)
    if name == "openai":
        from trustdesk_ai.providers.embeddings.openai import OpenAIEmbeddings

        return OpenAIEmbeddings(_secret(s.openai_api_key), model, dim)
    if name == "openai_compat":  # e.g. Gemini's OpenAI-compatible endpoint (gemini-embedding-001)
        from trustdesk_ai.providers.embeddings.openai import OpenAIEmbeddings

        emb = OpenAIEmbeddings(_secret(s.openai_api_key), model, dim, base_url=s.openai_base_url)
        emb.name = "openai_compat"
        return emb
    if name == "cohere":
        from trustdesk_ai.providers.embeddings.cohere import CohereEmbeddings

        return CohereEmbeddings(_secret(s.cohere_api_key), model, dim)
    if name == "local":
        from trustdesk_ai.providers.embeddings.local import LocalEmbeddings

        return LocalEmbeddings(model, dim)
    if name == "mock" and not s.is_production:
        from trustdesk_ai.providers.embeddings.mock import MockEmbeddings

        return MockEmbeddings(dim)
    raise ValueError(f"unknown or disallowed embedding provider: {name}")


def build_reranker(s: Settings, provider: str | None = None) -> RerankerProvider | None:
    name = provider or s.reranker_provider
    if name == "none":
        return None
    if name == "local":
        from trustdesk_ai.providers.rerank.local_cross_encoder import LocalCrossEncoderReranker

        return LocalCrossEncoderReranker(s.reranker_model)
    if name == "cohere":
        from trustdesk_ai.providers.rerank.cohere import CohereReranker

        return CohereReranker(_secret(s.cohere_api_key), s.reranker_model)
    if name == "mock" and not s.is_production:
        from trustdesk_ai.providers.rerank.mock import MockReranker

        return MockReranker()
    raise ValueError(f"unknown or disallowed reranker: {name}")


@lru_cache
def embeddings() -> EmbeddingProvider:
    return build_embeddings(get_settings())


@lru_cache
def default_llm() -> LLMProvider:
    return build_llm(get_settings())


@lru_cache
def default_reranker() -> RerankerProvider | None:
    return build_reranker(get_settings())
