"""What the declared members agree and disagree about, and what that costs.

Design decision 5: **different `natom`, or minimisation mixed with dynamics, is an error
and exits 1.** Everything else — `temp0`, `cut`, `ntt`, `ntp`, `dt`, a shared resolved seed
— is a finding, escalated by the existing `--strict`.

Design decision 4 governs the wording: the output states graph facts and never a
statistical property. "3 steps read the restart written by st_7 and carry 3 distinct
resolved seeds" is a claim about files. Whether that makes them independent samples is not
a question any file inspection can answer, so nothing here says it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ambermeta.cli import main
from ambermeta.gui.api import routes
from ambermeta.lineages import coherence, varying_axis
from ambermeta.mdout_header import MdoutHeader
from ambermeta.protocol import SimulationStage


def _stage(name, lineage=None, *, cntrl=None, natoms=None, ig=None,
           step_id=None, parent_id=None):
    """A stage carrying only what coherence reads: the raw mdin echo, the mdout's atom
    count, the resolved seed and the producer edge."""
    stage = SimulationStage(name=name, lineage=lineage,
                            step_id=step_id, parent_id=parent_id)
    if cntrl is not None:
        stage.mdin = SimpleNamespace(details=SimpleNamespace(cntrl_parameters=dict(cntrl)))
    if natoms is not None:
        stage.mdout = SimpleNamespace(details=SimpleNamespace(natoms=natoms))
    if ig is not None:
        stage.mdout_header = MdoutHeader(resolved_ig=ig)
    return stage


MD = {"imin": 0, "dt": 0.002, "temp0": 300.0, "cut": 9.0, "ntt": 3, "ntp": 1}


def _replicas(**overrides):
    """Three members running the same thing, with per-member `&cntrl` overrides."""
    return [_stage(f"{tag}/prod", tag, cntrl={**MD, **overrides.get(tag, {})})
            for tag in ("rep1", "rep2", "rep3")]


def _kinds(findings):
    return [(f.severity, f.kind) for f in findings]


# ---------------------------------------------------------------------------
# Silence is the default
# ---------------------------------------------------------------------------

def test_an_untagged_document_is_never_compared():
    """Every path in this feature is a no-op for a document that declares nothing, and
    coherence is the one most able to invent an opinion about it."""
    stages = [_stage("prod_0001", cntrl=MD), _stage("prod_0002", cntrl={**MD, "temp0": 310.0})]
    assert coherence(stages) == []
    assert varying_axis(stages) == {}


def test_one_declared_member_beside_untagged_runs_is_not_a_comparison():
    stages = [_stage("common/equil", cntrl=MD), _stage("rep1/prod", "rep1", cntrl=MD)]
    assert coherence(stages) == []


def test_members_that_agree_report_nothing():
    assert coherence(_replicas()) == []


# ---------------------------------------------------------------------------
# Category errors: not runs of the same thing
# ---------------------------------------------------------------------------

def test_members_holding_different_atom_counts_are_an_error():
    stages = [_stage("rep1/prod", "rep1", cntrl=MD, natoms=64528),
              _stage("rep2/prod", "rep2", cntrl=MD, natoms=64528),
              _stage("rep3/prod", "rep3", cntrl=MD, natoms=12000)]
    error, = [f for f in coherence(stages) if f.severity == "error"]
    assert error.kind == "atom_count"
    assert "rep3: 12000" in error.message


def test_minimisation_mixed_with_dynamics_is_an_error():
    stages = [_stage("rep1/prod", "rep1", cntrl=MD),
              _stage("rep2/min", "rep2", cntrl={"imin": 1})]
    error, = [f for f in coherence(stages) if f.severity == "error"]
    assert error.kind == "run_type"
    assert "rep2" in error.message


def test_a_member_that_minimises_and_then_runs_is_not_an_error():
    """The normal shape: every member minimises first. The error is a member that ran *no*
    dynamics at all beside one that did, not the presence of a minimisation step."""
    stages = [_stage("rep1/min", "rep1", cntrl={"imin": 1}),
              _stage("rep1/prod", "rep1", cntrl=MD),
              _stage("rep2/min", "rep2", cntrl={"imin": 1}),
              _stage("rep2/prod", "rep2", cntrl=MD)]
    assert [f for f in coherence(stages) if f.severity == "error"] == []


# ---------------------------------------------------------------------------
# Differences the user may well have meant
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key,value", [
    ("temp0", 310.0), ("cut", 10.0), ("ntt", 1), ("ntp", 0), ("dt", 0.004)])
def test_each_compared_parameter_becomes_a_warning(key, value):
    stages = _replicas(rep2={key: value})
    warning, = [f for f in coherence(stages) if f.severity == "warning"]
    assert warning.kind == "parameter"
    assert f"differ in {key}" in warning.message
    assert varying_axis(stages)[key]["rep2"] == value


def test_a_parameter_no_member_states_is_not_an_axis():
    """The `target_temp` trap, pinned. `MdinMetadata.target_temp` defaults to 300.0 when
    the mdin omits `temp0`, so comparing the normalized field reports agreement between
    two runs that never declared a temperature. The raw `cntrl_parameters` echo is read
    instead, and an absent key stays absent."""
    without = {k: v for k, v in MD.items() if k != "temp0"}
    stages = [_stage(f"{tag}/prod", tag, cntrl=without) for tag in ("rep1", "rep2")]
    assert "temp0" not in varying_axis(stages)
    assert coherence(stages) == []


def test_a_member_with_no_readable_mdin_contributes_nothing():
    """A document of mdouts with no mdins is a legitimate discover result — a run group
    needs an mdin *or* an mdout. Inferring `ntt` from the mdout's thermostat name would be
    a different fact wearing this one's label."""
    stages = [_stage("rep1/prod", "rep1", cntrl=MD), _stage("rep2/prod", "rep2")]
    assert varying_axis(stages) == {}


def test_silence_is_never_a_category_error():
    """A member that said nothing did not say it ran no dynamics.

    Reading an absent mdin as `imin != 0` made a **fatal** claim out of a file that was
    merely missing — and on `plan`, which is fault-tolerant about unreadable files by
    design, it turned a skipped file into exit 1 without `--strict`. That is Spec 1's
    guarantee, undone by a `.get()` default.
    """
    stages = [_stage("rep1/prod", "rep1", cntrl=MD), _stage("rep2/prod", "rep2")]
    assert coherence(stages) == []


def test_an_absent_imin_is_amber_s_own_default_of_dynamics():
    """`imin` omitted means `imin = 0`. A member that omits it has not opted out of
    dynamics, so it must not be reported against one that states it."""
    stated = {k: v for k, v in MD.items() if k != "imin"}
    stages = [_stage("rep1/prod", "rep1", cntrl=MD),
              _stage("rep2/prod", "rep2", cntrl=stated)]
    assert [f for f in coherence(stages) if f.kind == "run_type"] == []


def test_the_same_number_typed_two_ways_is_not_a_difference():
    """`cntrl_parameters` is a raw echo, so one member's `temp0 = 300` and another's
    `temp0 = 300.0` arrive as an int and a float. Comparing their reprs made an axis out
    of a decimal point, and under `--strict` failed the run over it."""
    stages = [_stage("rep1/prod", "rep1", cntrl={**MD, "temp0": 300}),
              _stage("rep2/prod", "rep2", cntrl={**MD, "temp0": 300.0})]
    assert varying_axis(stages) == {}
    assert coherence(stages) == []


# ---------------------------------------------------------------------------
# Seeds, scoped to the branch point
# ---------------------------------------------------------------------------

def _fan_out(*seeds):
    """One shared equilibration, then one production per member reading its restart."""
    stages = [_stage("common/equil", cntrl=MD, step_id="st_e")]
    for i, seed in enumerate(seeds, start=1):
        stages.append(_stage(f"rep{i}/prod", f"rep{i}", cntrl=MD,
                             step_id=f"st_{i}", parent_id="st_e", ig=seed))
    return stages


def test_distinct_seeds_off_one_restart_are_stated_as_a_graph_fact():
    finding, = [f for f in coherence(_fan_out(1, 2, 3)) if f.kind == "fan_out"]
    assert finding.severity == "info"
    assert finding.message == (
        "3 steps read the restart written by common/equil and carry 3 distinct "
        "resolved seeds.")
    # Decision 4: never a statistical claim, whatever the seeds say.
    assert "independent" not in finding.message and "ensemble" not in finding.message


def test_a_repeated_seed_off_one_restart_is_a_warning():
    """Children of one restart inherit identical coordinates *and* velocities, so the seed
    is the only thing left to separate them. Two that share it are the same trajectory."""
    warning, = [f for f in coherence(_fan_out(7, 7, 9)) if f.kind == "seed"]
    assert warning.severity == "warning"
    assert "only 2 distinct resolved seed(s)" in warning.message


def test_an_unstated_seed_is_reported_as_unknown_not_as_shared():
    """The whole point of reading the mdout header rather than the mdin. Absence must not
    read as agreement — that would say a campaign's replicas share one seed."""
    stages = _fan_out(7, 9)
    stages[2].mdout_header = None
    finding, = [f for f in coherence(stages) if f.kind in ("fan_out", "seed")]
    assert finding.severity == "info"
    assert "state no resolved seed" in finding.message


def test_members_that_share_no_producer_are_not_compared_on_seeds():
    """Repeating a seed between two runs with no common ancestor says nothing, so it is
    not said."""
    stages = [_stage("rep1/prod", "rep1", cntrl=MD, step_id="a", ig=7),
              _stage("rep2/prod", "rep2", cntrl=MD, step_id="b", ig=7)]
    assert [f for f in coherence(stages) if f.kind in ("seed", "fan_out")] == []


# ---------------------------------------------------------------------------
# What it costs: the exit code and the wire
# ---------------------------------------------------------------------------

MISMATCHED = """\
version: 2
simulation:
  topologies: [{ id: top, path: wt.prmtop, kind: normal }]
phases:
  - { id: ph, name: Production, role: production, order: 0 }
steps:
  - { id: s1, name: rep1/prod, phase: ph, order: 0, lineage: rep1, mdin: rep1.in }
  - { id: s2, name: rep2/prod, phase: ph, order: 1, lineage: rep2, mdin: rep2.in }
"""

MDIN = "prod\n &cntrl\n  imin = 0, nstlim = 1000, dt = 0.002, temp0 = {t},\n /\n"


@pytest.fixture
def differing_members(tmp_path):
    (tmp_path / "sim.yaml").write_text(MISMATCHED, encoding="utf-8")
    (tmp_path / "rep1.in").write_text(MDIN.format(t=300.0), encoding="utf-8")
    (tmp_path / "rep2.in").write_text(MDIN.format(t=310.0), encoding="utf-8")
    return tmp_path


def test_a_temperature_difference_is_printed_and_escalated_by_strict(
        differing_members, capsys):
    manifest = str(differing_members / "sim.yaml")
    assert main(["validate", "--manifest", manifest]) == 0
    out = capsys.readouterr().out
    assert "Lineage coherence:" in out
    assert "Members differ in temp0" in out
    assert main(["validate", "--manifest", manifest, "--strict"]) == 1


def test_plan_reports_the_same_difference(differing_members, capsys):
    assert main(["plan", str(differing_members), "-m",
                 str(differing_members / "sim.yaml")]) == 0
    assert "Members differ in temp0" in capsys.readouterr().out


DIFFERING_MDIN = "prod\n &cntrl\n  imin = 0, nstlim = 1000, dt = 0.002, temp0 = {t},\n /\n"


@pytest.fixture
def differing_tree(tmp_path):
    """The same disagreement, discoverable from a directory rather than a manifest."""
    for rep, temp in (("rep1", 300.0), ("rep2", 310.0)):
        run = tmp_path / rep
        run.mkdir()
        (run / "prod_0001.mdin").write_text(DIFFERING_MDIN.format(t=temp), encoding="utf-8")
    return tmp_path


def test_the_scan_path_reports_coherence_too(differing_tree, capsys):
    """`plan --recursive` has stages, and coherence needs nothing else. Leaving it to the
    manifest path meant one directory passed one plan mode and failed the other on the
    same files — the disagreement this whole task exists to remove."""
    assert main(["plan", "--recursive", str(differing_tree)]) == 0
    out = capsys.readouterr().out
    assert "Lineage coherence:" in out
    assert "Members differ in temp0" in out
    assert main(["plan", "--recursive", "--strict", str(differing_tree)]) == 1


MDOUT_ONLY = "|   MDOUT: x\n   1.  RESOURCE   USE:\n NATOM  =   100\n   4.  RESULTS\n"


def test_a_member_that_kept_only_its_mdout_is_not_an_error(tmp_path, capsys):
    """The reachable form of the worst defect this feature can have.

    `discover` counts a run group holding an mdin **or** an mdout, so a replica whose mdin
    was tidied away is a perfectly ordinary tree — and reading its silence as `imin != 0`
    made `plan` exit 1 on it, without `--strict`, on the strength of a file that simply was
    not there. That is a fabricated claim and a breach of the fault tolerance Spec 1 built.
    """
    for rep in ("rep1", "rep2", "rep3"):
        run = tmp_path / rep
        run.mkdir()
        if rep == "rep3":
            (run / "prod_0001.mdout").write_text(MDOUT_ONLY, encoding="utf-8")
        else:
            (run / "prod_0001.mdin").write_text(MDIN.format(t=300.0), encoding="utf-8")
    assert main(["plan", "--recursive", str(tmp_path)]) == 0
    assert "Members mix minimisation with dynamics" not in capsys.readouterr().out


def test_a_category_error_fails_the_scan_path_without_strict(tmp_path, capsys):
    """Decision 5: no flag makes two members that ran different things one experiment."""
    for rep, imin in (("rep1", 0), ("rep2", 1)):
        run = tmp_path / rep
        run.mkdir()
        (run / "prod_0001.mdin").write_text(
            f"run\n &cntrl\n  imin = {imin}, nstlim = 1000, dt = 0.002,\n /\n",
            encoding="utf-8")
    assert main(["plan", "--recursive", str(tmp_path)]) == 1
    assert "Members mix minimisation with dynamics" in capsys.readouterr().out


def test_the_report_carries_the_findings_and_ok_reflects_them(differing_members):
    routes.set_base_directory(str(differing_members))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    client = TestClient(app)
    assert client.post("/api/document/open",
                       json={"path": "sim.yaml"}).status_code == 200
    body = client.post("/api/validate").json()
    kinds = [(f["severity"], f["kind"]) for f in body["coherence"]]
    assert ("warning", "parameter") in kinds
    # A warning is not an error: `ok` still turns on whether anything is actually broken.
    assert body["ok"] is True
