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


# The shape the within-member check exists for: two independent campaigns that happen to
# share member labels. `apo/01..03` beside `holo/01..03` reconciles into THREE members, each
# holding one apo run and one holo run -- the accepted limitation the Task 6 ruling recorded
# ("deliberate parallel arms with distinct run names (apo/holo, wt/mut) have disjoint bases
# and still merge"), whose SILENCE was not accepted.
#
# The run stems are `apo_prod` / `holo_prod`, NOT a shared `prod`, and that is load-bearing
# rather than decorative: arms that share a run base fail the disjointness gate and the
# inference refuses them outright (verified -- `infer_lineages_from_layout` returns `{}`).
# Distinct run names are the shape that actually reaches this code, so the fixture uses it.
_APO_ATOMS, _HOLO_ATOMS = 50000, 50800


def _apo_holo(*, merged: bool):
    """The same six runs, grouped two ways.

    `merged=True` is what `infer_lineages_from_layout` produces on this tree: the replica
    index names the member, so `apo/01` and `holo/01` land in member `01`.
    `merged=False` is the grouping a user would have declared by hand, where the SYSTEM
    names the member. Same stages, same atom counts, different `lineage` strings -- which is
    what makes the pair a controlled comparison of the grouping alone.
    """
    stages = []
    for index in ("01", "02", "03"):
        for system, natoms in (("apo", _APO_ATOMS), ("holo", _HOLO_ATOMS)):
            stages.append(_stage(f"{system}/{index}/{system}_prod",
                                 index if merged else system,
                                 cntrl=MD, natoms=natoms))
    return stages


def test_a_member_holding_two_systems_is_an_error():
    """Measured before this check existed: the CORRECT grouping raised
    `error atom_count -- Members do not hold the same number of atoms (apo: 50000;
    holo: 50800)` and the MERGED one raised nothing at all.

    The cross-member check disabled itself on exactly the shape that needed it: it admits
    only tags holding ONE distinct atom count, so every merged member dropped out of the
    comparison rather than being reported. A merge the tool makes on its own must not be
    able to switch off the check that would have caught it.
    """
    error, = [f for f in coherence(_apo_holo(merged=True)) if f.severity == "error"]
    assert error.kind == "atom_count"
    assert "within one member" in error.message
    # Names the member and both counts, so the reader can see WHICH runs disagree.
    assert "01: 50000, 50800" in error.message
    assert "02: 50000, 50800" in error.message


def test_the_correctly_grouped_version_of_the_same_runs_still_reports_the_systems():
    """The control half. Same six stages, grouped by system instead of by index: the
    cross-member check is the one that fires, with its own wording, and the new
    within-member check stays quiet because each member really does hold one system.

    Without this, a within-member check that fired indiscriminately -- or a cross-member
    one broken while adding it -- would look identical to a correct implementation.
    """
    error, = [f for f in coherence(_apo_holo(merged=False)) if f.severity == "error"]
    assert error.kind == "atom_count"
    assert "within one member" not in error.message
    assert "apo: 50000" in error.message and "holo: 50800" in error.message


def test_a_mixed_member_does_not_mask_a_genuine_cross_member_difference():
    """Both checks are appended, neither short-circuits the other. `rep1` disagrees with
    itself while `rep2` and `rep3` each hold one count and disagree with each other -- two
    distinct facts about one document, and reporting only the first would hide a real
    category error behind a grouping complaint."""
    stages = [_stage("rep1/a", "rep1", cntrl=MD, natoms=50000),
              _stage("rep1/b", "rep1", cntrl=MD, natoms=50800),
              _stage("rep2/prod", "rep2", cntrl=MD, natoms=64528),
              _stage("rep3/prod", "rep3", cntrl=MD, natoms=12000)]
    errors = [f for f in coherence(stages) if f.kind == "atom_count"]
    assert len(errors) == 2
    assert "within one member" in errors[0].message
    assert "rep2: 64528" in errors[1].message and "rep3: 12000" in errors[1].message
    # The mixed member is absent from the cross-member line: it has no single value to
    # compare, which is what the first finding says.
    assert "rep1" not in errors[1].message


def test_one_declared_member_holding_two_systems_stays_silent():
    """`coherence` compares members. A single declared member is not a claim that anything
    matches anything, and the `len(members) < 2` gate covers the new check too -- so this
    document reports exactly what it reported before, which is nothing."""
    stages = [_stage("only/a", "only", cntrl=MD, natoms=50000),
              _stage("only/b", "only", cntrl=MD, natoms=50800)]
    assert coherence(stages) == []


def test_a_member_whose_runs_agree_on_atoms_raises_nothing_new():
    """The ordinary case, and the one every existing campaign is: several runs per member,
    all of one system. Chunked production would otherwise raise this on every project."""
    stages = [_stage(f"{tag}/prod_{i}", tag, cntrl=MD, natoms=64528)
              for tag in ("rep1", "rep2") for i in (1, 2, 3)]
    assert coherence(stages) == []


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


def test_the_merged_apo_holo_tree_is_tagged_and_then_reported_on(tmp_path, capsys):
    """End to end, from files on disk: `plan --recursive` tags the tree AND says the tags
    are wrong.

    Every other test in this section builds `SimulationStage` objects by hand, so the path
    from an mdout's `RESOURCE USE` block to a finding a user reads had never been walked --
    no fixture wrote a `NATOM` line at all, which made the entire atom-count half of
    coherence unreachable from a real tree. `RunSpec.natoms` is what closes that.

    The intended outcome, stated in full: the layout inference merges these six runs into
    three members (`apo/01` and `holo/01` both become `01` -- the accepted limitation for
    parallel arms with distinct run names), the runs are TAGGED because that is what
    `discover`/`plan` do with a grouping they resolved, and the user is told in the same
    breath that a member holds two different systems. Tags plus an error, not tags in
    silence. Exit 1 without `--strict`, like every other category error.
    """
    from tests.conftest import RunSpec, write_run_tree, _PROD_MDIN

    write_run_tree(tmp_path, [
        (f"{system}/{index}/{system}_prod_0001",
         RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0, begin_ps=0.0, natoms=natoms))
        for system, natoms in (("apo", _APO_ATOMS), ("holo", _HOLO_ATOMS))
        for index in ("01", "02", "03")])

    assert main(["plan", "--recursive", str(tmp_path)]) == 1
    printed = capsys.readouterr().out
    # Tagged: the merge really did happen, so the silence being fixed is the real one.
    assert "3 declared lineage(s)" in printed or "Per lineage:" in printed
    assert "Runs within one member hold different numbers of atoms" in printed
    assert "50000, 50800" in printed


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
