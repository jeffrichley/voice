"""madrigal.engine — pluggable TTS engine adapters.

The ``TTSBackend`` Protocol is the seam between madrigal's top-level
``generate()`` and the actual TTS model. v0 ships two concrete backends:

- ``FakeTTSBackend`` — deterministic synthetic-audio backend for tests
- ``QwenTTSBackend`` — Qwen3-TTS wrapper with in-context-learning voice cloning

Additional backends (ElevenLabs, OpenAI TTS, etc.) can be added as
separate adapter modules conforming to the Protocol. The library does
NOT auto-discover plugins; consumers wire the backend they want at
construction time.

``QwenTTSBackend.__init__`` lazy-imports ``qwen_tts`` and ``torch`` so
``import madrigal.engine`` works on hosts without torch installed. Real
Qwen synthesis requires the user to install ``qwen-tts`` separately
(not on PyPI today; agent_core releases ship a wheel as an asset).
"""

from madrigal.engine.fake import FakeTTSBackend
from madrigal.engine.protocol import (
    EmptyTextError,
    GPUOOMError,
    TextTooLongError,
    TTSBackend,
    VoiceError,
    VoiceInfo,
    VoiceNotPreparedError,
)
from madrigal.engine.qwen import QwenTTSBackend

__all__ = [
    "EmptyTextError",
    "FakeTTSBackend",
    "GPUOOMError",
    "QwenTTSBackend",
    "TTSBackend",
    "TextTooLongError",
    "VoiceError",
    "VoiceInfo",
    "VoiceNotPreparedError",
]
