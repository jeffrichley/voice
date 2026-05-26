"""Test the Protocol + error taxonomy shape (no real backend invocation)."""

from __future__ import annotations

from pathlib import Path

import pytest

from madrigal.engine import (
    EmptyTextError,
    GPUOOMError,
    TextTooLongError,
    TTSBackend,
    VoiceError,
    VoiceInfo,
    VoiceNotPreparedError,
)


def test_error_taxonomy_descends_from_voice_error() -> None:
    """All backend-raisable errors share the VoiceError base."""
    assert issubclass(EmptyTextError, VoiceError)
    assert issubclass(TextTooLongError, VoiceError)
    assert issubclass(GPUOOMError, VoiceError)
    assert issubclass(VoiceNotPreparedError, VoiceError)
    assert issubclass(VoiceError, Exception)


def test_voice_info_is_frozen_dataclass() -> None:
    info = VoiceInfo(
        voice_id="pepper",
        ref_wav=Path("/tmp/ref.wav"),
        ref_text="Reference text.",
    )
    import dataclasses

    assert info.voice_id == "pepper"
    assert info.blend is None
    # Frozen dataclass: mutation raises FrozenInstanceError specifically.
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.voice_id = "other"  # type: ignore[misc]


def test_voice_info_blend_optional() -> None:
    info = VoiceInfo(
        voice_id="pepper",
        ref_wav=Path("/tmp/ref.wav"),
        ref_text="Reference text.",
        blend="warm-low-70-20-10",
    )
    assert info.blend == "warm-low-70-20-10"


def test_tts_backend_is_runtime_checkable() -> None:
    """TTSBackend is a runtime_checkable Protocol; isinstance() works.

    v0.1: adapters must implement BOTH synthesize and synthesize_batch.
    """

    class MinimalBackend:
        def prepare_voice(self, voice_id: str, ref_wav: Path, ref_text: str) -> None:
            pass

        def synthesize(self, voice_id: str, text: str, seed: int) -> tuple[bytes, float]:
            return b"", 0.0

        def synthesize_batch(
            self, voice_id: str, texts: list[str], seed: int
        ) -> tuple[list[bytes], list[float]]:
            return [b""] * len(texts), [0.0] * len(texts)

    assert isinstance(MinimalBackend(), TTSBackend)


def test_tts_backend_rejects_non_conformant() -> None:
    """A class missing required methods is NOT a TTSBackend."""

    class IncompleteBackend:
        def prepare_voice(self, voice_id: str, ref_wav: Path, ref_text: str) -> None:
            pass

        # Missing synthesize()

    assert not isinstance(IncompleteBackend(), TTSBackend)
