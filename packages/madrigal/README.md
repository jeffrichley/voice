# madrigal (package)

The madrigal library package itself. See the repo-root `README.md` for the
project overview, design, install/develop/release instructions.

This package holds:

- `madrigal/engine/` — pluggable TTS engine adapters (Qwen3-TTS primary)
- `madrigal/cache/` — content-addressed cache
- `madrigal/registry/` — named voice registry
- `madrigal/chunking.py` — long-form text chunking strategies
- Top-level `generate()` + `speak()` APIs
