# tests/test_gui_core_bridge_sim.py
import json
from ambermeta.gui.api import core_bridge
from ambermeta.simulation import Simulation, Phase, Step, Topology


def _sim():
    return Simulation(
        topologies=[Topology(id="t0", path="wt.prmtop", kind="normal")],
        starting_structure="wt.inpcrd",
        phases=[Phase(id="p0", name="Min", role="minimization",
                      steps=[Step(id="s0", name="min", topology="t0", mdin="min.in")])],
    )


def test_open_v1_manifest_migrates(tmp_path):
    v1 = {"global_prmtop": "wt.prmtop",
          "stages": [{"name": "min", "stage_role": "minimization", "mdin": "min.in"},
                     {"name": "prod_001", "stage_role": "production", "mdin": "prod_001.in"}]}
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(v1))
    sim = core_bridge.open_simulation(str(path), str(tmp_path))
    assert sim.version == 2
    assert [p.role for p in sim.phases] == ["minimization", "production"]


def test_save_then_preview_round_trip(tmp_path):
    sim = _sim()
    target = tmp_path / "out.json"
    warnings = core_bridge.save_simulation(sim, str(tmp_path), str(target), "json")
    assert warnings == []
    reloaded = core_bridge.open_simulation(str(target), str(tmp_path))
    assert reloaded == sim
    out = core_bridge.preview_simulation(sim, str(tmp_path), "yaml")
    assert "phases" in out["content"] and out["warnings"] == []


def test_build_suggestions_flags_missing_run_and_hmr():
    sim = Simulation(
        topologies=[Topology(id="t0", path="wt.prmtop", kind="normal"),
                    Topology(id="t1", path="wt_hmr.prmtop", kind="hmr")],
        starting_structure="wt.inpcrd",
        phases=[Phase(id="p0", name="Production", role="production", steps=[
            Step(id="a", name="prod_0001", topology="t1"),
            Step(id="b", name="prod_0003", topology="t1")])],
    )
    sug = core_bridge.build_suggestions(sim, "/base")
    kinds = {s["kind"] for s in sug}
    assert "missing_run" in kinds        # prod_0002 absent
    assert "topology_confirm" in kinds   # two topologies, one HMR
    assert "starting_structure" in kinds and "role_guess" in kinds
    miss = next(s for s in sug if s["kind"] == "missing_run")
    assert "2" in miss["evidence"]
    assert miss["base"] == "prod"
    assert miss["missing"] == [2]


def test_continuity_gap_suggestions_are_step_scoped():
    # Driven by the structured per-stage `continuity` list, not fuzzy warning text.
    flat = [{"step_id": "a"}, {"step_id": "b"}]
    stage_issues = [{"continuity": []},
                    {"continuity": ["Observed gap 20 ps exceeds expected 5 ps."]}]
    out = core_bridge._continuity_gap_suggestions(flat, stage_issues)
    assert len(out) == 1
    assert out[0]["step_id"] == "b"
    assert "20" in out[0]["evidence"]

    # A general (non-continuity) warning must NOT produce a continuity suggestion:
    # the classifier reads `continuity`, never `warnings`.
    non_continuity = [{"step_id": "a"}, {"step_id": "b"}]
    non_continuity_issues = [{"continuity": [], "warnings": []},
                             {"continuity": [],
                              "warnings": ["Atom count mismatch across topology and coordinates."]}]
    out2 = core_bridge._continuity_gap_suggestions(non_continuity, non_continuity_issues)
    assert out2 == []


def test_continuity_gap_surfaces_note_without_ps_substring():
    # Regression: the real gap warning "Gap detected without stated expectation…" has no
    # "ps" substring; the old text-matcher silently dropped it. It must now surface.
    flat = [{"step_id": "a"}, {"step_id": "b"}]
    stage_issues = [{"continuity": []},
                    {"continuity": ["Gap detected without stated expectation; verify continuity."]}]
    out = core_bridge._continuity_gap_suggestions(flat, stage_issues)
    assert len(out) == 1 and out[0]["step_id"] == "b"


def test_continuity_gap_ignores_healthy_and_info_notes():
    # A satisfied transition ("within expected window") is INFO-prefixed at the source and
    # excluded upstream; even if one slips through, the classifier drops INFO defensively.
    flat = [{"step_id": "a"}, {"step_id": "b"}]
    stage_issues = [{"continuity": []},
                    {"continuity": ["INFO: Observed gap 5 ps is within expected window (5±1 ps)."]}]
    out = core_bridge._continuity_gap_suggestions(flat, stage_issues)
    assert out == []


def test_discover_draft_on_real_fixtures(sample_md_data_dir):
    out = core_bridge.discover_draft(str(sample_md_data_dir), recursive=False)
    sim = out["simulation"]
    # the .top topology is in the pool
    assert any(t.path.endswith(".top") for t in sim.topologies)
    # ntp_prod_000X.mdin/.mdout runs became steps
    step_names = [s.name for p in sim.phases for s in p.steps]
    assert any(n.startswith("ntp_prod_000") for n in step_names)
    # the single-frame .crd is picked as the starting structure, not a run
    assert sim.starting_structure and sim.starting_structure.endswith(".crd")
    assert not any(n.endswith("6NAG") for n in step_names)
    # first step reads the starting structure; a later one chains from a step
    flat = [s for p in sim.phases for s in p.steps]
    assert flat[0].input_coords.source == "starting_structure"
    if len(flat) > 1:
        assert flat[1].input_coords.source == "step"
        assert flat[1].input_coords.path   # resolved previous-run restart, for continuity
    assert isinstance(out["suggestions"], list)


def test_validate_simulation_reports_missing_files_and_suggestions(tmp_path):
    (tmp_path / "prod_0001.in").write_text("&cntrl\nimin=0, nstlim=1000, dt=0.002,\n/\n")
    sim = Simulation(
        topologies=[Topology(id="t0", path="wt.prmtop", kind="normal")],
        phases=[Phase(id="p0", name="Production", role="production", steps=[
            Step(id="a", name="prod_0001", topology="t0", mdin="prod_0001.in"),
            Step(id="b", name="prod_0003", topology="t0", mdin="prod_0003.in")])],
    )
    settings = {"strict_validation": True, "allow_gaps": False}
    report = core_bridge.validate_simulation(sim, settings, str(tmp_path))
    assert "stage_issues" in report and "suggestions" in report
    # prod_0003.in and the topology don't exist -> missing-file errors surface
    all_errors = [e for si in report["stage_issues"] for e in si["errors"]]
    assert any("missing" in e for e in all_errors)
    assert any(s["kind"] == "missing_run" for s in report["suggestions"])


def test_read_file_head_truncates(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("A" * 10000)
    out = core_bridge.read_file_head(str(f), max_bytes=100)
    assert out["truncated"] is True and len(out["content"]) == 100


def test_dead_flat_functions_are_gone():
    assert not hasattr(core_bridge, "discover")          # replaced by discover_draft
    assert not hasattr(core_bridge, "classify_topologies")
    assert not hasattr(core_bridge, "open_manifest")
