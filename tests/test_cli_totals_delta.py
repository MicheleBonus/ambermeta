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
