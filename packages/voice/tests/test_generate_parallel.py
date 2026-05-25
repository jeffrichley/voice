"""Integration tests for voice v0.1 parallel-gen orchestrator (UC1 + UC2).

Covers the §3 + §4 data-flow diagrams from parallel-gen-design.md:
- UC1: list-input + parallel=True → Result.audios populated
- UC2: chunked string + parallel=True → Result.audio (concat) populated
- Cache partition + reassemble (silent-shuffle catcher)
- cache_hit (any) + cache_fully_hit (all) semantics
- parallel_used flag
- max_batch_size sub-batching
"""

from __future__ import annotations

from pathlib import Path

import pytest

from voice import Cache, Result, Spec, generate
from voice.engine import FakeTTSBackend


@pytest.fixture
def ref_wav(tmp_path: Path) -> Path:
    p = tmp_path / "ref.wav"
    p.write_bytes(b"placeholder")
    return p


@pytest.fixture
def backend(ref_wav: Path) -> FakeTTSBackend:
    b = FakeTTSBackend()
    b.prepare_voice("pepper", ref_wav, "ref text")
    return b


# ---------------------------------------------------------------------------
# UC1 — explicit batch (list-input + parallel=True)
# ---------------------------------------------------------------------------

class TestUC1ExplicitBatch:
    """list-input + parallel=True → Result.audios populated."""

    def test_basic_returns_audios_list(self, backend: FakeTTSBackend) -> None:
        result = generate(["one", "two", "three"], Spec(voice_id="pepper", parallel=True), backend=backend)
        assert isinstance(result, Result)
        assert result.audios is not None
        assert len(result.audios) == 3
        assert all(isinstance(a, bytes) for a in result.audios)
        assert result.audio is None  # UC1 doesn't populate .audio
        assert result.parallel_used is True
        assert result.timings is not None
        assert len(result.timings) == 3

    def test_input_order_preserved(self, backend: FakeTTSBackend) -> None:
        """audios[i] corresponds to texts[i]. Determinism enforces this."""
        result = generate(["alpha", "beta", "gamma"], Spec(voice_id="pepper", parallel=True), backend=backend)
        seq = [backend.synthesize("pepper", t, 42) for t in ["alpha", "beta", "gamma"]]
        assert result.audios == [s[0] for s in seq]

    def test_list_input_without_parallel_raises(self, backend: FakeTTSBackend) -> None:
        with pytest.raises(ValueError, match="list input requires"):
            generate(["a", "b"], Spec(voice_id="pepper", parallel=False), backend=backend)

    def test_empty_list_returns_empty_result(self, backend: FakeTTSBackend) -> None:
        result = generate([], Spec(voice_id="pepper", parallel=True), backend=backend)
        assert result.audios == []
        assert result.timings == []
        assert result.parallel_used is True

    def test_single_item_list(self, backend: FakeTTSBackend) -> None:
        """N=1 still goes through the batch path; .audios has one element."""
        result = generate(["only"], Spec(voice_id="pepper", parallel=True), backend=backend)
        assert result.audios is not None
        assert len(result.audios) == 1
        assert result.audio is None


class TestUC1CacheAndParallelMutuallyExclusive:
    """Spec §5 conditional path (active after 2026-05-25 empirical test).

    Qwen3-TTS native batching is item-coupled; per-item cache + batch
    synthesis cannot safely compose. UC1 (declarative list-input) raises
    ValueError; consumer picks which flag to drop.
    """

    def test_cache_and_parallel_raises(
        self, backend: FakeTTSBackend, tmp_path: Path
    ) -> None:
        cache = Cache(root=tmp_path / "cache")
        with pytest.raises(ValueError, match="mutually exclusive"):
            generate(
                ["a", "b", "c"],
                Spec(voice_id="pepper", parallel=True, cache=True),
                backend=backend,
                cache=cache,
            )

    def test_error_message_names_alternatives(
        self, backend: FakeTTSBackend, tmp_path: Path
    ) -> None:
        """Useful error: tells consumer which flag to drop + why."""
        cache = Cache(root=tmp_path / "cache")
        with pytest.raises(ValueError) as exc:
            generate(
                ["a"],
                Spec(voice_id="pepper", parallel=True, cache=True),
                backend=backend,
                cache=cache,
            )
        msg = str(exc.value)
        assert "cache=True" in msg
        assert "parallel=True" in msg
        assert "item-coupled" in msg

    def test_parallel_only_works(self, backend: FakeTTSBackend) -> None:
        """parallel=True alone (cache=False): batch path active, no raise."""
        result = generate(
            ["a", "b", "c"],
            Spec(voice_id="pepper", parallel=True, cache=False),
            backend=backend,
        )
        assert result.parallel_used is True
        assert result.audios is not None
        assert len(result.audios) == 3

    def test_cache_only_with_list_raises(self, backend: FakeTTSBackend, tmp_path: Path) -> None:
        """cache=True alone with list-input still raises (list requires parallel)."""
        cache = Cache(root=tmp_path / "cache")
        # list input requires parallel=True; with parallel=False, raises
        # different error (list-without-parallel).
        with pytest.raises(ValueError, match="list input requires"):
            generate(
                ["a"],
                Spec(voice_id="pepper", parallel=False, cache=True),
                backend=backend,
                cache=cache,
            )

    def test_silent_shuffle_catcher_still_works_without_cache(
        self, backend: FakeTTSBackend
    ) -> None:
        """Input-order preservation still verified for parallel-only path."""
        result = generate(
            ["alpha", "beta", "gamma"],
            Spec(voice_id="pepper", parallel=True, cache=False),
            backend=backend,
        )
        assert result.audios is not None
        seq = [backend.synthesize("pepper", t, 42) for t in ["alpha", "beta", "gamma"]]
        assert result.audios == [s[0] for s in seq]


# ---------------------------------------------------------------------------
# UC2 — auto-parallel-on-chunk (str + chunking + parallel=True)
# ---------------------------------------------------------------------------

class TestUC2ChunkedParallel:
    """str + chunk_strategy + parallel=True → Result.audio (concat) populated."""

    def test_basic_returns_concat_audio(self, backend: FakeTTSBackend) -> None:
        result = generate(
            "First. Second. Third.",
            Spec(voice_id="pepper", chunk_strategy="sentence", parallel=True),
            backend=backend,
        )
        assert isinstance(result, Result)
        assert isinstance(result.audio, bytes)
        assert result.audios is None  # UC2 doesn't populate .audios
        assert result.parallel_used is True
        assert result.timings is not None
        assert len(result.timings) == 3

    def test_audio_is_concat_of_chunks(self, backend: FakeTTSBackend) -> None:
        """UC2's audio = concat of per-chunk audios."""
        text = "First. Second. Third."
        result = generate(
            text,
            Spec(voice_id="pepper", chunk_strategy="sentence", parallel=True),
            backend=backend,
        )
        # Compare against UC2 with parallel=False (sequential chunked v0 path).
        baseline = generate(
            text,
            Spec(voice_id="pepper", chunk_strategy="sentence", parallel=False),
            backend=backend,
        )
        # Same chunks + same sequential audio = same concat output.
        assert result.audio == baseline.audio

    def test_single_chunk_degenerates_to_v0_path(self, backend: FakeTTSBackend) -> None:
        """Long text with chunking that yields only 1 chunk → v0 path. parallel_used=False."""
        result = generate(
            "Just one sentence.",
            Spec(voice_id="pepper", chunk_strategy="sentence", parallel=True),
            backend=backend,
        )
        # Single sentence chunks to 1 chunk; no batching happened.
        assert result.parallel_used is False
        assert result.audio is not None

    def test_write_to_writes_concat(self, backend: FakeTTSBackend, tmp_path: Path) -> None:
        out = tmp_path / "out.wav"
        result = generate(
            "First. Second.",
            Spec(voice_id="pepper", chunk_strategy="sentence", parallel=True, write_to=out),
            backend=backend,
        )
        assert out.exists()
        assert out.read_bytes() == result.audio


class TestUC2CacheAndParallelSilentFallback:
    """Spec §5 conditional path for UC2 (active after 2026-05-25 empirical test).

    UC2 (str + chunking + parallel + cache) silently falls back to v0
    sequential cache+chunking path. Result.parallel_used=False signals
    the fallback fired. Audio is correct (per-chunk cache hits work
    because each chunk is synthesized alone, not in a batch).
    """

    def test_silent_fallback_sets_parallel_used_false(
        self, backend: FakeTTSBackend, tmp_path: Path
    ) -> None:
        cache = Cache(root=tmp_path / "cache")
        result = generate(
            "First. Second.",
            Spec(voice_id="pepper", chunk_strategy="sentence", parallel=True, cache=True),
            backend=backend,
            cache=cache,
        )
        # parallel was requested but fell back to sequential.
        assert result.parallel_used is False
        # Audio still produced correctly.
        assert isinstance(result.audio, bytes)
        # Cache populated normally (per-chunk).
        assert result.manifest is not None
        assert all(m["cache_key"] is not None for m in result.manifest)

    def test_second_call_all_hit_in_fallback_path(
        self, backend: FakeTTSBackend, tmp_path: Path
    ) -> None:
        """Cache works in fallback path; second call gets per-chunk hits."""
        cache = Cache(root=tmp_path / "cache")
        spec = Spec(
            voice_id="pepper", chunk_strategy="sentence", parallel=True, cache=True
        )
        r1 = generate("First. Second.", spec, backend=backend, cache=cache)
        r2 = generate("First. Second.", spec, backend=backend, cache=cache)
        assert r2.cache_fully_hit is True
        assert r2.audio == r1.audio
        # parallel_used False on both runs (fallback active).
        assert r1.parallel_used is False
        assert r2.parallel_used is False

    def test_uc2_parallel_only_works(self, backend: FakeTTSBackend) -> None:
        """parallel=True alone (no cache): batch path active, parallel_used True."""
        result = generate(
            "First. Second.",
            Spec(voice_id="pepper", chunk_strategy="sentence", parallel=True, cache=False),
            backend=backend,
        )
        assert result.parallel_used is True
        assert result.audio is not None

    def test_uc2_cache_only_works(self, backend: FakeTTSBackend, tmp_path: Path) -> None:
        """cache=True alone (no parallel): sequential cache+chunking, parallel_used False."""
        cache = Cache(root=tmp_path / "cache")
        result = generate(
            "First. Second.",
            Spec(voice_id="pepper", chunk_strategy="sentence", parallel=False, cache=True),
            backend=backend,
            cache=cache,
        )
        assert result.parallel_used is False
        assert result.manifest is not None
        assert len(result.manifest) == 2


# ---------------------------------------------------------------------------
# max_batch_size sub-batching
# ---------------------------------------------------------------------------

class TestMaxBatchSize:
    """Spec.max_batch_size slices large batches into sub-batches."""

    def test_unlimited_default(self, backend: FakeTTSBackend) -> None:
        """Default None passes the full list in one call. Equivalent output."""
        texts = ["a", "b", "c", "d", "e"]
        r_unlimited = generate(
            texts, Spec(voice_id="pepper", parallel=True, max_batch_size=None), backend=backend
        )
        r_sliced = generate(
            texts, Spec(voice_id="pepper", parallel=True, max_batch_size=2), backend=backend
        )
        # Same output regardless of slicing.
        assert r_unlimited.audios == r_sliced.audios

    def test_slicing_into_sub_batches(self, backend: FakeTTSBackend) -> None:
        """max_batch_size=2 on a 5-item list → 3 sub-batches (2 + 2 + 1)."""
        texts = [f"text_{i}" for i in range(5)]
        result = generate(
            texts,
            Spec(voice_id="pepper", parallel=True, max_batch_size=2),
            backend=backend,
        )
        assert result.audios is not None
        assert len(result.audios) == 5
        # Each audio matches direct synthesis.
        for i, t in enumerate(texts):
            expected, _ = backend.synthesize("pepper", t, 42)
            assert result.audios[i] == expected

    def test_slicing_with_cache_raises(self, backend: FakeTTSBackend, tmp_path: Path) -> None:
        """Sub-batching + cache + parallel: still raises per §5 (cache+parallel mutually exclusive)."""
        cache = Cache(root=tmp_path / "cache")
        spec = Spec(voice_id="pepper", parallel=True, cache=True, max_batch_size=2)
        texts = ["a", "b", "c", "d", "e"]
        with pytest.raises(ValueError, match="mutually exclusive"):
            generate(texts, spec, backend=backend, cache=cache)
