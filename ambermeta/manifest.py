from __future__ import annotations

import csv
import json
import os
import re
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from ambermeta.errors import AmberMetaError

try:  # pragma: no cover - optional dependency
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:  # pragma: no cover - optional dependency
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    try:
        import tomli as tomllib  # Fallback for older Python
    except ImportError:
        tomllib = None

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

STAGE_FILE_KINDS = ("prmtop", "mdin", "mdout", "mdcrd", "inpcrd")

CSV_COLUMNS = [
    "name", "stage_role", "prmtop", "mdin", "mdout", "mdcrd",
    "inpcrd", "expected_gap_ps", "gap_tolerance_ps", "notes",
]


# ---------------------------------------------------------------------------
# Internal helpers moved from protocol.py
# ---------------------------------------------------------------------------

def _expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in string values.

    Supports ${VAR} and $VAR syntax. Undefined variables are left unchanged.
    """
    if isinstance(value, str):
        # Collect all replacements from the original value first to avoid double-expansion
        replacements = []
        # Expand ${VAR} syntax
        for match in re.finditer(r'\$\{([^}]+)\}', value):
            var_name = match.group(1)
            env_value = os.environ.get(var_name)
            if env_value is not None:
                replacements.append((match.group(0), env_value))
        # Expand $VAR syntax (only if not followed by {)
        for match in re.finditer(r'\$([A-Za-z_][A-Za-z0-9_]*)(?!\{)', value):
            var_name = match.group(1)
            # Skip if this was already matched as ${VAR}
            if f'${{{var_name}}}' in value:
                continue
            env_value = os.environ.get(var_name)
            if env_value is not None:
                replacements.append((match.group(0), env_value))
        # Apply all replacements to the original value
        result = value
        for old, new in replacements:
            result = result.replace(old, new)
        return result
    elif isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    return value


def _parse_csv_manifest(text: str) -> List[Dict[str, Any]]:
    """Parse a CSV manifest file into a list of stage dictionaries.

    Expected CSV format:
    name,stage_role,prmtop,mdin,mdout,mdcrd,inpcrd,notes

    First row must be headers.
    Each row is passed through normalize_stage_keys so legacy column names
    (stage, role, expected_gap_ps, gap_tolerance_ps) round-trip correctly.
    """
    reader = csv.DictReader(StringIO(text))
    stages: List[Dict[str, Any]] = []

    for row in reader:
        stage: Dict[str, Any] = {}
        for key, value in row.items():
            if key is None or value is None:
                continue
            key = key.strip()
            value = value.strip()
            if not value:
                continue
            # Handle special fields
            if key in ("expected_gap_ps", "gap_tolerance_ps"):
                try:
                    stage[key] = float(value)
                except ValueError:
                    stage[key] = value
            elif key == "notes":
                # Support semicolon-separated notes
                stage[key] = [n.strip() for n in value.split(";") if n.strip()]
            else:
                stage[key] = value
        if stage.get("name") or stage.get("stage"):
            stages.append(normalize_stage_keys(stage))

    return stages


def _parse_toml_manifest(text: str) -> Any:
    """Parse a TOML manifest file.

    TOML manifests can have two formats:
    1. Array of tables: [[stages]]
    2. Table per stage: [stage.name]
    """
    if tomllib is None:
        raise ImportError(
            "tomllib/tomli is required to read TOML manifests. "
            "Install with `pip install tomli` (Python < 3.11) or use Python 3.11+."
        )

    data = tomllib.loads(text)

    # If there's a 'stages' key with a list, return the whole dict (preserving
    # global keys like global_prmtop) or just the stages list.
    if "stages" in data and isinstance(data["stages"], list):
        return data

    # If the data is a dict with stage names as keys
    return data


def _normalize_manifest(
    manifest: Any,
) -> Generator[Dict[str, Any], None, None]:
    """Yield normalised stage entries from any manifest container shape.

    This generator is used by validate_manifest and _manifest_to_stages
    (in protocol.py) to iterate over stages regardless of whether the
    manifest is a list or a dict-of-stages.
    """
    if isinstance(manifest, dict) and isinstance(manifest.get("stages"), list):
        yield from _normalize_manifest(manifest["stages"])
        return
    if isinstance(manifest, dict):
        for name, entry in manifest.items():
            if not isinstance(entry, dict):
                raise TypeError("Manifest entries must be dictionaries")
            normalized = dict(entry)
            normalized.setdefault("name", name)
            yield normalized
    elif isinstance(manifest, list):
        for entry in manifest:
            if not isinstance(entry, dict):
                raise TypeError("Manifest entries must be dictionaries")
            yield dict(entry)
    else:
        raise TypeError("Manifest must be a list or dictionary")


def validate_manifest(
    manifest: Any,
    directory: Optional[str] = None,
    strict: bool = True,
) -> None:
    kinds = {"prmtop", "inpcrd", "mdin", "mdout", "mdcrd"}
    missing: List[str] = []
    for entry in _normalize_manifest(manifest):
        name = entry.get("name")
        if not name:
            raise ValueError("Each manifest entry must include a 'name'.")

        files = entry.get("files", {})
        paths = {k: v for k, v in entry.items() if k in kinds}
        if isinstance(files, dict):
            for kind, path in files.items():
                if kind in kinds and path is not None:
                    paths.setdefault(kind, path)

        resolved = {}
        for kind, path in paths.items():
            if path is None:
                continue
            if directory and not os.path.isabs(path):
                resolved[kind] = os.path.normpath(os.path.join(directory, path))
            else:
                resolved[kind] = os.path.normpath(path)

        for kind, path in resolved.items():
            if not os.path.exists(path):
                missing.append(f"stage '{name}', {kind}: {path}")

    if missing and strict:
        message = "Manifest references missing files:\n" + "\n".join(missing)
        raise AmberMetaError(message)
    # In graceful mode, missing files are recorded per-file by _safe_parse.


# ---------------------------------------------------------------------------
# Key-alias normalisation
# ---------------------------------------------------------------------------

def normalize_stage_keys(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Accept legacy/variant stage keys; return a canonicalized copy.

    Handles:
    - ``stage``  -> ``name``
    - ``role``   -> ``stage_role`` (kept as alias if stage_role absent)
    - ``expected_gap_ps`` / ``gap_tolerance_ps`` -> ``gaps`` dict
    - ``gaps_expected`` / ``gaps_tolerance`` (TOML flat export) -> ``gaps`` dict
    """
    out = dict(entry)

    # name alias
    if "name" not in out and "stage" in out:
        out["name"] = out.pop("stage")

    # stage_role alias
    if "stage_role" not in out and "role" in out:
        out["stage_role"] = out.pop("role")

    # gaps: only build if no gaps/gap key already present
    if "gaps" not in out and "gap" not in out:
        # Legacy flat CSV/TOML keys
        expected = out.pop("expected_gap_ps", None)
        tolerance = out.pop("gap_tolerance_ps", None)

        # TOML canonical writer produces gaps_expected / gaps_tolerance
        if expected is None:
            expected = out.pop("gaps_expected", None)
        else:
            out.pop("gaps_expected", None)

        if tolerance is None:
            tolerance = out.pop("gaps_tolerance", None)
        else:
            out.pop("gaps_tolerance", None)

        if expected is not None or tolerance is not None:
            gaps: Dict[str, Any] = {}
            if expected is not None:
                gaps["expected"] = expected
            if tolerance is not None:
                gaps["tolerance"] = tolerance
            out["gaps"] = gaps

    return out


def _normalize_container(manifest: Any) -> Any:
    """Apply normalize_stage_keys to every stage entry in any container shape."""
    if isinstance(manifest, list):
        return [normalize_stage_keys(e) if isinstance(e, dict) else e
                for e in manifest]
    if isinstance(manifest, dict):
        if isinstance(manifest.get("stages"), list):
            manifest = dict(manifest)
            manifest["stages"] = [normalize_stage_keys(e) if isinstance(e, dict)
                                  else e for e in manifest["stages"]]
            return manifest
        # dict-of-stages: keys are stage names
        return {k: (normalize_stage_keys(v) if isinstance(v, dict) else v)
                for k, v in manifest.items()}
    return manifest


# ---------------------------------------------------------------------------
# Canonical writer
# ---------------------------------------------------------------------------

def _toml_escape(value: Any) -> str:
    s = str(value)
    return s.replace("\\", "\\\\").replace('"', '\\"')


def write_manifest(payload: Dict[str, Any], path: str, fmt: str) -> None:
    """Write a manifest payload ({'stages': [...]}, optional globals) canonically."""
    stages = payload.get("stages", [])
    if fmt == "json":
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        return
    if fmt == "yaml":
        if yaml is None:
            raise RuntimeError("PyYAML is required for YAML output")
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, sort_keys=False)
        return
    if fmt == "toml":
        lines: List[str] = []
        for key in ("global_prmtop", "hmr_prmtop"):
            if payload.get(key):
                lines.append(f'{key} = "{_toml_escape(payload[key])}"')
        if lines:
            lines.append("")
        for stage in stages:
            lines.append("[[stages]]")
            for k, v in stage.items():
                if isinstance(v, dict):  # gaps
                    for gk, gv in v.items():
                        lines.append(f"{k}_{gk} = {gv}")
                elif isinstance(v, list):  # notes
                    lines.append(f"{k} = {json.dumps(v)}")
                elif isinstance(v, bool):
                    lines.append(f"{k} = {str(v).lower()}")
                elif isinstance(v, (int, float)):
                    lines.append(f"{k} = {v}")
                else:
                    lines.append(f'{k} = "{_toml_escape(v)}"')
            lines.append("")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines).rstrip() + "\n")
        return
    if fmt == "csv":
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for stage in stages:
                gaps = stage.get("gaps", {}) or {}
                notes = stage.get("notes", []) or []
                writer.writerow({
                    "name": stage.get("name", ""),
                    "stage_role": stage.get("stage_role", ""),
                    "prmtop": stage.get("prmtop") or payload.get("global_prmtop", ""),
                    "mdin": stage.get("mdin", ""),
                    "mdout": stage.get("mdout", ""),
                    "mdcrd": stage.get("mdcrd", ""),
                    "inpcrd": stage.get("inpcrd", ""),
                    "expected_gap_ps": gaps.get("expected", ""),
                    "gap_tolerance_ps": gaps.get("tolerance", ""),
                    "notes": "; ".join(str(n) for n in notes),
                })
        return
    raise ValueError(f"Unsupported manifest format: {fmt}")


# ---------------------------------------------------------------------------
# Tolerant reader
# ---------------------------------------------------------------------------

def load_manifest(
    manifest_path: Any,
    expand_env: bool = True,
) -> Any:
    """Load a manifest from YAML, JSON, TOML, or CSV.

    Parameters
    ----------
    manifest_path:
        Path to a manifest describing simulation stages.
        Supported formats: .yaml, .yml, .json, .toml, .csv
    expand_env:
        If True, expand environment variables in file paths using ${VAR} or $VAR syntax.
        Default is True.

    Returns
    -------
    Manifest data as a list of stage dictionaries or a mapping, with all
    stage keys normalised via normalize_stage_keys.
    """
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise ImportError(
                "PyYAML is required to read YAML manifests. "
                "Install with `pip install pyyaml`."
            )
        manifest = yaml.safe_load(text)
    elif suffix == ".toml":
        manifest = _parse_toml_manifest(text)
    elif suffix == ".csv":
        manifest = _parse_csv_manifest(text)
    else:
        # Default to JSON
        manifest = json.loads(text)

    if manifest is None:
        return {}

    if not isinstance(manifest, (dict, list)):
        raise TypeError("Manifest must be a mapping or list of stage entries.")

    if expand_env:
        manifest = _expand_env_vars(manifest)

    return _normalize_container(manifest)


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
    "STAGE_FILE_KINDS",
    "CSV_COLUMNS",
    "normalize_stage_keys",
    "load_manifest",
    "write_manifest",
    "validate_manifest",
    "_expand_env_vars",
    "_normalize_manifest",
    "_normalize_container",
]
