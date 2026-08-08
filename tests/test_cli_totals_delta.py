"""When plan is about to contradict a number it wrote before, it says so.

The rule changed under existing projects: any tree holding a queued or truncated run now
reports less than it did. A user who quoted the old figure gets told, once, at the moment
the file is overwritten -- not by noticing later that two artifacts disagree.

Task 5's brief called for `plan --output <dir>`, a flag that does not exist (the write-path
flags are `--summary-path` / `--summary-format` / `--methods-summary-path` / `--stats-csv`,
and `--summary-path` takes a file, not a directory); every test below drives `plan` through
`--summary-path`, per the verified corrections in
`.superpowers/sdd/2026-08-07-truthful-defaults-and-declaring-lineages/task-5-corrections.md`.
"""
from __future__ import annotations

import json

from ambermeta.cli import main


def test_plan_reports_the_delta_when_it_contradicts_an_earlier_summary(sys021_tree, capsys):
    out = sys021_tree / "out"
    out.mkdir()
    (out / "summary.json").write_text(json.dumps(
        {"totals": {"steps": 50000000.0, "time_ps": 100000.0}, "stages": []}),
        encoding="utf-8")
    main(["plan", "--recursive", str(sys021_tree),
          "--summary-path", str(out / "summary.json")])
    printed = capsys.readouterr().out
    assert "totals changed since the last summary.json" in printed
    assert "100000.000" in printed and "71000.000" in printed


def test_plan_says_nothing_when_there_is_no_earlier_summary(sys021_tree, capsys):
    """No prior claim, nothing to contradict."""
    out = sys021_tree / "out"
    out.mkdir()
    main(["plan", "--recursive", str(sys021_tree),
          "--summary-path", str(out / "summary.json")])
    assert "totals changed" not in capsys.readouterr().out


def test_plan_names_the_summary_path_it_actually_read_not_a_fixed_directory(sys021_tree, capsys):
    """`--summary-path` can point anywhere -- several existing callers use
    `reports/summary.json`, `s.json`, or a path outside the scanned tree entirely. A
    message that claims the prior summary lives "in this directory" is wrong for all of
    them and names a file the user cannot locate; naming the path actually read is
    correct regardless of where `--summary-path` points."""
    reports = sys021_tree / "reports"
    reports.mkdir()
    summary_path = reports / "summary.json"
    summary_path.write_text(json.dumps(
        {"totals": {"steps": 1.0, "time_ps": 1.0}, "stages": []}), encoding="utf-8")
    main(["plan", "--recursive", str(sys021_tree), "--summary-path", str(summary_path)])
    assert str(summary_path) in capsys.readouterr().out


def test_plan_does_not_crash_on_a_prior_summary_that_is_not_a_json_object(sys021_tree, capsys):
    """A prior summary.json that parses but is not an object (a bare JSON string, here)
    must not raise: `.get("totals")` on a non-dict raises AttributeError, which is not
    covered by the (OSError, ValueError) guard around the read, and a merely odd file
    should not turn a working `plan` into a crash."""
    out = sys021_tree / "out"
    out.mkdir()
    (out / "summary.json").write_text(json.dumps("not-an-object"), encoding="utf-8")
    rc = main(["plan", "--recursive", str(sys021_tree),
               "--summary-path", str(out / "summary.json")])
    assert rc == 0
    assert "totals changed" not in capsys.readouterr().out


def test_plan_reads_a_yaml_prior_summary_instead_of_permanently_forgetting_it(sys021_tree, capsys):
    """`plan` writes YAML summaries when `--summary-path` ends `.yaml`/`.yml`
    (`_resolve_sim_format`). A prior claim written in that format must be read back as
    YAML: feeding it to `json.load` raises `JSONDecodeError`, and swallowing that into
    `{}` would mean "no prior claim" on every single run against this path forever, not
    just this one -- silently disabling the feature for any project that uses YAML
    summaries."""
    out = sys021_tree / "out"
    out.mkdir()
    summary_path = out / "summary.yaml"
    summary_path.write_text(
        "totals:\n  steps: 50000000.0\n  time_ps: 100000.0\nstages: []\n",
        encoding="utf-8")
    main(["plan", "--recursive", str(sys021_tree), "--summary-path", str(summary_path)])
    printed = capsys.readouterr().out
    assert "totals changed since the last summary.json" in printed
    assert "100000.000" in printed and "71000.000" in printed


def test_plan_with_only_stats_csv_requested_does_not_try_to_read_a_summary(sys021_tree, tmp_path):
    """`--stats-csv` alone leaves `args.summary_path` at its default `None` and
    "summary" out of `targets`; the prior-summary read must be guarded on
    `"summary" in targets`, not on `args.summary_path` being falsy. `open(None)` raises
    `TypeError`, which is not in the (OSError, ValueError) list and would escape to
    main()'s catch-all, turning a working `plan --stats-csv` into an "Unexpected error"
    exit instead of the row-per-step CSV it used to write."""
    stats_csv = tmp_path / "stats.csv"
    rc = main(["plan", "--recursive", str(sys021_tree), "--stats-csv", str(stats_csv)])
    assert rc == 0
    assert stats_csv.is_file()


# ---------------------------------------------------------------------------
# What the message may CLAIM. It used to build its "reason" line from the current
# ABSOLUTE `queued_count`, not from any decomposition of the delta -- so one changed
# run got "5 queued run(s) no longer counted", and a total that ROSE got the same
# sentence. Two summary.json artifacts carry totals, not a per-stage ledger, so the
# cause is not in evidence and the line must not assert one. Nothing pinned any of
# this before; the reason line was entirely unasserted.
# ---------------------------------------------------------------------------

def _delta_block(printed: str) -> list:
    """The `totals changed ...` heading plus its indented body, and nothing else.

    `plan` prints a full per-stage report around it, and several of those lines are also
    indented, so the block is taken as "the heading and the indented lines that
    immediately follow it" rather than by filtering the whole output.
    """
    out, collecting = [], False
    for line in printed.splitlines():
        if line.startswith("totals changed since"):
            out.append(line)
            collecting = True
        elif collecting and line.startswith("  "):
            out.append(line)
        elif collecting:
            break
    return out


def test_the_delta_does_not_claim_a_cause_it_has_not_established(sys021_tree, capsys):
    """The prior summary is LOWER, so the totals rose. "N queued run(s) no longer
    counted" would be a non-sequitur attached to the one sentence a researcher reads
    before quoting a number -- and it was printed verbatim in exactly this situation."""
    out = sys021_tree / "out"
    out.mkdir()
    (out / "summary.json").write_text(json.dumps(
        {"totals": {"steps": 1000.0, "time_ps": 2.0}, "stages": []}), encoding="utf-8")
    main(["plan", "--recursive", str(sys021_tree),
          "--summary-path", str(out / "summary.json")])
    block = _delta_block(capsys.readouterr().out)

    assert any("time_ps   2.000 -> 71000.000" in line for line in block)
    assert not any("no longer counted" in line for line in block)
    assert not any("reason" in line for line in block)


def test_the_delta_says_what_the_numbers_mean_and_states_queued_as_a_transition(
        sys021_tree, capsys):
    """The two things that ARE honestly available: what the totals count, and the one
    component both artifacts carry -- reported as a before -> after transition rather than
    as the delta's cause. The prior summary here declares 3 queued runs and the tree holds
    5, a pair the old absolute-count line could not have told apart from `0 -> 5`."""
    out = sys021_tree / "out"
    out.mkdir()
    (out / "summary.json").write_text(json.dumps(
        {"totals": {"steps": 50000000.0, "time_ps": 100000.0, "queued_count": 3.0},
         "stages": []}), encoding="utf-8")
    main(["plan", "--recursive", str(sys021_tree),
          "--summary-path", str(out / "summary.json")])
    block = _delta_block(capsys.readouterr().out)

    assert block[0].startswith("totals changed since the last summary.json")
    assert block[1] == "  steps     50000000.000 -> 35500000.000"
    assert block[2] == "  time_ps   100000.000 -> 71000.000"
    assert block[3] == ("  note      totals count what each run's mdout shows it RAN, "
                        "not what its mdin declared")
    assert block[4] == "  queued    3 -> 5 run(s) with an mdin and no mdout"
    assert len(block) == 5


def test_no_queued_line_when_neither_artifact_mentions_queued_runs(tmp_path, capsys):
    """`queued_count` is emitted only when there is at least one, so an absent key means
    zero -- but only once the OTHER side has stated one. Two artifacts that both omit it
    say nothing about queued runs, and a `0 -> 0` line would be noise dressed as a fact."""
    from tests.conftest import RunSpec, write_run_tree, _PROD_MDIN
    tree = write_run_tree(tmp_path, [
        ("prod_0001", RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0, begin_ps=0.0))])
    out = tree / "out"
    out.mkdir()
    (out / "summary.json").write_text(json.dumps(
        {"totals": {"steps": 1.0, "time_ps": 1.0}, "stages": []}), encoding="utf-8")
    main(["plan", "--recursive", str(tree), "--summary-path", str(out / "summary.json")])
    block = _delta_block(capsys.readouterr().out)

    assert any(line.startswith("  note") for line in block)
    assert not any(line.startswith("  queued") for line in block)
