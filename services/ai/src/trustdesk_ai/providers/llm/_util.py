from __future__ import annotations

from collections.abc import AsyncIterator


async def empty_stream() -> AsyncIterator[str]:
    """Placeholder iterator, replaced right after construction (lets the generator capture its LLMStream)."""
    for _ in ():
        yield ""
