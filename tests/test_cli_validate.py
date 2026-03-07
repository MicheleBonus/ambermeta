from __future__ import annotations

from types import SimpleNamespace

import ambermeta.cli as cli


class _ParserWithWarnings:
    def __init__(self, warnings):
        self._warnings = warnings

    def parse(self):
        return SimpleNamespace(warnings=self._warnings)


def test_validate_json_output_shape(monkeypatch, capsys):
    def fake_exists(path: str) -> bool:
        return path in {"ok.mdout", "warn.mdout", "unknown.bin"}

    def fake_get_parser(path: str):
        if path == "ok.mdout":
            return _ParserWithWarnings([])
        if path == "warn.mdout":
            return _ParserWithWarnings(["Incomplete trajectory"])
        return None

    monkeypatch.setattr(cli.os.path, "exists", fake_exists)
    monkeypatch.setattr(cli, "_get_parser_for_file", fake_get_parser)

    args = SimpleNamespace(
        files=["ok.mdout", "warn.mdout", "unknown.bin", "notfound.bin"],
        strict=False,
        format="json",
    )

    result_code = cli._validate_command(args)

    assert result_code == 1
    payload = cli.json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["files"] == [
        {"file": "ok.mdout", "status": "ok", "warnings": [], "errors": []},
        {
            "file": "warn.mdout",
            "status": "warning",
            "warnings": ["Incomplete trajectory"],
            "errors": [],
        },
        {
            "file": "unknown.bin",
            "status": "warning",
            "warnings": ["Unknown file type: unknown.bin"],
            "errors": [],
        },
        {
            "file": "notfound.bin",
            "status": "error",
            "warnings": [],
            "errors": ["File not found: notfound.bin"],
        },
    ]
    assert payload["warnings"] == [
        {"file": "warn.mdout", "message": "Incomplete trajectory"},
        {"file": "unknown.bin", "message": "Unknown file type: unknown.bin"},
    ]
    assert payload["errors"] == [
        {"file": "notfound.bin", "message": "File not found: notfound.bin"},
    ]


def test_validate_strict_mode_fails_on_warnings(monkeypatch):
    monkeypatch.setattr(cli.os.path, "exists", lambda path: True)
    monkeypatch.setattr(
        cli,
        "_get_parser_for_file",
        lambda path: _ParserWithWarnings(["Potential issue detected"]),
    )

    strict_args = SimpleNamespace(files=["warn.mdout"], strict=True, format="text")
    non_strict_args = SimpleNamespace(files=["warn.mdout"], strict=False, format="text")

    assert cli._validate_command(strict_args) == 1
    assert cli._validate_command(non_strict_args) == 0
