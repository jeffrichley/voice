"""Smoke test: voice package imports and runs.

Honest scaffold-time test: proves the test apparatus runs and the package
is importable. No real behavior yet; implementation lands in subsequent
PRs.
"""


def test_voice_imports() -> None:
    """`import voice` should not raise."""
    import voice  # noqa: F401


def test_smoke_apparatus_runs() -> None:
    """Pytest itself works in this scaffold."""
    assert True
