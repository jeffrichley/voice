# Spec: bump actions/upload-artifact + download-artifact v4 → v5

- **Issue:** [jeffrichley/voice#8](https://github.com/jeffrichley/voice/issues/8)
- **Type:** chore (mechanical version bump)
- **Base branch:** `main`
- **Date:** 2026-05-29

## Problem

GitHub is retiring the Node 20 runtime for Actions as part of its runtime
deprecation cycle (Node 16 → Node 20 → Node 24). The release pipeline
(`.github/workflows/release.yml`) pins two artifact actions that still run on
Node 20:

| File | Line | Current |
|---|---|---|
| `.github/workflows/release.yml` | 58 | `uses: actions/upload-artifact@v4` |
| `.github/workflows/release.yml` | 80 | `uses: actions/download-artifact@v4` |

When GitHub retires Node 20, these steps will start emitting deprecation
warnings and eventually fail, breaking the release → PyPI publish flow. `v5`
of both actions runs on Node 24 and is GA.

These two are coupled: the `build` job uploads the `wheels` artifact (line 58)
and the `publish-pypi` job downloads it (line 80). The download version must
match the upload version, so both bump together in a single change.

## Goals

1. Bump `actions/upload-artifact` from `@v4` to `@v5` (release.yml:58).
2. Bump `actions/download-artifact` from `@v4` to `@v5` (release.yml:80).
3. No other behavior changes — version-only bump.

## Non-goals (out of scope)

- Bumping other GitHub Actions (`actions/checkout`, `astral-sh/setup-uv`,
  `pypa/gh-action-pypi-publish`) — each gets its own ticket if due.
- Any workflow logic, job, or trigger changes.
- Adding new workflows.

## Approach

Two one-line edits in `.github/workflows/release.yml`:

- Line 58: `uses: actions/upload-artifact@v4` → `uses: actions/upload-artifact@v5`
- Line 80: `uses: actions/download-artifact@v4` → `uses: actions/download-artifact@v5`

Leave every surrounding key untouched. The `with:` blocks for both steps are
unchanged across v4 → v5 for the inputs this workflow uses (`name`, `path`,
`retention-days`, `if-no-files-found`), so no `with:` adjustments are needed.

### Compatibility note

`upload-artifact@v4`/`download-artifact@v4` artifacts are not interoperable
with `@v3` artifacts, but `@v5` is a runtime-only major bump from `@v4` (Node
20 → Node 24) — the on-disk artifact format and the `name`-based handshake
between upload and download are unchanged. Bumping both sides in the same
commit keeps upload and download on the same major, preserving the existing
`wheels` artifact handshake between the `build` and `publish-pypi` jobs.

## Risks

- **Low.** Runtime-only major bump; no input surface change for this
  workflow's usage.
- **Version skew:** if only one of the two were bumped, the download could
  fail to find/read the upload's artifact. Mitigated by bumping both in the
  same commit (an explicit acceptance criterion).
- **Unverifiable without a release:** `release.yml` triggers on
  `release: published`, so a normal PR push does not exercise it. See
  validation for the verification options.

## Validation

1. **Diff review:** confirm exactly two lines changed, both `@v4` → `@v5`,
   no other diff in the file.
2. **Syntax / lint:** confirm YAML is valid and the workflow still parses
   (e.g. `actionlint` if available, or GitHub's own workflow validation on
   push — a malformed workflow surfaces in the repo's Actions tab).
3. **Pipeline green:** because `release.yml` only runs on `release: published`
   (with a `workflow_dispatch` fallback), it cannot be exercised by the PR
   itself. Verify at the next release, or trigger manually against an existing
   tag once merged:

   ```bash
   gh workflow run release.yml -f tag=<an-existing-tag>
   ```

   Confirm the `build` job's "Upload wheels as workflow artifact" step and the
   `publish-pypi` job's "Download wheels from workflow artifact" step both
   succeed, and that the artifact handshake produces wheels in `dist/`.

## Acceptance criteria (from issue)

1. Both lines updated to `@v5`.
2. No other behavior changes (version-only bump; no adjacent refactors).
3. Workflow runs green on a triggered build, or syntax confirmed valid where a
   live trigger isn't available pre-merge.
