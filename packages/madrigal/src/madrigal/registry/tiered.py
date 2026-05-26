"""Tiered YAML voice registry: local → project → global, first-hit wins.

YAML shape (per ``voices.yaml``)::

    voices:
      - voice_id: pepper
        ref_wav: ~/voices/pepper-ref.wav
        ref_text: "Reference recording text."
        blend: null
      - voice_id: narrator-saki
        ref_wav: ~/voices/saki-ref.wav
        ref_text: "Sample line capturing the narrator's tone."

The ``blend`` field is optional. Paths in ``ref_wav`` are expanded
(``~`` → home) and resolved relative to the YAML file's directory if
not absolute.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

import yaml

from madrigal.engine.protocol import VoiceInfo


def default_lookup_paths(*, cwd: Path | None = None) -> list[Path]:
    """Return the default tiered lookup paths in priority order.

    Order: local (.madrigal/voices.yaml under cwd) → project (voices.yaml
    under cwd) → global (~/.config/madrigal/voices.yaml or
    $XDG_CONFIG_HOME/madrigal/voices.yaml).
    """
    cwd = (cwd or Path.cwd()).resolve()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        global_path = Path(xdg) / "madrigal" / "voices.yaml"
    else:
        global_path = Path.home() / ".config" / "madrigal" / "voices.yaml"
    return [
        cwd / ".madrigal" / "voices.yaml",
        cwd / "voices.yaml",
        global_path.expanduser(),
    ]


class Registry:
    """Tiered voice catalog with first-hit-wins lookup.

    Construct with no args to use the default tiered paths (relative to
    cwd at construction time), or pass an explicit ``paths`` list for
    test isolation or non-default layouts.
    """

    def __init__(self, paths: Iterable[Path] | None = None) -> None:
        self._paths: list[Path] = list(paths) if paths is not None else default_lookup_paths()
        self._cache: dict[str, VoiceInfo] | None = None

    @property
    def paths(self) -> list[Path]:
        """Lookup paths in priority order (first = most specific)."""
        return list(self._paths)

    def get(self, voice_id: str) -> VoiceInfo:
        """Return the VoiceInfo for ``voice_id``. Raises KeyError on miss."""
        catalog = self._load()
        if voice_id not in catalog:
            raise KeyError(
                f"voice_id {voice_id!r} not found in any tier. "
                f"Searched: {[str(p) for p in self._paths]}. "
                f"Known: {sorted(catalog)}"
            )
        return catalog[voice_id]

    def list_voice_ids(self) -> list[str]:
        """Return all known voice_ids sorted alphabetically."""
        return sorted(self._load())

    def reload(self) -> None:
        """Drop the in-memory cache; next ``get()`` re-reads the YAML files."""
        self._cache = None

    def _load(self) -> dict[str, VoiceInfo]:
        """Lazy-load the catalog. First-hit-wins per voice_id across tiers."""
        if self._cache is not None:
            return self._cache

        merged: dict[str, VoiceInfo] = {}
        for path in self._paths:
            if not path.exists():
                continue
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                raise ValueError(f"YAML parse error in {path}: {exc}") from exc
            if data is None:
                continue
            voices_list = data.get("voices", []) if isinstance(data, dict) else []
            for entry in voices_list:
                voice = _parse_voice_entry(entry, source_dir=path.parent)
                # First-hit-wins: only add if not already present from a
                # more-specific tier.
                if voice.voice_id not in merged:
                    merged[voice.voice_id] = voice

        self._cache = merged
        return merged


def _parse_voice_entry(entry: object, *, source_dir: Path) -> VoiceInfo:
    """Convert a YAML dict entry into a VoiceInfo. Resolves ref_wav relative to source."""
    if not isinstance(entry, dict):
        raise ValueError(f"voice entry must be a dict, got {type(entry).__name__}")
    try:
        voice_id = str(entry["voice_id"])
        ref_wav_raw = str(entry["ref_wav"])
        ref_text = str(entry["ref_text"])
    except KeyError as exc:
        raise ValueError(f"voice entry missing required field: {exc}") from exc

    ref_wav = Path(ref_wav_raw).expanduser()
    if not ref_wav.is_absolute():
        ref_wav = (source_dir / ref_wav).resolve()

    blend = entry.get("blend")
    return VoiceInfo(
        voice_id=voice_id,
        ref_wav=ref_wav,
        ref_text=ref_text,
        blend=str(blend) if blend is not None else None,
    )
