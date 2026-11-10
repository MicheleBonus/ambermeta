"""CLI audit findings 11 and 15.

11 Colour ignored `NO_COLOR` (no-color.org): from a terminal, `ambermeta ... 2>run.log`
   wrote escape codes into the log however the user had asked for plain text.
15 `export --format yaml` without `-o` printed JSON, and `discover --format json`
   without `--write` was ignored without a word.
"""
from __future__ import annotations

import sys

import pytest

import ambermeta.cli as cli


def test_no_color_turns_colour_off_even_on_a_terminal(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert "\x1b[" in cli.Colors.error("x")          # a terminal still gets colour

    monkeypatch.setenv("NO_COLOR", "1")

    assert cli.Colors.error("x") == "x"


def _run(argv, capsys):
    try:
        rc = cli.main(argv)
    except SystemExit as exc:
        rc = exc.code
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_export_prints_the_format_it_was_asked_for(tmp_path, sample_md_data_dir, capsys):
    yaml = pytest.importorskip("yaml")
    manifest = tmp_path / "sim.json"
    _run(["discover", str(sample_md_data_dir), "--write", str(manifest)], capsys)

    rc, out, _ = _run(["export", str(manifest), "--format", "yaml"], capsys)

    assert rc == 0
    assert out.lstrip().startswith("version: 2")
    assert yaml.safe_load(out)["version"] == 2


def test_discover_says_when_format_has_nothing_to_apply_to(sample_md_data_dir, capsys):
    rc, out, err = _run(["discover", str(sample_md_data_dir), "--format", "json"], capsys)

    assert rc == 0
    assert "--format" in out + err and "--write" in out + err
