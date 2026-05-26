"""madrigal.cache — content-addressed cache for synthesized audio.

Per plan v2 §2 + §5: minimal 6-field CacheEntry; consumer-wraps-for-extra.
The cache stores ONLY what madrigal itself cares about (audio bytes + format
metadata + cost telemetry); policy-shaped metadata (consent snapshots,
GPU-minutes accounting, regulatory wrappers) lives in consumer layers.

Key derivation lives in the orchestrator (`madrigal.generate()`), NOT in
the cache. The cache is a pure storage layer addressed by string keys.
This keeps cache reusable across different key-derivation policies if
they ever diverge across consumers.

Storage: filesystem hash store at ``~/.cache/madrigal/`` (configurable).
Two-level directory split (first 2 chars of key) to avoid one giant
flat dir. Each entry is two files: ``<key>.wav`` (audio) +
``<key>.json`` (metadata). Atomic writes via temp-file-then-rename.

Upgrade path: when querying becomes a real need (e.g., "all entries
older than N days," "all entries for voice_id X"), replace the
filesystem store with SQLite-backed storage. CacheEntry shape stays
the same; only the storage substrate changes.
"""

from madrigal.cache.store import Cache, CacheEntry

__all__ = ["Cache", "CacheEntry"]
