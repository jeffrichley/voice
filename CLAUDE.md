# voice

Pluggable TTS engine library with content-addressed cache, parallel generation, named voice registry, and mode-aware delivery for streaming and batch consumers.

## Working in this repo

- `uv sync` to install / refresh dependencies
- `just check` runs the full quality gate (lint + typecheck + tests)
- `just fix` applies ruff auto-fixes + formatting
- `.githooks/pre-push` runs `just check` before push; emergency bypass: `git push --no-verify` (use sparingly)

## Release

This project uses release-please. Conventional-commit messages on merged PRs
become CHANGELOG entries. release-please opens a PR with the next version's
release notes; merging it tags the release. `release.yml` then builds the
wheels and uploads them to the GitHub Release.

If `release.yml` doesn't auto-fire after release-please tags (GitHub's
GITHUB_TOKEN anti-recursion guard), trigger it manually:

```bash
gh workflow run release.yml -f tag=<the-tag>
```

OR toggle the release draft state to refire `release.published`:

```bash
gh release edit <tag> --draft
gh release edit <tag> --draft=false
```

## Conventions

- Conventional commits required (PR titles enforced by `.github/workflows/pr-title-lint.yml`)
- Subject must NOT start with an uppercase letter
- All allowed types: feat, fix, chore, docs, refactor, test, style, build, ci, perf, revert

## Design constraints (load-bearing — read before substantial changes)

This library was designed to serve THREE distinct consumers with different
requirement profiles:

- **Conversational use** (low-latency streaming, single-utterance, no cache needed)
- **Audiobook pipeline** (batch, long-form chunking, content-addressed cache, resume)
- **Narration / Chrona** (batch, character voices via named registry, music+voice mix)

**Hard constraints to preserve:**

- **No bus or agent_core dependencies.** voice is a pure library; consumers
  wire it into their own infrastructure. The `agent-core-voice` adapter
  (inside agent_core's workspace) is the thin layer that wires voice into
  agent_core's bus/MCP surface for in-agent_core consumers.
- **Cross-consumer-equal API.** API design must serve each consumer's
  needs as first-class; don't privilege any one consumer's flow at the
  others' expense.
- **Parallel-gen is load-bearing.** The worker-pool + futures-shaped batch
  API for parallel inference is the substantial new architecture; design
  carefully. `speak()` (single-utterance) and `produce()` (batch) are the
  intended top-level surfaces.
