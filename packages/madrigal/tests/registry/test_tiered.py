"""Test tiered voice registry: local-FIRST lookup, YAML parsing, error shapes."""

from __future__ import annotations

from pathlib import Path

import pytest

from madrigal.registry import Registry, default_lookup_paths


def _write_voices_yaml(path: Path, voices: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["voices:"]
    for v in voices:
        lines.append(f"  - voice_id: {v['voice_id']}")
        lines.append(f"    ref_wav: {v['ref_wav']}")
        lines.append(f"    ref_text: \"{v['ref_text']}\"")
        if "blend" in v:
            lines.append(f"    blend: {v['blend']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_default_lookup_order_local_project_global(tmp_path: Path) -> None:
    paths = default_lookup_paths(cwd=tmp_path)
    assert len(paths) == 3
    assert paths[0] == tmp_path / ".madrigal" / "voices.yaml"  # local first
    assert paths[1] == tmp_path / "voices.yaml"             # project second
    assert paths[2].name == "voices.yaml"                   # global last
    assert "config" in str(paths[2]).lower()


def test_default_global_honors_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    paths = default_lookup_paths(cwd=tmp_path)
    assert paths[2] == tmp_path / "madrigal" / "voices.yaml"


def test_get_returns_voice_info(tmp_path: Path) -> None:
    yaml_path = tmp_path / "voices.yaml"
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"placeholder")
    _write_voices_yaml(yaml_path, [
        {"voice_id": "pepper", "ref_wav": str(ref), "ref_text": "ref text"},
    ])
    registry = Registry(paths=[yaml_path])
    info = registry.get("pepper")
    assert info.voice_id == "pepper"
    assert info.ref_wav == ref.resolve()
    assert info.ref_text == "ref text"
    assert info.blend is None


def test_get_missing_raises_keyerror(tmp_path: Path) -> None:
    registry = Registry(paths=[tmp_path / "nope.yaml"])
    with pytest.raises(KeyError, match="not found"):
        registry.get("pepper")


def test_local_overrides_project_overrides_global(tmp_path: Path) -> None:
    """First-hit wins: local tier overrides project, which overrides global."""
    ref_local = tmp_path / "ref-local.wav"
    ref_project = tmp_path / "ref-project.wav"
    ref_global = tmp_path / "ref-global.wav"
    for r in (ref_local, ref_project, ref_global):
        r.write_bytes(b"placeholder")

    local = tmp_path / ".madrigal" / "voices.yaml"
    project = tmp_path / "voices.yaml"
    global_path = tmp_path / "global" / "voices.yaml"

    _write_voices_yaml(local, [{"voice_id": "pepper", "ref_wav": str(ref_local), "ref_text": "local"}])
    _write_voices_yaml(project, [{"voice_id": "pepper", "ref_wav": str(ref_project), "ref_text": "project"}])
    _write_voices_yaml(global_path, [{"voice_id": "pepper", "ref_wav": str(ref_global), "ref_text": "global"}])

    registry = Registry(paths=[local, project, global_path])
    info = registry.get("pepper")
    assert info.ref_text == "local"  # local won


def test_project_used_when_local_missing(tmp_path: Path) -> None:
    ref_project = tmp_path / "ref-project.wav"
    ref_project.write_bytes(b"placeholder")
    project = tmp_path / "voices.yaml"
    _write_voices_yaml(project, [{"voice_id": "pepper", "ref_wav": str(ref_project), "ref_text": "project"}])

    registry = Registry(paths=[tmp_path / ".madrigal" / "voices.yaml", project])
    info = registry.get("pepper")
    assert info.ref_text == "project"


def test_global_used_when_no_specific(tmp_path: Path) -> None:
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"placeholder")
    global_path = tmp_path / "global" / "voices.yaml"
    _write_voices_yaml(global_path, [{"voice_id": "pepper", "ref_wav": str(ref), "ref_text": "global"}])

    registry = Registry(paths=[tmp_path / "local.yaml", tmp_path / "project.yaml", global_path])
    info = registry.get("pepper")
    assert info.ref_text == "global"


def test_different_voices_can_come_from_different_tiers(tmp_path: Path) -> None:
    """Local has pepper; global has saki. Both should resolve from their respective tiers."""
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"placeholder")
    local = tmp_path / ".madrigal" / "voices.yaml"
    global_path = tmp_path / "global" / "voices.yaml"
    _write_voices_yaml(local, [{"voice_id": "pepper", "ref_wav": str(ref), "ref_text": "local pepper"}])
    _write_voices_yaml(global_path, [{"voice_id": "saki", "ref_wav": str(ref), "ref_text": "global saki"}])

    registry = Registry(paths=[local, global_path])
    assert registry.get("pepper").ref_text == "local pepper"
    assert registry.get("saki").ref_text == "global saki"


def test_relative_ref_wav_resolved_from_yaml_dir(tmp_path: Path) -> None:
    """Relative ref_wav paths are resolved against the YAML file's directory."""
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    ref = subdir / "voices" / "pepper.wav"
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"placeholder")
    yaml_path = subdir / "voices.yaml"
    _write_voices_yaml(yaml_path, [{"voice_id": "pepper", "ref_wav": "voices/pepper.wav", "ref_text": "rel"}])

    registry = Registry(paths=[yaml_path])
    info = registry.get("pepper")
    assert info.ref_wav == ref.resolve()


def test_list_voice_ids_sorted(tmp_path: Path) -> None:
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"placeholder")
    yaml_path = tmp_path / "voices.yaml"
    _write_voices_yaml(yaml_path, [
        {"voice_id": "pepper", "ref_wav": str(ref), "ref_text": "p"},
        {"voice_id": "saki",   "ref_wav": str(ref), "ref_text": "s"},
        {"voice_id": "amber",  "ref_wav": str(ref), "ref_text": "a"},
    ])
    registry = Registry(paths=[yaml_path])
    assert registry.list_voice_ids() == ["amber", "pepper", "saki"]


def test_reload_picks_up_changes(tmp_path: Path) -> None:
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"placeholder")
    yaml_path = tmp_path / "voices.yaml"
    _write_voices_yaml(yaml_path, [{"voice_id": "pepper", "ref_wav": str(ref), "ref_text": "first"}])
    registry = Registry(paths=[yaml_path])
    assert registry.get("pepper").ref_text == "first"

    _write_voices_yaml(yaml_path, [{"voice_id": "pepper", "ref_wav": str(ref), "ref_text": "second"}])
    # Without reload, returns cached.
    assert registry.get("pepper").ref_text == "first"
    registry.reload()
    assert registry.get("pepper").ref_text == "second"


def test_blend_field_optional_and_carried(tmp_path: Path) -> None:
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"placeholder")
    yaml_path = tmp_path / "voices.yaml"
    _write_voices_yaml(yaml_path, [
        {"voice_id": "pepper", "ref_wav": str(ref), "ref_text": "p", "blend": "warm-low-70-20-10"},
    ])
    registry = Registry(paths=[yaml_path])
    assert registry.get("pepper").blend == "warm-low-70-20-10"


def test_malformed_yaml_raises_value_error(tmp_path: Path) -> None:
    yaml_path = tmp_path / "voices.yaml"
    yaml_path.write_text("voices:\n  - voice_id: pepper\n    : :  bad: yaml: here", encoding="utf-8")
    registry = Registry(paths=[yaml_path])
    with pytest.raises(ValueError, match="YAML parse error"):
        registry.get("pepper")


def test_missing_required_field_raises(tmp_path: Path) -> None:
    yaml_path = tmp_path / "voices.yaml"
    yaml_path.write_text("voices:\n  - voice_id: pepper\n", encoding="utf-8")  # missing ref_wav, ref_text
    registry = Registry(paths=[yaml_path])
    with pytest.raises(ValueError, match="missing required field"):
        registry.get("pepper")


def test_empty_yaml_treated_as_no_voices(tmp_path: Path) -> None:
    yaml_path = tmp_path / "voices.yaml"
    yaml_path.write_text("", encoding="utf-8")
    registry = Registry(paths=[yaml_path])
    assert registry.list_voice_ids() == []
