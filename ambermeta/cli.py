from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from typing import Any, Dict, Iterable, List, Optional

from ambermeta.protocol import (
    SimulationProtocol,
    auto_discover,
    load_protocol_from_manifest,
)

try:  # pragma: no cover - optional dependency
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None


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


def _format_avg_std(values: Iterable[float], unit: str, precision: int = 3) -> Optional[str]:
    data = [float(v) for v in values if isinstance(v, (int, float))]
    if not data:
        return None

    avg = statistics.mean(data)
    suffix = f" {unit}" if unit else ""
    if len(data) == 1:
        return f"{avg:.{precision}f}{suffix}"

    stdev = statistics.stdev(data)
    return f"{avg:.{precision}f} ± {stdev:.{precision}f}{suffix}"


def _print_protocol(protocol: SimulationProtocol, verbose: bool = False) -> None:
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
        metadata_lines = []
        if stage.prmtop and stage.prmtop.details:
            prmtop_details = stage.prmtop.details
            prmtop_bits = []
            if getattr(prmtop_details, "natom", None):
                prmtop_bits.append(f"atoms={prmtop_details.natom}")
            if getattr(prmtop_details, "box_dimensions", None):
                dims = prmtop_details.box_dimensions
                if isinstance(dims, (list, tuple)) and len(dims) == 3:
                    prmtop_bits.append(
                        "box="
                        f"{float(dims[0]):.2f}×{float(dims[1]):.2f}×{float(dims[2]):.2f} Å"
                    )
                else:
                    prmtop_bits.append("box=yes")
            if getattr(prmtop_details, "density", None):
                prmtop_bits.append(f"density={float(prmtop_details.density):.3f} g/cc")
            metadata_lines.append(f"  prmtop: {', '.join(prmtop_bits) or 'parsed'}")
        if stage.mdin and stage.mdin.details:
            mdin_details = stage.mdin.details
            mdin_bits = []
            if getattr(mdin_details, "length_steps", None):
                mdin_bits.append(f"steps={mdin_details.length_steps}")
            if getattr(mdin_details, "dt", None):
                mdin_bits.append(f"dt={mdin_details.dt:g} ps")
            metadata_lines.append(f"  mdin: {', '.join(mdin_bits) or 'parsed'}")
        stats_line: Optional[str] = None
        if stage.mdout and stage.mdout.details:
            mdout_details = stage.mdout.details
            mdout_bits = []
            if getattr(mdout_details, "finished_properly", None) is not None:
                status = "complete" if mdout_details.finished_properly else "uncertain"
                mdout_bits.append(f"status={status}")
            if getattr(mdout_details, "nstlim", None):
                mdout_bits.append(f"steps={mdout_details.nstlim}")
            if getattr(mdout_details, "dt", None):
                mdout_bits.append(f"dt={mdout_details.dt:g} ps")
            if getattr(mdout_details, "thermostat", None):
                thermostat = mdout_details.thermostat
                target = getattr(mdout_details, "target_temp", None)
                if target:
                    thermostat = f"{thermostat} @ {target:g} K"
                mdout_bits.append(f"thermostat={thermostat}")
            if getattr(mdout_details, "barostat", None) and mdout_details.barostat != "None":
                mdout_bits.append(f"barostat={mdout_details.barostat}")
            if getattr(mdout_details, "box_type", None):
                mdout_bits.append(f"box={mdout_details.box_type}")

            stats_bits = []
            stats = getattr(mdout_details, "stats", None)
            if stats:
                if getattr(stats, "count", 0):
                    stats_bits.append(f"frames={stats.count}")
                if getattr(stats, "time_start", None) is not None and getattr(stats, "time_end", None) is not None:
                    stats_bits.append(
                        f"time={float(stats.time_start):g}–{float(stats.time_end):g} ps"
                    )
                temp_stats = _format_avg_std(getattr(stats, "temps", []), "K", precision=2)
                if temp_stats:
                    stats_bits.append(f"temp={temp_stats}")
                density_stats = _format_avg_std(
                    getattr(stats, "densities", []), "g/cc", precision=4
                )
                if density_stats:
                    stats_bits.append(f"density={density_stats}")
            if stats_bits:
                stats_line = f"  stats: {', '.join(stats_bits)}"

            metadata_lines.append(f"  mdout: {', '.join(mdout_bits) or 'parsed'}")
        if stage.mdcrd and stage.mdcrd.details:
            mdcrd_details = stage.mdcrd.details
            mdcrd_bits = []
            if getattr(mdcrd_details, "n_frames", None):
                mdcrd_bits.append(f"frames={mdcrd_details.n_frames}")
            if getattr(mdcrd_details, "time_start", None) is not None and getattr(mdcrd_details, "time_end", None) is not None:
                mdcrd_bits.append(
                    f"time={mdcrd_details.time_start:g}–{mdcrd_details.time_end:g} ps"
                )
            if getattr(mdcrd_details, "avg_dt", None):
                mdcrd_bits.append(f"dt≈{mdcrd_details.avg_dt:g} ps")
            if getattr(mdcrd_details, "has_box", False):
                box_desc = "box"
                if getattr(mdcrd_details, "box_type", None):
                    box_desc = f"box={mdcrd_details.box_type}"
                if getattr(mdcrd_details, "volume_stats", None):
                    volume_stats = mdcrd_details.volume_stats
                    if (
                        isinstance(volume_stats, (list, tuple))
                        and len(volume_stats) == 3
                        and all(isinstance(v, (int, float)) for v in volume_stats)
                    ):
                        box_desc += f", volume≈{float(volume_stats[2]):.2f} Å³"
                mdcrd_bits.append(box_desc)
            if getattr(mdcrd_details, "is_remd", False):
                remd_types = getattr(mdcrd_details, "remd_types", []) or []
                remd_desc = ", ".join(remd_types) if remd_types else "REMD"
                temps = getattr(mdcrd_details, "remd_temp_stats", None)
                if (
                    isinstance(temps, (list, tuple))
                    and len(temps) == 3
                    and all(isinstance(v, (int, float)) for v in temps)
                ):
                    remd_desc += f" ({temps[0]:.1f}–{temps[1]:.1f}K, avg {temps[2]:.1f}K)"
                mdcrd_bits.append(remd_desc)
            metadata_lines.append(f"  mdcrd: {', '.join(mdcrd_bits) or 'parsed'}")
        if stage.inpcrd and stage.inpcrd.details:
            inpcrd_details = stage.inpcrd.details
            inpcrd_bits = []
            if getattr(inpcrd_details, "natoms", None):
                inpcrd_bits.append(f"atoms={inpcrd_details.natoms}")
            if getattr(inpcrd_details, "has_box", False):
                inpcrd_bits.append("box")
            if getattr(inpcrd_details, "time", None) is not None:
                inpcrd_bits.append(f"time={inpcrd_details.time:g} ps")
            if inpcrd_bits:
                metadata_lines.append(f"  inpcrd: {', '.join(inpcrd_bits)}")
        if metadata_lines:
            for line in metadata_lines:
                print(line)
        if stats_line:
            print(stats_line)
        if stage.restart_path:
            print(f"  restart: {stage.restart_path}")
        if summary.get("evidence"):
            print(f"  evidence: {summary['evidence']}")
        if stage.validation:
            for note in stage.validation:
                print(f"  note: {note}")
        if verbose:
            print("  details:")
            stage_payload = stage.to_dict()
            for key in ("files", "validation", "continuity"):
                if key not in stage_payload:
                    continue
                block = stage_payload[key]
                if key == "files":
                    for file_kind, metadata in block.items():
                        if metadata is None:
                            continue
                        print(f"    {file_kind}:")
                        print(f"      file: {metadata.get('filename')}")
                        warnings = metadata.get("warnings") or []
                        for warn in warnings:
                            print(f"      warning: {warn}")
                        details = metadata.get("details")
                        if details:
                            for line in json.dumps(details, indent=6).splitlines():
                                print(f"      detail: {line}")
                else:
                    if not block:
                        continue
                    label = "validation" if key == "validation" else "continuity"
                    for item in block:
                        print(f"    {label}: {item}")


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

    _print_protocol(protocol, verbose=args.verbose)

    if args.summary_path:
        payload = protocol.to_dict()
        summary_format = args.summary_format
        if summary_format is None:
            _, ext = os.path.splitext(args.summary_path)
            ext = ext.lower().lstrip(".")
            if ext in {"yaml", "yml"}:
                summary_format = "yaml"
            else:
                summary_format = "json"
        if summary_format == "json":
            with open(args.summary_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
        elif summary_format == "yaml":
            if yaml is None:
                raise RuntimeError("PyYAML is required to write YAML summaries.")
            with open(args.summary_path, "w", encoding="utf-8") as fh:
                yaml.safe_dump(payload, fh, sort_keys=False)
        else:
            raise ValueError(f"Unsupported summary format: {summary_format}")
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
    plan_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed metadata, warnings, and continuity information for each stage",
    )
    plan_parser.add_argument(
        "--summary-path",
        help="Path to write a structured protocol summary (JSON or YAML)",
    )
    plan_parser.add_argument(
        "--summary-format",
        choices=["json", "yaml"],
        help="Force the structured summary format (default: inferred from file extension)",
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
