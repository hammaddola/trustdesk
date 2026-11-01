from __future__ import annotations

from trustdesk_ai.providers.base import ProviderError


def check_dimensions(vectors: list[list[float]], expected: int, provider: str, count: int) -> list[list[float]]:
    """Never store a vector of the wrong size: it would silently break the per-dimension index."""
    if len(vectors) != count:
        raise ProviderError(f"{provider} returned {len(vectors)} embeddings for {count} inputs")
    for v in vectors:
        if len(v) != expected:
            raise ProviderError(
                f"{provider} returned {len(v)}-dim vectors but EMBEDDING_DIMENSION is {expected}; "
                "fix the setting or re-index with the new model"
            )
    return vectors
