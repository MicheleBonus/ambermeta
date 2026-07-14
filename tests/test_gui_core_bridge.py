# tests/test_gui_core_bridge.py
from ambermeta.gui.api import core_bridge

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


# ---------------------------------------------------------------------------
# Task 4: validation report, file metadata, restart chain
# ---------------------------------------------------------------------------

_MDIN = "prod\n&cntrl\n  imin=0, nstlim=1000, dt=0.002, ntb=2,\n/\n"


def test_file_metadata_returns_real_details(tmp_path):
    # mdin is plain text and always parseable — no binary sample file needed.
    mdin = tmp_path / "prod.mdin"
    mdin.write_text(_MDIN, encoding="utf-8")
    out = cb.file_metadata(str(mdin))
    assert out["kind"] == "mdin"
    assert isinstance(out["details"], dict)
    assert "dt" in out["details"]  # real parsed field, not a dataclass-as-dict crash


def test_build_validation_report_flags_missing_file(tmp_path):
    stages = [{"id": "a1", "name": "min", "role": "minimization",
               "prmtop": None, "mdin": "does_not_exist.in", "mdout": None,
               "mdcrd": None, "inpcrd": None, "expected_gap_ps": None,
               "gap_tolerance_ps": None, "notes": []}]
    settings = _settings(strict_validation=True)
    report = cb.build_validation_report(stages, settings, str(tmp_path))
    assert report["ok"] is False
    issue = report["stage_issues"][0]
    assert issue["name"] == "min"
    assert any("does_not_exist.in" in e for e in issue["errors"])
    assert report["totals"]["stage_count"] == 1


def test_build_validation_report_ok_when_no_files(tmp_path):
    # An empty stage with no referenced files has no missing-file errors.
    stages = [{"id": "a1", "name": "s", "role": "", "prmtop": None, "mdin": None,
               "mdout": None, "mdcrd": None, "inpcrd": None, "expected_gap_ps": None,
               "gap_tolerance_ps": None, "notes": []}]
    report = cb.build_validation_report(stages, _settings(), str(tmp_path))
    assert report["stage_issues"][0]["ok"] is True
