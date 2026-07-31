from __future__ import annotations

import io
import sys


def test_init_writes_the_template_through_argparse(tmp_path):
    """`init` reached through main(), not by hand-building a Namespace: a parser/command
    wiring mistake (a renamed dest, a flag the command reads but the parser never adds)
    is invisible to a SimpleNamespace test."""
    from ambermeta.cli import main
    from ambermeta.simulation import load_simulation

    rc = main(["init", str(tmp_path), "-o", "sim.yaml"])
    assert rc == 0
    assert load_simulation(str(tmp_path / "sim.yaml")).version == 2


def test_init_force_overwrites_without_asking(tmp_path):
    from ambermeta.cli import main

    (tmp_path / "sim.yaml").write_text("stale\n", encoding="utf-8")
    rc = main(["init", str(tmp_path), "-o", "sim.yaml", "--force"])
    assert rc == 0
    assert "version: 2" in (tmp_path / "sim.yaml").read_text(encoding="utf-8")


def test_init_overwrites_when_the_prompt_is_answered_yes(tmp_path, monkeypatch):
    from ambermeta.cli import main

    (tmp_path / "sim.yaml").write_text("stale\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    rc = main(["init", str(tmp_path), "-o", "sim.yaml"])
    assert rc == 0
    assert "version: 2" in (tmp_path / "sim.yaml").read_text(encoding="utf-8")


def test_init_honours_an_answer_piped_in(tmp_path, monkeypatch):
    """`echo y | ambermeta init . -o sim.yaml` must still work.

    A script piping an answer is answering the prompt. An earlier fix gated the prompt
    on sys.stdin.isatty() to stop `< /dev/null` crashing, which also refused every piped
    answer — trading a crash for a broken workflow. Real non-terminal stdin here, and
    input() left alone, so this exercises the actual read rather than a stand-in.
    """
    from ambermeta.cli import main

    (tmp_path / "sim.yaml").write_text("stale\n", encoding="utf-8")
    piped = io.StringIO("y\n")
    assert not piped.isatty()
    monkeypatch.setattr(sys, "stdin", piped)

    rc = main(["init", str(tmp_path), "-o", "sim.yaml"])

    assert rc == 0
    assert "version: 2" in (tmp_path / "sim.yaml").read_text(encoding="utf-8")


def test_init_keeps_the_file_when_the_prompt_is_declined(tmp_path, monkeypatch):
    from ambermeta.cli import main

    (tmp_path / "sim.yaml").write_text("stale\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda *a: "")
    rc = main(["init", str(tmp_path), "-o", "sim.yaml"])
    assert rc == 1
    assert (tmp_path / "sim.yaml").read_text(encoding="utf-8") == "stale\n"


def test_init_on_unreadable_stdin_says_use_force_instead_of_crashing(tmp_path, capsys, monkeypatch):
    """`ambermeta init . -o sim.yaml < /dev/null` over an existing file used to reach
    input() and die with `Unexpected error (EOFError: EOF when reading a line)`.

    The EOF is raised explicitly rather than relying on pytest's captured stdin, which
    reports a real terminal under `pytest -s` and would quietly stop testing this.
    """
    from ambermeta.cli import main

    (tmp_path / "sim.yaml").write_text("stale\n", encoding="utf-8")

    def _eof(*_a):
        raise EOFError("EOF when reading a line")

    monkeypatch.setattr("builtins.input", _eof)
    rc = main(["init", str(tmp_path), "-o", "sim.yaml"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "already exists" in err and "--force" in err
    assert "EOFError" not in err and "Traceback" not in err
    assert (tmp_path / "sim.yaml").read_text(encoding="utf-8") == "stale\n"


def test_prmtop_substring_not_misclassified(tmp_path):
    """`_scan_directory_files` is still used by `plan --interactive`'s file
    suggestions (`_interactive_manifest`), not by `init` (which no longer
    scans anything)."""
    from ambermeta.cli import _scan_directory_files
    (tmp_path / "gen_prmtop.in").write_text("&cntrl\n/\n")
    files = _scan_directory_files(str(tmp_path))
    assert "gen_prmtop.in" in files["mdin"]
    assert "gen_prmtop.in" not in files["prmtop"]
