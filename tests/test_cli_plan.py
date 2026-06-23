from __future__ import annotations

from types import SimpleNamespace

import ambermeta.cli as cli


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
    parser = cli.build_parser()
    args = parser.parse_args(["plan", "--interactive", str(tmp_path)])

    monkeypatch.setattr(cli, "_interactive_manifest", lambda directory: [{"name": "prod"}])
    monkeypatch.setattr(
        cli,
        "auto_discover",
        lambda *a, **k: SimpleNamespace(stages=[], to_dict=lambda: {}, to_methods_dict=lambda: {}),
    )
    monkeypatch.setattr(cli, "_print_protocol", lambda protocol, verbose=False: None)

    result = cli._plan_command(args)

    assert result == 0


def test_quiet_suppresses_stdout(tmp_path, capsys, monkeypatch):
    import ambermeta.cli as _cli
    from ambermeta.cli import main
    (tmp_path / "manifest.yaml").write_text("stages: []\n")
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
