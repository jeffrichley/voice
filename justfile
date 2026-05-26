# Justfile — single quality-command surface for madrigal workspace.
#
# Keep this as the source of truth for local + CI check commands so
# developers and agents run the same gates in the same order.

set windows-shell := ["cmd.exe", "/c"]

# Workspace package scopes
pkg-src := "packages/madrigal/src"
pkg-tests := "packages/madrigal/tests"

default:
    @just --list

# Composite gate (recommended before push)
check: lint typecheck test

# Developer convenience: apply lint auto-fixes + formatter
fix:
    uv run --no-sync ruff check --fix packages/madrigal
    uv run --no-sync ruff format packages/madrigal

# Lint
lint:
    uv run --no-sync ruff check packages/madrigal

# Type-check
typecheck:
    uv run --no-sync mypy packages/madrigal/src

# Tests
test:
    uv run --no-sync pytest

# Build wheels locally (sanity-check that release.yml would succeed)
build:
    uv build --all-packages --wheel --out-dir dist/
