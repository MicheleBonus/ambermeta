"""Checks against what AMBER recorded, and per-run findings that reach `--strict`.

Two gaps the application-note review found by running the bundled sample:

* **The chain was never compared with AMBER's own record.** `discover` chains runs by file
  order, and continuity reads the time stored in the restart a Step *declares*. A run that
  actually read a different restart -- its mdout's File Assignments block names it --
  therefore passed `validate --manifest --strict` with exit 0, and so did the fourth chunk
  of a chain whose third chunk had been deleted. The mdout header has parsed that block
  since before lineages existed; nothing compared it with the declared input.
* **Per-run problems never reached the exit code.** An mdin that disagrees with its mdout,
  a run that stopped before its completion marker, and a 4-fs time step on a topology
  with standard hydrogen masses were each at most a line in `stage.validation`: not in
  the text output of `validate --manifest`, not counted by `--strict`, and in the last
  case overwritten in the methods summary by an HMR flag inferred from the time step.

Most tests work on a copy of the sample whose topology has had its hydrogen masses raised
(`_hmr_copy`), because the sample as bundled pairs a 4-fs time step with standard
hydrogen masses -- a real finding on every run, which would otherwise mask the one each
test is about.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

SAMPLE = Path(__file__).resolve().parent / "data" / "amber" / "md_test_files"
RUNS = [f"ntp_prod_{i:04d}" for i in range(1, 6)]
TOPOLOGY = "CH3L1_HUMAN_6NAG.top"


# --------------------------------------------------------------------------- helpers


def _copy(tmp_path, drop=()):
    dst = tmp_path / "md"
    shutil.copytree(SAMPLE, dst)
    for name in drop:
        (dst / name).unlink()
    return dst


def _hmr_copy(tmp_path, drop=()):
    """The sample with every hydrogen at 3.024 amu, i.e. a repartitioned topology.

    Only the MASS section is touched: 1.008 is the hydrogen mass and appears nowhere else
    in that section, and the HMR label is read from hydrogen masses alone.
    """
    dst = _copy(tmp_path, drop)
    top = dst / TOPOLOGY
    text = top.read_text(encoding="utf-8")
    head, rest = text.split("%FLAG MASS", 1)
    mass, tail = rest.split("%FLAG", 1)
    assert "1.00800000E+00" in mass
    top.write_text(head + "%FLAG MASS" + mass.replace("1.00800000E+00", "3.02400000E+00")
                   + "%FLAG" + tail, encoding="utf-8")
    return dst


def _replace_in(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {path.name}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _record_input(mdout, recorded_basename):
    """Rewrite the INPCRD line of `mdout`'s File Assignments, keeping its padding."""
    lines = mdout.read_text(encoding="utf-8").splitlines(keepends=True)
    i = next(i for i, line in enumerate(lines) if line.startswith("| INPCRD:"))
    head, _, old = lines[i].rstrip("\n").rpartition("/")
    base = old.rstrip()
    assert len(recorded_basename) == len(base), "keep the field width"
    lines[i] = f"{head}/{recorded_basename}{old[len(base):]}\n"
    mdout.write_text("".join(lines), encoding="utf-8")


def _cut_before(path, marker):
    """Drop everything from the first line containing `marker` on: a run cut short."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    i = next(i for i, line in enumerate(lines) if marker in line)
    path.write_text("".join(lines[:i]), encoding="utf-8")


def _draft(directory):
    from ambermeta.gui.api.core_bridge import discover_draft
    return discover_draft(str(directory))["simulation"]


def _validate(directory, sim=None):
    from ambermeta.gui.api.core_bridge import validate_simulation
    sim = sim or _draft(directory)
    return sim, validate_simulation(sim, {"strict_validation": True}, str(directory))


def _findings(report, kind):
    return [s for s in report["suggestions"] if s["kind"] == kind]


def _step_id(sim, name):
    return next(s.id for p in sim.phases for s in p.steps if s.name == name)


def _cli(*argv):
    from ambermeta.cli import main
    return main([str(a) for a in argv])


def _write_manifest(directory):
    manifest = directory / "sim.yaml"
    assert _cli("discover", directory, "--write", manifest) == 0
    return manifest


# --------------------------------------------------------- starting structure (C2)


def test_discover_starts_from_the_input_the_first_run_recorded(tmp_path):
    """ntp_prod_0001's mdout names ntp_prod_0000.rst as INPCRD, and that file is here."""
    sim = _draft(_copy(tmp_path))
    assert sim.starting_structure == "ntp_prod_0000.rst"


def test_discover_keeps_the_spelling_of_the_recorded_starting_structure(tmp_path):
    """The comparison is case-insensitive where the file system is; the name written into
    the manifest is the file's own, or a manifest moved to Linux names a missing file."""
    directory = _copy(tmp_path)
    (directory / "ntp_prod_0000.rst").rename(directory / "Start_Prod_00.rst")
    _record_input(directory / "ntp_prod_0001.mdout", "Start_Prod_00.rst")
    assert _draft(directory).starting_structure == "Start_Prod_00.rst"


def test_discover_keeps_the_coordinate_file_when_the_recorded_input_is_absent(tmp_path):
    sim = _draft(_copy(tmp_path, drop=["ntp_prod_0000.rst"]))
    assert sim.starting_structure == "CH3L1_HUMAN_6NAG.crd"


# ------------------------------------------------------------ recorded input (C3)


def test_a_run_that_read_another_restart_than_declared_is_reported(tmp_path):
    directory = _hmr_copy(tmp_path)
    _record_input(directory / "ntp_prod_0004.mdout", "ntp_prod_0002.rst")
    sim, report = _validate(directory)
    found = _findings(report, "input_mismatch")
    assert [f["step_id"] for f in found] == [_step_id(sim, "ntp_prod_0004")]
    assert "ntp_prod_0002.rst" in found[0]["evidence"]
    assert "ntp_prod_0003.rst" in found[0]["evidence"]


def test_the_unmodified_sample_reads_what_it_declares(tmp_path):
    _, report = _validate(_hmr_copy(tmp_path))
    assert _findings(report, "input_mismatch") == []


def test_a_deleted_segment_shows_on_the_run_that_read_its_restart(tmp_path):
    directory = _hmr_copy(
        tmp_path, drop=[f"ntp_prod_0003.{ext}" for ext in ("mdin", "mdout", "rst")])
    sim, report = _validate(directory)
    found = _findings(report, "input_mismatch")
    assert [f["step_id"] for f in found] == [_step_id(sim, "ntp_prod_0004")]
    assert "ntp_prod_0003.rst" in found[0]["evidence"]


def test_a_clipped_recorded_path_is_never_compared(tmp_path):
    directory = _hmr_copy(tmp_path)
    mdout = directory / "ntp_prod_0004.mdout"
    lines = mdout.read_text(encoding="utf-8").splitlines(keepends=True)
    i = next(i for i, line in enumerate(lines) if line.startswith("| INPCRD:"))
    # No trailing blank: the value ran to the end of its field and may be cut short.
    lines[i] = "| INPCRD: /l/home/bonus/work/Projects/YKL-40/CH3L1_HUMAN_6NAG/prod/ntp_prod_00\n"
    mdout.write_text("".join(lines), encoding="utf-8")
    _, report = _validate(directory)
    assert _findings(report, "input_mismatch") == []


@pytest.mark.parametrize("recorded, declared, expected", [
    # A path from the machine the run was on: only the file name can be compared.
    ("/cluster/proj/prod/prod_0002.rst", "prod/prod_0002.rst", None),
    ("/cluster/proj/prod/prod_0001.rst", "prod/prod_0002.rst", "prod_0001.rst"),
    # A relative path that resolves here is compared as a file, not by name.
    ("prod_0002.rst", "prod/prod_0002.rst", None),
    ("../other/prod_0002.rst", "prod/prod_0002.rst", "other"),
])
def test_recorded_inputs_are_compared_by_file_where_they_resolve(
        tmp_path, recorded, declared, expected):
    from ambermeta.recorded_inputs import compare_recorded_input
    for rel in ("prod/prod_0001.rst", "prod/prod_0002.rst", "other/prod_0002.rst"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x", encoding="utf-8")
    run_directory = tmp_path / "prod"
    message = compare_recorded_input(str(tmp_path / declared), recorded, str(run_directory))
    if expected is None:
        assert message is None
    else:
        assert message is not None and expected in message


# ------------------------------------------------- per-run findings reach --strict (C4)


def test_a_run_without_a_completion_marker_is_reported_as_unfinished(tmp_path):
    directory = _hmr_copy(tmp_path)
    _cut_before(directory / "ntp_prod_0005.mdout", "A V E R A G E S")
    sim, report = _validate(directory)
    found = _findings(report, "unfinished_run")
    assert [f["step_id"] for f in found] == [_step_id(sim, "ntp_prod_0005")]


def test_finished_and_queued_runs_of_a_campaign_are_not_unfinished(sys021_tree):
    """Queued chunks have an mdin and no mdout: a status, not an unfinished run."""
    _, report = _validate(sys021_tree)
    assert _findings(report, "unfinished_run") == []


def test_an_mdin_that_disagrees_with_its_mdout_is_a_finding(tmp_path):
    directory = _hmr_copy(tmp_path)
    _replace_in(directory / "ntp_prod_0002.mdin", "nstlim = 5000000,", "nstlim = 4000000,")
    sim, report = _validate(directory)
    flagged = [f for f in _findings(report, "step_check") if "Step count" in f["evidence"]]
    assert [f["step_id"] for f in flagged] == [_step_id(sim, "ntp_prod_0002")]


def test_a_write_frequency_that_differs_from_the_mdout_is_a_finding(tmp_path):
    directory = _hmr_copy(tmp_path)
    _replace_in(directory / "ntp_prod_0002.mdin", "ntwx = 25000,", "ntwx = 5000,")
    sim, report = _validate(directory)
    flagged = [f for f in _findings(report, "step_check")
               if "write frequency" in f["evidence"]]
    assert [f["step_id"] for f in flagged] == [_step_id(sim, "ntp_prod_0002")]


def test_the_hmr_sample_has_no_per_run_findings(tmp_path):
    _, report = _validate(_hmr_copy(tmp_path))
    kinds = ("step_check", "unfinished_run", "input_mismatch")
    assert [s for s in report["suggestions"] if s["kind"] in kinds] == []


def test_strict_validation_fails_on_a_per_run_finding(tmp_path, capsys):
    directory = _hmr_copy(tmp_path)
    _replace_in(directory / "ntp_prod_0002.mdin", "nstlim = 5000000,", "nstlim = 4000000,")
    manifest = _write_manifest(directory)
    capsys.readouterr()
    assert _cli("validate", "--manifest", manifest, "--strict") == 1
    assert "Step count differs" in capsys.readouterr().out


def test_strict_validation_passes_the_hmr_sample(tmp_path):
    manifest = _write_manifest(_hmr_copy(tmp_path))
    assert _cli("validate", "--manifest", manifest, "--strict") == 0


def test_strict_recursive_plan_fails_on_an_unfinished_run(tmp_path):
    directory = _hmr_copy(tmp_path)
    _cut_before(directory / "ntp_prod_0005.mdout", "A V E R A G E S")
    assert _cli("plan", directory, "--recursive", "--strict") == 1


def test_strict_recursive_plan_passes_the_hmr_sample(tmp_path):
    """The scan types the single-frame .crd as a trajectory by its extension. An ASCII
    trajectory states no atom count, and that is not a count of zero."""
    assert _cli("plan", _hmr_copy(tmp_path), "--recursive", "--strict") == 0


# ----------------------------------------------------- HMR and box in the outputs (C1)


def test_a_time_step_above_2_fs_with_standard_hydrogen_masses_is_a_finding(tmp_path):
    sim, report = _validate(_copy(tmp_path))
    flagged = {f["step_id"] for f in _findings(report, "step_check")
               if "hydrogen masses" in f["evidence"]}
    assert flagged == {_step_id(sim, name) for name in RUNS}


def _methods(directory):
    from ambermeta.gui.api.core_bridge import _flatten_simulation, build_protocol
    sim = _draft(directory)
    protocol = build_protocol(_flatten_simulation(sim), {}, str(directory))
    return {s["name"]: s for s in protocol.to_methods_dict()["stages"]}


def test_the_methods_summary_takes_hmr_from_the_topology_masses(tmp_path):
    for name, stage in _methods(_copy(tmp_path)).items():
        composition = stage["system"]["composition"]
        assert composition["hmr_active"] is False, name
        assert "hmr_inferred_from_timestep" not in composition, name


def test_the_methods_summary_reports_the_box_of_the_coordinates_a_run_read(tmp_path):
    """The topology's box is the one tLEaP wrote before equilibration (98.3 A along x);
    the restart ntp_prod_0002 read holds the simulated box (about 91.8 A)."""
    box = _methods(_copy(tmp_path))["ntp_prod_0002"]["system"]["box"]
    assert box["dimensions"][0] == pytest.approx(91.8, abs=0.5)
    assert box["source"] == "input coordinates"
