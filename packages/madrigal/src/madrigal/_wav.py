"""Private WAV helpers used by the orchestrator.

Two operations: read the sample rate from a WAV blob (for Result
population), and concatenate N WAVs of matching format into one
(for chunked synthesis where the chunks are stitched into a single
audio output).

Private — not part of the public API. Consumers needing WAV manipulation
beyond this should use ``soundfile`` or ``wave`` directly.
"""

from __future__ import annotations

import wave
from io import BytesIO


def wav_sample_rate_hz(audio: bytes) -> int:
    """Read the sample rate from a WAV blob. Raises if not parseable."""
    with wave.open(BytesIO(audio), "rb") as w:
        return w.getframerate()


def wav_duration_ms(audio: bytes) -> int:
    """Return duration in milliseconds. Raises if not parseable."""
    with wave.open(BytesIO(audio), "rb") as w:
        n_frames = w.getnframes()
        rate = w.getframerate()
        return int(n_frames * 1000 / rate) if rate else 0


def concat_wavs(wavs: list[bytes]) -> bytes:
    """Concatenate N WAV blobs (all must share sample format) into one.

    Empty input returns ``b""``. Single-element input returns the input
    unchanged. Raises ``ValueError`` if the WAVs have mismatched format
    (channels / sample-width / sample-rate).
    """
    if not wavs:
        return b""
    if len(wavs) == 1:
        return wavs[0]

    first_channels: int | None = None
    first_sampwidth: int | None = None
    first_rate: int | None = None
    all_frames = bytearray()

    for blob in wavs:
        with wave.open(BytesIO(blob), "rb") as w:
            channels = w.getnchannels()
            sampwidth = w.getsampwidth()
            rate = w.getframerate()
            frames = w.readframes(w.getnframes())

        if first_channels is None:
            first_channels = channels
            first_sampwidth = sampwidth
            first_rate = rate
        elif (channels, sampwidth, rate) != (first_channels, first_sampwidth, first_rate):
            raise ValueError(
                f"cannot concatenate WAVs with different format: "
                f"first was (channels={first_channels}, sampwidth={first_sampwidth}, "
                f"rate={first_rate}); got (channels={channels}, sampwidth={sampwidth}, "
                f"rate={rate})"
            )
        all_frames.extend(frames)

    assert first_channels is not None  # for mypy; loop guarantees not-None
    assert first_sampwidth is not None
    assert first_rate is not None

    buf = BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(first_channels)
        out.setsampwidth(first_sampwidth)
        out.setframerate(first_rate)
        out.writeframes(bytes(all_frames))
    return buf.getvalue()
