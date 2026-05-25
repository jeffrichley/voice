"""Sequential per-text fallback for adapters that don't natively batch.

Composition over inheritance: adapter authors delegate via one line
rather than inheriting a Mixin. Preserves the structural-typing shape
of the runtime_checkable Protocol; no inheritance gymnastics.

Usage (in an adapter that doesn't benefit from native batching):

    from voice.engine._batch_fallback import default_batch_loop

    class MyTTSBackend:
        def synthesize(self, voice_id, text, seed): ...
        def synthesize_batch(self, voice_id, texts, seed):
            return default_batch_loop(self, voice_id, texts, seed)

Adapters that DO benefit from native batching (Qwen3-TTS via
generate_voice_clone, ElevenLabs via concurrent HTTP, etc.) override
synthesize_batch with their own implementation.
"""

from __future__ import annotations

from voice.engine.protocol import TTSBackend


def default_batch_loop(
    backend: TTSBackend,
    voice_id: str,
    texts: list[str],
    seed: int,
) -> tuple[list[bytes], list[float]]:
    """Sequential per-text fallback. Same audio + timings as N separate synthesize() calls.

    Returns (audios, timings) parallel-indexed with the input texts.
    Raises whatever the backend's synthesize() raises (no error wrapping).
    """
    results = [backend.synthesize(voice_id, t, seed) for t in texts]
    audios = [r[0] for r in results]
    timings = [r[1] for r in results]
    return audios, timings
