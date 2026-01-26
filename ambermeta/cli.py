from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from typing import Any, Dict, Iterable, List, Optional

from ambermeta.logging_config import configure_logging, get_logger
from ambermeta.protocol import (
    SimulationProtocol,
    auto_discover,
    load_protocol_from_manifest,
)

try:  # pragma: no cover - optional dependency
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

# Module logger
logger = get_logger(__name__)


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
    print("\n" + "=" * 60)
    print("  AmberMeta Interactive Protocol Builder")
    print("=" * 60)
    print("\nDefine your simulation stages in order.")
    print("Press Enter without a name to finish, or 'q' to quit.\n")
    print("Common stage roles: minimization, heating, equilibration, production\n")

    manifest: List[Dict[str, Any]] = []
    kinds = ("prmtop", "mdin", "mdout", "mdcrd")
    stage_num = 1

    # Scan directory for existing files to help with suggestions
    available_files = _scan_directory_files(directory)

    while True:
        print(f"\n--- Stage {stage_num} ---")
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

        print(f"\n  Enter file paths relative to: {directory}")
        if available_files:
            print(f"  (Found {sum(len(v) for v in available_files.values())} simulation files)")

        for kind in kinds:
            # Show suggestions if available
            suggestions = available_files.get(kind, [])
            if suggestions:
                print(f"    Available {kind} files: {', '.join(suggestions[:3])}" +
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
                    print("    Invalid number; skipping.")
            tolerance = _prompt("    Gap tolerance (ps): ", default="0.1").strip()
            if tolerance:
                try:
                    gaps["tolerance"] = float(tolerance)
                except ValueError:
                    print("    Invalid number; using default 0.1.")
                    gaps["tolerance"] = 0.1
            if gaps:
                stage_entry["gaps"] = gaps

        note = _prompt("  Notes for this stage (optional): ").strip()
        if note:
            stage_entry["notes"] = [note]

        manifest.append(stage_entry)
        stage_num += 1

        # Summary of added stage
        print(f"\n  Added stage: {name}" + (f" ({role})" if role else ""))

        cont = _prompt("Add another stage? [Y/n]: ").strip().lower()
        if cont.startswith("n"):
            break

    if manifest:
        print(f"\n{len(manifest)} stage(s) defined.")

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

            if ext in (".prmtop", ".parm7", ".top") or "prmtop" in fl:
                files["prmtop"].append(f)
            elif ext in (".in", ".mdin") or "mdin" in fl:
                files["mdin"].append(f)
            elif ext in (".out", ".mdout") or "mdout" in fl:
                files["mdout"].append(f)
            elif ext in (".nc",) or ("mdcrd" in fl and ext != ".in"):
                files["mdcrd"].append(f)
            elif ext in (".rst", ".rst7", ".ncrst", ".inpcrd"):
                files["inpcrd"].append(f)
    except OSError:
        pass

    return files


def _suggest_stage_role(name: str) -> str:
    """Suggest a stage role based on the stage name."""
    name_lower = name.lower()

    if any(x in name_lower for x in ("min", "minim", "em")):
        return "minimization"
    if any(x in name_lower for x in ("heat", "warm", "therm")):
        return "heating"
    if any(x in name_lower for x in ("equil", "nvt", "npt")):
        return "equilibration"
    if any(x in name_lower for x in ("prod", "md", "run")):
        return "production"

    return ""


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
    has_errors = False
    has_warnings = False

    print(Colors.header("\nValidation Results"))
    print("=" * 50)

    for filepath in args.files:
        if not os.path.exists(filepath):
            print(f"\n{Colors.error('ERROR')}: File not found: {filepath}")
            has_errors = True
            continue

        parser = _get_parser_for_file(filepath)
        if parser is None:
            print(f"\n{Colors.warning('WARN')}: Unknown file type: {filepath}")
            has_warnings = True
            continue

        try:
            result = parser.parse()
            warnings = getattr(result, "warnings", []) or []

            if warnings:
                has_warnings = True
                print(f"\n{Colors.warning('WARN')}: {filepath}")
                for warn in warnings:
                    print(f"  - {warn}")
            else:
                print(f"\n{Colors.success('OK')}: {filepath}")

        except (IOError, OSError, ValueError) as e:
            print(f"\n{Colors.error('ERROR')}: {filepath}")
            print(f"  - {e}")
            has_errors = True

    print("\n" + "=" * 50)
    if has_errors:
        print(Colors.error("Validation FAILED with errors"))
        return 1
    elif has_warnings and args.strict:
        print(Colors.warning("Validation FAILED (strict mode, warnings present)"))
        return 1
    elif has_warnings:
        print(Colors.warning("Validation PASSED with warnings"))
        return 0
    else:
        print(Colors.success("Validation PASSED"))
        return 0


def _info_command(args: argparse.Namespace) -> int:
    """Display detailed metadata for a single file."""
    filepath = args.file

    if not os.path.exists(filepath):
        print(Colors.error(f"ERROR: File not found: {filepath}"))
        return 1

    parser = _get_parser_for_file(filepath)
    if parser is None:
        print(Colors.error(f"ERROR: Unknown file type: {filepath}"))
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
            print(Colors.header(f"\nFile Information: {os.path.basename(filepath)}"))
            print("=" * 60)

            if details:
                for key, value in vars(details).items():
                    if key.startswith("_"):
                        continue
                    if isinstance(value, (list, dict)) and not value:
                        continue
                    print(f"  {key}: {value}")

            warnings = getattr(result, "warnings", []) or []
            if warnings:
                print(f"\n{Colors.warning('Warnings:')}")
                for warn in warnings:
                    print(f"  - {warn}")

        return 0

    except (IOError, OSError, ValueError) as e:
        print(Colors.error(f"ERROR: Failed to parse file: {e}"))
        return 1


def _init_command(args: argparse.Namespace) -> int:
    """Generate an example manifest file."""
    directory = os.path.abspath(args.directory)
    output_path = os.path.join(directory, args.output)

    if os.path.exists(output_path):
        print(Colors.warning(f"WARNING: {args.output} already exists"))
        response = input("Overwrite? [y/N]: ").strip().lower()
        if response != "y":
            print("Aborted.")
            return 1

    # Scan directory for common file patterns
    discovered_files = {
        "prmtop": [],
        "mdin": [],
        "mdout": [],
        "mdcrd": [],
        "inpcrd": [],
    }

    for root, dirs, files in os.walk(directory):
        rel_root = os.path.relpath(root, directory)
        for f in files:
            rel_path = os.path.join(rel_root, f) if rel_root != "." else f
            ext = os.path.splitext(f)[1].lower()
            fl = f.lower()

            if ext in (".prmtop", ".parm7", ".top") or "prmtop" in fl:
                discovered_files["prmtop"].append(rel_path)
            elif ext in (".in", ".mdin") or "mdin" in fl:
                discovered_files["mdin"].append(rel_path)
            elif ext in (".out", ".mdout") or "mdout" in fl:
                discovered_files["mdout"].append(rel_path)
            elif ext in (".nc",) or "mdcrd" in fl:
                discovered_files["mdcrd"].append(rel_path)
            elif ext in (".rst", ".rst7", ".ncrst", ".inpcrd"):
                discovered_files["inpcrd"].append(rel_path)

    # Generate manifest content
    if args.template == "minimal":
        manifest_content = _generate_minimal_manifest(discovered_files)
    elif args.template == "comprehensive":
        manifest_content = _generate_comprehensive_manifest(discovered_files)
    else:
        manifest_content = _generate_standard_manifest(discovered_files)

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(manifest_content)

    print(Colors.success(f"Created {args.output}"))
    print(f"\nDiscovered files:")
    for kind, files in discovered_files.items():
        if files:
            print(f"  {kind}: {len(files)} file(s)")

    print(f"\nEdit {args.output} to customize your protocol stages.")
    return 0


def _generate_minimal_manifest(discovered: Dict[str, List[str]]) -> str:
    """Generate a minimal manifest template."""
    return """# AmberMeta Manifest - Minimal Template
# Edit this file to define your simulation protocol stages

stages:
  - name: production
    prmtop: system.prmtop
    mdin: prod.in
    mdout: prod.out
    mdcrd: prod.nc
"""


def _generate_standard_manifest(discovered: Dict[str, List[str]]) -> str:
    """Generate a standard manifest template."""
    prmtop = discovered["prmtop"][0] if discovered["prmtop"] else "system.prmtop"

    return f"""# AmberMeta Manifest - Standard Template
# Edit this file to define your simulation protocol stages
#
# Each stage can include:
#   - name: Stage identifier (required)
#   - stage_role: minimization, heating, equilibration, production
#   - prmtop, mdin, mdout, mdcrd, inpcrd: File paths (relative to manifest)
#   - notes: Optional annotations

stages:
  - name: minimize
    stage_role: minimization
    prmtop: {prmtop}
    mdin: min.in
    mdout: min.out

  - name: heat
    stage_role: heating
    prmtop: {prmtop}
    mdin: heat.in
    mdout: heat.out
    inpcrd: min.rst7  # Restart from minimization

  - name: equilibrate
    stage_role: equilibration
    prmtop: {prmtop}
    mdin: equil.in
    mdout: equil.out
    mdcrd: equil.nc
    inpcrd: heat.rst7

  - name: production
    stage_role: production
    prmtop: {prmtop}
    mdin: prod.in
    mdout: prod.out
    mdcrd: prod.nc
    inpcrd: equil.rst7
"""


def _generate_comprehensive_manifest(discovered: Dict[str, List[str]]) -> str:
    """Generate a comprehensive manifest template with all options."""
    prmtop = discovered["prmtop"][0] if discovered["prmtop"] else "system.prmtop"

    return f"""# AmberMeta Manifest - Comprehensive Template
# This template shows all available options for protocol definition
#
# Documentation: https://github.com/your-org/ambermeta

# Optional: Global settings
settings:
  strict_validation: false
  allow_gaps: false

# Optional: Stage role inference rules (regex patterns)
# Used when stage_role is not explicitly specified
stage_role_rules:
  - pattern: "min.*"
    role: minimization
  - pattern: "heat.*"
    role: heating
  - pattern: "equil.*"
    role: equilibration
  - pattern: "prod.*"
    role: production

stages:
  - name: minimize_1
    stage_role: minimization
    prmtop: {prmtop}
    mdin: min1.in
    mdout: min1.out
    notes:
      - "Initial minimization with restraints"

  - name: minimize_2
    stage_role: minimization
    prmtop: {prmtop}
    mdin: min2.in
    mdout: min2.out
    inpcrd: min1.rst7
    notes:
      - "Unrestrained minimization"

  - name: heat
    stage_role: heating
    prmtop: {prmtop}
    mdin: heat.in
    mdout: heat.out
    inpcrd: min2.rst7
    gaps:
      expected: 0.0
      tolerance: 0.1
    notes:
      - "Heat from 0K to 300K over 100ps"

  - name: equilibrate_nvt
    stage_role: equilibration
    prmtop: {prmtop}
    mdin: equil_nvt.in
    mdout: equil_nvt.out
    mdcrd: equil_nvt.nc
    inpcrd: heat.rst7
    notes:
      - "NVT equilibration at 300K"

  - name: equilibrate_npt
    stage_role: equilibration
    prmtop: {prmtop}
    mdin: equil_npt.in
    mdout: equil_npt.out
    mdcrd: equil_npt.nc
    inpcrd: equil_nvt.rst7
    notes:
      - "NPT equilibration at 300K, 1bar"

  - name: production
    stage_role: production
    prmtop: {prmtop}
    mdin: prod.in
    mdout: prod.out
    mdcrd: prod.nc
    inpcrd: equil_npt.rst7
    gaps:
      expected: 2.0  # Expected gap in ps (dt * ntwx)
      tolerance: 0.1
    notes:
      - "Production run at 300K, 1bar"
      - "10ns total simulation time"
"""


def _plan_command(args: argparse.Namespace) -> int:
    directory = os.path.abspath(args.directory)

    # Get new feature flags with defaults
    expand_env = not getattr(args, "no_expand_env", False)
    pattern_filter = getattr(args, "pattern", None)
    auto_detect_restarts = getattr(args, "auto_detect_restarts", False)

    if args.manifest:
        protocol = load_protocol_from_manifest(
            args.manifest,
            directory=directory,
            skip_cross_stage_validation=args.skip_cross_stage_validation,
            recursive=args.recursive,
            expand_env=expand_env,
        )
        # Apply auto-detect restarts if requested (after manifest loading)
        if auto_detect_restarts:
            from ambermeta.protocol import auto_detect_restart_chain
            from ambermeta.parsers.inpcrd import InpcrdParser
            auto_restarts = auto_detect_restart_chain(protocol.stages, directory)
            for stage in protocol.stages:
                if stage.name in auto_restarts and not stage.restart_path:
                    rst_path = auto_restarts[stage.name]
                    stage.inpcrd = InpcrdParser(rst_path).parse()
                    stage.restart_path = rst_path
                    stage.validation.append(f"INFO: restart file auto-detected: {rst_path}")
    else:
        manifest = _interactive_manifest(directory)
        if not manifest:
            print("No stages defined; exiting.")
            return 1

        protocol = auto_discover(
            directory,
            manifest=manifest,
            skip_cross_stage_validation=args.skip_cross_stage_validation,
            recursive=args.recursive,
            auto_detect_restarts=auto_detect_restarts,
            pattern_filter=pattern_filter,
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
    if args.methods_summary_path:
        with open(args.methods_summary_path, "w", encoding="utf-8") as fh:
            json.dump(protocol.to_methods_dict(), fh, indent=2)

    # UX-007: CSV export for statistics
    if getattr(args, "stats_csv", None):
        _export_stats_csv(protocol, args.stats_csv)

    return 0


def _export_stats_csv(protocol: SimulationProtocol, filepath: str) -> None:
    """Export per-stage statistics to a CSV file."""
    import csv

    headers = [
        "stage_name",
        "stage_role",
        "time_start_ps",
        "time_end_ps",
        "duration_ns",
        "frame_count",
        "temp_avg",
        "temp_std",
        "pressure_avg",
        "pressure_std",
        "density_avg",
        "density_std",
        "etot_avg",
        "etot_std",
    ]

    rows = []
    for stage in protocol.stages:
        row = {
            "stage_name": stage.name,
            "stage_role": stage.stage_role or "",
        }

        # Extract stats from mdout if available
        if stage.mdout and stage.mdout.details:
            stats = getattr(stage.mdout.details, "stats", None)
            if stats:
                row["time_start_ps"] = getattr(stats, "time_start", "")
                row["time_end_ps"] = getattr(stats, "time_end", "")
                row["duration_ns"] = getattr(stats, "duration_ns", "")
                row["frame_count"] = getattr(stats, "count", "")

                # Get streaming stats if available
                temp_stats = getattr(stats, "temp_stats", None)
                if temp_stats:
                    mean, std = temp_stats.get_stats()
                    row["temp_avg"] = mean if mean is not None else ""
                    row["temp_std"] = std if std is not None else ""

                pressure_stats = getattr(stats, "pressure_stats", None)
                if pressure_stats:
                    mean, std = pressure_stats.get_stats()
                    row["pressure_avg"] = mean if mean is not None else ""
                    row["pressure_std"] = std if std is not None else ""

                density_stats = getattr(stats, "density_stats", None)
                if density_stats:
                    mean, std = density_stats.get_stats()
                    row["density_avg"] = mean if mean is not None else ""
                    row["density_std"] = std if std is not None else ""

                etot_stats = getattr(stats, "etot_stats", None)
                if etot_stats:
                    mean, std = etot_stats.get_stats()
                    row["etot_avg"] = mean if mean is not None else ""
                    row["etot_std"] = std if std is not None else ""

        rows.append(row)

    with open(filepath, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            # Fill missing columns with empty strings
            writer.writerow({k: row.get(k, "") for k in headers})

    print(f"Statistics exported to: {filepath}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ambermeta",
        description="AmberMeta command-line tools for parsing and validating AMBER MD simulation files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ambermeta plan -m manifest.yaml           # Build protocol from manifest
  ambermeta plan . --recursive              # Auto-discover files recursively
  ambermeta validate -m manifest.yaml       # Validate a protocol
  ambermeta info system.prmtop              # Show file information
  ambermeta init my_project                 # Generate example manifest

For more information, visit: https://github.com/your-org/ambermeta
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
        help="Build and summarize a SimulationProtocol from a manifest or interactive input",
        description=(
            "Build and summarize a SimulationProtocol from a manifest or interactive input. "
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
        action="store_true",
        help="Skip continuity checks between consecutive stages",
    )
    plan_parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively discover stage files under the provided directory",
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

    # UX-005: validate subcommand
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate simulation files without building full protocol",
        description="Quick validation of simulation files with colored output.",
    )
    validate_parser.add_argument(
        "files",
        nargs="+",
        help="Files to validate (prmtop, mdin, mdout, mdcrd, inpcrd)",
    )
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors",
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

    # UX-009: init subcommand
    init_parser = subparsers.add_parser(
        "init",
        help="Generate an example manifest file",
        description="Create a template manifest.yaml with example stages.",
    )
    init_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan for files (default: current directory)",
    )
    init_parser.add_argument(
        "-o", "--output",
        default="manifest.yaml",
        help="Output manifest filename (default: manifest.yaml)",
    )
    init_parser.add_argument(
        "--template",
        choices=["minimal", "standard", "comprehensive"],
        default="standard",
        help="Template complexity (default: standard)",
    )

    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Configure logging based on CLI options
    log_level = "ERROR" if args.quiet else args.log_level
    configure_logging(
        level=log_level,
        log_file=args.log_file,
        format_style="verbose" if args.log_level == "DEBUG" else "default",
    )

    if args.command == "plan":
        return _plan_command(args)
    if args.command == "validate":
        return _validate_command(args)
    if args.command == "info":
        return _info_command(args)
    if args.command == "init":
        return _init_command(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
