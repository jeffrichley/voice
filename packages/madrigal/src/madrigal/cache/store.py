"""Filesystem-backed content-addressed cache for voice synthesis.

Per plan v2 §2 + §5: minimal 6-field entry; no eviction in v0; consumer
wraps with their own policy-shaped metadata.

The cache addresses entries by string keys; key derivation is the
orchestrator's concern (``madrigal.generate()`` builds keys from
model_id + voice_id + text + seed + params per the audiobook-spec
contract).

Storage layout::

    <root>/
      ab/
        abcdef0123...wav    # audio bytes
        abcdef0123...json   # the 5 metadata fields (no audio in JSON)
      cd/
        cdef...

Two-level dir split (first 2 chars of key) keeps any single directory
under sane file-count limits even at millions of entries.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CacheEntry:
    """One cached synthesis result.

    Voice owns ONLY these fields. Policy-shaped metadata (consent
    snapshots, GPU-min accounting, ledger pointers, scene metadata,
    etc.) lives in consumer-wrapper layers, NOT here. Adding to this
    list is a load-bearing decision.
    """

    audio: bytes          # the WAV-formatted audio
    sha256: str           # sha256(audio) — distinct from cache_key
    sample_rate_hz: int
    duration_ms: int
    generation_s: float   # wall time to synthesize (cost telemetry)
    timestamp_utc: str    # ISO-8601 when written


def default_cache_root() -> Path:
    """Default cache root: ~/.cache/madrigal/ (or $XDG_CACHE_HOME/madrigal/)."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "madrigal"
    return Path.home() / ".cache" / "madrigal"


class Cache:
    """Filesystem-backed content-addressed cache.

    Construct with an explicit root or accept the default
    (``~/.cache/madrigal/``). All operations are key-addressed; the
    cache does not derive keys itself.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or default_cache_root()).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def get(self, cache_key: str) -> CacheEntry | None:
        """Return the cached entry, or None on miss.

        A miss includes both "no entry at this key" and "partial entry
        (audio file present but metadata missing or vice versa)" — we
        treat partial entries as cache misses rather than raise, since
        the most likely cause is a crashed write.
        """
        meta_path, audio_path = self._paths_for(cache_key)
        if not meta_path.exists() or not audio_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            audio = audio_path.read_bytes()
        except (OSError, json.JSONDecodeError):
            return None
        return CacheEntry(
            audio=audio,
            sha256=meta["sha256"],
            sample_rate_hz=int(meta["sample_rate_hz"]),
            duration_ms=int(meta["duration_ms"]),
            generation_s=float(meta["generation_s"]),
            timestamp_utc=meta["timestamp_utc"],
        )

    def put(self, cache_key: str, entry: CacheEntry) -> None:
        """Write the entry atomically (temp file + rename).

        Atomic across the audio file write; the JSON metadata file is
        written second and also atomically. If the process crashes
        between them, the next ``get()`` will treat the entry as a miss
        (the audio file is present but metadata isn't) and overwrite on
        the next ``put()``.
        """
        meta_path, audio_path = self._paths_for(cache_key)
        meta_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic audio write.
        audio_tmp = audio_path.with_suffix(audio_path.suffix + ".tmp")
        audio_tmp.write_bytes(entry.audio)
        os.replace(audio_tmp, audio_path)

        # Atomic metadata write.
        meta = {
            "sha256": entry.sha256,
            "sample_rate_hz": entry.sample_rate_hz,
            "duration_ms": entry.duration_ms,
            "generation_s": entry.generation_s,
            "timestamp_utc": entry.timestamp_utc,
        }
        meta_tmp = meta_path.with_suffix(meta_path.suffix + ".tmp")
        meta_tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        os.replace(meta_tmp, meta_path)

    def has(self, cache_key: str) -> bool:
        """Fast existence check (both files present + readable). Useful for cache-hit telemetry without paying the read cost."""
        meta_path, audio_path = self._paths_for(cache_key)
        return meta_path.exists() and audio_path.exists()

    def delete(self, cache_key: str) -> None:
        """Remove an entry; no-op if it doesn't exist."""
        meta_path, audio_path = self._paths_for(cache_key)
        for p in (meta_path, audio_path):
            try:
                p.unlink()
            except FileNotFoundError:
                pass

    def clear(self) -> None:
        """Delete all cached entries. Mostly for tests; consumers rarely call this."""
        # Walk the two-level shard dirs + clean each subtree.
        if not self._root.exists():
            return
        for shard in self._root.iterdir():
            if shard.is_dir():
                for child in shard.iterdir():
                    try:
                        child.unlink()
                    except OSError:
                        pass
                try:
                    shard.rmdir()
                except OSError:
                    pass

    def _paths_for(self, cache_key: str) -> tuple[Path, Path]:
        """Return (meta_path, audio_path) for a key. Two-level dir split."""
        if len(cache_key) < 2:
            raise ValueError(f"cache_key too short: {cache_key!r} (need ≥2 chars for shard split)")
        shard = cache_key[:2]
        rest = cache_key[2:]
        meta = self._root / shard / f"{rest}.json"
        audio = self._root / shard / f"{rest}.wav"
        return meta, audio
