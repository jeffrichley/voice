"""Deterministic synthetic-audio backend for tests.

``FakeTTSBackend`` conforms to the ``TTSBackend`` Protocol and returns
WAV-formatted sine-wave audio whose pitch + duration are deterministic
functions of ``(voice_id, text, seed)``. This lets tests:

- Assert call shape (was ``synthesize`` invoked? with what args?)
- Assert deterministic output (same input → same bytes)
- Exercise the cache (cache hit returns identical bytes)
- Run without torch/CUDA installed

Never used in production. The Protocol the Fake conforms to is THE
contract real backends honor; if a Fake-test passes, the consumer's
generate-loop wiring is sound regardless of which real backend is
substituted at deploy time.
"""

from __future__ import annotations

import hashlib
import io
import math
import struct
import wave
from pathlib import Path

from voice.engine._batch_fallback import default_batch_loop
from voice.engine.protocol import EmptyTextError, VoiceNotPreparedError


class FakeTTSBackend:
    """Deterministic synthetic-audio backend.

    Generates a sine wave at a frequency derived from ``hash(voice_id)``
    for ``duration`` seconds derived from ``len(text)``. Same inputs
    always produce identical WAV bytes.
    """

    SAMPLE_RATE_HZ = 16_000
    SAMPLE_WIDTH_BYTES = 2  # int16

    def __init__(self) -> None:
        self._prepared: set[str] = set()
        self._call_log: list[tuple[str, str, str, int]] = []

    def prepare_voice(self, voice_id: str, ref_wav: Path, ref_text: str) -> None:
        """Record the voice as prepared. ref_wav existence is checked even though Fake doesn't read it."""
        ref_wav = Path(ref_wav)
        if not ref_wav.exists():
            raise FileNotFoundError(f"ref_wav not found: {ref_wav}")
        self._prepared.add(voice_id)
        self._call_log.append(("prepare_voice", voice_id, ref_text, 0))

    def synthesize(self, voice_id: str, text: str, seed: int) -> tuple[bytes, float]:
        """Return deterministic sine-wave WAV bytes + a fixed generation_s."""
        if voice_id not in self._prepared:
            raise VoiceNotPreparedError(f"voice {voice_id!r} not prepared")
        if not text.strip():
            raise EmptyTextError("text is empty or whitespace-only")

        self._call_log.append(("synthesize", voice_id, text, seed))

        frequency_hz = self._frequency_for(voice_id)
        duration_s = max(0.1, len(text) * 0.05)  # 50ms per character, floor 100ms
        wav_bytes = self._render_sine(frequency_hz=frequency_hz, duration_s=duration_s, seed=seed)

        # Deterministic "generation_s" — not real wall time, but stable per input.
        generation_s = round(duration_s * 0.1, 4)
        return wav_bytes, generation_s

    def synthesize_batch(
        self, voice_id: str, texts: list[str], seed: int
    ) -> tuple[list[bytes], list[float]]:
        """Sequential per-text fallback. Same output as N synthesize() calls.

        Fake does NOT natively batch; it delegates to the module fallback.
        Real backends that benefit from native batching (Qwen3-TTS,
        ElevenLabs) override this with their engine-specific path.
        """
        return default_batch_loop(self, voice_id, texts, seed)

    @property
    def call_log(self) -> list[tuple[str, str, str, int]]:
        """Inspect what was called during a test. Read-only-by-convention."""
        return list(self._call_log)

    def _frequency_for(self, voice_id: str) -> float:
        """Map voice_id → a frequency in the ~150-450 Hz range (deterministic)."""
        digest = hashlib.sha256(voice_id.encode("utf-8")).digest()
        # Map first 2 bytes (0-65535) into 150-450 Hz.
        raw = digest[0] * 256 + digest[1]
        return 150.0 + (raw / 65535.0) * 300.0

    def _render_sine(self, *, frequency_hz: float, duration_s: float, seed: int) -> bytes:
        """Encode a sine wave to mono 16-bit WAV. seed perturbs phase deterministically."""
        n_samples = int(self.SAMPLE_RATE_HZ * duration_s)
        phase_offset = (seed % 360) * math.pi / 180.0
        amplitude = 16_000  # well below int16 max to leave headroom

        samples = bytearray()
        two_pi_f_over_sr = 2.0 * math.pi * frequency_hz / self.SAMPLE_RATE_HZ
        for i in range(n_samples):
            sample = int(amplitude * math.sin(two_pi_f_over_sr * i + phase_offset))
            samples.extend(struct.pack("<h", sample))

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(self.SAMPLE_WIDTH_BYTES)
            wav.setframerate(self.SAMPLE_RATE_HZ)
            wav.writeframes(bytes(samples))
        return buf.getvalue()
