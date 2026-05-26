# madrigal

Polyphonic TTS engine library — parallel voice synthesis, content-addressed cache, named voice registry, and mode-aware delivery for streaming and batch consumers.

A madrigal is a Renaissance composition for multiple unaccompanied voices, sung in parallel — which is precisely what this library does. The orchestrator synthesizes chunks in parallel (`synthesize_batch`) under one shared voice prompt, then concatenates the result. The name self-documents the algorithm.

## Status

Greenfield. The repo apparatus is scaffolded; the library implementation is the next step.

## Design

This library serves three distinct consumers — conversational (low-latency streaming), audiobook (batch + cache + resume), and narration (character voices + music mix). It's deliberately a pure library with no bus or agent-core dependencies; consumers wire it into their own infrastructure.

In-workspace agent-core consumers use the `agent-core-voice` adapter (lives in agent_core's workspace, depends on this library, wires it into agent_core's bus/MCP surface). External consumers (audiobook, narration) consume this library directly.

## Install

```bash
pip install madrigal
```

(Once the first release is cut.)

## Usage

```python
from madrigal import generate, Spec
from madrigal.engine import FakeTTSBackend  # or QwenTTSBackend in prod
from madrigal.registry import Registry

backend = FakeTTSBackend()
backend.prepare_voice("pepper", Path("ref.wav"), "Reference text.")
result = generate("Hello, Jeff.", Spec(voice_id="pepper"), backend=backend)
audio_bytes = bytes(result)
```

## Develop

```bash
git clone https://github.com/jeffrichley/voice
cd voice
uv sync
just check
```

`just check` runs the full quality gate (lint + typecheck + tests).

## Release

This project uses [release-please](https://github.com/googleapis/release-please) for version management. Conventional-commit messages on merged PRs become CHANGELOG entries. release-please opens a release PR; merging it tags the release. The `release.yml` workflow builds wheels and uploads them to the GitHub Release.

If `release.yml` doesn't auto-fire after release-please tags, see `CLAUDE.md` for the manual trigger workaround.

## License

MIT. See `LICENSE`.

## Extraction-trigger

This library was extracted from the agent-core-voice + qwen-tts work in agent_core, then split as a standalone library to serve three distinct consumers equally (see `CLAUDE.md` for the design constraints). If a fourth consumer materializes with materially different requirements, revisit the API design to ensure it's still cross-consumer-equal. If usage patterns demonstrate the library's release cadence should diverge from any single consumer's, that's also healthy — madrigal's cadence is independent.

## Name

PyPI's `voice` slot is held by an unrelated Django/South utility, so the originally-intended distribution name was unavailable. `madrigal` was chosen because it names exactly what this library does: many voices, sung in parallel. The repository remains `jeffrichley/voice` to preserve URL/issue history; only the library identity (PyPI dist + Python module) is `madrigal`.
