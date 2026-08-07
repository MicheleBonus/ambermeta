# tests/test_protocol_queued.py
"""A run that was set up and never executed stays in the record, costing nothing.

Deleting it would hide that a campaign was cut short; counting it was the bug. What is
deliberately NOT asserted here: the arithmetic (test_protocol_totals_from_mdout.py).
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
