"""Test FakeTTSBackend conforms to the TTSBackend Protocol + behaves deterministically."""

from __future__ import annotations

import wave
from io import BytesIO
from pathlib import Path

import pytest

from madrigal.engine import (
    EmptyTextError,
    FakeTTSBackend,
    TTSBackend,
    VoiceNotPreparedError,
)


@pytest.fixture
def ref_wav(tmp_path: Path) -> Path:
    """Touch a placeholder ref_wav file so existence check passes."""
    p = tmp_path / "ref.wav"
    p.write_bytes(b"placeholder")
    return p


def test_conforms_to_protocol() -> None:
    """FakeTTSBackend is structurally a TTSBackend (runtime_checkable Protocol)."""
    backend = FakeTTSBackend()
    assert isinstance(backend, TTSBackend)


def test_synthesize_without_prepare_raises(ref_wav: Path) -> None:
    backend = FakeTTSBackend()
    with pytest.raises(VoiceNotPreparedError):
        backend.synthesize("pepper", "Hello", seed=42)


def test_prepare_missing_ref_wav_raises(tmp_path: Path) -> None:
    backend = FakeTTSBackend()
    missing = tmp_path / "nope.wav"
    with pytest.raises(FileNotFoundError):
        backend.prepare_voice("pepper", missing, "ref text")


def test_empty_text_raises(ref_wav: Path) -> None:
    backend = FakeTTSBackend()
    backend.prepare_voice("pepper", ref_wav, "ref text")
    with pytest.raises(EmptyTextError):
        backend.synthesize("pepper", "   ", seed=42)


def test_synthesize_returns_wav_bytes(ref_wav: Path) -> None:
    backend = FakeTTSBackend()
    backend.prepare_voice("pepper", ref_wav, "ref text")
    audio, gen_s = backend.synthesize("pepper", "Hello, world.", seed=42)

    assert isinstance(audio, bytes)
    assert gen_s > 0

    # Parseable as WAV.
    with wave.open(BytesIO(audio), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == FakeTTSBackend.SAMPLE_RATE_HZ
        assert w.getnframes() > 0


def test_deterministic_same_input_same_bytes(ref_wav: Path) -> None:
    """Same (voice_id, text, seed) → identical bytes. Cache hit reproducibility depends on this."""
    backend1 = FakeTTSBackend()
    backend1.prepare_voice("pepper", ref_wav, "ref text")
    audio1, _ = backend1.synthesize("pepper", "Hello.", seed=42)

    backend2 = FakeTTSBackend()
    backend2.prepare_voice("pepper", ref_wav, "ref text")
    audio2, _ = backend2.synthesize("pepper", "Hello.", seed=42)

    assert audio1 == audio2


def test_seed_changes_audio(ref_wav: Path) -> None:
    backend = FakeTTSBackend()
    backend.prepare_voice("pepper", ref_wav, "ref text")
    audio1, _ = backend.synthesize("pepper", "Hello.", seed=42)
    audio2, _ = backend.synthesize("pepper", "Hello.", seed=999)
    assert audio1 != audio2


def test_different_voices_different_frequencies(ref_wav: Path) -> None:
    backend = FakeTTSBackend()
    backend.prepare_voice("pepper", ref_wav, "ref text")
    backend.prepare_voice("saki", ref_wav, "ref text")
    audio_pepper, _ = backend.synthesize("pepper", "Hello.", seed=42)
    audio_saki, _ = backend.synthesize("saki", "Hello.", seed=42)
    assert audio_pepper != audio_saki


def test_call_log_records_invocations(ref_wav: Path) -> None:
    backend = FakeTTSBackend()
    backend.prepare_voice("pepper", ref_wav, "ref text")
    backend.synthesize("pepper", "Hello.", seed=42)
    backend.synthesize("pepper", "World.", seed=99)

    log = backend.call_log
    assert log[0][0] == "prepare_voice"
    assert log[1] == ("synthesize", "pepper", "Hello.", 42)
    assert log[2] == ("synthesize", "pepper", "World.", 99)
