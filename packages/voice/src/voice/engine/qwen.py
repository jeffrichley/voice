"""Qwen3-TTS backend with in-context-learning voice cloning.

Real backend. Lazy-imports ``torch`` and ``qwen_tts`` inside ``__init__``
so the rest of ``voice.engine`` is importable on hosts without torch
installed (CI runners, dev machines without GPU, etc.).

Real Qwen synthesis requires the user to install ``qwen-tts`` separately
— it's not on PyPI today. agent_core releases ship the wheel as an
asset (``qwen_tts-0.1.1-py3-none-any.whl``); consumers can pip-install
that directly or set up a local mirror.

Built-in voice cloning per plan §2: a `voices.yaml` row with `ref_wav` +
`ref_text` is all that's needed; ``prepare_voice()`` builds the ICL
prompt at startup, then ``synthesize()`` is the per-utterance hot path
with no further training cost.
"""

from __future__ import annotations

import logging
import time
from io import BytesIO
from pathlib import Path
from typing import Any

from voice.engine.protocol import (
    EmptyTextError,
    GPUOOMError,
    VoiceNotPreparedError,
)

log = logging.getLogger(__name__)


class QwenTTSBackend:
    """Real backend: loads Qwen3-TTS once, holds ICL prompts per voice.

    Raises ``ImportError`` at construction if ``qwen-tts`` or ``torch``
    aren't installed. The error message names what to install so users
    aren't left guessing.
    """

    def __init__(
        self,
        *,
        model_path: str,
        device: str = "cuda:0",
        attn_implementation: str = "sdpa",
    ) -> None:
        try:
            import torch
            from qwen_tts import Qwen3TTSModel
        except ImportError as exc:
            raise ImportError(
                "QwenTTSBackend requires `qwen-tts` and `torch`. Install qwen-tts "
                "from agent_core's GitHub releases (qwen_tts-0.1.1-py3-none-any.whl) "
                "or vendor it locally. Install torch via `pip install torch` (or your "
                "platform's recommended install command for CUDA). "
                f"Original ImportError: {exc}"
            ) from exc

        self._torch = torch
        self._device = device
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(
                f"QwenTTSBackend configured device={device!r} but CUDA is not "
                "available on this host. Set device='cpu' (slow but works) or "
                "fix the CUDA install."
            )
        log.info(
            "loading Qwen3-TTS: model_path=%s device=%s attn=%s",
            model_path,
            device,
            attn_implementation,
        )
        self._model = Qwen3TTSModel.from_pretrained(
            model_path,
            device_map=device,
            torch_dtype=torch.bfloat16,
            attn_implementation=attn_implementation,
        )
        self._prompts: dict[str, Any] = {}

    def prepare_voice(self, voice_id: str, ref_wav: Path, ref_text: str) -> None:
        ref_wav = Path(ref_wav)
        if not ref_wav.exists():
            raise FileNotFoundError(f"ref_wav not found: {ref_wav}")
        prompt = self._model.create_voice_clone_prompt(
            ref_audio=str(ref_wav),
            ref_text=ref_text,
        )
        self._prompts[voice_id] = prompt
        log.info("voice %r prepared", voice_id)

    def synthesize(self, voice_id: str, text: str, seed: int) -> tuple[bytes, float]:
        if voice_id not in self._prompts:
            raise VoiceNotPreparedError(f"voice {voice_id!r} not prepared")
        if not text.strip():
            raise EmptyTextError("text is empty or whitespace-only")

        prompt = self._prompts[voice_id]
        start = time.monotonic()

        try:
            # Seed for determinism — same (voice, text, seed) → same audio.
            # Set before the model call; Qwen3TTSModel.generate_voice_clone
            # doesn't expose a seed parameter so we control determinism via
            # the global torch RNG state.
            self._torch.manual_seed(seed)
            if self._torch.cuda.is_available():
                self._torch.cuda.manual_seed_all(seed)

            # Qwen3TTSModel returns (wavs, sample_rate) where wavs is a list
            # of audio arrays (one per batch element). For single-text input,
            # we take wavs[0].
            wavs, sample_rate = self._model.generate_voice_clone(
                text=text,
                language="english",
                voice_clone_prompt=prompt,
            )
            audio_array = wavs[0]
        except RuntimeError as exc:
            if "CUDA out of memory" in str(exc) or "out of memory" in str(exc).lower():
                raise GPUOOMError(str(exc)) from exc
            raise

        # Encode int16 / float32 audio array → WAV bytes.
        import soundfile as sf

        buf = BytesIO()
        sf.write(buf, audio_array, int(sample_rate), format="WAV", subtype="PCM_16")
        wav_bytes = buf.getvalue()

        generation_s = time.monotonic() - start
        log.debug(
            "synthesized voice=%r len=%d seed=%d gen=%.3fs bytes=%d",
            voice_id,
            len(text),
            seed,
            generation_s,
            len(wav_bytes),
        )
        return wav_bytes, generation_s
