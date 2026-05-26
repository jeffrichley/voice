"""Private cache-key derivation.

Per plan v2 §5 + audiobook-pipeline-spec-v0.md line 216:
    cache_key = hash(model_id, voice_id, text, seed, params)

Per Pepper's forward-looking note at checkpoint 2/4: include ONLY
output-affecting fields. Behavior-only fields (write_to, cache flag
itself, parallel) MUST NOT be in the key — they change what happens,
not what audio comes out. Consumer-wrapper metadata (consent ledger,
GPU-min accounting, etc.) also MUST NOT be in the key — those are
out-of-scope for madrigal's cache contract.

Output-affecting fields in v0:
- model_id (from spec.extra; default = "default" if not provided)
- voice_id
- text (the chunk-level text, not the original full text)
- seed
- watermark (when actually implemented in v0.X+, watermarked vs not is
  different audio; including in v0 key for forward-compat means future
  cache won't accidentally collide)
- spec.extra (engine-specific params; conservative-inclusion since
  user can put output-affecting things in there)
"""

from __future__ import annotations

import hashlib
import json

from madrigal.spec import Spec


def cache_key(*, spec: Spec, text: str, model_id: str = "default") -> str:
    """Derive a content-addressed sha256 key for a single chunk synthesis.

    The KEY is per-chunk; chunked text generates multiple keys (one per
    chunk). chunk_strategy itself is NOT in the key — it determines what
    text gets passed here, not what audio comes out for a given text.
    """
    # Sort extra to ensure deterministic hashing regardless of insertion order.
    extra_sorted = json.dumps(spec.extra, sort_keys=True, separators=(",", ":"))

    payload = "|".join(
        [
            model_id,
            spec.voice_id,
            text,
            str(spec.seed),
            str(spec.watermark),  # forward-compat: when v0.X+ implements, key already segments
            extra_sorted,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
