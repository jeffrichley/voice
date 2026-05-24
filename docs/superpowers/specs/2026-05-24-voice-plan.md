# voice — feature list (full ambition + v0 carve-out)

> **For Jeff:** This is the WHAT, not the HOW. Full library ambition first, then named subsets for what ships at each version. Architecture decisions are encoded as open questions at the end so you can react.
>
> **Author:** Wren (draft) · **Reviewer:** Pepper (criterion-check) · **Decision:** Jeff
> **Date:** 2026-05-24

---

## 0. What voice is

A shared TTS substrate. Three named consumers today, all with equal first-class status:

- **Pepper conversational** (via `agent-core-voice` bus adapter): short utterances, low-latency, bytes-back, ephemeral.
- **Audiobook pipeline**: long-form batch with content-addressed cache, manifest, resume-after-crash, watermarking.
- **Chrona narration**: scene-shaped batch with character voices (mix/blend), eventual music-mix.

Voice is the pure library these three (and future consumers) share. No bus, no agent_core ties, no consumer-policy concerns.

---

## 1. Core capabilities (always-on across versions)

These are the always-true things voice provides at every version. Not "v0 features"; the bedrock the rest sits on.

- **Synthesize text → audio bytes** via a chosen voice.
- **Pluggable engine backends** (today Qwen3-TTS; tomorrow ElevenLabs / OpenAI / IndexTTS-2 / Higgs / Chatterbox). Single Protocol, swap implementations.
- **Named voice registry** (`voice_id` → reference audio + config). Voice creation = config + sample, not code.
- **Deterministic synthesis** with seed control. Same (model, voice, text, seed, params) → same audio.
- **Content-addressed cache** keyed on the determinism inputs. Survives across runs + projects.
- **Long-form chunking** (sentence / paragraph; pluggable for future custom strategies).
- **Cross-consumer-equal API**: no consumer's flow shape privileged over others'.
- **Error taxonomy** consumers can dispatch on (`EmptyText`, `TextTooLong`, `GPUOOM`, `VoiceNotPrepared`, etc.).
- **Public + MIT-licensed** so audiobook, Chrona, and Pepper-via-adapter consume on equal terms.

---

## 2. v0 — shipping today (Sunday, after sign-off)

The starter subset that proves the core capabilities work end-to-end.

- `voice.generate(text, spec) → Result` — single entry point, uniform return.
- `voice.speak(text, voice_id) → bytes` — convenience wrapper (most common shape).
- `voice.Spec` — request object: voice_id + chunk_strategy + cache + write_to + seed + extra + watermark (flag exists, no-op in v0) + parallel (flag exists, raises in v0).
- `voice.Result` — uniform response: audio + sample_rate + cache_key + cache_hit + path + manifest + timings (attribute population varies by Spec).
- **Engine backends:** `QwenTTSBackend` (lazy-imports qwen-tts + torch) and `FakeTTSBackend` (deterministic synthetic, no torch, for tests).
- **Built-in voice cloning** via Qwen3-TTS's in-context-learning. Adding a voice = adding a `voices.yaml` entry with `ref_wav` + `ref_text`; `QwenTTSBackend.prepare_voice` builds the ICL prompt at startup. No LoRA training; that's deferred to v0.X+ as a separate API surface.
- **Tiered voice catalog:** YAML config files looked up in order — local (`./.voice/voices.yaml`) → project root (`./voices.yaml`) → global (`~/.config/voice/voices.yaml`). First match wins per `voice_id`. Matches standard config-layering conventions (.git, .npm, .python-version) — most-specific scope overrides broader. v0 does whole-voice override only; per-field partial overrides are a v0.X polish.
- **Cache:** filesystem hash store at `~/.cache/voice/`, minimal 6-field entry (audio, sha256, sample_rate, duration, generation_s, timestamp).
- **Chunking strategies:** `none` / `sentence` / `paragraph`. Simple registry dict.
- **Smoke tests** prove the apparatus.
- **Release apparatus already in place** (release-please + release.yml + qa-runner pattern available; ruleset). Per scaffold-agent-core-project skill, validated this morning.

v0 acceptance: a downstream consumer can `pip install voice`, register a voice, call `voice.speak(...)`, get bytes back. Audiobook can use it for batch with cache. Pepper can use it through the adapter for conversational.

---

## 3. v0.1 — Monday (the deferred-from-today work)

- **Parallel generation.** `Spec.parallel=True` actually works. List-input on `text=[...]` fans out across workers; `Result.audios` populates. The genuinely-novel piece: the engine-adapter-vs-worker-pool boundary question (does the adapter expose `synthesize_batch(texts)` or only single-shot + worker-pool wrapping?). Sub-spec Monday morning; implementation Monday afternoon.

---

## 4. v0.X+ — next-tier ambition (in scope; not next release)

Each here is roughly v0.2–v0.5 territory. Order is rough lean-on-priority, not committed.

- **Voice cloning *API* (higher-level workflow).** Today (v0) cloning is registry-driven: drop a `ref_wav` next to a `voices.yaml` row and you have a cloned voice. The v0.X+ API is `voice.clone_voice(name, ref_audio, ref_text=...)` — a single call that registers a new voice in the appropriate catalog tier programmatically. Companion CLI (`voice clone <name> <ref.wav>`) likely lands at the same time. **NOT the same as custom LoRA training** — that's a separately-deferred concern (next bullet).
- **Custom LoRA training pipeline.** Train a model-fine-tune from N hours of reference audio for higher-fidelity voice cloning than ICL alone can produce. Significantly more infrastructure (GPU training, model storage, evaluation). v0 + v0.X+ use Qwen3-TTS's built-in ICL only; LoRA is post-v1.0 ambition gated on explicit demand from a consumer where ICL fidelity isn't sufficient.
- **Voice direction / acting layer.** Prompt-driven emotion/style ("calm and slow," "excited"). Qwen3-TTS supports this via prompt; library exposes as `Spec.direction="calm and slow"` or similar.
- **Voice mixing / blending.** Combine voices in ratios (Pepper's voice is already 70/20/10 of three sources per the existing `VoiceInfo.blend` field). v0 carries the field through but doesn't expose mixing as a top-level operation; v0.X promotes blending to a first-class API.
- **Streaming generation.** For very long content, stream chunks as synthesized instead of buffering whole. Required for interactive conversational use at long-utterance scale.
- **Pluggable engines beyond Qwen3-TTS.** ElevenLabs adapter, OpenAI TTS adapter, IndexTTS-2, Higgs, Chatterbox. Each as a separate adapter conforming to the engine Protocol.
- **Multi-language voices.** Qwen3-TTS supports multiple languages; library exposes language-aware voice selection, or auto-detects from text.
- **Cross-engine voice equivalents.** Can `voice_id="pepper"` mean the same thing across Qwen / ElevenLabs / OpenAI, or is voice_id always engine-specific? Likely an architectural question (see §6).
- **Pronunciation override library.** Per-voice persistent dictionary so "Saki" pronounces a tricky proper noun the way Jeff says it should. Audiobook spec mentions this as a cached-resolutions store.
- **Voice safety guards.** Block named-person impersonation requests ("sound like Morgan Freeman"). Audiobook spec has a guard-LLM concept; library-level may be the right place.
- **Quality scoring / validation.** Automated quality check (MOS estimate, artifact detection) before delivering audio. Audiobook spec mentions threshold-based regen-on-fail.
- **Audio QA loop with regen-failed-segments.** If a segment fails QA, automatically retry with adjusted seed / params. Audiobook spec specifies 2-attempt ceiling.
- **Subtitle / timing export.** Audio + word-level timing for captioning. Audiobook needs this for SRT generation.
- **Real-time playback / interrupt.** For conversational use, allow consumer to interrupt mid-synthesis when user starts talking. Streaming + cancellation token.
- **Performance tuning + telemetry.** GPU-minutes per gen, throughput, cost projections. Already partially captured (`generation_s` per call); promote to first-class telemetry surface.
- **Watermark implementation.** Spec field is wired in v0; actual watermark generation algorithm lands here (EU AI Act Article 50 compliance for audiobook + Chrona public outputs).
- **Cache export / import.** Share a content-addressed cache across machines / between agents. "I generated chapter 1 on the desktop; pull it to the laptop." Audiobook + cross-machine work both want this.
- **A/B testing harness.** Same text, two voices, compare. Audiobook spec mentions this for narrator selection. Library-level support: `voice.compare(text, voices=[...])`.
- **Format support beyond WAV.** Today: WAV only. Future: MP3, FLAC, Opus, AAC. Audiobook wants FLAC; conversational streaming wants Opus; mobile wants AAC.
- **Sample rate selection.** Today: engine default. Future: `Spec.sample_rate_hz=22050` for audiobook quality, etc.
- **Voice versioning.** When "pepper v2" replaces "pepper v1" (re-recording, LoRA update), how does cache invalidate? Today: cache key includes model_id + params, so updating either invalidates. Future: explicit voice-version field in the registry.
- **Voice persona metadata.** Beyond voice_id: human-readable description, sample audio, typical use cases (for Pepper to ask "which voice fits this scene?"). Discoverability layer.
- **Deterministic seed catalog.** Knowledge that "for this voice, seed 17 always sounds best for emotional content" stored as voice-tagged metadata, not magic numbers in caller code.
- **Pluggable cache eviction strategies.** v0 cache grows monotonically; consumers wrap with their own logic if eviction is needed. Audiobook generates GB-scale audio over months; library-level eviction (LRU, size-cap, age-cap) will likely become a real demand within a year or two. Provide pluggable strategies then; until then, consumer-side wrapping is fine.

---

## 5. Out of scope (permanent — not planned even at v1.0)

These are things voice EXPLICITLY does not do, ever. Consumers either do them themselves or use a different tool.

- **CLI / standalone executable.** Voice is a library. The `voice` shell command does not exist; consumers wire one if they want.
- **GUI / web frontend.** Library only.
- **Audio post-processing** (EQ, compression, format conversion beyond what engines naturally produce). Consumer concern.
- **Real-time conversation orchestration.** Voice generates audio; the conversation loop (turn-taking, interrupt logic, ASR feedback) lives in `agent-core-voice` adapter or Pepper or Chrona.
- **Consent ledger / regulatory metadata storage.** Audiobook's manifest layer wraps voice.cache for this. Voice itself stays library-pure (no opinions on GDPR / EU AI Act / consent revocation policy).
- **Audio rendering for distribution.** Voice produces synthesis output. Mastering for podcast / audiobook distribution is downstream.
- **Multi-engine routing policy** (e.g., "use ElevenLabs for English, Qwen for Mandarin"). v0.X exposes per-call engine selection; the routing decision is consumer-layer.
- **Conversational state / dialogue management.** Voice synthesizes one utterance; conversation context lives in the consumer.

---

## 6. Architectural decisions (Jeff sign-off 2026-05-24)

Each question was presented with options + a recommendation; Jeff's
response is recorded as the decision. The original question + options
are preserved for audit-trail.

**6.1 — Voice catalog scope.**

*Question:* Per-project, per-workspace, or community? Options (A) per-project forever, (B) per-workspace overlay, (C) community-index. Wren recommendation: (A) now, (B) later.

**Decision: tiered lookup.** Local (`./.voice/voices.yaml`) → project root (`./voices.yaml`) → global (`~/.config/voice/voices.yaml`). First match per `voice_id` wins. Matches the standard config-layering convention (.git, .npm, .python-version) where most-specific scope overrides broader. Richer than my recommendation — Jeff named the tiered shape directly. Lands in v0, not deferred. Whole-voice override only in v0; per-field partial overrides are v0.X+.

**6.2 — Voice cloning workflow.**

*Question:* Does the library do training? Options (A) library does LoRA training, (B) library accepts pre-trained ref audio + voice_id, (C) `clone_voice()` API delegating to a training service. Wren recommendation: (B) for v0; (C) for v1.0+.

**Decision: built-in ICL only for v0 + v0.X; no LoRA training in the foreseeable plan.** v0 already does this via voices.yaml + ref_wav + `QwenTTSBackend.prepare_voice()` (see §2's "Built-in voice cloning" bullet). The v0.X `clone_voice()` API is the higher-level convenience layer over the same mechanism. Custom LoRA training is post-v1.0, gated on explicit demand where ICL fidelity is insufficient.

**6.3 — Cross-engine voice equivalents.**

*Question:* Is `voice_id="pepper"` engine-agnostic? Options (A) engine-specific, (B) engine-agnostic with per-engine registry config, (C) best-effort equivalency. Wren recommendation: (B).

**Decision: (B) — engine-agnostic at the API surface; per-engine details inside the registry entry.** Same as recommendation. (C) is dangerous due to silent voice substitution; (A) leaks engine-coupling into consumer code.

**6.4 — Voice safety guards.**

*Question:* Library-level or consumer-level? Options (A) library built-in, (B) consumer-level. Wren recommendation: (B).

**Decision: deferred with dependency.** Jeff's correct insight: library-level safety guards require an attestation pathway (a way for the voice-creator to assert "this voice has consent / isn't impersonating a specific person") that v0 doesn't have. The dependency is a `voice clone` CLI + attestation flow at voice-creation time; once that lands (probably v0.X+ alongside the cloning API), library-level guards become tractable. Until then: no built-in guards; consumers add safety policy in their own layers (audiobook's guard-LLM stays audiobook-layer).

**6.5 — Streaming generation: push or pull?**

*Question:* For streaming-synthesis when it lands, pull-from-generator or push-to-callback? Wren recommendation: pull as primary.

**Decision: pull as primary.** Same as recommendation. Callback wrapper available for consumers who prefer it; pull composes better with async + is more Pythonic.

**6.6 — Telemetry: library-aggregated or per-call return?**

*Question:* (A) library aggregates internally, (B) per-call return. Wren recommendation: (B).

**Decision: (B) — per-call return.** Same as recommendation. `Result.generation_s` already in v0; further telemetry fields added to `Result` as needs surface. Library stays state-free; aggregation is consumer-side wrapper if needed.

---

## What this brief asked for (status)

Three sign-offs requested:

1. ✅ **v0 scope** (§2) — Jeff approved with two refinements (tiered catalog + explicit built-in cloning call-out). Incorporated.
2. ✅ **v0.1 deferral** (§3) — parallel-gen confirmed for Monday.
3. ✅ **Architectural decisions** (§6) — 5 of 6 locked at his preferred shape; 6.4 deferred-with-dependency (CLI + attestation flow first).

Implementation gate now open. Tasks #181–#185 unlocked; engine adapter starts first per the §9 dependency graph in the implementation spec (`2026-05-24-voice-v0-design.md`, sibling to this file).

Anything in §4 to elevate to v0.1 or strike entirely? Jeff response if it lands: capture as a §4 edit.
