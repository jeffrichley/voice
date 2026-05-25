# voice v0.1 — parallel-gen design

> **Status:** Awaiting Jeff sign-off. Implementation begins on his green-light.
> **Authors:** Wren (draft), Pepper (criterion-check), Jeff (decision).
> **Date:** 2026-05-25.
> **Related:** `2026-05-24-voice-plan.md` (the WHAT this implements); `2026-05-24-voice-v0-design.md` (v0 implementation reference).

## 0. Preamble — context + the load-bearing acceptance criterion

### Context

Voice v0 shipped 2026-05-24 with a `Spec.parallel` flag wired through but
raising `NotImplementedError`. This spec lands the actual parallel-gen
implementation. Per the morning conversation with Jeff (2026-05-25),
two distinct consumer-facing use cases must work:

- **UC1 — explicit batch:** `voice.generate(text=["t1", "t2"], spec=Spec(parallel=True)) → Result.audios: list[bytes]`. Multiple independent texts; batch synth; list of audios back.
- **UC2 — auto-parallel-on-chunk:** `voice.generate(text=long_passage, spec=Spec(chunk_strategy="sentence", parallel=True)) → Result.audio: bytes`. Long passage; chunker splits it; batch synthesizes the chunks; concat back into one audio.

The ergonomic win for UC2: consumers don't think about chunking and
parallelism as separate concerns. They say "make this long passage fast"
and the library composes the two.

### Load-bearing acceptance criterion

**This spec is gated on an empirical test against real Qwen3-TTS, per
the rule Jeff locked Sunday night (2026-05-24): "We never call something
done if it wasn't run."**

Specifically: does `backend.synthesize_batch([t1, t2], seed=42)` produce
the SAME audio for `t1` as `backend.synthesize_batch([t1], seed=42)`
does? In other words, is engine batching item-independent (each item's
output depends only on its own text + the seed), or item-coupled (an
item's output depends on the OTHER items in the batch)?

This question cannot be answered from the Qwen3-TTS source code at spec
time. It must be run. The spec encodes both possible outcomes:

- **Primary path (item-independent):** cache + parallel compose freely;
  per-chunk cache keys work as designed; UC2 with cache+chunking+parallel
  is supported.
- **Fallback path (item-coupled):** cache + parallel become mutually
  exclusive in v0.1; the orchestrator raises `ValueError` if both are
  set. UC2 with cache+chunking+parallel falls back to the v0 sequential
  cache+chunking path.

The empirical test (Section 7.1) is the load-bearing acceptance gate.
The spec is honest about its conditional shape; we don't have to
spec-revise mid-implementation if the test reveals coupling.

---

## 1. Decisions locked from brainstorm

These are settled before this spec was written. Encoded here for the
record + so the implementation can't accidentally deviate.

1. **Architecture: X-with-function-fallback.** Engine adapter exposes
   both `synthesize` (single-utterance) and `synthesize_batch` (list).
   Adapters that natively batch (Qwen3-TTS) override `synthesize_batch`
   for the GPU-saturating win; adapters that don't (Fake, simple)
   delegate to `default_batch_loop()`. Module-level function fallback
   (per Pepper's refinement); not a Mixin (preserves the structural-
   typing shape of the `runtime_checkable` Protocol).

2. **Triggering: opt-in via `Spec.parallel=True`.** UC2 doesn't
   auto-parallelize even when chunking produces >1 chunk; consumer must
   explicitly opt in. v0.2 can flip to always-on if usage data warrants.

3. **Seed: single seed per batch.** `Spec.seed` applies to the whole
   call. Per-item determinism in batch mode depends on engine behavior
   (load-bearing acceptance criterion above).

4. **Cache hit semantics:** keep `Result.cache_hit` consistent across
   versions (= `any(per_chunk_hits)`). Add new `Result.cache_fully_hit`
   for the "did the whole batch shortcut?" question (= `all(per_chunk_hits)`).
   Per-chunk hit detail in `Result.manifest`.

5. **`max_batch_size`:** `Spec.max_batch_size: int | None = None` (user
   responsibility; default unlimited; trust backend). v0.2 promotes to
   backend-recommended-default when ElevenLabs adapter lands.

6. **Empirical-determinism test naming:** `@pytest.mark.real_engine`
   with done-gate enforcement (no silent skips). Tests skip without
   `VOICE_REAL_ENGINE_OK=1` env var; the done-gate fails if the marker
   is collected without the env var set.

---

## 2. Components

```
voice/
  generate.py                    ← MODIFIED: list-input branch + parallel routing
  spec.py                        ← MODIFIED: remove parallel raise, add max_batch_size
  result.py                      ← MODIFIED: add cache_fully_hit attribute
  engine/
    protocol.py                  ← MODIFIED: add synthesize_batch to TTSBackend Protocol
    _batch_fallback.py [NEW]     ← default_batch_loop() function
    fake.py                      ← MODIFIED: add synthesize_batch via default_batch_loop
    qwen.py                      ← MODIFIED: synthesize_batch via native generate_voice_clone list-call
  _wav.py                        ← UNCHANGED: concat_wavs already handles N-way concat
  _cache_key.py                  ← UNCHANGED: per-chunk-text keying works as-is
  chunking.py                    ← UNCHANGED: orchestrator routes chunks to batch path
```

**Net:** 1 new file; 6 modified files; 0 deletions.

### 2.1 `TTSBackend` Protocol extension

```python
@runtime_checkable
class TTSBackend(Protocol):
    def prepare_voice(self, voice_id: str, ref_wav: Path, ref_text: str) -> None: ...
    def synthesize(self, voice_id: str, text: str, seed: int) -> tuple[bytes, float]: ...

    # NEW in v0.1:
    def synthesize_batch(
        self, voice_id: str, texts: list[str], seed: int
    ) -> tuple[list[bytes], list[float]]:
        """Synthesize N texts; return per-item (audio, generation_s) lists.

        Adapters that natively batch should override for the speedup.
        Adapters that don't can delegate to default_batch_loop(self, ...).
        """
```

### 2.2 `voice/engine/_batch_fallback.py` (new)

```python
"""Module-level fallback for adapters that don't natively batch.

Composition over inheritance: adapter authors delegate via one line
rather than inheriting a Mixin. Preserves the structural-typing shape
of the runtime_checkable Protocol; no inheritance gymnastics.
"""

from voice.engine.protocol import TTSBackend


def default_batch_loop(
    backend: TTSBackend, voice_id: str, texts: list[str], seed: int
) -> tuple[list[bytes], list[float]]:
    """Sequential per-text fallback. Same audio + timings as N separate synthesize() calls.

    Adapters that don't benefit from native batching (Fake; simple adapters
    that wrap synchronous APIs) one-line this from their synthesize_batch.
    """
    results = [backend.synthesize(voice_id, t, seed) for t in texts]
    audios = [r[0] for r in results]
    timings = [r[1] for r in results]
    return audios, timings
```

### 2.3 `FakeTTSBackend.synthesize_batch` (modification)

```python
def synthesize_batch(self, voice_id, texts, seed):
    from voice.engine._batch_fallback import default_batch_loop
    return default_batch_loop(self, voice_id, texts, seed)
```

One-line delegation. The Fake's sequential output matches its single-shot
output; tests assert this equality.

### 2.4 `QwenTTSBackend.synthesize_batch` (modification)

```python
def synthesize_batch(self, voice_id, texts, seed):
    if voice_id not in self._prompts:
        raise VoiceNotPreparedError(...)
    if not texts:
        return [], []
    for t in texts:
        if not t.strip():
            raise EmptyTextError("text is empty or whitespace-only")

    prompt = self._prompts[voice_id]
    start = time.monotonic()
    self._torch.manual_seed(seed)
    if self._torch.cuda.is_available():
        self._torch.cuda.manual_seed_all(seed)

    try:
        # Native Qwen3-TTS batching:
        wavs, sample_rate = self._model.generate_voice_clone(
            text=texts,                          # list[str] (batch mode)
            language="english",
            voice_clone_prompt=[prompt] * len(texts),  # one prompt per item
        )
    except RuntimeError as exc:
        if "out of memory" in str(exc).lower():
            raise GPUOOMError(
                f"GPU OOM during synthesize_batch with N={len(texts)}. "
                "Reduce Spec.max_batch_size or use a coarser chunk_strategy."
            ) from exc
        raise

    total_s = time.monotonic() - start
    # Apportion generation_s evenly across items: timings approximated by
    # equal apportion for batched calls. Total wall-time is exact; per-item
    # is nominal. Consumers needing real per-item timing can call
    # synthesize_batch with singletons (loses GPU-batch speedup; gains
    # per-item timing). Known v0.1 limit; documented in §8 open questions.
    per_item_s = total_s / len(texts)
    timings = [per_item_s] * len(texts)

    # Convert each numpy audio array → WAV bytes.
    import soundfile as sf
    audio_bytes_list = []
    for wav_array in wavs:
        buf = BytesIO()
        sf.write(buf, wav_array, int(sample_rate), format="WAV", subtype="PCM_16")
        audio_bytes_list.append(buf.getvalue())

    return audio_bytes_list, timings
```

### 2.5 `Spec` modifications

```python
@dataclass(frozen=True)
class Spec:
    voice_id: str
    chunk_strategy: str = "none"
    cache: bool = False
    parallel: bool = False                    # in v0.1: actually works (was raise)
    write_to: Path | None = None
    watermark: bool = False
    seed: int = 42
    extra: dict[str, Any] = field(default_factory=dict)

    # NEW in v0.1:
    max_batch_size: int | None = None         # None = unlimited; trust backend
```

`__hash__` and `__eq__` are extended to include `max_batch_size` (it
affects behavior but NOT output, so it's NOT in the cache key — same
as `write_to` exclusion).

### 2.6 `Result` additions

```python
@dataclass(frozen=True)
class Result:
    audio: bytes | None = None
    audios: list[bytes] | None = None
    path: Path | None = None
    manifest: list[dict[str, Any]] | None = None
    timings: list[float] | None = None
    sample_rate_hz: int = 16_000
    cache_key: str | None = None
    cache_hit: bool = False                   # any() — consistent across versions
    cache_fully_hit: bool = False             # NEW: all() — "did the whole batch shortcut?"
    parallel_used: bool = False               # NEW: did synthesize_batch actually fire?
```

`cache_hit` retains v0 semantics (any chunk hit) for backward compat. New
`cache_fully_hit` answers the strict question for batched calls. v0 single
calls have `cache_fully_hit == cache_hit` when N=1; chunked-single in v0
get the strict-all() version too.

`parallel_used` is the **transparent-silent-fallback** flag for UC2.
When the consumer passes `Spec(parallel=True)` but the orchestrator
falls back to sequential (per §5 conditional path, or any other future
reason), this flag reports the truth. UC2 consumers can check
`result.parallel_used` to know whether parallel actually fired. Avoids
the "I asked for parallel; why is it slow?" surprise.

For UC1 (list-input + parallel): raise happens before any Result is
built when the conditional path is active, so this flag would always
be True or never get returned. For UC2: True when batch path fired;
False when sequential fallback fired.

---

## 3. Data flow — UC1 (explicit batch)

```
consumer:
    voice.generate(text=["t1", "t2", "t3"], Spec(voice_id="pepper", parallel=True))
  │
  ▼
orchestrator.generate():
  branch: isinstance(text, list) AND spec.parallel
  │
  ▼
[chunking NOT applied; consumer pre-chunked]
  │
  ▼
if spec.cache:
    # === Cache partition step (load-bearing for ordering) ===
    keys = [cache_key(spec, t, model_id) for t in texts]
    miss_indices = [i for i, k in enumerate(keys) if cache.get(k) is None]
    miss_texts = [texts[i] for i in miss_indices]

    if miss_texts:
        miss_audios, miss_timings = backend.synthesize_batch(
            voice_id, miss_texts, spec.seed
        )
    else:
        miss_audios, miss_timings = [], []

    # === Reassemble in input order ===
    audios: list[bytes | None] = [None] * len(texts)
    timings: list[float] = [0.0] * len(texts)
    per_chunk_hits: list[bool] = [False] * len(texts)

    for j, i in enumerate(miss_indices):
        audios[i] = miss_audios[j]
        timings[i] = miss_timings[j]
        # ... compute sha256, duration; cache.put(keys[i], CacheEntry(...))

    for i, key in enumerate(keys):
        if audios[i] is None:
            entry = cache.get(key)  # guaranteed hit per partition logic above
            audios[i] = entry.audio
            timings[i] = 0.0  # no synthesis happened this call
            per_chunk_hits[i] = True

else:
    audios, timings = backend.synthesize_batch(voice_id, texts, spec.seed)
    per_chunk_hits = [False] * len(texts)
    keys = [None] * len(texts)
  │
  ▼
Result(
    audio=None,
    audios=audios,
    timings=timings,
    cache_key=None,                              # per-chunk keys live in manifest
    cache_hit=any(per_chunk_hits),               # v0-consistent semantics
    cache_fully_hit=all(per_chunk_hits) if spec.cache else False,
    parallel_used=True,                          # batch path fired (always True for UC1 reaching this point)
    manifest=[
        {"text": t, "cache_key": k, "cache_hit": h, "generation_s": gen}
        for t, k, h, gen in zip(texts, keys, per_chunk_hits, timings)
    ] if spec.cache else None,
    sample_rate_hz=<from first non-empty audio>,
)
```

**Critical:** input-order preservation is enforced by `miss_indices`
tracking. A unit test (Section 7) covers the mixed-partition case
explicitly — getting reassembly wrong means silently shuffled audio.

---

## 4. Data flow — UC2 (auto-parallel-on-chunk)

```
consumer:
    voice.generate(text=long_passage, Spec(voice_id="pepper", chunk_strategy="sentence", parallel=True))
  │
  ▼
orchestrator.generate():
  branch: isinstance(text, str) AND spec.parallel AND chunk_strategy != "none"
  │
  ▼
chunks = chunking.chunk(long_passage, spec.chunk_strategy)  # ["sent_1", "sent_2", ...]
  │
  ▼
[same cache-partition + reassemble logic as UC1; treat `chunks` as the batch]
audios_in_order, timings_in_order, per_chunk_hits = <partition + reassemble>
  │
  ▼
full_audio = _wav.concat_wavs(audios_in_order)   # input-order preserved; existing helper
  │
  ▼
Result(
    audio=full_audio,                            # SINGLE audio (concat path)
    audios=None,
    timings=timings_in_order,                    # per-chunk diagnostics
    cache_key=None,
    cache_hit=any(per_chunk_hits),
    cache_fully_hit=all(per_chunk_hits) if spec.cache else False,
    parallel_used=True,                          # batch path fired (False when §5 fallback to sequential)
    manifest=[...] if spec.cache else None,
    sample_rate_hz=<from full_audio header>,
)
```

**Key distinction from UC1:** UC2 populates `.audio` (concat); UC1 populates
`.audios` (list). Both populate `.timings` + (conditionally) `.manifest`.

**`parallel_used` in UC2 silent-fallback case:** when §5 fallback engages
(cache+parallel both set + engine is item-coupled), UC2 silently runs
the v0 sequential cache+chunking path. The Result is built with
`parallel_used=False` so consumers checking the flag know parallel did
not actually fire. Avoids the "I asked for parallel; why is it slow?"
surprise.

---

## 5. Conditional path (fallback if empirical test reveals item-coupling)

If `test_batch_item_independence_empirical` FAILS, the orchestrator
must enforce mutually-exclusive `spec.cache` and `spec.parallel`:

```python
def generate(text, spec, *, backend, cache=None, registry=None, model_id="default"):
    if spec.cache and spec.parallel:
        raise ValueError(
            "spec.cache=True and spec.parallel=True are mutually exclusive on "
            "this backend: engine batching is item-coupled (an item's output "
            "depends on other batch items), so per-item cache hits would return "
            "stale audio. Use cache=True OR parallel=True, not both. "
            "Tracked: see voice-parallel-gen-design.md §5."
        )
    # ... rest of generate
```

UC2 with `cache=True` + `parallel=True` falls back to the v0 sequential
cache+chunking path (no parallel speedup, but correctness preserved).
UC1 with the same combination raises; consumer drops one flag.

This shape gets baked in at implementation time and tested via the
empirical test. The spec doesn't pre-decide; the test does.

---

## 6. Error handling

| Error | When | How handled |
|---|---|---|
| `EmptyTextError` | any text in batch is empty/whitespace | raised by backend; orchestrator surfaces unchanged |
| `VoiceNotPreparedError` | voice_id not prepared on backend | raised at first synthesize attempt |
| `GPUOOMError` | batch too large for VRAM | raised with hint: "reduce Spec.max_batch_size or use a coarser chunk_strategy" |
| `ValueError` (cache+parallel) | conditional fallback engaged | raised at orchestrator entry per §5 |
| Other backend errors | engine-specific failures | propagate; consumer's responsibility to retry |

**Partial-success reporting** is OUT OF SCOPE for v0.1. One item in the
batch failing fails the whole batch. v0.X+ may add `Result.errors:
list[Exception | None]` for partial-success shape.

**Backpressure / auto-bisect on OOM** is OUT OF SCOPE for v0.1.
`max_batch_size` is the user's control. v1.0+ may add adapter-side
auto-bisection.

---

## 7. Testing strategy

### 7.1 The empirical-determinism test (load-bearing acceptance criterion)

```python
# packages/voice/tests/engine/test_qwen_batch_independence.py

import os
import pytest

pytestmark = pytest.mark.real_engine

@pytest.mark.skipif(
    not os.environ.get("VOICE_REAL_ENGINE_OK"),
    reason="requires real Qwen3-TTS engine; set VOICE_REAL_ENGINE_OK=1 to run",
)
def test_batch_item_independence_empirical():
    """LOAD-BEARING acceptance criterion (per the never-done-without-running rule).

    Determines whether v0.1 can ship with cache + parallel composing freely
    (item-independent path) or whether they must be mutually exclusive
    (item-coupled fallback). The test result selects which path is active
    when we declare done.
    """
    from pathlib import Path
    from voice.engine import QwenTTSBackend

    backend = QwenTTSBackend(
        model_path=os.environ["VOICE_TEST_MODEL_PATH"],
        device="cuda:0",
    )
    backend.prepare_voice(
        "pepper",
        Path(os.environ["VOICE_TEST_REF_WAV"]),
        os.environ["VOICE_TEST_REF_TEXT"],
    )

    # Same text alone vs. in a batch with another text.
    alone, _ = backend.synthesize_batch("pepper", ["Hello, world."], seed=42)
    in_batch, _ = backend.synthesize_batch("pepper", ["Hello, world.", "Second item."], seed=42)

    if alone[0] != in_batch[0]:
        pytest.fail(
            "ITEM-COUPLED engine batching detected. v0.1 cache + parallel "
            "must be mutually exclusive; the orchestrator must raise "
            "ValueError when both flags are set. Spec §5 fallback path is "
            "active. Implementer: implement the raise + remove the cache+parallel "
            "test path; update the brief to Jeff naming the empirical result."
        )
    # Else: item-independent. Cache + parallel compose freely. Standard path active.
```

### 7.2 Static-suite tests (no real engine; ~85 + ~20 new = ~105 total)

- **`test_protocol.py`**: TTSBackend Protocol now requires synthesize_batch
- **`test_fake_backend.py`**: FakeTTSBackend.synthesize_batch via default_batch_loop matches sequential synthesize output item-by-item
- **`test_generate.py`** (new UC1 + UC2 tests):
  - UC1 default: returns Result with .audios populated, .audio None
  - UC1 with cache: per-chunk keys in manifest; reassemble preserves order
  - UC1 mixed cache hits/misses: orchestrator partitions correctly + reassembles in input order (the silent-shuffle catcher)
  - UC2 default: returns Result with .audio populated (concat), .audios None
  - UC2 with cache: same as UC1 mixed-partition case applied to chunked-string
  - UC2 with chunk_strategy="none": equivalent to v0 single-text path (no batch invocation)
  - cache_hit consistent with v0 (any() across paths)
  - cache_fully_hit = all() across paths
  - empty batch / N=1 batch edge cases
  - cache + parallel raise (if §5 fallback active per empirical result)

### 7.3 `@pytest.mark.real_engine` convention

- All tests requiring torch + qwen-tts + GPU tagged `@pytest.mark.real_engine`
- Skip-with-reason if `VOICE_REAL_ENGINE_OK` env var not set
- pyproject.toml registers the marker so pytest doesn't warn
- Done-gate convention: declaring v0.1 done REQUIRES `VOICE_REAL_ENGINE_OK=1`
  on the validation run that collects + passes the real_engine tests.
  The done-gate is procedural (developer discipline + the brief asserts
  it), not enforced by tooling.

---

## 8. Open questions / decisions deferred to v0.2+

1. **`Backend.recommended_batch_size` property.** When ElevenLabs adapter
   lands, the per-engine optimal batch size differs ~10x; promoting
   max_batch_size from user-controlled to backend-suggested makes sense.
2. **Auto-bisect on GPUOOMError.** v1.0+ when consumers report it as a
   real pain point.
3. **Always-on parallel when chunking produces >1 chunk.** v0.2 if
   `Spec.parallel=True` becomes the obvious default in practice.
4. **Per-item error reporting** (`Result.errors`). v0.X+ when partial-
   success becomes a real consumer need.
5. **Multi-GPU support.** v1.0+ when a consumer has multi-GPU + wants
   to saturate both.
6. **Real per-item timing for batched calls.** v0.1 apportions total
   wall-time equally across batch items (`per_item_s = total_s / N`).
   Real per-item timing isn't directly available from
   `Qwen3TTSModel.generate_voice_clone`. Consumers needing real
   per-item timing today must call `synthesize_batch` with singletons
   (loses GPU-batch speedup; gains per-item timing). v0.X+ may add
   per-item-timing capture if engines start exposing it.

---

## 9. Acceptance criteria for v0.1 ship-ready PR

- [ ] All v0 tests still pass (the ~85 from voice v0 stay green).
- [ ] New static tests pass (~20 new tests covering UC1 + UC2 + cache partition + cache_fully_hit + edge cases).
- [ ] ruff clean.
- [ ] mypy clean.
- [ ] **`test_batch_item_independence_empirical` has been RUN against real Qwen3-TTS with `VOICE_REAL_ENGINE_OK=1`.** Result recorded in the PR description (either item-independent or item-coupled).
- [ ] If item-coupled: §5 fallback (cache+parallel raise) is implemented + tested.
- [ ] **Real-engine UC1 + UC2 synthesis run end-to-end** with Pepper's voice; audio produced + saved + Jeff confirms it sounds correct (UC1: multiple short utterances; UC2: a paragraph chunked-and-batched-and-concat'd).
- [ ] PR description names which empirical result is active + links to this spec.

---

## 10. Sign-off requested

- [ ] Jeff approves the two use cases (UC1 + UC2) and the opt-in-via-`Spec.parallel=True` trigger
- [ ] Jeff approves the conditional shape (item-independent primary + item-coupled fallback) gated on the empirical test
- [ ] Jeff approves `cache_fully_hit` as a new Result attribute (different question from `cache_hit`)
- [ ] Jeff approves `max_batch_size` as user-controlled in v0.1 with `None` default
- [ ] Jeff approves the acceptance criteria including the real-engine UC1 + UC2 run + listen-check

On green-light: implementation begins via PR workflow (branch off main, worktree, real-engine validation before declaring done). ETA ~2-3 hours for v0.1 ship-ready PR.
