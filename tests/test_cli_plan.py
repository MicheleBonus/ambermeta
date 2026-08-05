from __future__ import annotations

import shutil

import ambermeta.cli as cli
from ambermeta.protocol import SimulationProtocol, SimulationStage


def test_plan_requires_explicit_mode(capsys, tmp_path):
    parser = cli.build_parser()
    args = parser.parse_args(["plan", str(tmp_path)])

    result = cli._plan_command(args)

    assert result == 2
    captured = capsys.readouterr()
    # Usage errors are routed to stderr so they surface even under -q
    assert "Select a planning mode" in captured.err
    assert "--manifest, --recursive, or --interactive" in captured.err


def test_plan_parser_accepts_interactive_flag(tmp_path):
    parser = cli.build_parser()
    args = parser.parse_args(["plan", "--interactive", str(tmp_path)])

    assert args.interactive is True


def test_plan_interactive_mode_runs_only_with_opt_in(monkeypatch, tmp_path):
    # Justification: the guard introduced by CORE-C7 returns 1 on empty stages, so
    # this test now provides a one-stage protocol to confirm the interactive path is
    # reachable and exits 0 when stages are actually present.
    parser = cli.build_parser()
    args = parser.parse_args(["plan", "--interactive", str(tmp_path)])

    # A real protocol rather than a SimpleNamespace: the scan paths now ask it for its
    # sequence findings, and a duck that answers only the three methods this test happened
    # to need would fail the next time the command learns to ask a fourth question.
    fake_stage = SimulationStage(name="prod")
    monkeypatch.setattr(cli, "_interactive_manifest", lambda directory: [{"name": "prod"}])
    monkeypatch.setattr(
        cli, "auto_discover", lambda *a, **k: SimulationProtocol(stages=[fake_stage]),
    )
    monkeypatch.setattr(cli, "_print_protocol", lambda protocol, verbose=False: None)

    result = cli._plan_command(args)

    assert result == 0


def test_quiet_suppresses_stdout(tmp_path, capsys, monkeypatch):
    import ambermeta.cli as _cli
    from ambermeta.cli import main
    (tmp_path / "manifest.yaml").write_text("version: 2\nsteps: []\n")
    # monkeypatch ensures _QUIET is restored to False after this test
    monkeypatch.setattr(_cli, "_QUIET", False)
    main(["-q", "plan", str(tmp_path), "--manifest",
          str(tmp_path / "manifest.yaml")])
    out = capsys.readouterr().out
    assert out.strip() == ""


def test_quiet_suppresses_info_text(tmp_path, capsys, monkeypatch):
    """With -q, `info` text-format output must be silent (stdout empty)."""
    import ambermeta.cli as _cli
    from ambermeta.cli import main

    prmtop = tmp_path / "test.prmtop"
    prmtop.write_text(
        "%VERSION  VERSION_STAMP = V0001.000  DATE = 01/01/01  00:00:00\n"
        "%FLAG POINTERS\n"
        "%FORMAT(10I8)\n"
        "      10       0       0       0       0       0       0       0       0       0\n"
        "       0       0       0       0       0       0       0       0       0       0\n"
        "       0       0       0       0       0       0       0       0       0       0\n"
        "       0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(_cli, "_QUIET", False)
    rc = main(["-q", "info", str(prmtop)])
    out = capsys.readouterr().out
    assert out.strip() == ""
    assert rc == 0


def test_plan_no_mode_errors_to_stderr_under_quiet(tmp_path, capsys, monkeypatch):
    """Under -q, the usage error from plan (no mode flag) appears on stderr, not stdout."""
    import ambermeta.cli as _cli
    from ambermeta.cli import main

    monkeypatch.setattr(_cli, "_QUIET", False)
    rc = main(["-q", "plan", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "Select a planning mode" in captured.err
    assert captured.out.strip() == ""


def test_pattern_warns_in_manifest_mode(tmp_path, capsys):
    from ambermeta.cli import main
    (tmp_path / "manifest.yaml").write_text("version: 2\nsteps: []\n", encoding="utf-8")
    main(["plan", str(tmp_path), "--manifest", str(tmp_path / "manifest.yaml"),
          "--pattern", "prod_.*"])
    out = capsys.readouterr()              # call ONCE
    assert "pattern" in (out.out + out.err).lower()


def test_skip_flag_defaults_to_none():
    from ambermeta.cli import build_parser
    args = build_parser().parse_args(["plan", "."])
    assert args.skip_cross_stage_validation is None


def test_plan_empty_manifest_nonzero(tmp_path):
    """plan --manifest with an empty v2 manifest should warn and return 1."""
    from ambermeta.cli import main
    (tmp_path / "m.yaml").write_text("version: 2\nsteps: []\n")
    rc = main(["plan", str(tmp_path), "--manifest", str(tmp_path / "m.yaml")])
    assert rc == 1


def test_plan_recursive_creates_missing_parent_directories(tmp_path, sample_md_data_dir):
    """The recursive path used to raise FileNotFoundError on a missing parent."""
    from ambermeta.cli import main
    for f in sample_md_data_dir.iterdir():
        shutil.copy(f, tmp_path)
    rc = main(["plan", str(tmp_path), "--recursive",
               "--summary-path", str(tmp_path / "out" / "summary.json")])
    assert rc == 0
    assert (tmp_path / "out" / "summary.json").is_file()
