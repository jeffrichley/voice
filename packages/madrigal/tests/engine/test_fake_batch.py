"""Tests for FakeTTSBackend.synthesize_batch via default_batch_loop.

The Fake doesn't natively batch; it delegates to the module fallback.
These tests prove the fallback produces the same audio + timings as
N separate synthesize() calls — so any test using Fake.synthesize_batch
is equivalent to testing the orchestrator's batch-routing behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from madrigal.engine import EmptyTextError, FakeTTSBackend, VoiceNotPreparedError
from madrigal.engine._batch_fallback import default_batch_loop


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


def test_synthesize_batch_returns_two_lists(backend: FakeTTSBackend) -> None:
    audios, timings = backend.synthesize_batch("pepper", ["one", "two", "three"], seed=42)
    assert len(audios) == 3
    assert len(timings) == 3
    assert all(isinstance(a, bytes) for a in audios)
    assert all(isinstance(t, float) for t in timings)


def test_synthesize_batch_matches_sequential(backend: FakeTTSBackend) -> None:
    """Fake's batch = N sequential calls. Determinism end-to-end."""
    texts = ["alpha", "beta", "gamma"]
    seed = 42

    batched_audios, batched_timings = backend.synthesize_batch("pepper", texts, seed)

    sequential_results = [backend.synthesize("pepper", t, seed) for t in texts]
    sequential_audios = [r[0] for r in sequential_results]
    sequential_timings = [r[1] for r in sequential_results]

    assert batched_audios == sequential_audios
    assert batched_timings == sequential_timings


def test_synthesize_batch_empty_input(backend: FakeTTSBackend) -> None:
    """N=0 batch returns ([], []) without invoking the backend."""
    audios, timings = backend.synthesize_batch("pepper", [], seed=42)
    assert audios == []
    assert timings == []


def test_synthesize_batch_single_item(backend: FakeTTSBackend) -> None:
    """N=1 batch equivalent to one synthesize() call."""
    audios, timings = backend.synthesize_batch("pepper", ["only"], seed=42)
    one_audio, one_gen = backend.synthesize("pepper", "only", seed=42)
    assert audios == [one_audio]
    assert timings == [one_gen]


def test_synthesize_batch_propagates_voice_not_prepared(ref_wav: Path) -> None:
    backend = FakeTTSBackend()  # NOT prepared
    with pytest.raises(VoiceNotPreparedError):
        backend.synthesize_batch("missing-voice", ["text"], seed=42)


def test_synthesize_batch_propagates_empty_text(backend: FakeTTSBackend) -> None:
    """Any empty text in the batch fails the whole batch (v0.1 partial-success-OOS)."""
    with pytest.raises(EmptyTextError):
        backend.synthesize_batch("pepper", ["good", "   "], seed=42)


def test_default_batch_loop_function_directly(backend: FakeTTSBackend) -> None:
    """The module function works as a standalone helper too."""
    audios, timings = default_batch_loop(backend, "pepper", ["a", "b"], seed=99)
    assert len(audios) == 2
    assert len(timings) == 2
