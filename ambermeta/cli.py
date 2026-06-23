from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

from ambermeta.errors import AmberMetaError
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

    if re.search(r'(?:^|[_.\-])(?:min|minim|em)(?:[_.\-]|$)', name_lower):
        return "minimization"
    if re.search(r'(?:^|[_.\-])(?:heat|warm|therm)(?:[_.\-]|$)', name_lower):
        return "heating"
    if re.search(r'(?:^|[_.\-])(?:equil|nvt|npt)(?:[_.\-]|$)', name_lower):
        return "equilibration"
    if re.search(r'(?:^|[_.\-])(?:prod|md|run)(?:[_.\-]|$)', name_lower):
        return "production"

    return ""



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
        print(Colors.header("\nValidation Results"))
        print("=" * 50)

        for file_result in result["files"]:
            filepath = file_result["file"]
            status = file_result["status"]
            if status == "error":
                print(f"\n{Colors.error('ERROR')}: {filepath}")
                for err in file_result["errors"]:
                    print(f"  - {err}")
            elif status == "warning":
                print(f"\n{Colors.warning('WARN')}: {filepath}")
                for warn in file_result["warnings"]:
                    print(f"  - {warn}")
            else:
                print(f"\n{Colors.success('OK')}: {filepath}")

        print("\n" + "=" * 50)
        if has_errors:
            print(Colors.error("Validation FAILED with errors"))
        elif has_warnings and args.strict:
            print(Colors.warning("Validation FAILED (strict mode, warnings present)"))
        elif has_warnings:
            print(Colors.warning("Validation PASSED with warnings"))
        else:
            print(Colors.success("Validation PASSED"))

    if has_errors:
        return 1
    if has_warnings and args.strict:
        return 1
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


def _completion_script(shell: str) -> str:
    """Return a shell completion script for the requested shell."""
    scripts = {
        "bash": r'''# ambermeta bash completion
_ambermeta_completion() {
    local cur prev
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    local commands="plan validate info init tui gui completion"
    local global_opts="--help --log-level --log-file --quiet -q"

    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${commands} ${global_opts}" -- "$cur") )
        return 0
    fi

    case "${COMP_WORDS[1]}" in
        plan)
            COMPREPLY=( $(compgen -W "--help -m --manifest --skip-cross-stage-validation --strict --recursive --interactive -v --verbose --summary-path --summary-format --methods-summary-path --stats-csv --no-expand-env --pattern --auto-detect-restarts --prmtop" -- "$cur") )
            ;;
        validate)
            COMPREPLY=( $(compgen -W "--help --strict --format" -- "$cur") )
            ;;
        info)
            COMPREPLY=( $(compgen -W "--help --format" -- "$cur") )
            ;;
        init)
            COMPREPLY=( $(compgen -W "--help -o --output --template --auto --format --validate --dry-run --force" -- "$cur") )
            ;;
        tui)
            COMPREPLY=( $(compgen -W "--help" -- "$cur") )
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
    'validate:Validate simulation files'
    'info:Display metadata for a single file'
    'init:Generate example manifest templates'
    'tui:Launch interactive terminal UI'
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
        validate)
          _arguments '--strict[Treat warnings as errors]' '--format[Output format]:format:(text json yaml)' '*:file:_files'
          ;;
        info)
          _arguments '--format[Output format]:format:(text json yaml)' '1:file:_files'
          ;;
        init)
          _arguments '--output[Manifest output filename]:file:_files' '--template[Template complexity]:template:(minimal standard comprehensive)' '--auto[Auto-generate grouped stages]' '--format[Manifest format]:format:(yaml json toml csv)' '--validate[Validate discovered files after writing manifest]' '--dry-run[Preview discovery without writing]' '--force[Overwrite existing output]' '*:path:_files'
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
complete -c ambermeta -n "__fish_use_subcommand" -a "validate" -d "Validate simulation files"
complete -c ambermeta -n "__fish_use_subcommand" -a "info" -d "Display metadata for a single file"
complete -c ambermeta -n "__fish_use_subcommand" -a "init" -d "Generate example manifest templates"
complete -c ambermeta -n "__fish_use_subcommand" -a "tui" -d "Launch interactive terminal UI"
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

complete -c ambermeta -n "__fish_seen_subcommand_from validate" -l strict -d "Treat warnings as errors"
complete -c ambermeta -n "__fish_seen_subcommand_from validate" -l format -d "Output format" -xa "text json yaml"

complete -c ambermeta -n "__fish_seen_subcommand_from info" -l format -d "Output format" -xa "text json yaml"

complete -c ambermeta -n "__fish_seen_subcommand_from init" -s o -l output -d "Output manifest filename"
complete -c ambermeta -n "__fish_seen_subcommand_from init" -l template -d "Template complexity" -xa "minimal standard comprehensive"
complete -c ambermeta -n "__fish_seen_subcommand_from init" -l auto -d "Auto-discover and group stages"
complete -c ambermeta -n "__fish_seen_subcommand_from init" -l format -d "Manifest output format" -xa "yaml json toml csv"
complete -c ambermeta -n "__fish_seen_subcommand_from init" -l validate -d "Run parsers after writing manifest"
complete -c ambermeta -n "__fish_seen_subcommand_from init" -l dry-run -d "Preview stage grouping only"
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
    """Generate an example manifest file."""
    directory = os.path.abspath(args.directory)
    output_path = os.path.join(directory, args.output)
    auto_mode = getattr(args, "auto", False)

    if os.path.exists(output_path) and not getattr(args, "dry_run", False):
        if getattr(args, "force", False):
            pass
        elif auto_mode:
            print(Colors.error(f"ERROR: {args.output} already exists. Use --force to overwrite."))
            return 1
        else:
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

    stage_candidates = _build_stage_candidates(discovered_files)

    if auto_mode:
        manifest_payload = _build_auto_manifest_payload(discovered_files, stage_candidates)
        if getattr(args, "dry_run", False):
            _print_auto_stage_preview(stage_candidates, discovered_files)
            print("\nDry run complete; no files were written.")
            return 0

        manifest_format = _resolve_manifest_format(args)
        from ambermeta import manifest as manifest_io
        manifest_io.write_manifest(manifest_payload, output_path, manifest_format)
        print(Colors.success(f"Created {args.output} ({manifest_format})"))
        _print_auto_stage_preview(stage_candidates, discovered_files)
        if getattr(args, "validate", False):
            _run_init_validation_summary(directory, stage_candidates, discovered_files)
        return 0

    if hasattr(args, 'format') and args.format and args.format != "yaml" and not args.auto:
        print(Colors.warning("WARNING: --format is only applied in --auto mode. Output will be YAML."))

    # Generate manifest content
    if args.template == "minimal":
        manifest_content = _generate_minimal_manifest(discovered_files, stage_candidates)
    elif args.template == "comprehensive":
        manifest_content = _generate_comprehensive_manifest(discovered_files, stage_candidates)
    else:
        manifest_content = _generate_standard_manifest(discovered_files, stage_candidates)

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(manifest_content)

    print(Colors.success(f"Created {args.output}"))
    print(f"\nDiscovered files:")
    for kind, files in discovered_files.items():
        if files:
            print(f"  {kind}: {len(files)} file(s)")

    print(f"\nEdit {args.output} to customize your protocol stages.")
    return 0


def _normalize_stage_stem(path: str) -> str:
    """Normalize a file path stem into a stage grouping key."""
    stem = os.path.splitext(os.path.basename(path))[0]
    match = re.match(r"^(.*?)(?:[._-]?\d+)$", stem)
    if match and match.group(1):
        return match.group(1).rstrip("._-") or stem
    return stem


def _build_stage_candidates(discovered_files: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    """Build ordered stage candidates from discovered file groupings."""
    grouped: Dict[str, Dict[str, Any]] = {}

    for kind in ("mdin", "mdout", "mdcrd", "inpcrd"):
        for path in sorted(discovered_files.get(kind, [])):
            key = _normalize_stage_stem(path)
            entry = grouped.setdefault(
                key,
                {
                    "name": key,
                    "stage_role": _suggest_stage_role(key),
                    "files": {},
                },
            )
            entry["files"][kind] = path

    return [grouped[key] for key in sorted(grouped)]


def _build_auto_manifest_payload(
    discovered: Dict[str, List[str]], stage_candidates: List[Dict[str, Any]]
) -> Dict[str, Any]:
    prmtop = discovered["prmtop"][0] if discovered["prmtop"] else None
    stages: List[Dict[str, Any]] = []
    for candidate in stage_candidates:
        stage: Dict[str, Any] = {"name": candidate["name"]}
        if candidate.get("stage_role"):
            stage["stage_role"] = candidate["stage_role"]
        if prmtop:
            stage["prmtop"] = prmtop
        for key in ("mdin", "mdout", "mdcrd", "inpcrd"):
            value = candidate.get("files", {}).get(key)
            if value:
                stage[key] = value
        stages.append(stage)
    return {"stages": stages}


def _resolve_manifest_format(args: argparse.Namespace) -> str:
    requested = getattr(args, "format", None)
    if requested:
        return requested

    ext = os.path.splitext(getattr(args, "output", ""))[1].lower().lstrip(".")
    ext_map = {"yml": "yaml", "yaml": "yaml", "json": "json", "toml": "toml", "csv": "csv"}
    return ext_map.get(ext, "yaml")


def _print_auto_stage_preview(stage_candidates: List[Dict[str, Any]], discovered: Dict[str, List[str]]) -> None:
    print("\nAuto-grouped stages:")
    if not stage_candidates:
        print("  (no stages discovered)")
        return

    prmtop = discovered["prmtop"][0] if discovered["prmtop"] else None
    for idx, candidate in enumerate(stage_candidates, start=1):
        role = candidate.get("stage_role") or "unclassified"
        print(f"  {idx}. {candidate['name']} [{role}]")
        if prmtop:
            print(f"     prmtop: {prmtop}")
        for kind in ("mdin", "mdout", "mdcrd", "inpcrd"):
            value = candidate.get("files", {}).get(kind)
            if value:
                print(f"     {kind}: {value}")



def _run_init_validation_summary(
    directory: str, stage_candidates: List[Dict[str, Any]], discovered: Dict[str, List[str]]
) -> None:
    checked = 0
    warnings = 0
    errors = 0
    unique_files = set(discovered.get("prmtop", []))
    for candidate in stage_candidates:
        for path in candidate.get("files", {}).values():
            unique_files.add(path)

    for rel_path in sorted(unique_files):
        parser = _get_parser_for_file(os.path.join(directory, rel_path))
        if parser is None:
            warnings += 1
            continue
        checked += 1
        try:
            result = parser.parse()
            file_warnings = getattr(result, "warnings", []) or []
            warnings += len(file_warnings)
        except (IOError, OSError, ValueError):
            errors += 1

    status = "OK" if errors == 0 else "FAILED"
    print(f"\nValidation summary: {status} (files={checked}, warnings={warnings}, errors={errors})")


def _render_candidate_stages(
    discovered: Dict[str, List[str]],
    stage_candidates: List[Dict[str, Any]],
    include_role: bool = True,
) -> List[str]:
    """Render candidate stages as YAML lines."""
    prmtop = discovered["prmtop"][0] if discovered["prmtop"] else "system.prmtop"
    lines: List[str] = []

    for candidate in stage_candidates:
        lines.append(f"  - name: {candidate['name']}")
        if include_role and candidate.get("stage_role"):
            lines.append(f"    stage_role: {candidate['stage_role']}")
        lines.append(f"    prmtop: {prmtop}")

        files = candidate.get("files", {})
        for key in ("mdin", "mdout", "mdcrd", "inpcrd"):
            value = files.get(key)
            if value:
                lines.append(f"    {key}: {value}")
        lines.append("")

    return lines


def _generate_minimal_manifest(discovered: Dict[str, List[str]], stage_candidates: List[Dict[str, Any]]) -> str:
    """Generate a minimal manifest template."""
    if stage_candidates:
        rendered = _render_candidate_stages(discovered, stage_candidates, include_role=False)
        body = "\n".join(rendered).rstrip()
        return (
            "# AmberMeta Manifest - Minimal Template\n"
            "# Edit this file to define your simulation protocol stages\n\n"
            "stages:\n"
            f"{body}\n"
        )

    return """# AmberMeta Manifest - Minimal Template
# Edit this file to define your simulation protocol stages

stages:
  - name: production
    prmtop: system.prmtop
    mdin: prod.in
    mdout: prod.out
    mdcrd: prod.nc
"""


def _generate_standard_manifest(discovered: Dict[str, List[str]], stage_candidates: List[Dict[str, Any]]) -> str:
    """Generate a standard manifest template."""
    if stage_candidates:
        rendered = _render_candidate_stages(discovered, stage_candidates, include_role=True)
        body = "\n".join(rendered).rstrip()
        return (
            "# AmberMeta Manifest - Standard Template\n"
            "# Edit this file to define your simulation protocol stages\n"
            "#\n"
            "# Each stage can include:\n"
            "#   - name: Stage identifier (required)\n"
            "#   - stage_role: minimization, heating, equilibration, production\n"
            "#   - prmtop, mdin, mdout, mdcrd, inpcrd: File paths (relative to manifest)\n"
            "#   - notes: Optional annotations\n\n"
            "stages:\n"
            f"{body}\n"
        )

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


def _generate_comprehensive_manifest(discovered: Dict[str, List[str]], stage_candidates: List[Dict[str, Any]]) -> str:
    """Generate a comprehensive manifest template with all options."""
    if stage_candidates:
        rendered = _render_candidate_stages(discovered, stage_candidates, include_role=True)
        body = "\n".join(rendered).rstrip()
        return (
            "# AmberMeta Manifest - Comprehensive Template\n"
            "# This template shows all available options for protocol definition\n"
            "#\n"
            "# Documentation: https://github.com/your-org/ambermeta\n\n"
            "# Optional: Global settings\n"
            "settings:\n"
            "  strict_validation: false\n"
            "  allow_gaps: false\n\n"
            "# Optional: Stage role inference rules (regex patterns)\n"
            "# Used when stage_role is not explicitly specified\n"
            "stage_role_rules:\n"
            "  - pattern: \"min.*\"\n"
            "    role: minimization\n"
            "  - pattern: \"heat.*\"\n"
            "    role: heating\n"
            "  - pattern: \"equil.*\"\n"
            "    role: equilibration\n"
            "  - pattern: \"prod.*\"\n"
            "    role: production\n\n"
            "stages:\n"
            f"{body}\n"
        )

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
    global_prmtop = getattr(args, "prmtop", None)
    interactive = getattr(args, "interactive", False)
    strict = getattr(args, "strict", False)

    if not any((args.manifest, args.recursive, interactive)):
        print("ERROR: Select a planning mode.")
        print("Use one of: --manifest, --recursive, or --interactive.")
        print("Examples:")
        print("  ambermeta plan --manifest manifest.yaml /path/to/simulations")
        print("  ambermeta plan --recursive /path/to/simulations")
        print("  ambermeta plan --interactive /path/to/simulations")
        print("Run 'ambermeta plan --help' for full usage.")
        return 2

    # Progress callback for reporting
    def progress_reporter(stage_name: str, current: int, total: int) -> None:
        if sys.stdout.isatty():
            # Truncate long stage names
            name = stage_name[:40] + "..." if len(stage_name) > 40 else stage_name
            sys.stdout.write(f"\rProcessing: {current}/{total} [{name}]" + " " * 20)
            sys.stdout.flush()
            if current == total:
                sys.stdout.write("\n")

    if args.manifest:
        print(f"Loading manifest: {args.manifest}")
        protocol = load_protocol_from_manifest(
            args.manifest,
            directory=directory,
            skip_cross_stage_validation=args.skip_cross_stage_validation,
            recursive=args.recursive,
            expand_env=expand_env,
            global_prmtop=global_prmtop,
            progress_callback=progress_reporter,
            strict=strict,
        )
        # Apply auto-detect restarts if requested (after manifest loading)
        if auto_detect_restarts:
            from ambermeta.protocol import auto_detect_restart_chain, _safe_parse
            from ambermeta.parsers.inpcrd import InpcrdParser
            auto_restarts = auto_detect_restart_chain(protocol.stages, directory)
            for stage in protocol.stages:
                if stage.name in auto_restarts and not stage.restart_path:
                    rst_path = auto_restarts[stage.name]
                    stage.inpcrd = _safe_parse(InpcrdParser, rst_path, "inpcrd", stage, strict=strict)
                    if stage.inpcrd is not None:
                        stage.restart_path = rst_path
                        stage.validation.append(f"INFO: restart file auto-detected: {rst_path}")
    elif args.recursive:
        # Recursive mode: auto-discover files without interactive prompts
        print(f"\nScanning {directory} recursively for simulation files...")
        protocol = auto_discover(
            directory,
            manifest=None,
            skip_cross_stage_validation=args.skip_cross_stage_validation,
            recursive=True,
            auto_detect_restarts=auto_detect_restarts,
            pattern_filter=pattern_filter,
            global_prmtop=global_prmtop,
            strict=strict,
        )
        if not protocol.stages:
            print("No simulation files discovered; exiting.")
            print("\nHint: Check that your directory contains files with recognized extensions:")
            print("  prmtop: .prmtop, .parm7, .top")
            print("  mdin:   .mdin, .in")
            print("  mdout:  .mdout, .out")
            print("  mdcrd:  .nc, .mdcrd, .crd, .x")
            print("  inpcrd: .inpcrd, .rst, .rst7, .ncrst, .restrt")
            return 1
        print(f"Discovered {len(protocol.stages)} stage(s).\n")
    else:
        manifest = _interactive_manifest(directory)
        if not manifest:
            print("No stages defined; exiting.")
            return 1

        protocol = auto_discover(
            directory,
            manifest=manifest,
            skip_cross_stage_validation=args.skip_cross_stage_validation,
            recursive=False,
            auto_detect_restarts=auto_detect_restarts,
            pattern_filter=pattern_filter,
            global_prmtop=global_prmtop,
            strict=strict,
        )

    degraded = [s for s in protocol.stages if s.degraded]
    if degraded:
        total_errors = sum(len(s.load_errors) for s in degraded)
        print(
            f"\n{Colors.warning('WARNING')}: {len(degraded)} stage(s) had "
            f"{total_errors} unreadable file(s):"
        )
        for stage in degraded:
            for err in stage.load_errors:
                print(f"  - {stage.name}: {err.kind} ({err.error_type}) {err.path}")

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


def _tui_command(args: argparse.Namespace) -> int:
    """Launch the TUI for building protocol manifests."""
    try:
        from ambermeta.tui import run_tui, TEXTUAL_AVAILABLE
    except ImportError:
        print(Colors.error("ERROR: TUI module not available."))
        print("Install with: pip install ambermeta[tui]")
        return 1

    if not TEXTUAL_AVAILABLE:
        print(Colors.error("ERROR: Textual library is required for the TUI."))
        print("Install with: pip install textual")
        return 1

    directory = os.path.abspath(args.directory)
    if not os.path.isdir(directory):
        print(Colors.error(f"ERROR: Directory not found: {directory}"))
        return 1

    try:
        run_tui(directory)
        return 0
    except Exception as e:
        print(Colors.error(f"ERROR: TUI failed: {e}"))
        return 1


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
        description=(
            "AmberMeta - Simulation provenance engine for AMBER molecular dynamics.\n\n"
            "Extract, organize, and validate metadata from AMBER simulation files.\n"
            "Supports prmtop, mdin, mdout, mdcrd (NetCDF), and restart files."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  plan      Build a simulation protocol from manifest or auto-discovery
  tui       Launch interactive terminal UI for building manifests
  validate  Quick validation of simulation files
  info      Display detailed metadata for a single file
  init      Generate example manifest templates

Examples:
  ambermeta plan -m manifest.yaml           Build protocol from manifest
  ambermeta plan . --recursive              Auto-discover files recursively
  ambermeta plan . --interactive            Prompt for stage definitions
  ambermeta plan -m manifest.yaml \\
    --methods-summary-path methods.json     Export publication-ready summary
  ambermeta tui /path/to/simulations        Launch interactive TUI
  ambermeta validate system.prmtop *.mdout  Validate multiple files
  ambermeta info --format json system.prmtop  Show metadata as JSON
  ambermeta init --template standard .      Generate manifest template

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
        action="store_true",
        help="Skip continuity checks between consecutive stages",
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
    validate_parser.add_argument(
        "--format",
        choices=["text", "json", "yaml"],
        default="text",
        help="Output format (default: text)",
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

    # TUI subcommand
    tui_parser = subparsers.add_parser(
        "tui",
        help="Launch interactive TUI for building protocol manifests",
        description=(
            "Launch a terminal user interface for interactively building "
            "simulation protocol manifests. Features include file browser, "
            "stage management, sequence detection, and export to multiple formats."
        ),
    )
    tui_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory containing simulation files (default: current directory)",
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
    init_parser.add_argument(
        "--auto",
        action="store_true",
        help="Non-interactive bootstrap mode: recursively discover files and auto-generate grouped stages",
    )
    init_parser.add_argument(
        "--format",
        choices=["yaml", "json", "toml", "csv"],
        help="Manifest output format for --auto mode (default: inferred from output extension or yaml)",
    )
    init_parser.add_argument(
        "--validate",
        action="store_true",
        help="Run parsers against discovered files after writing the manifest and print a concise summary",
    )
    init_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview discovered stage grouping in --auto mode without writing output files",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output file without prompting (required for non-interactive --auto mode)",
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
        if args.command == "validate":
            return _validate_command(args)
        if args.command == "info":
            return _info_command(args)
        if args.command == "init":
            return _init_command(args)
        if args.command == "tui":
            return _tui_command(args)
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
