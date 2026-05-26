"""Integration tests for madrigal.generate() + madrigal.speak().

Covers the attribute-population matrix from plan v2 §3 case-by-case.
Uses FakeTTSBackend (deterministic) so cache-hit + repro tests are sound.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from madrigal import Cache, Result, Spec, generate, speak
from madrigal.engine import FakeTTSBackend


@pytest.fixture
def ref_wav(tmp_path: Path) -> Path:
    p = tmp_path / "ref.wav"
    p.write_bytes(b"placeholder")
    return p


@pytest.fixture
def backend(ref_wav: Path) -> FakeTTSBackend:
    b = FakeTTSBackend()
    b.prepare_voice("pepper", ref_wav, "Reference text.")
    return b


# ---------------------------------------------------------------------------
# Population matrix — conversational default
# ---------------------------------------------------------------------------

def test_conversational_default(backend: FakeTTSBackend) -> None:
    result = generate("Hello.", Spec(voice_id="pepper"), backend=backend)
    assert isinstance(result, Result)
    assert isinstance(result.audio, bytes)
    assert len(result.audio) > 0
    assert result.audios is None
    assert result.path is None
    assert result.manifest is None
    assert result.timings is None
    assert result.cache_key is None
    assert result.cache_hit is False
    assert result.sample_rate_hz == FakeTTSBackend.SAMPLE_RATE_HZ


# ---------------------------------------------------------------------------
# bytes() fast-path
# ---------------------------------------------------------------------------

def test_bytes_fast_path(backend: FakeTTSBackend) -> None:
    result = generate("Hello.", Spec(voice_id="pepper"), backend=backend)
    audio = bytes(result)
    assert audio == result.audio
    assert isinstance(audio, bytes)


def test_bytes_on_audios_only_raises() -> None:
    """Result with .audio=None (e.g., parallel-gen path) raises on bytes()."""
    r = Result(audios=[b"x", b"y"])  # constructed directly; never produced by v0 generate()
    with pytest.raises(ValueError, match="no .audio"):
        bytes(r)


# ---------------------------------------------------------------------------
# Cache: miss then hit
# ---------------------------------------------------------------------------

def test_cache_miss_then_hit(backend: FakeTTSBackend, tmp_path: Path) -> None:
    cache = Cache(root=tmp_path / "cache")
    spec = Spec(voice_id="pepper", cache=True)

    # First call: miss.
    r1 = generate("Hello.", spec, backend=backend, cache=cache)
    assert r1.cache_key is not None
    assert r1.cache_hit is False
    assert r1.audio is not None

    # Second call: hit. Same key. Same audio.
    r2 = generate("Hello.", spec, backend=backend, cache=cache)
    assert r2.cache_key == r1.cache_key
    assert r2.cache_hit is True
    assert r2.audio == r1.audio


def test_cache_different_text_different_key(backend: FakeTTSBackend, tmp_path: Path) -> None:
    cache = Cache(root=tmp_path / "cache")
    spec = Spec(voice_id="pepper", cache=True)
    r1 = generate("Hello.", spec, backend=backend, cache=cache)
    r2 = generate("World.", spec, backend=backend, cache=cache)
    assert r1.cache_key != r2.cache_key


def test_cache_different_seed_different_key(backend: FakeTTSBackend, tmp_path: Path) -> None:
    cache = Cache(root=tmp_path / "cache")
    r1 = generate("Hello.", Spec(voice_id="pepper", cache=True, seed=1), backend=backend, cache=cache)
    r2 = generate("Hello.", Spec(voice_id="pepper", cache=True, seed=2), backend=backend, cache=cache)
    assert r1.cache_key != r2.cache_key


def test_cache_required_when_cache_true(backend: FakeTTSBackend) -> None:
    with pytest.raises(ValueError, match="requires a Cache instance"):
        generate("Hello.", Spec(voice_id="pepper", cache=True), backend=backend)


def test_cache_disabled_no_key(backend: FakeTTSBackend, tmp_path: Path) -> None:
    """Even if a cache is passed, spec.cache=False means no key derivation, no lookup."""
    cache = Cache(root=tmp_path / "cache")
    result = generate("Hello.", Spec(voice_id="pepper", cache=False), backend=backend, cache=cache)
    assert result.cache_key is None
    assert result.cache_hit is False
    # Cache should be untouched.
    assert not any(cache.root.iterdir()) if cache.root.exists() else True


# ---------------------------------------------------------------------------
# Cache-key derivation properties (Pepper's strict-purity ask)
# ---------------------------------------------------------------------------

def test_cache_key_ignores_write_to(backend: FakeTTSBackend, tmp_path: Path) -> None:
    """write_to changes behavior, not output. Must NOT affect cache key."""
    cache = Cache(root=tmp_path / "cache")
    r1 = generate(
        "Hello.",
        Spec(voice_id="pepper", cache=True),
        backend=backend,
        cache=cache,
    )
    r2 = generate(
        "Hello.",
        Spec(voice_id="pepper", cache=True, write_to=tmp_path / "out.wav"),
        backend=backend,
        cache=cache,
    )
    # Same key → cache HIT on the second call.
    assert r2.cache_key == r1.cache_key
    assert r2.cache_hit is True


def test_cache_key_extra_dict_order_independent(backend: FakeTTSBackend, tmp_path: Path) -> None:
    """spec.extra dict-ordering must not affect the key."""
    cache = Cache(root=tmp_path / "cache")
    r1 = generate(
        "Hello.",
        Spec(voice_id="pepper", cache=True, extra={"a": 1, "b": 2}),
        backend=backend,
        cache=cache,
    )
    r2 = generate(
        "Hello.",
        Spec(voice_id="pepper", cache=True, extra={"b": 2, "a": 1}),
        backend=backend,
        cache=cache,
    )
    assert r2.cache_key == r1.cache_key
    assert r2.cache_hit is True


# ---------------------------------------------------------------------------
# write_to
# ---------------------------------------------------------------------------

def test_write_to_populates_path_and_keeps_audio(backend: FakeTTSBackend, tmp_path: Path) -> None:
    out = tmp_path / "out.wav"
    result = generate("Hello.", Spec(voice_id="pepper", write_to=out), backend=backend)
    assert result.path == out
    assert out.exists()
    assert out.read_bytes() == result.audio


def test_write_to_creates_parent_dir(backend: FakeTTSBackend, tmp_path: Path) -> None:
    out = tmp_path / "nested" / "subdir" / "out.wav"
    result = generate("Hello.", Spec(voice_id="pepper", write_to=out), backend=backend)
    assert out.exists()
    assert result.path == out


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def test_sentence_chunking_populates_manifest_and_timings(backend: FakeTTSBackend) -> None:
    text = "First. Second. Third."
    result = generate(text, Spec(voice_id="pepper", chunk_strategy="sentence"), backend=backend)
    assert result.manifest is not None
    assert len(result.manifest) == 3
    assert [m["text"] for m in result.manifest] == ["First.", "Second.", "Third."]
    assert result.timings is not None
    assert len(result.timings) == 3
    assert all(t > 0 for t in result.timings)
    assert result.cache_key is None  # chunked path: per-chunk keys live in manifest


def test_sentence_chunking_audio_is_concat_of_chunks(backend: FakeTTSBackend) -> None:
    """The concat result should be different from any single chunk."""
    text = "First. Second."
    result = generate(text, Spec(voice_id="pepper", chunk_strategy="sentence"), backend=backend)
    single = generate("First.", Spec(voice_id="pepper"), backend=backend)
    # Concat is strictly longer than the single first chunk.
    assert result.audio is not None and single.audio is not None
    assert len(result.audio) > len(single.audio)


def test_paragraph_chunking(backend: FakeTTSBackend) -> None:
    text = "Para one.\n\nPara two.\n\nPara three."
    result = generate(text, Spec(voice_id="pepper", chunk_strategy="paragraph"), backend=backend)
    assert result.manifest is not None
    assert len(result.manifest) == 3


def test_chunk_strategy_none_is_single_chunk_path(backend: FakeTTSBackend) -> None:
    """`none` means no chunking. Result has cache_key (when cache on), no manifest."""
    result = generate("Hello world.", Spec(voice_id="pepper", chunk_strategy="none"), backend=backend)
    assert result.manifest is None
    assert result.timings is None


# ---------------------------------------------------------------------------
# Chunking + cache
# ---------------------------------------------------------------------------

def test_chunking_plus_cache_per_chunk_keys_in_manifest(
    backend: FakeTTSBackend, tmp_path: Path
) -> None:
    cache = Cache(root=tmp_path / "cache")
    spec = Spec(voice_id="pepper", chunk_strategy="sentence", cache=True)
    result = generate("First. Second.", spec, backend=backend, cache=cache)
    assert result.manifest is not None
    for entry in result.manifest:
        assert entry["cache_key"] is not None
        assert entry["cache_hit"] is False  # first run: all misses
    assert result.cache_hit is False  # any-chunk-hit


def test_chunking_plus_cache_second_run_all_hits(
    backend: FakeTTSBackend, tmp_path: Path
) -> None:
    cache = Cache(root=tmp_path / "cache")
    spec = Spec(voice_id="pepper", chunk_strategy="sentence", cache=True)
    _ = generate("First. Second.", spec, backend=backend, cache=cache)
    # Second run: all chunks should hit.
    r2 = generate("First. Second.", spec, backend=backend, cache=cache)
    assert r2.manifest is not None
    assert all(m["cache_hit"] for m in r2.manifest)
    assert r2.cache_hit is True


# ---------------------------------------------------------------------------
# Deferred features (v0.X+) still raise NotImplementedError
# ---------------------------------------------------------------------------

def test_parallel_true_without_list_or_chunking_v0_path(backend: FakeTTSBackend) -> None:
    """v0.1: parallel=True on str-input without chunking degenerates to v0 sequential.

    Single-chunk batch isn't a useful parallelization; route through the
    single-text path. No raise.
    """
    result = generate("Hello.", Spec(voice_id="pepper", parallel=True), backend=backend)
    assert isinstance(result.audio, bytes)
    # parallel_used False because v0-path was taken (no actual batch invocation).
    assert result.parallel_used is False


def test_watermark_true_raises(backend: FakeTTSBackend) -> None:
    with pytest.raises(NotImplementedError, match="watermark.*v0.X"):
        generate("Hello.", Spec(voice_id="pepper", watermark=True), backend=backend)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_text_raises_via_chunker(backend: FakeTTSBackend) -> None:
    with pytest.raises(ValueError, match="produced no chunks"):
        generate("   ", Spec(voice_id="pepper", chunk_strategy="sentence"), backend=backend)


def test_unknown_chunk_strategy_raises(backend: FakeTTSBackend) -> None:
    with pytest.raises(ValueError, match="unknown chunk strategy"):
        generate("Hello.", Spec(voice_id="pepper", chunk_strategy="lstm"), backend=backend)


# ---------------------------------------------------------------------------
# speak() convenience wrapper
# ---------------------------------------------------------------------------

def test_speak_returns_bytes(backend: FakeTTSBackend) -> None:
    audio = speak("Hello.", "pepper", backend=backend)
    assert isinstance(audio, bytes)
    assert len(audio) > 0


def test_speak_equivalent_to_bytes_of_generate(backend: FakeTTSBackend) -> None:
    audio_speak = speak("Hello.", "pepper", backend=backend, seed=99)
    result = generate("Hello.", Spec(voice_id="pepper", seed=99), backend=backend)
    assert audio_speak == bytes(result)


def test_speak_passes_through_spec_kwargs(backend: FakeTTSBackend) -> None:
    """speak(**spec_kwargs) supports extra Spec fields (seed, extra, etc.)."""
    a1 = speak("Hello.", "pepper", backend=backend, seed=1)
    a2 = speak("Hello.", "pepper", backend=backend, seed=2)
    assert a1 != a2  # seed varies output
