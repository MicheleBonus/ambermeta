from __future__ import annotations

from types import SimpleNamespace

import ambermeta.cli as cli


def test_plan_requires_explicit_mode(capsys, tmp_path):
    parser = cli.build_parser()
    args = parser.parse_args(["plan", str(tmp_path)])

    result = cli._plan_command(args)

    assert result == 2
    output = capsys.readouterr().out
    assert "Select a planning mode" in output
    assert "--manifest, --recursive, or --interactive" in output


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
