# voice (package)

The voice library package itself. See the repo-root `README.md` for the
project overview, design, install/develop/release instructions.

This package will hold:

- `voice/engine/` — pluggable TTS engine adapters (Qwen3-TTS primary)
- `voice/cache/` — content-addressed cache
- `voice/registry/` — named voice registry
- `voice/parallel/` — worker pool + futures-shaped batch API
- `voice/chunking/` — long-form chunking
- `voice/pronunciation/` — pronunciation library
- Top-level `speak()` (streaming) + `produce()` (batch) APIs

Implementation lands in subsequent PRs.
