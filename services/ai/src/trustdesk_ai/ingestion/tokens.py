"""Token counting for chunk sizing (a stable size measure, not the generation model's tokenizer)."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from functools import lru_cache

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _counter() -> Callable[[str], int]:
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return lambda s: len(enc.encode(s, disallowed_special=()))
    except Exception as exc:  # offline first run: tiktoken downloads its BPE file once
        log.warning("tiktoken unavailable (%s); using a character-based token estimate", exc)
        return lambda s: math.ceil(len(s) / 3.5)


def count_tokens(text: str) -> int:
    return _counter()(text)
