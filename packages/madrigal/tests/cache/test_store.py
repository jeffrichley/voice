"""Test the filesystem Cache: round-trip, sharding, atomicity, miss-shapes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from madrigal.cache import Cache, CacheEntry
from madrigal.cache.store import default_cache_root


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(root=tmp_path / "voice-cache")


@pytest.fixture
def entry() -> CacheEntry:
    return CacheEntry(
        audio=b"FAKE WAV DATA",
        sha256="abc123",
        sample_rate_hz=16_000,
        duration_ms=500,
        generation_s=0.05,
        timestamp_utc="2026-05-24T21:30:00+00:00",
    )


KEY = "abcdef0123456789"  # 16 hex chars; first 2 = shard


def test_round_trip(cache: Cache, entry: CacheEntry) -> None:
    cache.put(KEY, entry)
    got = cache.get(KEY)
    assert got == entry


def test_miss_returns_none(cache: Cache) -> None:
    assert cache.get(KEY) is None


def test_has_fast_check(cache: Cache, entry: CacheEntry) -> None:
    assert not cache.has(KEY)
    cache.put(KEY, entry)
    assert cache.has(KEY)


def test_two_level_dir_shard(cache: Cache, entry: CacheEntry) -> None:
    cache.put(KEY, entry)
    shard = KEY[:2]
    rest = KEY[2:]
    assert (cache.root / shard / f"{rest}.wav").exists()
    assert (cache.root / shard / f"{rest}.json").exists()


def test_metadata_persists_correctly(cache: Cache, entry: CacheEntry) -> None:
    cache.put(KEY, entry)
    meta_path = cache.root / KEY[:2] / f"{KEY[2:]}.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["sha256"] == "abc123"
    assert meta["sample_rate_hz"] == 16_000
    assert meta["duration_ms"] == 500
    assert meta["generation_s"] == 0.05
    assert meta["timestamp_utc"] == "2026-05-24T21:30:00+00:00"


def test_audio_in_separate_file_not_in_json(cache: Cache, entry: CacheEntry) -> None:
    """JSON sidecar must NOT contain audio bytes — keeps metadata small + greppable."""
    cache.put(KEY, entry)
    meta_path = cache.root / KEY[:2] / f"{KEY[2:]}.json"
    meta_text = meta_path.read_text(encoding="utf-8")
    assert "FAKE WAV DATA" not in meta_text
    assert "audio" not in meta_text


def test_partial_entry_treated_as_miss(cache: Cache, entry: CacheEntry) -> None:
    """If audio is present but metadata isn't (or vice versa), get() returns None."""
    cache.put(KEY, entry)
    # Simulate crashed write: nuke the metadata.
    (cache.root / KEY[:2] / f"{KEY[2:]}.json").unlink()
    assert cache.get(KEY) is None
    assert not cache.has(KEY)


def test_corrupt_metadata_treated_as_miss(cache: Cache, entry: CacheEntry) -> None:
    cache.put(KEY, entry)
    meta_path = cache.root / KEY[:2] / f"{KEY[2:]}.json"
    meta_path.write_text("{not valid json", encoding="utf-8")
    assert cache.get(KEY) is None


def test_delete_removes_both_files(cache: Cache, entry: CacheEntry) -> None:
    cache.put(KEY, entry)
    cache.delete(KEY)
    assert cache.get(KEY) is None


def test_delete_missing_is_noop(cache: Cache) -> None:
    # Should not raise.
    cache.delete(KEY)


def test_clear_removes_all_entries(cache: Cache, entry: CacheEntry) -> None:
    for k in ["abcdef", "abdef1", "cd1234", "ef5678"]:
        cache.put(k, entry)
    cache.clear()
    for k in ["abcdef", "abdef1", "cd1234", "ef5678"]:
        assert cache.get(k) is None


def test_atomic_overwrite(cache: Cache, entry: CacheEntry) -> None:
    """A second put() with same key replaces the first cleanly."""
    cache.put(KEY, entry)
    entry2 = CacheEntry(
        audio=b"NEW WAV",
        sha256="def456",
        sample_rate_hz=22_050,
        duration_ms=1000,
        generation_s=0.1,
        timestamp_utc="2026-05-25T00:00:00+00:00",
    )
    cache.put(KEY, entry2)
    got = cache.get(KEY)
    assert got == entry2


def test_short_key_raises(cache: Cache, entry: CacheEntry) -> None:
    with pytest.raises(ValueError, match="too short"):
        cache.put("x", entry)


def test_default_root_under_home() -> None:
    """default_cache_root falls under HOME/.cache when XDG_CACHE_HOME unset."""
    import os
    # Make sure XDG_CACHE_HOME isn't set for the test.
    os.environ.pop("XDG_CACHE_HOME", None)
    root = default_cache_root()
    assert root.name == "madrigal"
    assert root.parent.name == ".cache"


def test_default_root_honors_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    root = default_cache_root()
    assert root == tmp_path / "madrigal"
