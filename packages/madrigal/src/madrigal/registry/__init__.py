"""madrigal.registry — tiered YAML voice catalog.

Per plan v2 §2 + §6.1: lookup order is local-FIRST (most-specific scope
wins on first hit). Standard config-layering convention; matches .git,
.npm, pip.conf, .python-version.

Lookup path order:
    1. ./.madrigal/voices.yaml         (per-cwd local override)
    2. ./voices.yaml                   (project root)
    3. ~/.config/madrigal/voices.yaml  (user global; honors $XDG_CONFIG_HOME)

First match per ``voice_id`` wins. Whole-voice override only in v0;
per-field partial overlays are a v0.X polish.
"""

from madrigal.registry.tiered import Registry, default_lookup_paths

__all__ = ["Registry", "default_lookup_paths"]
