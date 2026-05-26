# Changelog

## [0.2.0](https://github.com/jeffrichley/voice/compare/v0.1.0...v0.2.0) (2026-05-26)


### ⚠ BREAKING CHANGES

* PyPI dist name and Python module name both change from `voice` to `madrigal`. Driver was a PyPI name collision (`voice` is squatted by an unrelated Django/South utility, making clean publish impossible under the original name).

### Features

* rename library from voice to madrigal ([#5](https://github.com/jeffrichley/voice/issues/5)) ([32eefef](https://github.com/jeffrichley/voice/commit/32eefefa2d69e0d25eb5f54833abe362019daaf2))

## 0.1.0 (2026-05-25)


### Features

* **voice:** v0 implementation — engine adapter, cache, registry, chunking, generate() + speak() orchestrator ([f3ad165](https://github.com/jeffrichley/voice/commit/f3ad1657f46e5be86d066310c9f76675ab7e037a))
* **voice:** v0.1 parallel-gen (UC1 + UC2 + §5 item-coupled fallback) ([#1](https://github.com/jeffrichley/voice/issues/1)) ([f1ce5b2](https://github.com/jeffrichley/voice/commit/f1ce5b2c0ab8d888d7e60c538d6860e681a47aa9))


### Bug Fixes

* **voice:** QwenTTSBackend.synthesize uses actual generate_voice_clone API ([3481759](https://github.com/jeffrichley/voice/commit/3481759c955436da9fad8e426be3daca364cf6f5))

## Changelog

All notable changes to this project will be documented in this file.

This project uses [release-please](https://github.com/googleapis/release-please)
to manage releases. Entries are generated from conventional-commit messages on
merged PRs.
