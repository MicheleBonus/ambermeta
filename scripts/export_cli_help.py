#!/usr/bin/env python3
"""Export argparse help text from ambermeta.cli.build_parser into docs/cli.md blocks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ambermeta.cli import build_parser

DOCS_PATH = Path("docs/cli.md")
START = "<!-- BEGIN_CLI_HELP:{name} -->"
END = "<!-- END_CLI_HELP:{name} -->"

# argparse renders help differently across releases (3.10 renamed "optional
# arguments:" to "options:"; 3.13 shortened "-o OUTPUT, --output OUTPUT" to
# "-o, --output OUTPUT"). Since we embed that output verbatim, docs/cli.md is
# only reproducible on one version. Keep in sync with the python-version pin
# in .github/workflows/cli-docs-sync.yml.
REQUIRED_PYTHON = (3, 11)
BLOCK_ORDER = [
    "root",
    "plan",
    "discover",
    "validate",
    "export",
    "init",
    "info",
    "gui",
    "completion",
]


def _get_subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:  # type: ignore[attr-defined]
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _render_block(help_text: str) -> str:
    return f"```text\n{help_text.rstrip()}\n```"


def _replace_block(content: str, name: str, replacement: str) -> str:
    start_token = START.format(name=name)
    end_token = END.format(name=name)

    start_idx = content.find(start_token)
    end_idx = content.find(end_token)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        raise ValueError(f"Missing or malformed block markers for '{name}' in {DOCS_PATH}")

    block_start = start_idx + len(start_token)
    return content[:block_start] + "\n" + replacement + "\n" + content[end_idx:]


def generate_docs_content(existing_docs: str) -> str:
    parser = build_parser()
    subparsers = _get_subparsers(parser)

    help_map: dict[str, str] = {"root": parser.format_help()}
    for command in BLOCK_ORDER:
        if command == "root":
            continue
        help_map[command] = subparsers[command].format_help()

    rendered = existing_docs
    for name in BLOCK_ORDER:
        rendered = _replace_block(rendered, name, _render_block(help_map[name]))

    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if docs/cli.md is out of date; do not modify files.",
    )
    args = parser.parse_args()

    if sys.version_info[:2] != REQUIRED_PYTHON:
        want = ".".join(str(p) for p in REQUIRED_PYTHON)
        got = ".".join(str(p) for p in sys.version_info[:3])
        print(
            f"error: docs/cli.md must be generated with Python {want}, but this is {got}.\n"
            f"argparse's help formatting is version-dependent, so running this on "
            f"{got} would silently rewrite docs/cli.md into a form that fails the "
            f"cli-docs-sync check on CI (which pins {want}).",
            file=sys.stderr,
        )
        return 2

    existing = DOCS_PATH.read_text(encoding="utf-8")
    updated = generate_docs_content(existing)

    if args.check:
        if existing != updated:
            print("docs/cli.md is out of date. Run: python scripts/export_cli_help.py")
            return 1
        print("docs/cli.md is up to date.")
        return 0

    if existing != updated:
        DOCS_PATH.write_text(updated, encoding="utf-8")
        print(f"Updated {DOCS_PATH}")
    else:
        print(f"No changes needed in {DOCS_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
