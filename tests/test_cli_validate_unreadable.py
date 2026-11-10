"""Per-file `validate` on files that hold nothing usable.

The status of a file used to come from its parser's warnings alone, and the topology and
mdout parsers raised none for an empty file, a text file named `.prmtop`, or an mdout cut
off mid-run. All of them came back `OK` with exit 0, even under `--strict`, while
`plan --recursive` on the same files reported "Run did not finish". `validate` is the
command a pipeline gate calls, so `OK` there is the one answer that must not be wrong.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import ambermeta.cli as cli


def _validate(paths, capsys, strict=False):
    args = SimpleNamespace(files=[str(p) for p in paths], strict=strict, format="json")
    code = cli._validate_command(args)
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def truncated_mdout(tmp_path, sample_md_data_dir):
    # The first 60 kB of a 160 kB mdout: the header and the early energy records are
    # there, the completion block is not. What a crashed or still-running run leaves.
    path = tmp_path / "trunc.mdout"
    path.write_bytes((sample_md_data_dir / "ntp_prod_0001.mdout").read_bytes()[:60000])
    return path


@pytest.mark.parametrize("name, content", [
    ("empty.prmtop", b""),
    ("junk.prmtop", b"this is not a topology\n"),
    ("empty.mdout", b""),
])
def test_a_file_with_nothing_usable_is_not_ok(tmp_path, capsys, name, content):
    path = tmp_path / name
    path.write_bytes(content)

    code, report = _validate([path], capsys)

    assert report["files"][0]["status"] == "warning"
    assert report["files"][0]["warnings"]
    assert code == 0  # a warning, not an error: --strict is what fails on it


def test_an_mdout_that_stops_mid_run_is_not_ok(truncated_mdout, capsys):
    code, report = _validate([truncated_mdout], capsys)

    assert report["files"][0]["status"] == "warning"
    assert report["files"][0]["warnings"]
    assert code == 0


def test_strict_fails_on_a_file_with_nothing_usable(tmp_path, truncated_mdout, capsys):
    empty_top = tmp_path / "empty.prmtop"
    empty_top.write_bytes(b"")

    code, report = _validate([empty_top, truncated_mdout], capsys, strict=True)

    assert code == 1
    assert report["status"] == "warning"


def test_intact_sample_files_stay_ok(sample_md_data_dir, capsys):
    paths = [sample_md_data_dir / "CH3L1_HUMAN_6NAG.top",
             sample_md_data_dir / "ntp_prod_0001.mdin",
             sample_md_data_dir / "ntp_prod_0001.mdout"]

    code, report = _validate(paths, capsys, strict=True)

    assert [f["status"] for f in report["files"]] == ["ok", "ok", "ok"]
    assert code == 0
