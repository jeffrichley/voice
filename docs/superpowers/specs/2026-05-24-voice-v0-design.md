# voice v0 — design brief (the HOW)

> **This is the implementation HOW that implements the WHAT in
> [`2026-05-24-voice-plan.md`](./2026-05-24-voice-plan.md).**
> Read the plan for the feature surface + scope + architectural decisions
> (including Jeff's 2026-05-24 sign-off on §6.1–§6.6). This document
> covers the implementation-side spec for the v0 scope the plan names.
> Will be aligned with plan v2 before implementation starts.
>
> **Status:** Pre-implementation reference. Plan v2 architectural decisions take
> precedence over anything here that conflicts; this document will be aligned
> before the engine-adapter implementation lands.
> **Authors:** Wren (draft), Pepper (criterion-check), Jeff (decision via plan).
> **Date:** 2026-05-24.

## 0. Preamble

### Context

This brief specifies v0 of the standalone `voice` library — a pluggable TTS engine with content-addressed caching, named voice registry, and chunking strategies, designed to serve three distinct consumers as a shared substrate.

The library was scaffolded earlier today at https://github.com/jeffrichley/voice (public, MIT) using the `scaffold-agent-core-project` skill. The placement decision (standalone repo, not inside agent_core) was made this morning after Jeff's pushback exposed that the three named consumers have genuinely different requirement profiles — standalone is the right shape to keep API design cross-consumer-equal. See the morning bus thread for the full reasoning; the (C)→(A) flip is referenced here only as audit-trail.

### Cross-consumer-equal as a load-bearing principle

The single most important design constraint for v0:

**No consumer's needs are privileged at the API level. The three named consumers (Pepper conversational, audiobook pipeline, Chrona narration) each get first-class support; no one's flow shape defines the library's defaults at the others' expense.**

This principle drove the decisions in §1–§7. Reading through, every section explains why the chosen shape works equally well for all three.

### Three-consumer requirement profile

| Consumer | Latency profile | Mode | Chunking | Parallel | Metadata wrap | Bytes vs file-path |
|---|---|---|---|---|---|---|
| **Pepper conversational** (via agent-core-voice adapter) | Low-latency (<1s ideal; <3s acceptable) | Single-utterance | None | No | None (bytes back, ephemeral) | Bytes |
| **Audiobook pipeline** | Throughput-optimized; per-segment seconds is fine | Batch, long-form | Sentence or paragraph | Yes (across segments) | Consent snapshot, GPU-min, ledger pointer | File-path + manifest |
| **Chrona narration** | Throughput-optimized | Batch, scene-shaped | Paragraph (typically) | Yes (multi-line scenes) | Scene metadata, music-mix metadata | File-path + scene-manifest |

The API shape (§1) + Spec class (§2) + Result class (§3) all serve this table directly. Each consumer picks their fields; the same `generate()` function dispatches all three flows.

### Topology: voice library vs agent-core-voice adapter

- **`voice` (this repo, standalone):** the pure substrate. Engine adapter, cache, voice registry, chunking, top-level `generate()`. No bus, no agent_core dependencies, no consumer-policy concerns.
- **`agent-core-voice` (agent_core workspace):** thin adapter. Imports `voice`, wires it into agent_core's MCP/bus surface so Pepper conversational use lands cleanly through the existing bus apparatus. Stays in agent_core's workspace (it's the agent_core-internal-consumer layer).
- **`audiobook`, `chrona` (separate repos):** import `voice` directly. Wrap with their own manifest layers (consent ledger for audiobook; scene metadata for Chrona).

```
              ┌───────────────────────┐
              │   voice (this repo)   │
              │  pure substrate       │
              └─────────┬─────────────┘
                        │
            ┌───────────┼───────────┐
            │           │           │
            ▼           ▼           ▼
  ┌──────────────┐  ┌────────┐  ┌────────┐
  │ agent-core-  │  │audio-  │  │ chrona │
  │  voice       │  │ book   │  │        │
  │ (bus adapter)│  │        │  │        │
  └──────────────┘  └────────┘  └────────┘
        │
        ▼
   (Pepper, Wren — via bus)
```

### What's locked vs unlocked

**Locked (this brief asks Jeff to confirm):**
- API shape: `generate(text, spec) → Result` + `speak(text, voice_id)` wrapper
- Naming: `voice.Spec` (request), `voice.Result` (response), `bytes(result)` fast-path
- Cache contract: minimal 6-field; consumer-wraps-for-extra
- Engine adapter Protocol + error taxonomy: pulled from agent-core-voice
- Voice registry: YAML config + VoiceInfo dataclass
- Chunking: simple registry dict; 3 built-ins (none / sentence / paragraph); pluggy upgrade-path documented

**Deferred (named in §8 + not in v0 scope):**
- Parallel-gen architecture + the engine-adapter-vs-worker-pool boundary question

---

## 1. API shape

Single entry point with a uniform return type:

```python
import voice

# Conversational fast-path
result = voice.generate(text="Hello, Jeff.", spec=voice.Spec(voice_id="pepper"))
audio = bytes(result)  # __bytes__ for the simplest case

# Batch
result = voice.generate(
    text=chapter_text,
    spec=voice.Spec(
        voice_id="narrator-saki",
        chunk_strategy="sentence",
        cache=True,
        watermark=True,
        write_to="chapter-01.wav",
    ),
)
result.path        # Path to the written file
result.manifest    # Per-chunk metadata
result.audio       # Always populated unless explicitly discarded

# Convenience wrapper for the most common shape
audio = voice.speak("Hello, Jeff.", voice_id="pepper")  # equivalent to bytes(generate(...))
```

`speak(text, voice_id)` is a one-liner over `generate()` that returns bytes directly. Provided because the conversational shape is common enough to warrant the shorter call.

---

## 2. Spec class

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class Spec:
    """One request to voice.generate().

    All fields beyond voice_id are optional. Default values give the
    conversational fast-path; opting into batch / parallel / cache / etc.
    is explicit.
    """

    voice_id: str                                  # required; looked up in the voice registry
    chunk_strategy: str = "none"                   # one of: "none", "sentence", "paragraph"
    cache: bool = False                            # enable content-addressed cache
    parallel: bool = False                         # v0.1 — flag exists but raises NotImplementedError in v0
    write_to: Path | None = None                   # if set, also writes the audio to this path
    watermark: bool = False                        # EU AI Act Article 50 — opt-in (see rationale below)
    seed: int = 42                                 # determinism knob; same seed → same audio
    extra: dict[str, Any] = field(default_factory=dict)  # engine-specific params (model_id, sample_rate, etc.)
```

### Field rationale

- **`voice_id`** — only required field. Looked up in `voice.registry` to resolve to a `VoiceInfo`.
- **`chunk_strategy`** — default `"none"` (single-shot). Audiobook + Chrona override to `"sentence"` or `"paragraph"`.
- **`cache`** — default `False`. Audiobook turns it on; Pepper conversational doesn't (each utterance unique).
- **`parallel`** — flag exists in v0's Spec so consumers can write code today that won't break in v0.1. Raises `NotImplementedError` if set in v0. Deferring the actual implementation per §8.
- **`write_to`** — Path for the file-write case. Triggers `result.path` population; bytes are still in `result.audio` for callers that want both.
- **`watermark`** — **opt-in by design**, NOT always-on. EU AI Act Article 50 applies to public audio outputs (audiobook, Chrona). It does NOT apply to private conversational use (Pepper-to-Jeff utterances that never leave the bus). Opt-in lets audiobook turn it on for distribution; Pepper conversational doesn't force the regulatory-disclosure shape on private exchanges. If always-on, every consumer would need to handle watermark-removal for private cases — worse default.
- **`seed`** — deterministic synthesis knob. Same `(voice_id, text, seed, params)` → same audio. Underpins the cache key.
- **`extra`** — engine-specific dict for params like `model_id`, `sample_rate_hz`, attention implementation. Kept as a typed `dict[str, Any]` to avoid forcing the Spec class to know about every engine's quirks.

### Why frozen dataclass

Spec is hashable when frozen. The cache key derivation (§5) uses `hash(spec)` as part of its key; frozen + hashable is the prerequisite. Also makes Spec accidentally-mutation-proof, which is the right shape for a request object.

---

## 3. Result class

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class Result:
    """One response from voice.generate(). Attribute population varies by config.

    See the population matrix below.
    """

    audio: bytes | None = None        # primary audio (single-input cases)
    audios: list[bytes] | None = None # parallel-gen output (v0.1)
    path: Path | None = None          # populated if Spec.write_to was set
    manifest: list[dict[str, Any]] | None = None  # per-chunk metadata (chunked cases)
    timings: list[float] | None = None             # per-chunk/per-line generation_s
    sample_rate_hz: int = 16_000      # audio format metadata; always populated
    cache_key: str | None = None      # hex sha256 if cache was hit/written; None if cache=False
    cache_hit: bool = False           # True if synthesis was skipped due to cache hit

    def __bytes__(self) -> bytes:
        """Conversational fast-path: bytes(result) → the audio."""
        if self.audio is None:
            raise ValueError(
                "Result has no .audio (parallel-gen result with .audios? "
                "file-write-only result?). Inspect .audios / .path instead."
            )
        return self.audio
```

### Attribute population matrix

This table is THE architectural contract for what a consumer sees from `generate()`.

| Spec configuration | `.audio` | `.audios` | `.path` | `.manifest` | `.timings` | `.cache_key` | `.cache_hit` |
|---|---|---|---|---|---|---|---|
| Conversational default (just `voice_id`) | bytes | — | — | — | — | — | False |
| `cache=True`, miss | bytes | — | — | — | — | hex | False |
| `cache=True`, hit | bytes | — | — | — | — | hex | True |
| `write_to=path` | bytes | — | Path | — | — | — | False |
| `chunk_strategy="sentence"` | bytes (concat) | — | — | per-chunk dicts | per-chunk seconds | — | False |
| `chunk_strategy="sentence", cache=True` | bytes | — | — | per-chunk + cache_hit per chunk | per-chunk | per-result | mixed |
| `chunk_strategy="sentence", write_to=path` | bytes | — | Path | per-chunk | per-chunk | — | False |
| `parallel=True` (v0.1) | — | list[bytes] | — | — | per-line | — | False |
| `parallel=True, cache=True` (v0.1) | — | list[bytes] | — | — | per-line | per-line keys | per-line hits |

**Reading the matrix:** `—` means the attribute is `None` (default). A consumer SHOULD check the attribute they care about; the table tells them what's populated for the configuration they passed.

### Why uniform Result, not return-type variance

If `generate()` returned `bytes` sometimes and `Result` other times, the type checker can't help and consumers learn the shape only at runtime. Uniform Result keeps the type signature clean; the variance lives in WHICH attributes are populated, not in WHAT type comes back. `bytes(result)` is the ergonomic fast-path for the case where only `.audio` matters.

---

## 4. Engine adapter contract

Pattern-pulled from `agent-core-voice/protocol.py`. Preserved verbatim except for module namespace (`voice.engine.protocol` instead of `agent_core_voice.protocol`).

### Protocol

```python
from typing import Protocol, runtime_checkable
from pathlib import Path

@runtime_checkable
class TTSBackend(Protocol):
    """The seam between voice.generate() and the concrete TTS engine."""

    def prepare_voice(self, voice_id: str, ref_wav: Path, ref_text: str) -> None:
        """Build + cache the prompt for voice_id. Called once per voice at startup."""

    def synthesize(self, voice_id: str, text: str, seed: int) -> tuple[bytes, float]:
        """Generate audio for an already-prepared voice.

        Returns (wav_bytes, generation_s). Raises a VoiceError subclass on failure.
        """
```

### Error taxonomy

```python
class VoiceError(Exception): ...                  # base for every backend error
class EmptyTextError(VoiceError): ...             # empty / whitespace-only text
class TextTooLongError(VoiceError): ...           # exceeds model token budget
class GPUOOMError(VoiceError): ...                # GPU OOM during synthesis (retryable)
class VoiceNotPreparedError(VoiceError): ...      # synthesize() before prepare_voice()
```

### VoiceInfo

```python
@dataclass(frozen=True)
class VoiceInfo:
    voice_id: str
    ref_wav: Path
    ref_text: str
    blend: str | None = None
```

### Concrete backends

**v0 ships:**

- **`FakeTTSBackend`** — deterministic synthetic-audio (sine wave at hash(voice_id)-derived frequency). Pure-Python; no torch. Used by tests + as a fallback for hosts without torch installed.
- **`QwenTTSBackend`** — Qwen3-TTS wrapper. Lazy-imports `qwen_tts` + `torch` so importing `voice.engine` works on torch-less hosts. Real synthesis requires the user to install `qwen-tts` separately (it's not on PyPI; agent_core releases ship a wheel as an asset, or vendor it).

**v0 does NOT ship:**
- ElevenLabs adapter, OpenAI TTS adapter, etc. Adding them is a v0.2+ concern as real demand surfaces.

### Backend lifecycle

```python
backend = QwenTTSBackend(model_path="...", device="cuda:0")  # expensive: loads model
backend.prepare_voice("pepper", Path("ref.wav"), "Reference text...")  # expensive: builds ICL prompt
# Per utterance:
wav_bytes, generation_s = backend.synthesize("pepper", "Hello!", seed=42)  # the hot path
```

`prepare_voice` is called once per voice at registry-load time; `synthesize` is the hot path inside `generate()`. The voice registry (§6) handles the pairing.

---

## 5. Cache shape

Pattern-pulled from `audiobook-pipeline-spec-v0.md` (Stage 5, lines 215-219). Minimal: voice's cache stores what voice cares about; consumers wrap with their own policy-shaped metadata.

### Cache key

```python
cache_key = sha256(
    f"{model_id}|{voice_id}|{text}|{seed}|{normalize_params(spec.extra)}"
).hexdigest()
```

Same (model, voice, text, seed, params) → same key → same audio. Deterministic. Survives across runs + books + projects.

### Cache value (the 6 fields voice owns)

```python
@dataclass(frozen=True)
class CacheEntry:
    audio: bytes          # the WAV-formatted audio
    sha256: str           # hash of audio bytes (different from cache_key)
    sample_rate_hz: int
    duration_ms: int
    generation_s: float   # wall time to synthesize (cost telemetry)
    timestamp_utc: str    # ISO-8601 when written
```

Nothing else. No `consent_snapshot`, no `GPU_minutes`, no `ledger_pointer` — those belong to whichever consumer needs them (audiobook wraps for consent; Chrona wraps for scene context).

### Storage

**v0:** simple filesystem hash store. Cache root configurable; default `~/.cache/voice/`.
```
~/.cache/voice/
  ab/abcdef...123.wav         # the audio
  ab/abcdef...123.json        # the 5 metadata fields (no audio bytes)
```

Two-level directory split (first 2 chars) to avoid one giant flat dir.

**Upgrade path:** SQLite-backed cache if querying (e.g., "all entries for voice_id X", "all entries older than N days") becomes a need. The CacheEntry shape stays the same; only the storage substrate changes. Document in code comment.

### Cache API

```python
class Cache:
    def __init__(self, root: Path = Path("~/.cache/voice").expanduser()): ...
    def get(self, cache_key: str) -> CacheEntry | None: ...
    def put(self, cache_key: str, entry: CacheEntry) -> None: ...
    def clear(self) -> None: ...  # nuke for testing; consumers rarely call this
```

`get()` returns None on miss; `put()` writes atomically (temp file + rename). No fancy eviction in v0; size grows monotonically. Consumers needing eviction wrap.

---

## 6. Voice registry

YAML config + the `VoiceInfo` data shape from §4.

### Config file shape

```yaml
# ~/.config/voice/voices.yaml (default; configurable via env var)
voices:
  - voice_id: pepper
    ref_wav: ~/voices/pepper-ref.wav
    ref_text: "This is a reference recording of Pepper's voice for ICL."
    blend: null

  - voice_id: narrator-saki
    ref_wav: ~/voices/saki-ref.wav
    ref_text: "Sample line capturing the narrator's tone."
    blend: null
```

### Registry API

```python
class Registry:
    def __init__(self, config_path: Path = Path("~/.config/voice/voices.yaml").expanduser()): ...
    def get(self, voice_id: str) -> VoiceInfo: ...  # raises KeyError on miss
    def list_voice_ids(self) -> list[str]: ...
    def reload(self) -> None: ...  # re-read the YAML
```

Registry is a per-process singleton in practice (one YAML, one process). Not enforced via global state; consumers construct one explicitly.

### Voice = config row, not code

Adding a new voice = adding a YAML row. No code change. Matches Jeff's "generate tons of voices easily" user-story goal: voice creation is a config + reference-audio operation, not a development operation.

---

## 7. Chunking strategies

Simple registry dict with 3 built-in strategies. Pluggy upgrade-path documented in code comment.

### Strategies

```python
from typing import Callable

ChunkStrategy = Callable[[str], list[str]]

_STRATEGIES: dict[str, ChunkStrategy] = {
    "none": lambda text: [text],                     # one chunk = whole text
    "sentence": _split_by_sentence,                  # rough sentence boundary heuristic
    "paragraph": lambda text: text.split("\n\n"),    # blank-line-separated paragraphs
}

def chunk(text: str, strategy: str) -> list[str]:
    if strategy not in _STRATEGIES:
        raise ValueError(
            f"unknown chunk strategy {strategy!r}; available: {list(_STRATEGIES)}"
        )
    return _STRATEGIES[strategy](text)
```

### Why not pluggy

Briefs-framework uses pluggy for plugin discovery. For voice v0 with 3 built-in strategies (a closed set), pluggy is premature library-extraction — adds a dependency for plugins that don't yet exist. Code comment names the upgrade path:

```python
# UPGRADE PATH: if external chunking-strategy plugins become a real demand
# (3+ user-defined strategies materialize across consumers), replace this
# registry dict with pluggy-based discovery. Migrate signature to:
#     class ChunkStrategy(Protocol):
#         def split(self, text: str) -> list[str]: ...
# Discovery via importlib.metadata entry_points group "voice.chunk_strategies".
# Until then, simple dict + closed set is the right shape.
```

### `_split_by_sentence` heuristic

Regex-based: split on `[.!?]` followed by whitespace, preserving the punctuation with the preceding chunk. Not ML-grade; deliberately simple. Audiobook's downstream processing may want stronger sentence-boundary detection; that's audiobook-layer work, not voice-layer.

---

## 8. Deferred to v0.1: parallel-gen

The genuinely novel design call for voice. Deferred because the engine-adapter-vs-worker-pool boundary question is unresolved and benefits from Monday-fresh thought.

### Open design question

**Does the engine adapter expose `synthesize_batch(texts)` and the worker pool just calls it once per batch? Or does the engine adapter only expose `synthesize(text)` and the worker pool wraps it with N concurrent calls?**

Each shape has different perf characteristics:
- `synthesize_batch` lets engines that support real batching (some TTS models do; Qwen3-TTS may or may not) skip Python-level concurrency overhead
- `synthesize`-only is simpler but caps throughput at single-utterance throughput × workers

The Right Answer depends on what Qwen3-TTS actually supports, what ElevenLabs / OpenAI TTS expose if those adapters land later, and whether the per-engine perf cost of the wrapping matters for any consumer's actual workload.

### v0 shape (placeholder)

`Spec.parallel = True` raises `NotImplementedError` in v0. The field exists so consumer code written today doesn't break in v0.1. `Result.audios` + `Result.timings` are typed `list[bytes] | None` so the consumer-facing type contract is already in place.

### v0.1 implementation order

Monday morning: write the parallel-gen sub-spec (engine-adapter boundary + worker-pool shape + futures contract). Monday afternoon: implement. Lands as v0.1 of the library.

---

## 9. Implementation order

### Dependency graph

```
        [protocol + errors + VoiceInfo]    [chunking]
                    │                          │
                    ▼                          │
        [FakeTTSBackend, QwenTTSBackend]      │
                    │                          │
                    ▼                          │
                [Registry]  ─────► [Cache]    │
                    │                 │        │
                    └──────┬──────────┴────────┘
                           ▼
                  [generate() + Spec + Result]
                           │
                           ▼
                       [speak()]
                           │
                           ▼
                    [smoke tests]
```

### Pattern-pull vs novel work

| Piece | Source | Effort |
|---|---|---|
| Protocol + errors + VoiceInfo | agent-core-voice/protocol.py — verbatim | trivial (copy + namespace) |
| FakeTTSBackend | agent-core-voice/fake.py + small adaptation | small |
| QwenTTSBackend | agent-core-voice/qwen_backend.py — lift + lazy-import | small |
| Cache | audiobook-pipeline-spec-v0.md cache contract (lines 215-219) | small |
| Registry | YAML-driven, VoiceInfo from §4 | small |
| Chunking | simple registry dict (NOT pulled from briefs/pluggy) | trivial |
| generate() + Spec + Result | new wiring; the orchestrator | medium |
| speak() wrapper | one-liner over generate() | trivial |
| Smoke tests | Fake-based; per-piece unit tests + integration test | small |
| Parallel-gen | **deferred to v0.1** — genuinely novel | (Monday) |

4 of 5 architectural pieces are pattern-pull. The 1 piece that's novel (parallel-gen) is the one that benefits from Monday-fresh; everything else is execution-shape.

### v0 acceptance criteria

- `pip install -e .` succeeds; `import voice` works.
- `voice.speak("hello", voice_id="pepper")` returns WAV bytes (against FakeTTSBackend in tests; against QwenTTSBackend in production with qwen-tts installed).
- `voice.generate(text, spec=Spec(...))` returns `Result` with the attribute population matrix in §3 honored.
- Cache hit/miss works for `Spec.cache=True`.
- `Spec.write_to=path` writes the file AND populates `result.audio`.
- `Spec.chunk_strategy="sentence"` chunks + synthesizes per chunk + concatenates.
- `Spec.parallel=True` raises `NotImplementedError("parallel-gen deferred to v0.1")`.
- `just check` green (lint + typecheck + tests).
- Pre-push hook fires + passes.

---

## 10. Out of scope

Things v0 explicitly does NOT do:

- **Parallel generation.** Deferred to v0.1 per §8.
- **Streaming synthesis.** Whole-utterance synthesis only; streaming partial-audio is a v0.2+ concern when a consumer demands it.
- **Audio post-processing.** No EQ, no compression, no format conversion beyond WAV bytes. Consumers handle.
- **Real Discord / sandbox channel integration.** voice is a pure library; transport is consumer-layer.
- **Real consent-ledger / regulatory metadata.** Audiobook's manifest layer wraps voice.cache for this; voice itself stays library-pure.
- **Watermark generation algorithm.** v0's `Spec.watermark=True` flag is wired through but the actual watermark insertion is a v0.2+ implementation (today it raises `NotImplementedError` if set). Spec field exists so consumer code is forward-compatible.
- **Multi-engine routing.** v0 picks one engine per `voice.generate()` call. Routing across engines (e.g., "use ElevenLabs for English, Qwen for Mandarin") is a v0.3+ concern.
- **Eviction policies on the cache.** v0 cache grows monotonically. Consumers needing eviction wrap.
- **CLI / standalone executable.** v0 is library-only. `voice` doesn't ship a CLI; consumers wire one if they want.

---

## Sign-off requested

- [ ] Jeff approves the API shape (§1 + §2 + §3).
- [ ] Jeff approves the engine + cache + registry + chunking shapes (§4-§7).
- [ ] Jeff approves the v0.1 deferral of parallel-gen (§8).
- [ ] Jeff approves the implementation order + acceptance criteria (§9).
- [ ] Pepper criterion-checks before send to Jeff (this happens before §0–§10 lands in Jeff's view).

On green-light from Jeff, implementation begins per the §9 dependency graph; ETA ~3-4 hours to v0 ship-ready PR.
