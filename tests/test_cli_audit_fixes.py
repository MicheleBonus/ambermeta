"""Findings from the CLI audit (`.claude/ux-audit/reports/2026-11-10-cli.md`).

3  `discover --write` and `export -o` replaced an existing file without a word, while
   `init` refused; re-running `discover --write sim.yaml` wiped a hand-edited manifest.
12 A missing parent directory was "Unexpected error (FileNotFoundError ...)" for
   `discover --write`, `export -o` and `init`, while `plan --summary-path` creates it.
5  `-q` dropped error messages, against docs/cli.md ("errors/usage still go to stderr").
16 A `--pattern` that is not a regular expression was an "Unexpected error".
13 There was no `--version`; `ambermeta --version` answered with a usage error.
7  `plan -m` reported a malformed or missing manifest as "Unexpected error".
8  `plan -m` printed "Validation: ISSUES FOUND" without ever saying what the issues were.
"""
from __future__ import annotations

import json

import pytest

import ambermeta
from ambermeta.cli import main


def _run(argv, capsys):
    try:
        rc = main(argv)
    except SystemExit as exc:          # argparse leaves through SystemExit
        rc = exc.code
    out = capsys.readouterr()
    return rc, out.out, out.err


# --- 3: never overwrite without --force --------------------------------------------

def test_discover_will_not_overwrite_a_file_without_force(tmp_path, sample_md_data_dir, capsys):
    target = tmp_path / "sim.yaml"
    target.write_text("my hand-edited manifest\n", encoding="utf-8")

    rc, out, err = _run(["discover", str(sample_md_data_dir), "--write", str(target)], capsys)

    assert rc == 1
    assert "--force" in out + err
    assert target.read_text(encoding="utf-8") == "my hand-edited manifest\n"


def test_discover_overwrites_with_force(tmp_path, sample_md_data_dir, capsys):
    target = tmp_path / "sim.yaml"
    target.write_text("old\n", encoding="utf-8")

    rc, _, _ = _run(["discover", str(sample_md_data_dir), "--write", str(target), "--force"], capsys)

    assert rc == 0
    text = target.read_text(encoding="utf-8")
    # Replaced: the old content is gone and a manifest is there (after the draft's
    # comment header, so not necessarily on the first line).
    assert "old\n" not in text and "\nversion: 2" in text


def test_export_will_not_overwrite_a_file_without_force(tmp_path, sample_md_data_dir, capsys):
    manifest = tmp_path / "sim.yaml"
    _run(["discover", str(sample_md_data_dir), "--write", str(manifest)], capsys)
    target = tmp_path / "sim.json"
    target.write_text("{}", encoding="utf-8")

    rc, out, err = _run(["export", str(manifest), "-o", str(target)], capsys)
    assert (rc, target.read_text(encoding="utf-8")) == (1, "{}")
    assert "--force" in out + err

    rc, _, _ = _run(["export", str(manifest), "-o", str(target), "--force"], capsys)
    assert rc == 0 and json.loads(target.read_text(encoding="utf-8"))["version"] == 2


# --- 12: a missing parent directory is created, as plan --summary-path does ------

def test_every_manifest_writer_creates_a_missing_parent_directory(tmp_path, sample_md_data_dir, capsys):
    a = tmp_path / "new" / "a.yaml"
    rc, _, err = _run(["discover", str(sample_md_data_dir), "--write", str(a)], capsys)
    assert (rc, a.is_file()) == (0, True), err

    b = tmp_path / "other" / "b.json"
    rc, _, err = _run(["export", str(a), "-o", str(b)], capsys)
    assert (rc, b.is_file()) == (0, True), err

    rc, _, err = _run(["init", str(tmp_path), "-o", "third/m.yaml"], capsys)
    assert (rc, (tmp_path / "third" / "m.yaml").is_file()) == (0, True), err


# --- 5: -q keeps errors -------------------------------------------------------------

def test_quiet_still_reports_a_file_that_cannot_be_validated(tmp_path, capsys):
    rc, out, err = _run(["-q", "validate", str(tmp_path / "nope.mdout")], capsys)

    assert rc == 1
    assert out == ""
    assert "nope.mdout" in err


# --- 16: an invalid --pattern is a usage error -------------------------------------

@pytest.mark.parametrize("command", [["discover", "."], ["plan", ".", "--recursive"]])
def test_an_invalid_pattern_is_a_usage_error(command, capsys):
    rc, _, err = _run(command + ["--pattern", "["], capsys)

    assert rc == 2
    assert "not a valid regular expression" in err
    assert "Unexpected error" not in err


# --- 13: --version ------------------------------------------------------------------

def test_version_prints_the_version(capsys):
    rc, out, _ = _run(["--version"], capsys)

    assert rc == 0
    assert out.strip() == f"ambermeta {ambermeta.__version__}"


# --- 7: plan -m reports a bad or missing manifest cleanly --------------------------

@pytest.mark.parametrize("name, content", [
    ("broken.yaml", "version: 2\nsteps: [ {id: a, name: x\n"),
    ("broken.json", '{"version": 2, "steps": ['),
])
def test_plan_reports_a_malformed_manifest_without_an_unexpected_error(tmp_path, capsys, name, content):
    manifest = tmp_path / name
    manifest.write_text(content, encoding="utf-8")

    rc, out, err = _run(["plan", str(tmp_path), "-m", str(manifest)], capsys)

    assert rc == 1
    assert "Unexpected error" not in out + err
    assert name in err


def test_plan_reports_a_missing_manifest_without_an_unexpected_error(tmp_path, capsys):
    rc, out, err = _run(["plan", str(tmp_path), "-m", str(tmp_path / "nope.yaml")], capsys)

    assert rc == 1
    assert "Unexpected error" not in out + err
    assert "nope.yaml" in err


# --- 8: plan -m says what the issues are -------------------------------------------

def test_plan_names_the_files_behind_issues_found(tmp_path, capsys):
    manifest = tmp_path / "sim.json"
    manifest.write_text(json.dumps({
        "version": 2,
        "simulation": {"topologies": [{"id": "top", "path": "absent.prmtop", "kind": "normal"}],
                       "starting_structure": "absent.inpcrd"},
        "phases": [{"id": "ph", "name": "Production", "role": "production", "order": 0}],
        "steps": [{"id": "st1", "name": "prod_0001", "phase": "ph", "order": 0, "topology": "top",
                   "input_coords": {"source": "starting_structure"}, "mdin": "absent.mdin"}],
    }), encoding="utf-8")

    rc, out, _ = _run(["plan", str(tmp_path), "-m", str(manifest)], capsys)

    assert "ISSUES FOUND" in out
    # A line saying what is wrong with the file, not the step listing's `(mdin=absent.mdin)`.
    import re
    assert re.search(r"missing\b[^\n]*absent\.mdin", out), out
    assert rc == 0      # fault-tolerant by design without --strict (docs/cli.md)
