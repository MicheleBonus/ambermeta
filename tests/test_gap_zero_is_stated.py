"""A stated gap of 0 ps, or a tolerance of 0 ps, is a statement, not an absence.

The manifest reader took `gaps.expected` and `gaps.tolerance` with `or`, so a 0 fell
through to "not stated": `expected: 0` became no expectation at all (and a real gap
became "Gap detected without stated expectation"), and `tolerance: 0` became the default
window of max(0.1 ps, half a frame interval) -- 5 ps for 10-ps frames -- so a gap the user
asked to have flagged passed. The GUI sends exactly these zeros when someone types 0 into
a step's Continuity fields, and `validate --manifest` / `plan -m` read the same way.
"""
from __future__ import annotations

from types import SimpleNamespace

import ambermeta.protocol as protocol
from ambermeta.protocol import auto_discover


def _parser_by_file(details_by_name):
    class _Parser:
        def __init__(self, filename):
            self.filename = filename

        def parse(self):
            name = self.filename.replace("\\", "/").rsplit("/", 1)[-1]
            return SimpleNamespace(details=SimpleNamespace(**details_by_name[name]),
                                   filename=self.filename)

    return _Parser


def _two_stages(tmp_path, monkeypatch, gaps, prev_end=10.0, next_start=10.0, avg_dt=None):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()
    (stage_dir / "stage1.mdcrd").write_text("")
    (stage_dir / "stage2.rst").write_text("")
    mdcrd = {"time_end": prev_end}
    if avg_dt is not None:
        mdcrd["avg_dt"] = avg_dt
    monkeypatch.setattr(protocol, "MdcrdParser", _parser_by_file({"stage1.mdcrd": mdcrd}))
    monkeypatch.setattr(protocol, "InpcrdParser",
                        _parser_by_file({"stage2.rst": {"time": next_start}}))
    manifest = [
        {"name": "stage1", "files": {"mdcrd": "stage1.mdcrd"}},
        {"name": "stage2", "files": {"inpcrd": "stage2.rst"}, "gaps": gaps},
    ]
    return auto_discover(str(stage_dir), manifest=manifest).stages[1]


def test_an_expected_gap_of_zero_is_kept(tmp_path, monkeypatch):
    stage = _two_stages(tmp_path, monkeypatch, {"expected": 0, "tolerance": 2})

    assert stage.expected_gap_ps == 0.0
    assert stage.gap_tolerance_ps == 2.0
    assert any("within expected window (0±2 ps)" in n for n in stage.continuity)


def test_a_gap_against_an_expected_zero_is_measured_not_unexpected(tmp_path, monkeypatch):
    stage = _two_stages(tmp_path, monkeypatch, {"expected": 0, "tolerance": 0.5},
                        prev_end=10.0, next_start=13.0)

    assert any("exceeds expected 0 ps" in n for n in stage.continuity)
    assert not any("without stated expectation" in n for n in stage.continuity)


def test_a_tolerance_of_zero_is_not_widened_to_the_default(tmp_path, monkeypatch):
    # 10-ps frames make the default window 5 ps wide, which would swallow this 3-ps gap.
    stage = _two_stages(tmp_path, monkeypatch, {"expected": 0, "tolerance": 0},
                        prev_end=10.0, next_start=13.0, avg_dt=10.0)

    assert stage.gap_tolerance_ps == 0.0
    assert any("exceeds expected 0 ps" in n for n in stage.continuity)


def test_a_tolerance_of_zero_still_allows_float_noise(tmp_path, monkeypatch):
    # Frame times are single precision in NetCDF; an exact match arrives a hair off.
    stage = _two_stages(tmp_path, monkeypatch, {"expected": 0, "tolerance": 0},
                        prev_end=10.0, next_start=10.0 + 1e-9)

    assert any("within expected window (0±0 ps)" in n for n in stage.continuity)


def test_the_expected_ps_spelling_of_zero_is_kept_too(tmp_path, monkeypatch):
    stage = _two_stages(tmp_path, monkeypatch, {"expected_ps": 0, "tolerance_ps": 0})

    assert stage.expected_gap_ps == 0.0
    assert stage.gap_tolerance_ps == 0.0
