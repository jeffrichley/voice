"""voice.generate — the orchestrator + voice.speak convenience wrapper.

Per plan v2 §1: single entry point with uniform Result return.

This module wires together:
- voice.Spec (request)
- voice.engine.TTSBackend (synthesis)
- voice.registry.Registry (voice_id → VoiceInfo)
- voice.cache.Cache (content-addressed)
- voice.chunking (text splitting)
- voice.Result (response, attribute-population-by-config)

v0.1 added: parallel-gen via backend.synthesize_batch. Two use cases:
- UC1: text=list[str] + parallel=True → Result.audios populated
- UC2: text=str + chunk_strategy + parallel=True → Result.audio (concat) populated

See plan v2 §3 + parallel-gen-design.md §3 + §4 for the attribute population matrix.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from voice._cache_key import cache_key as _derive_cache_key
from voice._wav import concat_wavs, wav_duration_ms, wav_sample_rate_hz
from voice.cache import Cache, CacheEntry
from voice.chunking import chunk as _chunk_text
from voice.engine.protocol import TTSBackend
from voice.registry import Registry
from voice.result import Result
from voice.spec import Spec

# v0.1 default model_id used for cache-key derivation when caller doesn't
# pass an explicit model_id. Forward-compat: the cache key always includes
# model_id, so a future engine adapter that sets a different model_id will
# segment its cache cleanly.
_DEFAULT_MODEL_ID = "default"


def generate(
    text: str | list[str],
    spec: Spec,
    *,
    backend: TTSBackend,
    registry: Registry | None = None,
    cache: Cache | None = None,
    model_id: str = _DEFAULT_MODEL_ID,
) -> Result:
    """Synthesize ``text`` per ``spec`` via ``backend``.

    Branches on (input type, spec.parallel, spec.chunk_strategy):
    - ``text: str`` + ``parallel=False``: v0 single-text path (with optional chunking).
    - ``text: list[str]`` + ``parallel=True``: UC1 explicit batch path.
    - ``text: str`` + ``parallel=True`` + ``chunk_strategy != "none"``: UC2 chunked-parallel path.
    - ``text: list[str]`` + ``parallel=False``: ValueError ("list input requires parallel=True").

    See parallel-gen-design.md §3 / §4 / §5 for the matrix.
    """
    # 1. Watermark guard (still deferred to v0.X+).
    if spec.watermark:
        raise NotImplementedError(
            "spec.watermark=True is deferred to v0.X+. The flag is wired "
            "through Spec for forward-compatibility but watermark insertion "
            "is not yet implemented."
        )

    # 2. Cache requirement check.
    if spec.cache and cache is None:
        raise ValueError("spec.cache=True requires a Cache instance be passed via `cache=`")

    # 3. Input-type vs parallel-flag validation.
    if isinstance(text, list) and not spec.parallel:
        raise ValueError(
            "list input requires spec.parallel=True. "
            "For sequential per-text synthesis, call generate() once per text."
        )

    # 4. Spec §5 conditional path — cache + parallel handling.
    # The empirical test (2026-05-25) revealed Qwen3-TTS's
    # `generate_voice_clone` native batching is ITEM-COUPLED: an item's
    # output depends on the other items in the batch. Per-item cache
    # entries from one batch would be stale when reused in a different
    # batch. v0.1 enforces mutual exclusion:
    # - UC1 (list-input + cache=True): raise ValueError; consumer drops a flag.
    # - UC2 (str + chunking + cache=True): silent fallback to v0 sequential
    #   cache+chunking; Result.parallel_used=False signals the fallback fired.
    if spec.cache and spec.parallel:
        if isinstance(text, list):
            # UC1: declarative list-input. Raise so consumer picks one flag.
            raise ValueError(
                "spec.cache=True AND spec.parallel=True are mutually exclusive "
                "on this backend (Qwen3-TTS native batching is item-coupled per "
                "the 2026-05-25 empirical test; per-item cache hits would return "
                "stale audio). Drop one flag: cache=True for repeated identical "
                "texts; parallel=True for fresh batch synthesis without cache. "
                "See voice-parallel-gen-design.md §5."
            )
        # UC2: str + chunking. Silent fallback to v0 sequential cache+chunking.
        # parallel_used=False on the Result so consumer knows parallel didn't fire.
        # Fall through to the v0 sequential path below.

    # 5. Voice resolution (Registry is optional but useful for diagnostics).
    if registry is not None:
        registry.get(spec.voice_id)

    # 6. Route to appropriate path.
    if isinstance(text, list):
        # UC1: explicit batch (cache is False, guaranteed by §5 check above).
        return _generate_uc1_batch(
            texts=text,
            spec=spec,
            backend=backend,
            cache=cache,
            model_id=model_id,
        )

    # text is str. If parallel + chunking (and NOT cache, per §5), UC2;
    # else v0 single-text path.
    if spec.parallel and spec.chunk_strategy != "none" and not spec.cache:
        return _generate_uc2_chunked_parallel(
            text=text,
            spec=spec,
            backend=backend,
            cache=cache,
            model_id=model_id,
        )

    # v0 path (preserved): str input, no parallel-batch-eligible (sequential
    # cache+chunking falls here too per §5 silent fallback).
    return _generate_v0_sequential(
        text=text,
        spec=spec,
        backend=backend,
        cache=cache,
        model_id=model_id,
    )


def speak(
    text: str,
    voice_id: str,
    *,
    backend: TTSBackend,
    registry: Registry | None = None,
    **spec_kwargs: Any,
) -> bytes:
    """Convenience wrapper: synthesize one utterance, return bytes.

    Equivalent to ``bytes(generate(text, Spec(voice_id=voice_id, **spec_kwargs), backend=backend, registry=registry))``.

    For batch synthesis with chunking, cache, or write-to-file, use
    ``generate()`` directly and inspect the returned ``Result``.
    """
    spec = Spec(voice_id=voice_id, **spec_kwargs)
    result = generate(text, spec, backend=backend, registry=registry)
    return bytes(result)


# ---------------------------------------------------------------------------
# v0 sequential path (preserved; routes here when parallel=False or N=1)
# ---------------------------------------------------------------------------

def _generate_v0_sequential(
    *,
    text: str,
    spec: Spec,
    backend: TTSBackend,
    cache: Cache | None,
    model_id: str,
) -> Result:
    """v0 single-text path (with optional chunking). Sequential per-chunk synthesis."""
    chunks = _chunk_text(text, spec.chunk_strategy)
    if not chunks:
        raise ValueError(
            f"chunk_strategy={spec.chunk_strategy!r} produced no chunks "
            f"from input (text was empty or whitespace-only)"
        )

    per_chunk_audios: list[bytes] = []
    per_chunk_timings: list[float] = []
    per_chunk_manifest: list[dict[str, Any]] = []
    per_chunk_cache_hits: list[bool] = []
    per_chunk_keys: list[str] = []

    for chunk_text in chunks:
        audio_bytes, gen_s, key, hit = _synthesize_chunk_sequential(
            text=chunk_text,
            spec=spec,
            backend=backend,
            cache=cache,
            model_id=model_id,
        )
        per_chunk_audios.append(audio_bytes)
        per_chunk_timings.append(gen_s)
        per_chunk_cache_hits.append(hit)
        if key is not None:
            per_chunk_keys.append(key)
        per_chunk_manifest.append(
            {
                "text": chunk_text,
                "cache_key": key,
                "cache_hit": hit,
                "generation_s": gen_s,
            }
        )

    full_audio = concat_wavs(per_chunk_audios)
    sample_rate = wav_sample_rate_hz(full_audio) if full_audio else 16_000

    is_chunked = len(chunks) > 1 or spec.chunk_strategy != "none"
    any_hit = any(per_chunk_cache_hits)
    all_hit = all(per_chunk_cache_hits) if spec.cache and per_chunk_cache_hits else False

    if is_chunked:
        result = Result(
            audio=full_audio,
            sample_rate_hz=sample_rate,
            manifest=per_chunk_manifest,
            timings=per_chunk_timings,
            cache_hit=any_hit,
            cache_fully_hit=all_hit,
            parallel_used=False,
        )
    else:
        single_key = per_chunk_keys[0] if per_chunk_keys else None
        single_hit = per_chunk_cache_hits[0] if per_chunk_cache_hits else False
        result = Result(
            audio=full_audio,
            sample_rate_hz=sample_rate,
            cache_key=single_key,
            cache_hit=single_hit,
            cache_fully_hit=single_hit if spec.cache else False,
            parallel_used=False,
        )

    if spec.write_to is not None:
        spec.write_to.parent.mkdir(parents=True, exist_ok=True)
        spec.write_to.write_bytes(full_audio)
        result = replace(result, path=spec.write_to)

    return result


def _synthesize_chunk_sequential(
    *,
    text: str,
    spec: Spec,
    backend: TTSBackend,
    cache: Cache | None,
    model_id: str,
) -> tuple[bytes, float, str | None, bool]:
    """Synthesize a single chunk with optional cache lookup. Single-text path."""
    if not spec.cache:
        audio, gen_s = backend.synthesize(spec.voice_id, text, spec.seed)
        return audio, gen_s, None, False

    assert cache is not None
    key = _derive_cache_key(spec=spec, text=text, model_id=model_id)
    hit = cache.get(key)
    if hit is not None:
        return hit.audio, 0.0, key, True

    audio, gen_s = backend.synthesize(spec.voice_id, text, spec.seed)
    _cache_put(cache, key, audio, gen_s)
    return audio, gen_s, key, False


# ---------------------------------------------------------------------------
# UC1 — explicit batch (list-input + parallel=True)
# ---------------------------------------------------------------------------

def _generate_uc1_batch(
    *,
    texts: list[str],
    spec: Spec,
    backend: TTSBackend,
    cache: Cache | None,
    model_id: str,
) -> Result:
    """UC1: explicit batch path. Populates Result.audios (list)."""
    if not texts:
        # Empty batch: return empty Result.
        return Result(
            audio=None,
            audios=[],
            timings=[],
            sample_rate_hz=16_000,
            cache_hit=False,
            cache_fully_hit=False,
            parallel_used=True,
        )

    audios, timings, per_chunk_hits, keys = _batched_synth_with_cache(
        texts=texts,
        spec=spec,
        backend=backend,
        cache=cache,
        model_id=model_id,
    )

    sample_rate = wav_sample_rate_hz(audios[0]) if audios and audios[0] else 16_000
    any_hit = any(per_chunk_hits)
    all_hit = all(per_chunk_hits) if spec.cache and per_chunk_hits else False

    manifest: list[dict[str, Any]] | None = None
    if spec.cache:
        manifest = [
            {"text": t, "cache_key": k, "cache_hit": h, "generation_s": gen}
            for t, k, h, gen in zip(texts, keys, per_chunk_hits, timings, strict=True)
        ]

    result = Result(
        audio=None,
        audios=audios,
        timings=timings,
        sample_rate_hz=sample_rate,
        cache_hit=any_hit,
        cache_fully_hit=all_hit,
        parallel_used=True,
        manifest=manifest,
    )

    # UC1 with write_to: writes the CONCATENATED audio (consumer can also
    # access .audios for individual files). Same write-to semantics as UC2.
    if spec.write_to is not None:
        concat = concat_wavs(audios)
        spec.write_to.parent.mkdir(parents=True, exist_ok=True)
        spec.write_to.write_bytes(concat)
        result = replace(result, path=spec.write_to)

    return result


# ---------------------------------------------------------------------------
# UC2 — auto-parallel-on-chunk (str-input + chunking + parallel=True)
# ---------------------------------------------------------------------------

def _generate_uc2_chunked_parallel(
    *,
    text: str,
    spec: Spec,
    backend: TTSBackend,
    cache: Cache | None,
    model_id: str,
) -> Result:
    """UC2: chunk a long passage, batch-synthesize, concat back into one audio."""
    chunks = _chunk_text(text, spec.chunk_strategy)
    if not chunks:
        raise ValueError(
            f"chunk_strategy={spec.chunk_strategy!r} produced no chunks "
            f"from input (text was empty or whitespace-only)"
        )

    # If chunking produced only 1 chunk, this degenerates to a single-text
    # synthesis. No reason to invoke the batch path. Route to v0 sequential.
    if len(chunks) == 1:
        return _generate_v0_sequential(
            text=text,
            spec=spec,
            backend=backend,
            cache=cache,
            model_id=model_id,
        )

    audios, timings, per_chunk_hits, keys = _batched_synth_with_cache(
        texts=chunks,
        spec=spec,
        backend=backend,
        cache=cache,
        model_id=model_id,
    )

    # Concat the chunks into one audio (input-order preserved by
    # _batched_synth_with_cache).
    full_audio = concat_wavs(audios)
    sample_rate = wav_sample_rate_hz(full_audio) if full_audio else 16_000

    any_hit = any(per_chunk_hits)
    all_hit = all(per_chunk_hits) if spec.cache and per_chunk_hits else False

    manifest: list[dict[str, Any]] | None = None
    if spec.cache:
        manifest = [
            {"text": c, "cache_key": k, "cache_hit": h, "generation_s": gen}
            for c, k, h, gen in zip(chunks, keys, per_chunk_hits, timings, strict=True)
        ]

    result = Result(
        audio=full_audio,
        sample_rate_hz=sample_rate,
        timings=timings,
        cache_hit=any_hit,
        cache_fully_hit=all_hit,
        parallel_used=True,
        manifest=manifest,
    )

    if spec.write_to is not None:
        spec.write_to.parent.mkdir(parents=True, exist_ok=True)
        spec.write_to.write_bytes(full_audio)
        result = replace(result, path=spec.write_to)

    return result


# ---------------------------------------------------------------------------
# Shared: cache partition + reassemble for batched paths
# ---------------------------------------------------------------------------

def _batched_synth_with_cache(
    *,
    texts: list[str],
    spec: Spec,
    backend: TTSBackend,
    cache: Cache | None,
    model_id: str,
) -> tuple[list[bytes], list[float], list[bool], list[str | None]]:
    """Run a batch through cache + backend.synthesize_batch. Input order preserved.

    Returns (audios, timings, per_chunk_hits, keys), each parallel-indexed
    with ``texts``. ``keys`` entries are sha256 hex when ``spec.cache`` is
    True; None otherwise (entries match per-index regardless).

    When cache is enabled, the orchestrator partitions texts into hits
    (read from cache) and misses (synthesize), then reassembles in input
    order. The reassembly is load-bearing: getting it wrong = silently
    shuffled audio.
    """
    n = len(texts)

    if not spec.cache:
        # No cache: pass all texts through to the backend. max_batch_size
        # sub-batching still applies.
        nocache_audios, nocache_timings = _synthesize_batch_chunked(
            backend=backend,
            voice_id=spec.voice_id,
            texts=texts,
            seed=spec.seed,
            max_batch_size=spec.max_batch_size,
        )
        return nocache_audios, nocache_timings, [False] * n, [None] * n

    # Cache enabled.
    assert cache is not None
    keys: list[str | None] = [
        _derive_cache_key(spec=spec, text=t, model_id=model_id) for t in texts
    ]

    # Partition into hits + misses.
    miss_indices: list[int] = []
    audios_slots: list[bytes | None] = [None] * n
    timings: list[float] = [0.0] * n
    per_chunk_hits: list[bool] = [False] * n

    for i, key in enumerate(keys):
        assert key is not None  # cache=True path always produces keys
        entry = cache.get(key)
        if entry is not None:
            audios_slots[i] = entry.audio
            per_chunk_hits[i] = True
        else:
            miss_indices.append(i)

    # Synthesize the misses in one batch (or sub-batched per max_batch_size).
    if miss_indices:
        miss_texts = [texts[i] for i in miss_indices]
        miss_audios, miss_timings = _synthesize_batch_chunked(
            backend=backend,
            voice_id=spec.voice_id,
            texts=miss_texts,
            seed=spec.seed,
            max_batch_size=spec.max_batch_size,
        )
        # Reassemble + cache the new entries.
        for j, i in enumerate(miss_indices):
            audio = miss_audios[j]
            gen_s = miss_timings[j]
            audios_slots[i] = audio
            timings[i] = gen_s
            key = keys[i]
            assert key is not None
            _cache_put(cache, key, audio, gen_s)

    # Type narrow: all entries populated by now.
    audios_final: list[bytes] = []
    for a in audios_slots:
        assert a is not None  # both hits and misses are filled above
        audios_final.append(a)

    return audios_final, timings, per_chunk_hits, keys


def _synthesize_batch_chunked(
    *,
    backend: TTSBackend,
    voice_id: str,
    texts: list[str],
    seed: int,
    max_batch_size: int | None,
) -> tuple[list[bytes], list[float]]:
    """Call backend.synthesize_batch, sub-batching to honor max_batch_size if set.

    Empty input returns ``([], [])``. ``max_batch_size=None`` passes the full
    list in one call.
    """
    if not texts:
        return [], []
    if max_batch_size is None or max_batch_size >= len(texts):
        return backend.synthesize_batch(voice_id, texts, seed)

    # Sub-batch: slice into chunks of max_batch_size + call repeatedly.
    audios: list[bytes] = []
    timings: list[float] = []
    for i in range(0, len(texts), max_batch_size):
        slice_texts = texts[i : i + max_batch_size]
        slice_audios, slice_timings = backend.synthesize_batch(voice_id, slice_texts, seed)
        audios.extend(slice_audios)
        timings.extend(slice_timings)
    return audios, timings


def _cache_put(cache: Cache, key: str, audio: bytes, gen_s: float) -> None:
    """Build a CacheEntry from the synthesis output + persist it."""
    audio_sha256 = hashlib.sha256(audio).hexdigest()
    sample_rate = wav_sample_rate_hz(audio) if audio else 0
    duration = wav_duration_ms(audio) if audio else 0
    entry = CacheEntry(
        audio=audio,
        sha256=audio_sha256,
        sample_rate_hz=sample_rate,
        duration_ms=duration,
        generation_s=gen_s,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    cache.put(key, entry)


__all__ = ["generate", "speak"]
