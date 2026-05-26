"""madrigal.Result — uniform response from ``madrigal.generate()``.

Per plan v2 §3: attribute population varies by Spec configuration; the
return TYPE is always Result. Type-checker stays happy; consumers
discover what's populated for their config via the population matrix.

``bytes(result)`` is the conversational fast-path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Result:
    """One response from ``madrigal.generate()``.

    See plan v2 §3 for the attribute-population matrix (which fields are
    populated for which Spec configurations).
    """

    audio: bytes | None = None
    audios: list[bytes] | None = None
    path: Path | None = None
    manifest: list[dict[str, Any]] | None = None
    timings: list[float] | None = None
    sample_rate_hz: int = 16_000
    cache_key: str | None = None
    cache_hit: bool = False
    # NEW in v0.1:
    cache_fully_hit: bool = False
    """Did EVERY chunk in the batch hit the cache? (= all(per_chunk_hits))

    Distinct from ``cache_hit`` which is the v0-compatible ``any()`` shape.
    For v0 single-text calls: ``cache_fully_hit == cache_hit`` (N=1).
    For batched calls in v0.1+: ``cache_fully_hit`` answers the strict
    "did the whole batch shortcut?" question."""

    parallel_used: bool = False
    """Did the batch path actually fire? Transparent-silent-fallback flag.

    UC2 (chunked-parallel) may silently fall back to sequential
    cache+chunking when the spec §5 conditional path is active (engine
    is item-coupled and cache+parallel was requested). Consumer checks
    this flag to know whether parallel actually fired. Avoids the
    "I asked for parallel; why is it slow?" surprise."""

    def __bytes__(self) -> bytes:
        """Conversational fast-path: ``bytes(result)`` → the audio.

        Raises ``ValueError`` if ``audio`` is None (e.g., parallel-gen
        result where only ``audios`` is populated). Callers needing
        list-of-bytes should inspect ``.audios`` directly.
        """
        if self.audio is None:
            raise ValueError(
                "Result has no .audio (parallel-gen result with .audios? "
                "file-write-only result?). Inspect .audios / .path instead."
            )
        return self.audio


__all__ = ["Result"]
