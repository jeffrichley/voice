# Agent guidelines for voice

This file documents conventions for AI agents (Claude Code, Codex, etc.)
working in this repo.

## Required reads before substantial changes

- `README.md` — project overview
- `CLAUDE.md` — repo-specific working conventions + load-bearing design constraints
- `docs/superpowers/specs/` — design specs for any in-flight feature work

## Conventions

- **Conventional commits** — PR titles enforced by CI (`pr-title-lint`); subject must NOT start with uppercase.
- **Pre-push gate** — `.githooks/pre-push` runs `just check`. Don't skip.
- **Specs before code** — non-trivial features land a design doc in
  `docs/superpowers/specs/` before the implementation PR.
- **Squash-merge only** — repo is configured for squash-merge; the PR
  description becomes the commit body.

## Project-specific guardrails

- **No bus or agent_core dependencies.** voice is a pure library. NEVER
  add `from agent_core.X import ...` or any agent-core-* package as a
  dependency. The structural separation between voice and agent_core is
  load-bearing; it's enforced by living in a separate repo.
- **Cross-consumer-equal API.** Three named consumers (Pepper
  conversational use via agent-core-voice adapter, audiobook pipeline,
  Chrona narration) must each get first-class API support. Don't
  optimize for one at another's expense.
- **Parallel-gen is the load-bearing new architecture.** Worker-pool +
  futures-shaped batch API. `speak()` (single-utterance) and `produce()`
  (batch) are the top-level surfaces. Discuss design changes to this
  area carefully before changing.
