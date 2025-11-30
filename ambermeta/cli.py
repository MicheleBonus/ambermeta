from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

from ambermeta.protocol import (
    SimulationProtocol,
    auto_discover,
    load_protocol_from_manifest,
)


def _prompt(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def _interactive_manifest(directory: str) -> List[Dict[str, Any]]:
    print("Interactive mode: define simulation stages in order. Press Enter without a name to stop.")
    manifest: List[Dict[str, Any]] = []
    kinds = ("prmtop", "inpcrd", "mdin", "mdout", "mdcrd")

    while True:
        name = _prompt("Stage name (blank to finish): ").strip()
        if not name:
            break

        stage_entry: Dict[str, Any] = {"name": name}
        role = _prompt("  Stage role (e.g., minimization, equilibration, production): ").strip()
        if role:
            stage_entry["stage_role"] = role

        print("  Enter file paths relative to", directory)
        for kind in kinds:
            value = _prompt(f"    {kind} file path (optional): ").strip()
            if value:
                stage_entry[kind] = value

        note = _prompt("  Known gaps/notes for this stage (optional): ").strip()
        if note:
            stage_entry["notes"] = [note]

        manifest.append(stage_entry)
        cont = _prompt("Add another stage? [Y/n]: ").strip().lower()
        if cont.startswith("n"):
            break

    return manifest


def _print_protocol(protocol: SimulationProtocol) -> None:
    totals = protocol.totals()
    print("\nProtocol summary")
    print("================")
    print(f"Stages: {len(protocol.stages)}")
    print(f"Total steps: {totals['steps']:.0f}")
    print(f"Total simulated time (ps): {totals['time_ps']:.3f}")

    for stage in protocol.stages:
        summary = stage.summary()
        print(f"\n- {stage.name}")
        print(f"  intent: {summary['intent']}")
        print(f"  result: {summary['result']}")
        if stage.restart_path:
            print(f"  restart: {stage.restart_path}")
        if summary.get("evidence"):
            print(f"  evidence: {summary['evidence']}")
        if stage.validation:
            for note in stage.validation:
                print(f"  note: {note}")


def _plan_command(args: argparse.Namespace) -> int:
    directory = os.path.abspath(args.directory)

    if args.manifest:
        protocol = load_protocol_from_manifest(
            args.manifest,
            directory=directory,
            skip_cross_stage_validation=args.skip_cross_stage_validation,
        )
    else:
        manifest = _interactive_manifest(directory)
        if not manifest:
            print("No stages defined; exiting.")
            return 1

        protocol = auto_discover(
            directory,
            manifest=manifest,
            skip_cross_stage_validation=args.skip_cross_stage_validation,
        )

    _print_protocol(protocol)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ambermeta", description="AmberMeta command-line tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser(
        "plan",
        help="Build and summarize a SimulationProtocol from a manifest or interactive input",
    )
    plan_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory containing the files referenced by the manifest (default: current directory)",
    )
    plan_parser.add_argument(
        "-m",
        "--manifest",
        help="Path to a YAML or JSON manifest describing stages and file paths",
    )
    plan_parser.add_argument(
        "--skip-cross-stage-validation",
        action="store_true",
        help="Skip continuity checks between consecutive stages",
    )

    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "plan":
        return _plan_command(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
