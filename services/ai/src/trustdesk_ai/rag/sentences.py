"""Incremental sentence segmentation for streamed model output.

A sentence is released only once text that is neither whitespace nor a citation marker follows its
terminator, so markers written after the full stop ("... stores. [E2]") stay with their sentence.
Newlines (bullets, paragraphs) are boundaries too.
"""

from __future__ import annotations

import re

_TERMINATOR = re.compile(r"[.!?۔؟]+|\n")
_TRAILING = re.compile(r"(?:\s*\[E\d{1,2}\])+")


class SentenceBuffer:
    def __init__(self) -> None:
        self._buf = ""

    def feed(self, delta: str) -> list[str]:
        self._buf += delta
        out: list[str] = []
        while True:
            cut = self._next_cut()
            if cut is None:
                return out
            sentence, self._buf = self._buf[:cut], self._buf[cut:]
            if sentence.strip():
                out.append(sentence)

    def flush(self) -> list[str]:
        rest, self._buf = self._buf, ""
        return [rest] if rest.strip() else []

    def _next_cut(self) -> int | None:
        for m in _TERMINATOR.finditer(self._buf):
            end = m.end()
            # Decimal points and abbreviations like "1.5" or "e.g." keep going: need whitespace after.
            if m.group() != "\n" and end < len(self._buf) and not self._buf[end].isspace() and self._buf[end] != "[":
                continue
            trailing = _TRAILING.match(self._buf, end)
            if trailing:
                end = trailing.end()
            rest = self._buf[end:]
            if not rest.strip():
                return None  # wait for more text: a marker or more of this sentence may follow
            if re.match(r"\s*\[(E\d{0,2})?$", rest):
                return None  # partial marker still streaming
            # Include following whitespace in this sentence so spacing is preserved when re-joined.
            ws = len(rest) - len(rest.lstrip())
            return end + ws
        return None
