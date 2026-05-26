"""madrigal.chunking — text-splitting strategies for long-form synthesis.

v0 ships three built-in strategies in a simple registry dict. They share
the same shape: ``Callable[[str], list[str]]``. The orchestrator
(``madrigal.generate()``) picks one by name from ``Spec.chunk_strategy``.

UPGRADE PATH (per plan v2 §7): if external chunking-strategy plugins
become a real demand (3+ user-defined strategies materialize across
consumers), replace this registry dict with pluggy-based discovery.
Migrate the signature to:

    class ChunkStrategy(Protocol):
        def split(self, text: str) -> list[str]: ...

Discovery via importlib.metadata entry_points group "madrigal.chunk_strategies".
Until then, a simple dict + closed set is the right shape; pluggy is
premature library-extraction for a closed set of 3 strategies.

The 3 strategies:

- ``"none"``: one chunk = whole text. Conversational + already-short content.
- ``"sentence"``: rough sentence-boundary heuristic. Audiobook narration.
- ``"paragraph"``: blank-line-separated paragraphs. Chrona scenes / formatted writing.

None of the strategies are ML-grade. Consumers needing stronger
sentence-boundary detection should preprocess + pass to ``chunk_strategy="none"``.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# Public type alias for the strategy signature.
ChunkStrategy = Callable[[str], list[str]]


def _split_none(text: str) -> list[str]:
    """One chunk = whole text."""
    return [text]


# Sentence-end characters followed by whitespace OR end-of-string.
# Captures the punctuation with the preceding chunk via lookbehind-style split.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def _split_sentence(text: str) -> list[str]:
    """Rough sentence-boundary split. Not ML-grade; deliberately simple.

    Splits on ``[.!?]`` followed by whitespace, preserving the
    punctuation with the preceding sentence. Strips whitespace + drops
    empty chunks. Single-sentence input returns a single-element list.
    """
    if not text.strip():
        return []
    chunks = _SENTENCE_BOUNDARY.split(text)
    return [c.strip() for c in chunks if c.strip()]


_PARAGRAPH_BOUNDARY = re.compile(r"\n\s*\n+")


def _split_paragraph(text: str) -> list[str]:
    """Blank-line-separated paragraphs. Single paragraph returns [text]."""
    if not text.strip():
        return []
    chunks = _PARAGRAPH_BOUNDARY.split(text)
    return [c.strip() for c in chunks if c.strip()]


_STRATEGIES: dict[str, ChunkStrategy] = {
    "none": _split_none,
    "sentence": _split_sentence,
    "paragraph": _split_paragraph,
}


def list_strategies() -> list[str]:
    """Return the names of all built-in chunking strategies."""
    return sorted(_STRATEGIES)


def chunk(text: str, strategy: str) -> list[str]:
    """Split ``text`` according to the named ``strategy``.

    Raises ``ValueError`` with the list of valid names if the strategy
    is unknown.
    """
    if strategy not in _STRATEGIES:
        raise ValueError(
            f"unknown chunk strategy {strategy!r}; available: {list_strategies()}"
        )
    return _STRATEGIES[strategy](text)


__all__ = ["ChunkStrategy", "chunk", "list_strategies"]
