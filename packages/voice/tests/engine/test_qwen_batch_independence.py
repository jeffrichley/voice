"""LOAD-BEARING acceptance criterion (per the never-done-without-running rule).

Determines whether v0.1 can ship with cache + parallel composing freely
(item-independent path) or whether they must be mutually exclusive
(item-coupled fallback). The test result selects which path is active
when we declare done.

Per parallel-gen-design.md §7.1 + §0 preamble:
- This test MUST run + pass on real Qwen3-TTS before v0.1 is declared done.
- Tagged `@pytest.mark.real_engine`; skipped without VOICE_REAL_ENGINE_OK=1.
- Done-gate convention: declaring v0.1 done requires VOICE_REAL_ENGINE_OK=1
  on the validation run that collects + passes this test.

**Empirical result captured 2026-05-25 (Wren, Jeff's workstation):**
Qwen3-TTS native batching is ITEM-COUPLED. Same text produces different
audio when batched with different other texts. v0.1 ships with the
spec §5 fallback active: cache + parallel mutually exclusive for UC1
(ValueError); silent fallback to v0 sequential cache+chunking for UC2
(Result.parallel_used=False signals the fallback).

This test records the result + verifies the orchestrator's behavior
matches. Either way (item-independent OR item-coupled) passes. The
test's PURPOSE is to keep the empirical evidence in the test suite —
re-run on engine upgrades to catch behavior changes.

Required env vars when VOICE_REAL_ENGINE_OK=1:
- VOICE_TEST_MODEL_PATH: filesystem path to Qwen3-TTS model
- VOICE_TEST_REF_WAV: filesystem path to a reference WAV
- VOICE_TEST_REF_TEXT: reference text matching the WAV
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_engine


@pytest.mark.skipif(
    not os.environ.get("VOICE_REAL_ENGINE_OK"),
    reason=(
        "Requires real Qwen3-TTS engine (torch + qwen-tts + GPU). "
        "Set VOICE_REAL_ENGINE_OK=1 + VOICE_TEST_MODEL_PATH/REF_WAV/REF_TEXT to run. "
        "Per the never-done-without-running rule (2026-05-24): v0.1 cannot ship "
        "without running this test."
    ),
)
def test_batch_item_independence_empirical() -> None:
    """Does `synthesize_batch(["a", "b"], seed=42)` produce same audio for "a"
    as `synthesize_batch(["a"], seed=42)` does?

    Result is RECORDED here for audit. Test passes regardless of outcome;
    the orchestrator's §5 fallback path matches the recorded result.

    Re-run this test if Qwen3-TTS is upgraded or replaced — behavior change
    may warrant lifting the §5 fallback (item-independent) or keeping it
    (item-coupled).
    """
    from voice.engine import QwenTTSBackend

    model_path = os.environ.get("VOICE_TEST_MODEL_PATH")
    ref_wav_path = os.environ.get("VOICE_TEST_REF_WAV")
    ref_text = os.environ.get("VOICE_TEST_REF_TEXT")

    assert model_path, "VOICE_TEST_MODEL_PATH must be set"
    assert ref_wav_path, "VOICE_TEST_REF_WAV must be set"
    assert ref_text, "VOICE_TEST_REF_TEXT must be set"

    backend = QwenTTSBackend(
        model_path=model_path,
        device="cuda:0",
    )
    backend.prepare_voice("pepper", Path(ref_wav_path), ref_text)

    # Same text alone vs. in a batch with another text.
    alone_audios, _ = backend.synthesize_batch("pepper", ["Hello, world."], seed=42)
    in_batch_audios, _ = backend.synthesize_batch(
        "pepper", ["Hello, world.", "Second item, different text."], seed=42
    )

    is_item_independent = alone_audios[0] == in_batch_audios[0]

    if is_item_independent:
        # Engine behavior unexpectedly improved (or never had coupling on this
        # config). The §5 fallback in voice.generate is overly conservative —
        # could be lifted. File an issue.
        print(
            "\nEMPIRICAL RESULT: ITEM-INDEPENDENT. "
            "Spec §5 fallback is overly conservative for this backend; "
            "consider lifting the cache+parallel mutual-exclusion in "
            "voice.generate. Re-validate orchestrator behavior."
        )
    else:
        # The recorded 2026-05-25 result. Confirms §5 fallback is correct.
        print(
            "\nEMPIRICAL RESULT: ITEM-COUPLED. "
            "Spec §5 fallback active in voice.generate (cache+parallel "
            "mutually exclusive). Confirmed correct."
        )

    # Verify orchestrator behavior matches the recorded result.
    if not is_item_independent:
        from voice import Cache, Spec, generate

        cache = Cache(root=Path(os.environ.get("TMP", "/tmp")) / "voice-empirical-cache")
        with pytest.raises(ValueError, match="mutually exclusive"):
            generate(
                ["x"],
                Spec(voice_id="pepper", parallel=True, cache=True),
                backend=backend,
                cache=cache,
            )
