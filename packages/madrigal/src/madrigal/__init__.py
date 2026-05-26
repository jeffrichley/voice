"""madrigal — pluggable TTS engine library.

Pure library: no bus, no agent-core dependencies. Three named consumers
(conversational via agent-core-voice adapter, audiobook pipeline, narration)
each get first-class API support. See repo CLAUDE.md for design constraints
and `docs/superpowers/specs/2026-05-24-voice-plan.md` for the full plan.

Public API:
    madrigal.generate(text, spec) -> Result    # single entry point
    madrigal.speak(text, voice_id) -> bytes    # convenience wrapper
    madrigal.Spec                              # request object
    madrigal.Result                            # response object
    madrigal.Registry                          # voice catalog
    madrigal.Cache, madrigal.CacheEntry           # content-addressed cache
    madrigal.engine                            # engine adapter submodule
    madrigal.chunking                          # chunking strategies

Quick start:

    from madrigal import generate, Spec
    from madrigal.engine import FakeTTSBackend  # or QwenTTSBackend in prod
    from madrigal.registry import Registry

    backend = FakeTTSBackend()
    backend.prepare_voice("pepper", Path("ref.wav"), "Reference text.")
    result = generate("Hello, Jeff.", Spec(voice_id="pepper"), backend=backend)
    audio_bytes = bytes(result)
"""

from madrigal.cache import Cache, CacheEntry
from madrigal.generate import generate, speak
from madrigal.registry import Registry
from madrigal.result import Result
from madrigal.spec import Spec

__all__ = [
    "Cache",
    "CacheEntry",
    "Registry",
    "Result",
    "Spec",
    "generate",
    "speak",
]
