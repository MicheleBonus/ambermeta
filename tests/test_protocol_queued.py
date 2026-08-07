# tests/test_protocol_queued.py
"""A run that was set up and never executed stays in the record, costing nothing.

Deleting it would hide that a campaign was cut short; counting it was the bug. What is
deliberately NOT asserted here: the arithmetic (test_protocol_totals_from_mdout.py).

Pinned on all three surfaces a queued run has to survive to, not only the engine: the
scan/manifest entry points into `SimulationStage` (round 1), `core_bridge.discover_draft`'s
`Step` objects -- the actual output of `ambermeta discover` and the GUI's document, which
went unchecked in round 1 and reported zero queued steps -- and `SimulationStage.to_dict()`,
the artifact a user keeps.
"""
from __future__ import annotations

from ambermeta.protocol import auto_discover


def test_a_stem_with_an_mdin_and_no_mdout_is_marked_queued(sys021_tree):
    protocol = auto_discover(str(sys021_tree), recursive=True)
    queued = sorted(s.name for s in protocol.stages if s.status == "queued")
    assert queued == [
        "prod/01/nvt_prod_0004", "prod/02/nvt_prod_0003", "prod/03/nvt_prod_0003",
        "prod/04/nvt_prod_0003", "prod/05/nvt_prod_0003",
    ]


def test_a_run_that_produced_output_carries_no_status(sys021_tree):
    """Emit-when-set: only the non-default value is ever recorded, so an ordinary
    document's artifacts are byte-identical to what they were before the field existed."""
    protocol = auto_discover(str(sys021_tree), recursive=True)
    ran = [s for s in protocol.stages if s.name == "prod/01/nvt_prod_0001"]
    assert ran and ran[0].status is None


def test_the_artifact_reports_queued_runs_beside_the_completed_ones(sys021_tree):
    protocol = auto_discover(str(sys021_tree), recursive=True)
    assert protocol.to_dict()["totals"]["queued_count"] == 5.0


def test_a_stray_file_sharing_the_mdin_extension_is_not_marked_queued(sys021_tree):
    """`sys021_tree` also holds `prod/01/cpptraj.in`, a cpptraj post-processing script
    that the extension-based file typing reads as an mdin candidate exactly like a real
    one -- and, like the five genuine queued chunks, it has no mdout beside it. It must
    NOT appear in the five names above: it never was a run, and reporting it as one would
    invent a sixth queued chunk with no basis in the campaign this fixture reproduces."""
    protocol = auto_discover(str(sys021_tree), recursive=True)
    cpptraj = [s for s in protocol.stages if s.name == "prod/01/cpptraj"]
    assert cpptraj and cpptraj[0].status is None


def test_a_queued_minimisation_is_also_marked_queued(tmp_path):
    """A minimisation mdin declares `maxcyc`, never `nstlim` -- `length_steps` stays 0 for
    a genuine one, the same shape `cpptraj.in` has -- so `_looks_queued` checks
    `cntrl_parameters` rather than `length_steps` specifically so a queued minimisation is
    not a false negative alongside `cpptraj`."""
    (tmp_path / "min.mdin").write_text(
        "minimise\n &cntrl\n  imin = 1, maxcyc = 1000, ntb = 1,\n /\n", encoding="utf-8")
    protocol = auto_discover(str(tmp_path), recursive=True)
    stage, = protocol.stages
    assert stage.status == "queued"


def test_a_declared_mdin_that_does_not_exist_is_not_marked_queued(tmp_path):
    """A manifest can name a file nobody ever wrote -- a template stage, a stale path, a
    typo. `_looks_queued` requires the mdin to have actually parsed (`cntrl_parameters`
    read off it), so a broken reference reads as broken -- `degraded` via a
    `FileLoadError` -- rather than as a real run waiting to happen, which would be a
    second, misleading claim about the same missing file."""
    protocol = auto_discover(
        str(tmp_path), manifest=[{"name": "phantom", "mdin": "nonexistent.mdin"}])
    stage, = protocol.stages
    assert stage.status is None
    assert stage.degraded is True


# --- the artifact: which stage, not only how many -----------------------------

def test_the_artifact_marks_which_stage_is_queued(sys021_tree):
    """`queued_count` (above) says how many; `to_dict()` is what lets a reader of
    summary.json find out WHICH ones, rather than inferring it indirectly from
    `files.mdout: null` plus an absent `load_errors` entry."""
    protocol = auto_discover(str(sys021_tree), recursive=True)
    stages = {s["name"]: s for s in protocol.to_dict()["stages"]}
    assert stages["prod/01/nvt_prod_0004"]["status"] == "queued"


def test_a_run_that_produced_output_has_no_status_key_in_the_artifact(sys021_tree):
    """Emit-when-set at the artifact layer too: `to_dict()` feeds summary.json, byte-pinned
    by test_lineage_backcompat.py's assert_matches_golden, which fails on any ADDED key
    path -- so an ordinary stage's block must stay exactly what it was."""
    protocol = auto_discover(str(sys021_tree), recursive=True)
    stages = {s["name"]: s for s in protocol.to_dict()["stages"]}
    assert "status" not in stages["prod/01/nvt_prod_0001"]


# --- discover_draft: the actual output of `ambermeta discover` and the GUI ----

def test_discover_draft_marks_the_same_five_steps_queued(sys021_tree):
    """`ambermeta discover` and the GUI's document route through `core_bridge.discover_draft`,
    not through `auto_discover` -- so the engine getting this right (above) says nothing
    about what a user's manifest or the GUI's canvas actually shows. This is the same
    fixture, the same five names, through the path a saved `sys021.yaml` actually takes."""
    from ambermeta.gui.api.core_bridge import discover_draft

    sim = discover_draft(str(sys021_tree), recursive=True)["simulation"]
    queued = sorted(s.name for p in sim.phases for s in p.steps if s.status == "queued")
    assert queued == [
        "prod/01/nvt_prod_0004", "prod/02/nvt_prod_0003", "prod/03/nvt_prod_0003",
        "prod/04/nvt_prod_0003", "prod/05/nvt_prod_0003",
    ]


def test_discover_draft_does_not_mark_the_stray_cpptraj_file_queued(sys021_tree):
    from ambermeta.gui.api.core_bridge import discover_draft

    sim = discover_draft(str(sys021_tree), recursive=True)["simulation"]
    cpptraj = [s for p in sim.phases for s in p.steps if s.name == "prod/01/cpptraj"]
    assert cpptraj and cpptraj[0].status is None
