# tests/test_gui_core_bridge.py
import os
import pytest
from ambermeta.gui.api import core_bridge
from ambermeta.manifest import write_manifest, load_manifest

cb = core_bridge


def _stage(**kw):
    base = {"id": "deadbeef", "name": "s", "role": "", "prmtop": None,
            "mdin": None, "mdout": None, "mdcrd": None, "inpcrd": None,
            "expected_gap_ps": None, "gap_tolerance_ps": None, "notes": []}
    base.update(kw)
    return base


def _settings(**kw):
    base = {"global_prmtop": None, "hmr_prmtop": None, "initial_coordinates": None,
            "auto_link_restarts": True, "strict_validation": True,
            "allow_gaps": False, "use_relative_paths": True}
    base.update(kw)
    return base


def test_resolve_format_prefers_explicit_then_extension_then_default():
    assert core_bridge.resolve_format("x.csv", "toml") == "toml"
    assert core_bridge.resolve_format("x.yml", None) == "yaml"
    assert core_bridge.resolve_format("x.json", None) == "json"
    assert core_bridge.resolve_format(None, None) == "yaml"


def test_document_to_payload_omits_empties_and_strips_id(tmp_path):
    stages = [_stage(name="prod_001", role="production", mdin="prod_001.in")]
    payload = core_bridge.document_to_payload(stages, _settings(global_prmtop="sys.prmtop"),
                                              str(tmp_path))
    assert payload["global_prmtop"] == "sys.prmtop"
    assert payload["stages"] == [{"name": "prod_001", "stage_role": "production",
                                  "mdin": "prod_001.in"}]
    assert "id" not in payload["stages"][0]
    assert "hmr_prmtop" not in payload


def test_document_to_payload_keeps_absolute_when_relative_disabled(tmp_path):
    abs_in = str(tmp_path / "prod.in")
    stages = [_stage(name="prod", role="production", mdin=abs_in)]
    payload = core_bridge.document_to_payload(
        stages, _settings(use_relative_paths=False), str(tmp_path))
    assert payload["stages"][0]["mdin"] == abs_in


def test_save_document_byte_identical_to_write_manifest(tmp_path):
    stages = [_stage(name="min", role="minimization", mdin="min.in"),
              _stage(name="prod", role="production", mdin="prod.in",
                     expected_gap_ps=2.0, gap_tolerance_ps=0.5)]
    settings = _settings(global_prmtop="sys.prmtop")
    gui_path = tmp_path / "gui.yaml"
    warnings = core_bridge.save_document(stages, settings, str(tmp_path),
                                         str(gui_path), "yaml")
    assert warnings == []
    # Build the same payload independently and write via the core writer.
    payload = core_bridge.document_to_payload(stages, settings, str(tmp_path))
    ref_path = tmp_path / "ref.yaml"
    write_manifest(payload, str(ref_path), "yaml")
    assert gui_path.read_text(encoding="utf-8") == ref_path.read_text(encoding="utf-8")


def test_save_document_warns_csv_hmr(tmp_path):
    stages = [_stage(name="prod", mdin="prod.in")]
    settings = _settings(global_prmtop="sys.prmtop", hmr_prmtop="sys_hmr.prmtop")
    warnings = core_bridge.save_document(stages, settings, str(tmp_path),
                                         str(tmp_path / "p.csv"), "csv")
    assert any("HMR" in w for w in warnings)


def test_open_manifest_round_trips_globals_and_gaps(tmp_path):
    payload = {"global_prmtop": "sys.prmtop", "hmr_prmtop": "sys_hmr.prmtop",
               "stages": [{"name": "prod", "stage_role": "production",
                           "mdin": "prod.in",
                           "gaps": {"expected": 2.0, "tolerance": 0.5}}]}
    p = tmp_path / "m.yaml"
    write_manifest(payload, str(p), "yaml")
    result = core_bridge.open_manifest(str(p), str(tmp_path))
    assert result["settings_patch"]["global_prmtop"] == "sys.prmtop"
    assert result["settings_patch"]["hmr_prmtop"] == "sys_hmr.prmtop"
    assert len(result["stages"]) == 1
    s = result["stages"][0]
    assert s["name"] == "prod"
    assert s["role"] == "production"
    assert s["mdin"] == "prod.in"
    assert s["expected_gap_ps"] == 2.0
    assert s["gap_tolerance_ps"] == 0.5
    assert len(s["id"]) == 8


def test_preview_matches_save(tmp_path):
    stages = [_stage(name="prod", role="production", mdin="prod.in")]
    settings = _settings(global_prmtop="sys.prmtop")
    preview = core_bridge.preview_document(stages, settings, str(tmp_path), "json")
    saved = tmp_path / "p.json"
    core_bridge.save_document(stages, settings, str(tmp_path), str(saved), "json")
    assert preview["content"] == saved.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Task 3: discovery + HMR/normal topology split
# ---------------------------------------------------------------------------


def _touch(p):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")


def test_discover_one_stage_per_numbered_file(tmp_path):
    # Bug-1 parity: numbered production runs must NOT collapse to the last file.
    for i in (1, 2, 3):
        _touch(tmp_path / f"prod_{i:03d}.mdin")
        _touch(tmp_path / f"prod_{i:03d}.mdout")
    result = cb.discover(str(tmp_path), recursive=False)
    names = sorted(s["name"] for s in result["stages"])
    assert names == ["prod_001", "prod_002", "prod_003"]
    for s in result["stages"]:
        assert s["mdin"] is not None and s["mdout"] is not None
        assert len(s["id"]) == 8


def test_discover_skips_prmtop_only_groups(tmp_path):
    _touch(tmp_path / "system.prmtop")
    _touch(tmp_path / "min.mdin")
    result = cb.discover(str(tmp_path), recursive=False)
    names = [s["name"] for s in result["stages"]]
    assert names == ["min"]  # system.prmtop alone is not a stage
    assert all(s["prmtop"] is None for s in result["stages"])  # topology is global


def test_classify_topologies_warns_on_multiple(tmp_path):
    _touch(tmp_path / "a.prmtop")
    _touch(tmp_path / "b.prmtop")
    out = cb.classify_topologies(str(tmp_path), ["a.prmtop", "b.prmtop"])
    assert out["global_prmtop"] in ("a.prmtop", "b.prmtop")
    assert any("topology files found" in w for w in out["warnings"])


def test_classify_topologies_splits_hmr_via_monkeypatch(tmp_path, monkeypatch):
    """HMR split branch: one file is HMR, one is normal; assert correct routing."""

    class _Stub:
        def __init__(self, hmr_active):
            self.hmr_active = hmr_active

    def _fake_extract(path):
        basename = os.path.basename(path)
        return _Stub(hmr_active=(basename == "hmr.prmtop"))

    monkeypatch.setattr(core_bridge, "extract_prmtop_metadata", _fake_extract)

    out = core_bridge.classify_topologies(str(tmp_path), ["normal.prmtop", "hmr.prmtop"])
    assert out["hmr_prmtop"] == "hmr.prmtop"
    assert out["global_prmtop"] == "normal.prmtop"
    assert any("topology files found" in w for w in out["warnings"])
