"""`plan` reports what it found, on every mode, in the artifact, and in the exit code.

Before this, `plan --manifest` printed the crashed-replica finding and then dropped it:
`plan --recursive` computed nothing at all, `summary.json` said `{totals, stages}` and
nothing else, and `--strict` — the flag a pipeline uses to mean "fail on anything
questionable" — exited 0 while `validate --strict` exited 1 on the same manifest.

The tree throughout is the one the feature exists for: rep1 and rep3 ran three production
chunks, rep2 stopped after one.
"""
from __future__ import annotations

import json

import pytest

from ambermeta.cli import main


@pytest.fixture
def crashed_manifest(crashed_replica_tree):
    """`discover --write` over the crashed tree, so the manifest carries the real tags."""
    path = crashed_replica_tree / "manifest.yaml"
    assert main(["discover", str(crashed_replica_tree), "--write", str(path)]) == 0
    return path


FINDING = "rep2/prod sequence is missing member(s) 2, 3"


# ---------------------------------------------------------------------------
# Every mode says the same thing about the same directory
# ---------------------------------------------------------------------------

def test_the_manifest_path_names_the_short_member_exactly_once(
        crashed_replica_tree, crashed_manifest, capsys):
    """Once, not twice: this path already printed the finding through `validate_simulation`,
    so the obvious way to "add a findings channel to plan" prints it a second time."""
    assert main(["plan", str(crashed_replica_tree), "-m", str(crashed_manifest)]) == 0
    out = capsys.readouterr().out
    assert out.count(FINDING) == 1
    assert out.count("Continuity / sequence findings:") == 1


def test_the_scan_path_names_the_short_member_too(crashed_replica_tree, capsys):
    """`plan --recursive` never builds a Simulation, so `build_suggestions` cannot run —
    it reads `sim.phases` and raises on a protocol. The names and the tags are on the
    stages, which is all the sequence half needs."""
    assert main(["plan", "--recursive", str(crashed_replica_tree)]) == 0
    assert FINDING in capsys.readouterr().out


def test_a_complete_ensemble_prints_no_findings_block(replica_tree, capsys):
    assert main(["plan", "--recursive", str(replica_tree)]) == 0
    assert "Continuity / sequence findings:" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The exit code
# ---------------------------------------------------------------------------

def test_strict_fails_on_a_finding_on_both_plan_modes(
        crashed_replica_tree, crashed_manifest):
    """The divergence this closes: `validate --manifest --strict` exited 1 on this
    manifest and `plan --manifest --strict` exited 0, on the same finding, printed in the
    same words. `--strict` on `plan` used to mean only "abort on the first unreadable
    file"; it now means both halves of being strict."""
    assert main(["validate", "--manifest", str(crashed_manifest), "--strict"]) == 1
    assert main(["plan", str(crashed_replica_tree), "-m", str(crashed_manifest),
                 "--strict"]) == 1
    assert main(["plan", "--recursive", "--strict", str(crashed_replica_tree)]) == 1


def test_without_strict_a_finding_is_reported_and_the_run_succeeds(
        crashed_replica_tree, crashed_manifest):
    """A hole in a sequence is a fact about the data, not a failure of the run. The
    default stays exit 0 so `plan` remains usable on a campaign still in flight."""
    assert main(["plan", str(crashed_replica_tree), "-m", str(crashed_manifest)]) == 0
    assert main(["plan", "--recursive", str(crashed_replica_tree)]) == 0


def test_strict_passes_on_a_complete_ensemble(replica_tree):
    assert main(["plan", "--recursive", "--strict", str(replica_tree)]) == 0


def test_the_status_line_does_not_say_ok_while_exiting_1(
        crashed_replica_tree, crashed_manifest, capsys):
    """`ok` is about validity and a sequence hole does not make a document invalid, so the
    report said OK and the command then returned 1. Saying OK and failing is worse than
    either alone."""
    assert main(["plan", str(crashed_replica_tree), "-m", str(crashed_manifest),
                 "--strict"]) == 1
    assert "Validation: ISSUES FOUND" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The artifact
# ---------------------------------------------------------------------------

def _summary(tree, manifest, tmp_path):
    out = tmp_path / "summary.json"
    assert main(["plan", str(tree), "-m", str(manifest),
                 "--summary-path", str(out)]) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def test_the_summary_carries_the_finding(crashed_replica_tree, crashed_manifest, tmp_path):
    """The terminal scrolls; the artifact is what the user keeps."""
    summary = _summary(crashed_replica_tree, crashed_manifest, tmp_path)
    card, = summary["findings"]
    assert card["kind"] == "missing_run"
    assert card["lineage"] == "rep2"
    assert card["base"] == "prod"
    assert card["missing"] == [2, 3]


def test_a_summary_with_nothing_to_report_has_no_findings_key(
        replica_tree, tmp_path, capsys):
    """Emit-when-non-empty, the same rule `stage_sequence`'s lineage key follows: a
    document with no holes writes the summary.json it always wrote. An unconditional key
    — even an empty list — fails the back-compat gate, which compares the exact leaf-path
    set of the committed golden."""
    manifest = replica_tree / "manifest.yaml"
    assert main(["discover", str(replica_tree), "--write", str(manifest)]) == 0
    summary = _summary(replica_tree, manifest, tmp_path)
    assert "findings" not in summary
