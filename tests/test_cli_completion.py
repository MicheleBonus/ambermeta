from __future__ import annotations

import ambermeta.cli as cli


def test_parser_accepts_completion_command() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["completion", "bash"])

    assert args.command == "completion"
    assert args.shell == "bash"


def test_completion_script_contains_expected_tokens() -> None:
    bash_script = cli._completion_script("bash")
    zsh_script = cli._completion_script("zsh")
    fish_script = cli._completion_script("fish")

    assert "complete -F _ambermeta_completion ambermeta" in bash_script
    assert "#compdef ambermeta" in zsh_script
    assert "complete -c ambermeta" in fish_script


def test_completion_scripts_have_no_tui_branch() -> None:
    # The TUI was removed; completion scripts must not advertise it.
    for shell in ("bash", "zsh", "fish"):
        assert "tui" not in cli._completion_script(shell)
