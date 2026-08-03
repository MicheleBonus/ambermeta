from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from ambermeta.errors import AmberMetaError
from ambermeta.logging_config import configure_logging, get_logger
from ambermeta.roles import classify_role
from ambermeta.protocol import (
    SimulationProtocol,
    auto_discover,
)

try:  # pragma: no cover - optional dependency
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

# Module logger
logger = get_logger(__name__)

# Quiet-mode flag — set to True by main() when -q/--quiet is passed.
_QUIET = False


def _out(*args, **kwargs) -> None:
    """Print to stdout only when quiet mode is not active."""
    if not _QUIET:
        print(*args, **kwargs)


def _prompt(prompt: str, default: str = "") -> str:
    """Enhanced prompt with default value support."""
    try:
        if default:
            result = input(f"{prompt} [{default}]: ").strip()
            return result if result else default
        return input(prompt).strip()
    except EOFError:
        return default


# UX-003: Progress indicator for file processing
class ProgressIndicator:
    """Simple progress indicator for terminal output."""

    def __init__(self, total: int, description: str = "Processing"):
        self.total = total
        self.current = 0
        self.description = description
        self.enabled = sys.stdout.isatty()

    def update(self, item: str = "") -> None:
        """Update progress display."""
        self.current += 1
        if self.enabled:
            percent = (self.current / self.total * 100) if self.total > 0 else 100
            item_display = f" ({item})" if item else ""
            sys.stdout.write(f"\r{self.description}: {self.current}/{self.total} [{percent:.0f}%]{item_display}    ")
            sys.stdout.flush()

    def finish(self) -> None:
        """Complete progress and move to new line."""
        if self.enabled:
            sys.stdout.write("\n")
            sys.stdout.flush()


# UX-006: Enhanced interactive manifest creation
def _interactive_manifest(directory: str) -> List[Dict[str, Any]]:
    """Interactive mode for creating simulation manifests with guided prompts."""
    _out("\n" + "=" * 60)
    _out("  AmberMeta Interactive Protocol Builder")
    _out("=" * 60)
    _out("\nDefine your simulation stages in order.")
    _out("Press Enter without a name to finish, or 'q' to quit.\n")
    _out("Common stage roles: minimization, heating, equilibration, production\n")

    manifest: List[Dict[str, Any]] = []
    kinds = ("prmtop", "mdin", "mdout", "mdcrd")
    stage_num = 1

    # Scan directory for existing files to help with suggestions
    available_files = _scan_directory_files(directory)

    while True:
        _out(f"\n--- Stage {stage_num} ---")
        name = _prompt("Stage name (blank to finish, 'q' to quit): ").strip()
        if not name:
            break
        if name.lower() == 'q':
            if manifest:
                confirm = _prompt("Discard all stages? [y/N]: ").strip().lower()
                if confirm == 'y':
                    return []
            else:
                return []
            continue

        stage_entry: Dict[str, Any] = {"name": name}

        # Suggest role based on name
        suggested_role = _suggest_stage_role(name)
        role = _prompt(f"  Stage role", default=suggested_role).strip()
        if role:
            stage_entry["stage_role"] = role

        _out(f"\n  Enter file paths relative to: {directory}")
        if available_files:
            _out(f"  (Found {sum(len(v) for v in available_files.values())} simulation files)")

        for kind in kinds:
            # Show suggestions if available
            suggestions = available_files.get(kind, [])
            if suggestions:
                _out(f"    Available {kind} files: {', '.join(suggestions[:3])}" +
                     (f" (+{len(suggestions)-3} more)" if len(suggestions) > 3 else ""))
            value = _prompt(f"    {kind} file path (optional): ").strip()
            if value:
                stage_entry[kind] = value

        restart_path = _prompt("  Restart/inpcrd file path (optional): ").strip()
        if restart_path:
            stage_entry["inpcrd"] = restart_path

        # Gap configuration with better explanation
        use_gaps = _prompt("  Configure expected gaps? [y/N]: ").strip().lower()
        if use_gaps == 'y':
            gaps: Dict[str, float] = {}
            expected_gap = _prompt("    Expected gap between frames (ps): ").strip()
            if expected_gap:
                try:
                    gaps["expected"] = float(expected_gap)
                except ValueError:
                    _out("    Invalid number; skipping.")
            tolerance = _prompt("    Gap tolerance (ps): ", default="0.1").strip()
            if tolerance:
                try:
                    gaps["tolerance"] = float(tolerance)
                except ValueError:
                    _out("    Invalid number; using default 0.1.")
                    gaps["tolerance"] = 0.1
            if gaps:
                stage_entry["gaps"] = gaps

        note = _prompt("  Notes for this stage (optional): ").strip()
        if note:
            stage_entry["notes"] = [note]

        manifest.append(stage_entry)
        stage_num += 1

        # Summary of added stage
        _out(f"\n  Added stage: {name}" + (f" ({role})" if role else ""))

        cont = _prompt("Add another stage? [Y/n]: ").strip().lower()
        if cont.startswith("n"):
            break

    if manifest:
        _out(f"\n{len(manifest)} stage(s) defined.")

    return manifest


def _scan_directory_files(directory: str) -> Dict[str, List[str]]:
    """Scan directory for common AMBER simulation files."""
    files: Dict[str, List[str]] = {
        "prmtop": [],
        "mdin": [],
        "mdout": [],
        "mdcrd": [],
        "inpcrd": [],
    }

    try:
        for f in os.listdir(directory):
            ext = os.path.splitext(f)[1].lower()
            fl = f.lower()

            if ext in (".in", ".mdin") or "mdin" in fl:
                files["mdin"].append(f)
            elif ext in (".out", ".mdout") or "mdout" in fl:
                files["mdout"].append(f)
            elif ext in (".nc",) or ("mdcrd" in fl and ext != ".in"):
                files["mdcrd"].append(f)
            elif ext in (".rst", ".rst7", ".ncrst", ".inpcrd"):
                files["inpcrd"].append(f)
            elif ext in (".prmtop", ".parm7", ".top") or "prmtop" in fl:
                files["prmtop"].append(f)
    except OSError:
        pass

    return files


def _suggest_stage_role(name: str) -> str:
    """Suggest a stage role based on the stage name."""
    return classify_role(name)


def _topology_path(sim, topo_id: Optional[str]) -> str:
    for t in sim.topologies:
        if t.id == topo_id:
            return t.path
    return topo_id or "no topology"


def _input_source_label(sim, step) -> str:
    """Where this step's coordinates come from, in words.

    Names the step it continues from, not that step's id: ids are uuid4 hex slices, so
    printing the raw ref said the run started from something called "bd573ee9".
    """
    from ambermeta.simulation import iter_steps, resolve_input_coords

    ic = step.input_coords
    if ic.source == "starting_structure":
        return "starting structure"
    if ic.source == "step":
        if not ic.ref:
            return "previous step"
        name = next((s.name for _, s in iter_steps(sim) if s.id == ic.ref), None)
        if name is None:
            return f"step {ic.ref} (missing)"
        resolved = resolve_input_coords(sim, step)
        return f"restart of {name}" + (f" ({resolved})" if resolved else "")
    return ic.path or "?"


def _print_simulation(sim, report=None, *, verbose: bool = False) -> None:
    """Print the three-level Simulation structure (pool, starting structure, phases→steps)."""
    _out("\nSimulation summary")
    _out("==================")
    _out(f"Topologies (pool): {len(sim.topologies)}")
    for t in sim.topologies:
        _out(f"  - {t.id} [{t.kind}]  {t.path}")
    _out(f"Starting structure: {sim.starting_structure or '(none)'}")
    _out(f"Phases: {len(sim.phases)}")
    for phase in sim.phases:
        role = phase.role or "unclassified"
        _out(f"\nPhase: {phase.name} [{role}]")
        for step in phase.steps:
            topo = _topology_path(sim, step.topology) if step.topology else "no topology"
            files = ", ".join(
                f"{k}={getattr(step, k)}" for k in ("mdin", "mdout", "mdcrd") if getattr(step, k)
            )
            line = f"  - {step.name}  topology={topo}  input={_input_source_label(sim, step)}"
            _out(line + (f"  ({files})" if files else ""))
    if report is not None:
        if verbose:
            for issue in report.get("stage_issues", []):
                lines = ((issue.get("errors") or []) + (issue.get("warnings") or [])
                         + (issue.get("info") or []))
                for line in lines:
                    _out(f"    {issue['name']}: {line}")
        _sim_findings(report)


def _sim_findings(report) -> None:
    """Print continuity/sequence findings + protocol notes + an overall status line."""
    suggestions = report.get("suggestions", []) or []
    findings = [s for s in suggestions if s.get("kind") in ("continuity_gap", "missing_run")]
    if findings:
        _out("\nContinuity / sequence findings:")
        for s in findings:
            _out(f"  - {s.get('title')}: {s.get('evidence')}")
    issues = report.get("protocol_issues", []) or []
    if issues:
        _out("\nProtocol notes:")
        for note in issues:
            _out(f"  - {note}")
    _out(f"\nValidation: {'OK' if report.get('ok') else 'ISSUES FOUND'}")


def _resolve_sim_format(path: str, requested: Optional[str]) -> str:
    """Choose a v2 serialization format: explicit request, else by extension, else json."""
    if requested:
        return requested
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return "yaml" if ext in ("yaml", "yml") else "json"


def _discover_command(args: argparse.Namespace) -> int:
    """Discover-as-draft: scan a directory into a Simulation draft; optionally write v2."""
    from ambermeta.gui.api.core_bridge import discover_draft

    directory = os.path.abspath(args.directory)
    if not os.path.isdir(directory):
        print(Colors.error(f"ERROR: Directory not found: {directory}"), file=sys.stderr)
        return 1

    result = discover_draft(directory, recursive=args.recursive, pattern=args.pattern)
    sim = result["simulation"]
    if not sim.phases:
        _out("No simulation files discovered; nothing to draft.")
        return 1

    _print_simulation(sim)
    for w in result.get("warnings", []) or []:
        _out(Colors.warning(f"WARNING: {w}"))
    suggestions = result.get("suggestions", []) or []
    if suggestions:
        _out("\nSuggestions:")
        for s in suggestions:
            _out(f"  - [{s.get('severity')}] {s.get('title')}")

    if getattr(args, "write", None):
        from ambermeta.simulation import write_simulation
        fmt = _resolve_sim_format(args.write, getattr(args, "format", None))
        write_simulation(sim, args.write, fmt)
        _out(Colors.success(f"\nWrote v2 draft manifest: {args.write} ({fmt})"))
    return 0


def _export_command(args: argparse.Namespace) -> int:
    """Load a v2 manifest and re-emit it as canonical v2, optionally converting format."""
    from ambermeta.simulation import load_simulation, write_simulation, simulation_to_payload

    manifest = args.manifest
    if not os.path.exists(manifest):
        print(Colors.error(f"ERROR: Manifest not found: {manifest}"), file=sys.stderr)
        return 1
    try:
        sim = load_simulation(manifest)
    except (IOError, OSError, ValueError, RuntimeError, AmberMetaError) as e:
        print(Colors.error(f"ERROR: Failed to load manifest: {e}"), file=sys.stderr)
        return 1

    if args.output:
        fmt = _resolve_sim_format(args.output, getattr(args, "format", None))
        write_simulation(sim, args.output, fmt)
        _out(Colors.success(f"Wrote v2 manifest: {args.output} ({fmt})"))
    else:
        print(json.dumps(simulation_to_payload(sim), indent=2))
    return 0


def _print_protocol(protocol: SimulationProtocol, verbose: bool = False) -> None:
    totals = protocol.totals()
    _out("\nProtocol summary")
    _out("================")
    _out(f"Stages: {len(protocol.stages)}")
    _out(f"Total steps: {totals['steps']:.0f}")
    _out(f"Total simulated time (ps): {totals['time_ps']:.3f}")

    for stage in protocol.stages:
        summary = stage.summary()
        _out(f"\n- {stage.name}")
        _out(f"  intent: {summary['intent']}")
        _out(f"  result: {summary['result']}")
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
                # Use streaming stats (temp_stats, density_stats) instead of empty list properties
                temp_streaming = getattr(stats, "temp_stats", None)
                if temp_streaming and hasattr(temp_streaming, "get_stats"):
                    t_avg, t_std = temp_streaming.get_stats()
                    if t_avg is not None:
                        stats_bits.append(f"temp={t_avg:.2f} ± {t_std:.2f} K")
                density_streaming = getattr(stats, "density_stats", None)
                if density_streaming and hasattr(density_streaming, "get_stats"):
                    d_avg, d_std = density_streaming.get_stats()
                    if d_avg is not None:
                        stats_bits.append(f"density={d_avg:.4f} ± {d_std:.4f} g/cc")
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
                _out(line)
        if stats_line:
            _out(stats_line)
        if stage.restart_path:
            _out(f"  restart: {stage.restart_path}")
        if summary.get("evidence"):
            _out(f"  evidence: {summary['evidence']}")
        if stage.validation:
            for note in stage.validation:
                _out(f"  note: {note}")
        if verbose:
            _out("  details:")
            stage_payload = stage.to_dict()
            for key in ("files", "validation", "continuity"):
                if key not in stage_payload:
                    continue
                block = stage_payload[key]
                if key == "files":
                    for file_kind, metadata in block.items():
                        if metadata is None:
                            continue
                        _out(f"    {file_kind}:")
                        _out(f"      file: {metadata.get('filename')}")
                        warnings = metadata.get("warnings") or []
                        for warn in warnings:
                            _out(f"      warning: {warn}")
                        details = metadata.get("details")
                        if details:
                            for line in json.dumps(details, indent=6).splitlines():
                                _out(f"      detail: {line}")
                else:
                    if not block:
                        continue
                    label = "validation" if key == "validation" else "continuity"
                    for item in block:
                        _out(f"    {label}: {item}")


# UX-004: Color codes for terminal output
class Colors:
    """ANSI color codes for terminal output."""
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"

    @classmethod
    def enabled(cls) -> bool:
        """Check if colors should be enabled."""
        return sys.stdout.isatty()

    @classmethod
    def success(cls, text: str) -> str:
        return f"{cls.GREEN}{text}{cls.RESET}" if cls.enabled() else text

    @classmethod
    def warning(cls, text: str) -> str:
        return f"{cls.YELLOW}{text}{cls.RESET}" if cls.enabled() else text

    @classmethod
    def error(cls, text: str) -> str:
        return f"{cls.RED}{text}{cls.RESET}" if cls.enabled() else text

    @classmethod
    def info(cls, text: str) -> str:
        return f"{cls.CYAN}{text}{cls.RESET}" if cls.enabled() else text

    @classmethod
    def header(cls, text: str) -> str:
        return f"{cls.BOLD}{cls.BLUE}{text}{cls.RESET}" if cls.enabled() else text


def _get_parser_for_file(filepath: str):
    """Determine the appropriate parser based on file extension."""
    from ambermeta.parsers.prmtop import PrmtopParser
    from ambermeta.parsers.mdin import MdinParser
    from ambermeta.parsers.mdout import MdoutParser
    from ambermeta.parsers.mdcrd import MdcrdParser
    from ambermeta.parsers.inpcrd import InpcrdParser

    ext = os.path.splitext(filepath)[1].lower()
    basename = os.path.basename(filepath).lower()

    # Match by extension or basename pattern
    if ext in (".prmtop", ".parm7", ".top"):
        return PrmtopParser(filepath)
    elif ext in (".in", ".mdin") or "mdin" in basename:
        return MdinParser(filepath)
    elif ext in (".out", ".mdout") or "mdout" in basename:
        return MdoutParser(filepath)
    elif ext in (".nc", ".mdcrd", ".crd", ".x") or "mdcrd" in basename:
        return MdcrdParser(filepath)
    elif ext in (".rst", ".rst7", ".ncrst", ".inpcrd", ".restrt"):
        return InpcrdParser(filepath)
    elif "prmtop" in basename or "parm" in basename:
        return PrmtopParser(filepath)
    elif "inpcrd" in basename or "restrt" in basename:
        return InpcrdParser(filepath)

    # Default: try to guess from content
    logger.warning(f"Unknown file type for {filepath}, attempting auto-detection")
    return None


def _validate_command(args: argparse.Namespace) -> int:
    """Validate simulation files and report issues."""
    manifest = getattr(args, "manifest", None)
    if manifest:
        return _validate_manifest(args, manifest)
    if not getattr(args, "files", None):
        print("ERROR: provide files to validate or --manifest.", file=sys.stderr)
        return 2
    result: Dict[str, Any] = {
        "status": "ok",
        "files": [],
        "warnings": [],
        "errors": [],
    }

    for filepath in args.files:
        file_result: Dict[str, Any] = {
            "file": filepath,
            "status": "ok",
            "warnings": [],
            "errors": [],
        }

        if not os.path.exists(filepath):
            message = f"File not found: {filepath}"
            file_result["status"] = "error"
            file_result["errors"].append(message)
            result["errors"].append({"file": filepath, "message": message})
            result["files"].append(file_result)
            continue

        parser = _get_parser_for_file(filepath)
        if parser is None:
            message = f"Unknown file type: {filepath}"
            file_result["status"] = "warning"
            file_result["warnings"].append(message)
            result["warnings"].append({"file": filepath, "message": message})
            result["files"].append(file_result)
            continue

        try:
            parse_result = parser.parse()
            warnings = getattr(parse_result, "warnings", []) or []

            if warnings:
                file_result["status"] = "warning"
                for warn in warnings:
                    file_result["warnings"].append(str(warn))
                    result["warnings"].append({"file": filepath, "message": str(warn)})

        except (IOError, OSError, ValueError) as e:
            message = str(e)
            file_result["status"] = "error"
            file_result["errors"].append(message)
            result["errors"].append({"file": filepath, "message": message})

        result["files"].append(file_result)

    has_errors = bool(result["errors"])
    has_warnings = bool(result["warnings"])

    if has_errors:
        result["status"] = "error"
    elif has_warnings:
        result["status"] = "warning"

    if args.format == "json":
        print(json.dumps(result, indent=2))
    elif args.format == "yaml":
        if yaml is None:
            print(Colors.error("ERROR: PyYAML is required for YAML output"))
            return 1
        print(yaml.safe_dump(result, sort_keys=False))
    else:
        _out(Colors.header("\nValidation Results"))
        _out("=" * 50)

        for file_result in result["files"]:
            filepath = file_result["file"]
            status = file_result["status"]
            if status == "error":
                _out(f"\n{Colors.error('ERROR')}: {filepath}")
                for err in file_result["errors"]:
                    _out(f"  - {err}")
            elif status == "warning":
                _out(f"\n{Colors.warning('WARN')}: {filepath}")
                for warn in file_result["warnings"]:
                    _out(f"  - {warn}")
            else:
                _out(f"\n{Colors.success('OK')}: {filepath}")

        _out("\n" + "=" * 50)
        if has_errors:
            _out(Colors.error("Validation FAILED with errors"))
        elif has_warnings and args.strict:
            _out(Colors.warning("Validation FAILED (strict mode, warnings present)"))
        elif has_warnings:
            _out(Colors.warning("Validation PASSED with warnings"))
        else:
            _out(Colors.success("Validation PASSED"))

    if has_errors:
        return 1
    if has_warnings and args.strict:
        return 1
    return 0


def _validate_manifest(args: argparse.Namespace, manifest: str) -> int:
    """Validate a whole Simulation manifest: continuity, sequence holes, suggestions."""
    from ambermeta.simulation import load_simulation
    from ambermeta.gui.api.core_bridge import validate_simulation

    if not os.path.exists(manifest):
        print(Colors.error(f"ERROR: Manifest not found: {manifest}"), file=sys.stderr)
        return 1
    try:
        sim = load_simulation(manifest)
    except (IOError, OSError, ValueError, RuntimeError, AmberMetaError) as e:
        print(Colors.error(f"ERROR: Failed to load manifest: {e}"), file=sys.stderr)
        return 1

    base_dir = os.path.dirname(os.path.abspath(manifest)) or "."
    settings = {
        "strict_validation": True,
        "allow_gaps": bool(getattr(args, "allow_gaps", False)),
        "use_relative_paths": True,
    }
    report = validate_simulation(sim, settings, base_dir)

    if args.format == "json":
        print(json.dumps(report, indent=2))
    elif args.format == "yaml":
        if yaml is None:
            print(Colors.error("ERROR: PyYAML is required for YAML output"), file=sys.stderr)
            return 1
        print(yaml.safe_dump(report, sort_keys=False))
    else:
        _out(Colors.header("\nSimulation validation"))
        for stage in report.get("stage_issues", []):
            for err in stage.get("errors", []):
                _out(f"  {Colors.error('ERROR')} {stage['name']}: {err}")
        _sim_findings(report)

    ok = bool(report.get("ok", True))
    findings = [s for s in report.get("suggestions", []) if s.get("kind") in ("continuity_gap", "missing_run")]
    if not ok:
        return 1
    if args.strict and findings:
        return 1
    return 0


def _info_command(args: argparse.Namespace) -> int:
    """Display detailed metadata for a single file."""
    filepath = args.file

    if not os.path.exists(filepath):
        print(Colors.error(f"ERROR: File not found: {filepath}"), file=sys.stderr)
        return 1

    parser = _get_parser_for_file(filepath)
    if parser is None:
        print(Colors.error(f"ERROR: Unknown file type: {filepath}"), file=sys.stderr)
        return 1

    try:
        result = parser.parse()
        details = getattr(result, "details", None)

        if args.format == "json":
            from ambermeta.protocol import _serialize_value
            payload = _serialize_value(details) if details else {}
            print(json.dumps(payload, indent=2))
        elif args.format == "yaml":
            if yaml is None:
                print(Colors.error("ERROR: PyYAML is required for YAML output"))
                return 1
            from ambermeta.protocol import _serialize_value
            payload = _serialize_value(details) if details else {}
            print(yaml.safe_dump(payload, sort_keys=False))
        else:
            # Text format
            _out(Colors.header(f"\nFile Information: {os.path.basename(filepath)}"))
            _out("=" * 60)

            if details:
                for key, value in vars(details).items():
                    if key.startswith("_"):
                        continue
                    if isinstance(value, (list, dict)) and not value:
                        continue
                    _out(f"  {key}: {value}")

            warnings = getattr(result, "warnings", []) or []
            if warnings:
                _out(f"\n{Colors.warning('Warnings:')}")
                for warn in warnings:
                    _out(f"  - {warn}")

        return 0

    except (IOError, OSError, ValueError) as e:
        print(Colors.error(f"ERROR: Failed to parse file: {e}"), file=sys.stderr)
        return 1


def _completion_script(shell: str) -> str:
    """Return a shell completion script for the requested shell."""
    scripts = {
        "bash": r'''# ambermeta bash completion
_ambermeta_completion() {
    local cur prev
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    local commands="plan discover validate info init export gui completion"
    local global_opts="--help --log-level --log-file --quiet -q"

    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${commands} ${global_opts}" -- "$cur") )
        return 0
    fi

    case "${COMP_WORDS[1]}" in
        plan)
            COMPREPLY=( $(compgen -W "--help -m --manifest --skip-cross-stage-validation --strict --recursive --interactive -v --verbose --summary-path --summary-format --methods-summary-path --stats-csv --no-expand-env --pattern --auto-detect-restarts --prmtop" -- "$cur") )
            ;;
        discover)
            COMPREPLY=( $(compgen -W "--help --recursive --no-recursive --pattern --write --format" -- "$cur") )
            ;;
        validate)
            COMPREPLY=( $(compgen -W "--help --strict --format --manifest --allow-gaps" -- "$cur") )
            ;;
        info)
            COMPREPLY=( $(compgen -W "--help --format" -- "$cur") )
            ;;
        init)
            COMPREPLY=( $(compgen -W "--help -o --output --force" -- "$cur") )
            ;;
        export)
            COMPREPLY=( $(compgen -W "--help -o --output --format" -- "$cur") )
            ;;
        gui)
            COMPREPLY=( $(compgen -W "--help --host --port --no-browser" -- "$cur") )
            ;;
        completion)
            COMPREPLY=( $(compgen -W "--help bash zsh fish" -- "$cur") )
            ;;
    esac

    if [[ ${#COMPREPLY[@]} -eq 0 && "$cur" != -* ]]; then
        COMPREPLY=( $(compgen -f -- "$cur") )
    fi
}

complete -F _ambermeta_completion ambermeta
''',
        "zsh": r'''#compdef ambermeta

_ambermeta() {
  local -a commands
  commands=(
    'plan:Build and summarize a SimulationProtocol'
    'discover:Discover files into a Simulation draft (v2)'
    'export:Re-emit a v2 manifest, optionally converting its format'
    'validate:Validate simulation files'
    'info:Display metadata for a single file'
    'init:Generate a starting v2 manifest file'
    'gui:Launch web-based GUI'
    'completion:Print shell completion script'
  )

  _arguments \
    '--log-level[Set logging level]:level:(DEBUG INFO WARNING ERROR)' \
    '--log-file[Write logs to a file]:file:_files' \
    '(-q --quiet)'{-q,--quiet}'[Suppress all output except errors]' \
    '1:command:->cmds' \
    '*::arg:->args'

  case $state in
    cmds)
      _describe 'ambermeta command' commands
      ;;
    args)
      case "$words[2]" in
        plan)
          _arguments '--manifest[Path to manifest file]:file:_files' '--recursive[Auto-discover files]' '--interactive[Prompt for stages]' '--summary-path[Write protocol summary]:file:_files' '--summary-format[Summary format]:format:(json yaml)' '--methods-summary-path[Write methods summary]:file:_files' '--stats-csv[Write stats CSV]:file:_files' '--pattern[Regex file filter]:pattern:' '--prmtop[Global topology file]:file:_files' '--skip-cross-stage-validation[Skip continuity checks]' '--strict[Abort on first unreadable file]' '--no-expand-env[Disable env var expansion]' '--auto-detect-restarts[Link restarts automatically]' '(-v --verbose)'{-v,--verbose}'[Show detailed stage metadata]' '*:path:_files'
          ;;
        discover)
          _arguments '(--recursive --no-recursive)'{--recursive,--no-recursive}'[Recurse into subdirectories]' '--pattern[Regex file filter]:pattern:' '--write[Write v2 manifest to path]:file:_files' '--format[Format for --write]:format:(json yaml)' '*:path:_files'
          ;;
        export)
          _arguments '(-o --output)'{-o,--output}'[Output path]:file:_files' '--format[Output format]:format:(json yaml)' '1:manifest:_files'
          ;;
        validate)
          _arguments '--strict[Treat warnings as errors]' '--format[Output format]:format:(text json yaml)' '--manifest[Validate a whole simulation manifest]:file:_files' '--allow-gaps[Treat unexpected inter-step gaps as allowed]' '*:file:_files'
          ;;
        info)
          _arguments '--format[Output format]:format:(text json yaml)' '1:file:_files'
          ;;
        init)
          _arguments '(-o --output)'{-o,--output}'[Manifest output filename]:file:_files' '--force[Overwrite existing output]' '*:path:_files'
          ;;
        gui)
          _arguments '--host[Host interface]' '--port[Port number]' '--no-browser[Do not open browser after server starts]' '*:path:_files'
          ;;
        completion)
          _arguments '1:shell:(bash zsh fish)'
          ;;
      esac
      ;;
  esac
}

_ambermeta "$@"
''',
        "fish": r'''# ambermeta fish completion
complete -c ambermeta -f

complete -c ambermeta -n "__fish_use_subcommand" -a "plan" -d "Build and summarize a SimulationProtocol"
complete -c ambermeta -n "__fish_use_subcommand" -a "discover" -d "Discover files into a Simulation draft (v2)"
complete -c ambermeta -n "__fish_use_subcommand" -a "export" -d "Re-emit a v2 manifest, optionally converting its format"
complete -c ambermeta -n "__fish_use_subcommand" -a "validate" -d "Validate simulation files"
complete -c ambermeta -n "__fish_use_subcommand" -a "info" -d "Display metadata for a single file"
complete -c ambermeta -n "__fish_use_subcommand" -a "init" -d "Generate a starting v2 manifest file"
complete -c ambermeta -n "__fish_use_subcommand" -a "gui" -d "Launch web-based GUI"
complete -c ambermeta -n "__fish_use_subcommand" -a "completion" -d "Print shell completion script"

complete -c ambermeta -s q -l quiet -d "Suppress all output except errors"
complete -c ambermeta -l log-level -d "Set logging level" -xa "DEBUG INFO WARNING ERROR"
complete -c ambermeta -l log-file -d "Write logs to a file"

complete -c ambermeta -n "__fish_seen_subcommand_from plan" -l manifest -d "Path to a YAML or JSON manifest"
complete -c ambermeta -n "__fish_seen_subcommand_from plan" -l skip-cross-stage-validation -d "Skip continuity checks"
complete -c ambermeta -n "__fish_seen_subcommand_from plan" -l strict -d "Abort on first unreadable file"
complete -c ambermeta -n "__fish_seen_subcommand_from plan" -l recursive -d "Auto-discover simulation files recursively"
complete -c ambermeta -n "__fish_seen_subcommand_from plan" -l interactive -d "Enable interactive prompt mode"
complete -c ambermeta -n "__fish_seen_subcommand_from plan" -s v -l verbose -d "Show detailed metadata"
complete -c ambermeta -n "__fish_seen_subcommand_from plan" -l summary-path -d "Write protocol summary"
complete -c ambermeta -n "__fish_seen_subcommand_from plan" -l summary-format -d "Summary format" -xa "json yaml"
complete -c ambermeta -n "__fish_seen_subcommand_from plan" -l methods-summary-path -d "Write methods summary JSON"
complete -c ambermeta -n "__fish_seen_subcommand_from plan" -l stats-csv -d "Export per-stage statistics"
complete -c ambermeta -n "__fish_seen_subcommand_from plan" -l no-expand-env -d "Disable environment var expansion"
complete -c ambermeta -n "__fish_seen_subcommand_from plan" -l pattern -d "Regex filter for discovered files"
complete -c ambermeta -n "__fish_seen_subcommand_from plan" -l auto-detect-restarts -d "Auto-link restart files"
complete -c ambermeta -n "__fish_seen_subcommand_from plan" -l prmtop -d "Global prmtop file"

complete -c ambermeta -n "__fish_seen_subcommand_from discover" -l recursive -d "Recurse into subdirectories"
complete -c ambermeta -n "__fish_seen_subcommand_from discover" -l no-recursive -d "Do not recurse"
complete -c ambermeta -n "__fish_seen_subcommand_from discover" -l pattern -d "Regex file filter"
complete -c ambermeta -n "__fish_seen_subcommand_from discover" -l write -d "Write v2 manifest to path"
complete -c ambermeta -n "__fish_seen_subcommand_from discover" -l format -d "Format for --write" -xa "json yaml"

complete -c ambermeta -n "__fish_seen_subcommand_from export" -s o -l output -d "Output path"
complete -c ambermeta -n "__fish_seen_subcommand_from export" -l format -d "Output format" -xa "json yaml"

complete -c ambermeta -n "__fish_seen_subcommand_from validate" -l strict -d "Treat warnings as errors"
complete -c ambermeta -n "__fish_seen_subcommand_from validate" -l format -d "Output format" -xa "text json yaml"
complete -c ambermeta -n "__fish_seen_subcommand_from validate" -l manifest -d "Validate a whole simulation manifest (v2)"
complete -c ambermeta -n "__fish_seen_subcommand_from validate" -l allow-gaps -d "Treat unexpected inter-step gaps as allowed"

complete -c ambermeta -n "__fish_seen_subcommand_from info" -l format -d "Output format" -xa "text json yaml"

complete -c ambermeta -n "__fish_seen_subcommand_from init" -s o -l output -d "Output manifest filename"
complete -c ambermeta -n "__fish_seen_subcommand_from init" -l force -d "Overwrite output without prompting"

complete -c ambermeta -n "__fish_seen_subcommand_from gui" -l host -d "Host interface"
complete -c ambermeta -n "__fish_seen_subcommand_from gui" -l port -d "Port"
complete -c ambermeta -n "__fish_seen_subcommand_from gui" -l no-browser -d "Do not open browser on startup"

complete -c ambermeta -n "__fish_seen_subcommand_from completion" -a "bash zsh fish"
''',
    }
    return scripts[shell]


def _completion_command(args: argparse.Namespace) -> int:
    print(_completion_script(args.shell).rstrip())
    return 0


def _init_command(args: argparse.Namespace) -> int:
    """Write a starting v2 (Simulation -> Phase -> Step) manifest template."""
    directory = os.path.abspath(args.directory)
    output_path = os.path.join(directory, args.output)

    if os.path.exists(output_path) and not args.force:
        refuse = Colors.error(f"ERROR: {args.output} already exists. "
                              "Use --force to overwrite.")
        # Deliberately NOT gated on isatty(). `echo y | ambermeta init ...` is a
        # script answering the prompt, and input() reads a pipe perfectly well —
        # refusing every non-terminal stdin would break that working shape to
        # avoid a crash that only empty stdin causes. So: attempt the prompt, and
        # treat "cannot be read at all" as the refusal. That covers
        # `< /dev/null`, a closed pipe, and a harness that swaps stdin for an
        # object which raises on read, all at the exit code and message the old
        # non-interactive `--auto` path used.
        if getattr(sys, "stdin", None) is None:
            print(refuse, file=sys.stderr)
            return 1
        _out(Colors.warning(f"WARNING: {args.output} already exists"))
        try:
            response = input("Overwrite? [y/N]: ").strip().lower()
        except (EOFError, OSError, RuntimeError):
            print(refuse, file=sys.stderr)
            return 1
        if response != "y":
            _out("Aborted.")
            return 1

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(_generate_v2_template())
    _out(Colors.success(f"Created {args.output} (v2)"))
    return 0


def _generate_v2_template() -> str:
    """A commented v2 (Simulation) template manifest a user can edit."""
    return """\
# AmberMeta Manifest - v2 (Simulation -> Phase -> Step)
# Topologies live in a Simulation-owned pool; each step binds one by id.
# input_coords.source is one of: starting_structure | step (ref: <step id>) | path
version: 2
simulation:
  topologies:
    - id: top_wt
      path: system.prmtop
      kind: normal          # "normal" or "hmr" (hydrogen-mass-repartitioned)
    - id: top_wt_hmr
      path: system_hmr.prmtop
      kind: hmr
  starting_structure: system.inpcrd
phases:
  - { id: ph_min,  name: Minimization,  role: minimization, order: 0 }
  - { id: ph_prod, name: Production,     role: production,   order: 1 }
steps:
  - id: st_min
    phase: ph_min
    order: 0
    topology: top_wt
    input_coords: { source: starting_structure }
    mdin: min.in
    mdout: min.out
  - id: st_prod_001
    phase: ph_prod
    order: 0
    topology: top_wt_hmr
    input_coords: { source: step, ref: st_min }
    mdin: prod_001.in
    mdout: prod_001.out
    mdcrd: prod_001.nc
    gaps: { expected: null, tolerance: null }
"""


def _write_plan_artifacts(args: argparse.Namespace, protocol: SimulationProtocol) -> int:
    """Build the requested plan artifacts from an already-built protocol and report
    the outcome.

    Shared by both `plan` paths (v2 manifest and the flat manifest/recursive/interactive
    modes) so the two writers cannot drift apart again: one set of targets, one
    duplicate-target guard, one call to :func:`write_protocol_outputs`, one report.

    Returns 0 on success (or nothing requested), 2 if two artifacts target the same
    file, 1 if any artifact failed to write.
    """
    from ambermeta.protocol import write_protocol_outputs

    targets = {}
    for artifact, raw in (("summary", args.summary_path),
                          ("methods_summary", args.methods_summary_path),
                          ("stats_csv", getattr(args, "stats_csv", None))):
        if raw:
            targets[artifact] = os.path.abspath(raw)
    if not targets:
        return 0

    paths = list(targets.values())
    # normcase: a no-op on POSIX, lowercases (and normalizes slashes) on Windows, where
    # S.json and s.json name the same NTFS file — two artifacts "landing" on distinct
    # strings but one physical file, one silently overwriting the other while both
    # report success.
    normed = [os.path.normcase(p) for p in paths]
    dupe_keys = {k for k in normed if normed.count(k) > 1}
    dupes = sorted({p for p in paths if os.path.normcase(p) in dupe_keys})
    if dupes:
        print(Colors.error("ERROR: each output needs its own file; more than one is "
                           "aimed at " + ", ".join(dupes)), file=sys.stderr)
        return 2

    fmt = _resolve_sim_format(args.summary_path or "", args.summary_format)
    result = write_protocol_outputs(protocol, targets, summary_format=fmt)
    for item in result["written"]:
        _out(f"Wrote {item['artifact']}: {item['path']}")
    for warning in result["warnings"]:
        print(Colors.warning(f"WARNING: {warning}"), file=sys.stderr)
    for item in result["failed"]:
        print(Colors.error(f"ERROR: could not write {item['artifact']} to "
                           f"{item['path']}: {item['error']}"), file=sys.stderr)
    return 1 if result["failed"] else 0


def _plan_v2(args: argparse.Namespace, directory: str) -> int:
    """Summarize a v2 manifest and write any requested plan artifacts."""
    from ambermeta.simulation import load_simulation
    from ambermeta.gui.api.core_bridge import (
        _flatten_simulation, build_protocol, validate_simulation,
    )

    expand_env = not getattr(args, "no_expand_env", False)
    sim = load_simulation(args.manifest, expand_env=expand_env)
    settings = {
        "strict_validation": not bool(getattr(args, "skip_cross_stage_validation", None)),
        "allow_gaps": False,
        "use_relative_paths": True,
        "global_prmtop": getattr(args, "prmtop", None),
        "auto_detect_restarts": bool(getattr(args, "auto_detect_restarts", False)),
        "strict": bool(getattr(args, "strict", False)),
    }
    protocol = build_protocol(_flatten_simulation(sim), settings, directory)

    # An empty manifest was an error on the old flat path; keep that contract.
    if not protocol.stages:
        print(Colors.error("ERROR: nothing to plan: 0 stages."), file=sys.stderr)
        return 1

    report = validate_simulation(sim, settings, directory, protocol=protocol)
    _print_simulation(sim, report, verbose=bool(getattr(args, "verbose", False)))

    return _write_plan_artifacts(args, protocol)


def _plan_command(args: argparse.Namespace) -> int:
    directory = os.path.abspath(args.directory)

    # Get new feature flags with defaults
    pattern_filter = getattr(args, "pattern", None)
    auto_detect_restarts = getattr(args, "auto_detect_restarts", False)
    global_prmtop = getattr(args, "prmtop", None)
    interactive = getattr(args, "interactive", False)
    strict = getattr(args, "strict", False)

    if not any((args.manifest, args.recursive, interactive)):
        print("ERROR: Select a planning mode.", file=sys.stderr)
        print("Use one of: --manifest, --recursive, or --interactive.", file=sys.stderr)
        print("Examples:", file=sys.stderr)
        print("  ambermeta plan --manifest manifest.yaml /path/to/simulations", file=sys.stderr)
        print("  ambermeta plan --recursive /path/to/simulations", file=sys.stderr)
        print("  ambermeta plan --interactive /path/to/simulations", file=sys.stderr)
        print("Run 'ambermeta plan --help' for full usage.", file=sys.stderr)
        return 2

    # Warn if --pattern is used without --recursive
    if pattern_filter and not args.recursive:
        print(Colors.warning(
            "WARNING: --pattern only applies to --recursive discovery; ignored."),
            file=sys.stderr)

    if args.manifest:
        return _plan_v2(args, directory)
    elif args.recursive:
        # Recursive mode: auto-discover files without interactive prompts
        _out(f"\nScanning {directory} recursively for simulation files...")
        protocol = auto_discover(
            directory,
            manifest=None,
            skip_cross_stage_validation=bool(args.skip_cross_stage_validation),
            recursive=True,
            auto_detect_restarts=auto_detect_restarts,
            pattern_filter=pattern_filter,
            global_prmtop=global_prmtop,
            strict=strict,
        )
        if not protocol.stages:
            _out("No simulation files discovered; exiting.")
            _out("\nHint: Check that your directory contains files with recognized extensions:")
            _out("  prmtop: .prmtop, .parm7, .top")
            _out("  mdin:   .mdin, .in")
            _out("  mdout:  .mdout, .out")
            _out("  mdcrd:  .nc, .mdcrd, .crd, .x")
            _out("  inpcrd: .inpcrd, .rst, .rst7, .ncrst, .restrt")
            return 1
        _out(f"Discovered {len(protocol.stages)} stage(s).\n")
    else:
        manifest = _interactive_manifest(directory)
        if not manifest:
            _out("No stages defined; exiting.")
            return 1

        protocol = auto_discover(
            directory,
            manifest=manifest,
            skip_cross_stage_validation=bool(args.skip_cross_stage_validation),
            recursive=False,
            auto_detect_restarts=auto_detect_restarts,
            pattern_filter=pattern_filter,
            global_prmtop=global_prmtop,
            strict=strict,
        )

    if not protocol.stages:
        print(Colors.error("ERROR: nothing to plan: 0 stages."), file=sys.stderr)
        return 1

    degraded = [s for s in protocol.stages if s.degraded]
    if degraded:
        total_errors = sum(len(s.load_errors) for s in degraded)
        _out(
            f"\n{Colors.warning('WARNING')}: {len(degraded)} stage(s) had "
            f"{total_errors} unreadable file(s):"
        )
        for stage in degraded:
            for err in stage.load_errors:
                _out(f"  - {stage.name}: {err.kind} ({err.error_type}) {err.path}")

    _print_protocol(protocol, verbose=args.verbose)

    return _write_plan_artifacts(args, protocol)


def _gui_command(args: argparse.Namespace) -> int:
    """Launch the web-based GUI for building protocol manifests."""
    try:
        from ambermeta.gui import run_gui
    except ImportError:
        print(Colors.error("ERROR: GUI module not available."))
        print("Install with: pip install ambermeta[gui]")
        return 1

    directory = os.path.abspath(args.directory)
    if not os.path.isdir(directory):
        print(Colors.error(f"ERROR: Directory not found: {directory}"))
        return 1

    try:
        run_gui(
            directory,
            port=args.port,
            host=args.host,
            open_browser=not args.no_browser,
        )
        return 0
    except Exception as e:
        print(Colors.error(f"ERROR: GUI failed: {e}"))
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ambermeta",
        description=(
            "AmberMeta - Simulation provenance engine for AMBER molecular dynamics.\n\n"
            "Extract, organize, and validate metadata from AMBER simulation files.\n"
            "Supports prmtop, mdin, mdout, mdcrd (NetCDF), and restart files."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  plan      Build a simulation protocol from manifest or auto-discovery
  discover  Discover files into a Simulation draft (v2) and optionally write a manifest
  validate  Quick validation of simulation files
  info      Display detailed metadata for a single file
  init      Generate a starting v2 manifest file
  export    Re-emit a v2 manifest, optionally converting its format (json/yaml)

Examples:
  ambermeta plan -m manifest.yaml           Build protocol from manifest
  ambermeta plan . --recursive              Auto-discover files recursively
  ambermeta plan . --interactive            Prompt for stage definitions
  ambermeta plan -m manifest.yaml \\
    --methods-summary-path methods.json     Export publication-ready summary
  ambermeta discover . --write sim.yaml       Draft a v2 manifest from a directory
  ambermeta validate system.prmtop *.mdout  Validate multiple files
  ambermeta validate --manifest sim.yaml      Validate a whole simulation (continuity/gaps)
  ambermeta info --format json system.prmtop  Show metadata as JSON
  ambermeta init -o template.yaml           Write a starting v2 manifest template
  ambermeta export sim.yaml -o sim.json       Convert a v2 manifest to JSON

File Types:
  prmtop:  .prmtop, .top, .parm7    (topology/parameters)
  mdin:    .mdin, .in               (input control)
  mdout:   .mdout, .out             (output log)
  mdcrd:   .nc, .mdcrd, .crd        (trajectory)
  inpcrd:  .rst, .rst7, .ncrst      (coordinates/restart)

For documentation, visit: https://github.com/MicheleBonus/ambermeta
""",
    )

    # Global logging options
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level (default: INFO)",
    )
    parser.add_argument(
        "--log-file",
        help="Write logs to a file in addition to stderr",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress all output except errors",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser(
        "plan",
        help="Build and summarize a SimulationProtocol from manifest, recursive discovery, or explicit interactive mode",
        description=(
            "Build and summarize a SimulationProtocol from manifest, recursive discovery, or explicit interactive mode. "
            "Interactive mode prompts for stage roles, file paths, restart (inpcrd) paths, "
            "and expected gap/tolerance values."
        ),
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
        action="store_const", const=True, default=None,
        help="Skip the continuity checks between consecutive stages "
             "(they run by default)",
    )
    plan_parser.add_argument(
        "--strict",
        action="store_true",
        help="Abort on the first unreadable/malformed input file instead of "
             "skipping it. Default is to skip the file and continue.",
    )
    plan_parser.add_argument(
        "--recursive",
        action="store_true",
        help="Auto-discover simulation files recursively (no interactive prompts). "
             "Files are grouped by stem (filename without extension) and stage roles "
             "are inferred from directory names (equil→equilibration, prod→production).",
    )
    plan_parser.add_argument(
        "--interactive",
        action="store_true",
        help="Enable interactive prompt mode for manually defining stages.",
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
    plan_parser.add_argument(
        "--methods-summary-path",
        help=(
            "Write a Materials & Methods-ready JSON summary with reproducibility-critical metadata "
            "(software versions, MD settings, system composition, and trajectory cadence) while omitting "
            "energies and other nonessential arrays"
        ),
    )
    # UX-007: CSV export for statistics
    plan_parser.add_argument(
        "--stats-csv",
        help="Export per-stage statistics to a CSV file",
    )
    # DS-002: Environment variable expansion
    plan_parser.add_argument(
        "--no-expand-env",
        action="store_true",
        help="Disable environment variable expansion in manifest paths",
    )
    # DS-004: Pattern-based filtering
    plan_parser.add_argument(
        "--pattern",
        help="Regex pattern to filter discovered files (e.g., 'prod_.*' for production runs)",
    )
    # DS-005: Auto restart detection
    plan_parser.add_argument(
        "--auto-detect-restarts",
        action="store_true",
        help="Automatically detect and link restart files between stages",
    )
    # Global prmtop to avoid redundant specification
    plan_parser.add_argument(
        "--prmtop",
        help="Global prmtop file to use for all stages (avoids specifying it per stage)",
    )

    discover_parser = subparsers.add_parser(
        "discover",
        help="Discover files into a Simulation draft (Sim→Phase→Step) and optionally write a v2 manifest",
        description=(
            "Scan a directory into a draft Simulation using the same discover-as-draft engine "
            "as the GUI: a topology pool, phases inferred by role, and steps with per-step "
            "topology binding and input-coordinate sources. Prints the draft and any suggestions; "
            "with --write, saves a v2 manifest you can edit."
        ),
    )
    discover_parser.add_argument("directory", nargs="?", default=".", help="Directory to scan (default: current directory)")
    discover_parser.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=True, help="Recurse into subdirectories (default: on; use --no-recursive to disable)")
    discover_parser.add_argument("--pattern", help="Regex filter for discovered files")
    discover_parser.add_argument("--write", help="Write the draft to this path as a v2 manifest")
    discover_parser.add_argument("--format", choices=["json", "yaml"], help="Format for --write (default: inferred from extension, else json)")

    # UX-005: validate subcommand
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate simulation files without building full protocol",
        description="Quick validation of simulation files with colored output.",
    )
    validate_parser.add_argument(
        "files",
        nargs="*",
        help="Files to validate (prmtop, mdin, mdout, mdcrd, inpcrd). Omit when using --manifest.",
    )
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors",
    )
    validate_parser.add_argument(
        "--format",
        choices=["text", "json", "yaml"],
        default="text",
        help="Output format (default: text)",
    )
    validate_parser.add_argument(
        "--manifest",
        help="Validate a whole simulation manifest (v2) — continuity, sequence holes, suggestions",
    )
    validate_parser.add_argument(
        "--allow-gaps",
        action="store_true",
        help="With --manifest: treat unexpected inter-step gaps as allowed",
    )

    # UX-005: info subcommand
    info_parser = subparsers.add_parser(
        "info",
        help="Display detailed metadata for a single file",
        description="Parse and display detailed metadata for AMBER simulation files.",
    )
    info_parser.add_argument(
        "file",
        help="File to inspect (prmtop, mdin, mdout, mdcrd, inpcrd)",
    )
    info_parser.add_argument(
        "--format",
        choices=["text", "json", "yaml"],
        default="text",
        help="Output format (default: text)",
    )

    export_parser = subparsers.add_parser(
        "export",
        help="Re-emit a v2 manifest, optionally converting its format",
        description=(
            "Read a v2 manifest and re-emit it as canonical v2. Useful for converting "
            "between json and yaml, or for pretty-printing to stdout. Without --output, "
            "prints JSON to stdout."
        ),
    )
    export_parser.add_argument("manifest", help="Path to the v2 manifest to convert")
    export_parser.add_argument("-o", "--output", help="Write to this path (default: print JSON to stdout)")
    export_parser.add_argument("--format", choices=["json", "yaml"], help="Output format (default: inferred from --output extension)")

    # UX-009: init subcommand
    init_parser = subparsers.add_parser(
        "init",
        help="Generate a starting v2 manifest file",
        description=("Create a template manifest.yaml: a commented v2 "
                     "(Simulation -> Phase -> Step) document to edit."),
    )
    init_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to write the manifest into (default: current directory)",
    )
    init_parser.add_argument(
        "-o", "--output",
        default="manifest.yaml",
        help="Output manifest filename (default: manifest.yaml)",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output file without prompting",
    )

    # GUI subcommand
    gui_parser = subparsers.add_parser(
        "gui",
        help="Launch web-based GUI for building protocol manifests",
        description=(
            "Launch a modern web-based graphical user interface for building "
            "simulation protocol manifests. Features include drag-and-drop file "
            "assignment, visual stage management, sequence detection, and export "
            "to multiple formats. Opens in your default web browser."
        ),
    )
    gui_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory containing simulation files (default: current directory)",
    )
    gui_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Server port (default: 8765)",
    )
    gui_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't automatically open the browser",
    )
    gui_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Server host (default: 127.0.0.1)",
    )

    completion_parser = subparsers.add_parser(
        "completion",
        help="Print shell completion script for bash, zsh, or fish",
        description="Generate shell completion scripts for ambermeta commands.",
    )
    completion_parser.add_argument(
        "shell",
        choices=["bash", "zsh", "fish"],
        help="Shell type for completion script",
    )

    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    global _QUIET
    _QUIET = bool(args.quiet)

    # Configure logging based on CLI options
    log_level = "ERROR" if args.quiet else args.log_level
    configure_logging(
        level=log_level,
        log_file=args.log_file,
        format_style="verbose" if log_level == "DEBUG" else "default",
    )

    def _dispatch() -> int:
        if args.command == "plan":
            return _plan_command(args)
        if args.command == "discover":
            return _discover_command(args)
        if args.command == "validate":
            return _validate_command(args)
        if args.command == "info":
            return _info_command(args)
        if args.command == "export":
            return _export_command(args)
        if args.command == "init":
            return _init_command(args)
        if args.command == "gui":
            return _gui_command(args)
        if args.command == "completion":
            return _completion_command(args)

        parser.print_help()
        return 1

    try:
        return _dispatch()
    except AmberMetaError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level guard
        logger.debug("Unhandled exception", exc_info=True)
        print(
            f"Unexpected error ({type(exc).__name__}: {exc}). "
            "Re-run with --log-level DEBUG for the full traceback.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
