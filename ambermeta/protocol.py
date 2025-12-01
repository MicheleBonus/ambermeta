from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Pattern

import re

from ambermeta.parsers.inpcrd import InpcrdData, InpcrdParser
from ambermeta.parsers.mdcrd import MdcrdData, MdcrdParser
from ambermeta.parsers.mdin import MdinData, MdinParser
from ambermeta.parsers.mdout import MdoutData, MdoutParser
from ambermeta.parsers.prmtop import PrmtopData, PrmtopParser

try:  # pragma: no cover - optional dependency
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None


@dataclass
class SimulationStage:
    name: str
    stage_role: Optional[str] = None
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    observed_gap_ps: Optional[float] = None
    prmtop: Optional[PrmtopData] = None
    inpcrd: Optional[InpcrdData] = None
    mdin: Optional[MdinData] = None
    mdout: Optional[MdoutData] = None
    mdcrd: Optional[MdcrdData] = None
    restart_path: Optional[str] = None
    validation: List[str] = field(default_factory=list)
    continuity: List[str] = field(default_factory=list)

    def validate(self) -> None:
        self.validation.extend(self._validate_atoms())
        self.validation.extend(self._validate_box())
        self.validation.extend(self._validate_timing())
        self.validation.extend(self._validate_sampling())

    def _validate_atoms(self) -> List[str]:
        counts = []
        labels = []
        if self.prmtop and self.prmtop.details and getattr(self.prmtop.details, "natom", None):
            counts.append(self.prmtop.details.natom)
            labels.append("prmtop")
        if self.inpcrd and self.inpcrd.details and getattr(self.inpcrd.details, "natoms", None):
            counts.append(self.inpcrd.details.natoms)
            labels.append("inpcrd")
        if self.mdout and self.mdout.details and getattr(self.mdout.details, "natoms", None):
            counts.append(self.mdout.details.natoms)
            labels.append("mdout")
        if self.mdcrd and self.mdcrd.details and getattr(self.mdcrd.details, "n_atoms", None):
            counts.append(self.mdcrd.details.n_atoms)
            labels.append("mdcrd")

        if not counts:
            return ["No atom counts available for validation."]
        if len(set(counts)) > 1:
            return [f"Atom count mismatch across {labels}: {counts}"]
        return []

    def _validate_box(self) -> List[str]:
        boxes = []
        if self.prmtop and self.prmtop.details and getattr(self.prmtop.details, "box_dimensions", None):
            boxes.append("prmtop")
        if self.inpcrd and self.inpcrd.details and getattr(self.inpcrd.details, "has_box", False):
            boxes.append("inpcrd")
        if self.mdcrd and self.mdcrd.details and getattr(self.mdcrd.details, "has_box", False):
            boxes.append("mdcrd")
        if self.mdout and self.mdout.details and getattr(self.mdout.details, "box_type", None):
            boxes.append("mdout")

        if boxes and len(boxes) < 2:
            return [f"Only {boxes[0]} reports box information; check consistency."]
        return []

    def _validate_timing(self) -> List[str]:
        notes: List[str] = []

        step_counts: Dict[str, float] = {}
        timesteps: Dict[str, float] = {}
        expected_durations: Dict[str, float] = {}

        if self.mdin and self.mdin.details:
            length = getattr(self.mdin.details, "length_steps", None)
            dt = getattr(self.mdin.details, "dt", None)
            if length:
                step_counts["mdin"] = length
            if dt:
                timesteps["mdin"] = dt
            if length and dt:
                expected_durations["mdin"] = length * dt

        if self.mdout and self.mdout.details:
            length = getattr(self.mdout.details, "nstlim", None)
            dt = getattr(self.mdout.details, "dt", None)
            if length:
                step_counts["mdout"] = length
            if dt:
                timesteps["mdout"] = dt
            if length and dt:
                expected_durations["mdout"] = length * dt

        mdcrd_duration: Optional[float] = None
        if self.mdcrd and self.mdcrd.details:
            dur = getattr(self.mdcrd.details, "total_duration", None)
            avg_dt = getattr(self.mdcrd.details, "avg_dt", None)
            n_frames = getattr(self.mdcrd.details, "n_frames", None)

            if dur:
                mdcrd_duration = dur
            elif avg_dt and n_frames and n_frames > 1:
                mdcrd_duration = avg_dt * (n_frames - 1)

        def _compare(values: Dict[str, float], description: str, suffix: str = "") -> None:
            if len(values) < 2:
                return
            items = list(values.items())
            base_label, base_value = items[0]
            for label, value in items[1:]:
                if isinstance(base_value, (int, float)) and isinstance(value, (int, float)) and base_value != value:
                    sep = " " if suffix else ""
                    notes.append(
                        f"{description} differs between {base_label} and {label} ({base_value:g}{sep}{suffix} vs {value:g}{sep}{suffix})."
                    )

        _compare(step_counts, "Step count")
        _compare(timesteps, "Timestep", "ps per step")
        _compare(expected_durations, "Simulation duration", "ps")

        if mdcrd_duration and expected_durations:
            for label, duration in expected_durations.items():
                if isinstance(duration, (int, float)) and duration != mdcrd_duration:
                    notes.append(
                        f"Trajectory duration from mdcrd ({mdcrd_duration:g} ps) differs from expected duration from {label} ({duration:g} ps)."
                    )

        return notes

    def _validate_sampling(self) -> List[str]:
        freq = []
        if self.mdin and self.mdin.details:
            freq.append(("mdin", getattr(self.mdin.details, "coord_freq", None)))
        if self.mdout and self.mdout.details:
            freq.append(("mdout", getattr(self.mdout.details, "ntwx", None)))
        notes: List[str] = []
        if len(freq) > 1:
            base = freq[0]
            for label, val in freq[1:]:
                if base[1] and val and base[1] != val:
                    notes.append(f"Coordinate write frequency differs between {base[0]} and {label} ({base[1]} vs {val}).")
        return notes

    def _add_continuity_note(self, message: str) -> None:
        self.continuity.append(message)
        self.validation.append(message)

    def summary(self) -> Dict[str, str]:
        intent = self.stage_role or "Unknown"
        result = "Unknown"
        if self.mdin and self.mdin.details:
            intent = self.stage_role or getattr(self.mdin.details, "stage_role", "MD Stage")
        if self.mdout and self.mdout.details:
            result = "Completed" if getattr(self.mdout.details, "finished_properly", False) else "Unclear"
        expected_gap = None
        if self.expected_gap_ps is not None:
            tolerance = f"±{self.gap_tolerance_ps:g} " if self.gap_tolerance_ps is not None else ""
            expected_gap = f"{self.expected_gap_ps:g} {tolerance}ps"
        observed_gap = f"{self.observed_gap_ps:g} ps" if self.observed_gap_ps is not None else None
        continuity = "; ".join(self.continuity or [])
        evidence = "; ".join(self.validation or [])
        return {
            "intent": intent,
            "result": result,
            "expected_gap_ps": expected_gap or "",
            "observed_gap_ps": observed_gap or "",
            "continuity": continuity,
            "evidence": evidence,
        }


@dataclass
class SimulationProtocol:
    stages: List[SimulationStage] = field(default_factory=list)

    def validate(self, cross_stage: bool = True) -> None:
        for stage in self.stages:
            stage.validate()
        if cross_stage:
            self._check_continuity()

    def _check_continuity(self) -> None:
        for prev, current in zip(self.stages, self.stages[1:]):
            if prev.mdcrd and prev.mdcrd.details and current.inpcrd and current.inpcrd.details:
                end_time = getattr(prev.mdcrd.details, "time_end", None)
                start_time = getattr(current.inpcrd.details, "time", None)
                if end_time is None or start_time is None:
                    if current.expected_gap_ps is not None:
                        current._add_continuity_note(
                            "Expected gap could not be verified because timing metadata is missing."
                        )
                    continue

                gap = start_time - end_time

                # When no explicit gap expectation is provided, treat very small
                # differences as numerical noise instead of real gaps/overlaps.
                if current.expected_gap_ps is None:
                    default_tolerance = 1e-6
                    prior_dt = getattr(prev.mdcrd.details, "avg_dt", None)
                    tolerance = (
                        max(float(prior_dt) * 1e-6, default_tolerance)
                        if isinstance(prior_dt, (int, float))
                        else default_tolerance
                    )
                    if abs(gap) <= tolerance:
                        gap = 0.0

                current.observed_gap_ps = gap

                if gap < 0:
                    current._add_continuity_note(
                        f"Stage appears to overlap previous stage by {abs(gap):g} ps."
                    )
                elif gap > 0:
                    current._add_continuity_note(f"Stage starts {gap:g} ps after previous ended.")

                if current.expected_gap_ps is not None:
                    tolerance = current.gap_tolerance_ps or 0.0
                    lower = current.expected_gap_ps - tolerance
                    upper = current.expected_gap_ps + tolerance
                    if gap < lower:
                        current._add_continuity_note(
                            f"Observed gap {gap:g} ps is shorter than expected {current.expected_gap_ps:g} ps."
                        )
                    elif gap > upper:
                        current._add_continuity_note(
                            f"Observed gap {gap:g} ps exceeds expected {current.expected_gap_ps:g} ps."
                        )
                    else:
                        current._add_continuity_note(
                            f"Observed gap {gap:g} ps is within expected window ({current.expected_gap_ps:g}±{tolerance:g} ps)."
                        )
                elif gap != 0:
                    current._add_continuity_note("Gap detected without stated expectation; verify continuity.")

    def totals(self) -> Dict[str, float]:
        total_steps = 0.0
        total_time = 0.0
        for stage in self.stages:
            if stage.mdin and stage.mdin.details:
                length = getattr(stage.mdin.details, "length_steps", 0) or 0
                dt = getattr(stage.mdin.details, "dt", 0) or 0
                if isinstance(length, (int, float)) and isinstance(dt, (int, float)):
                    total_steps += float(length)
                    total_time += float(length) * float(dt)
        return {"steps": total_steps, "time_ps": total_time}


def _normalize_manifest(manifest: Dict[str, Dict[str, str]] | List[Dict[str, str]]):
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


def _manifest_to_stages(
    manifest: Dict[str, Dict[str, str]] | List[Dict[str, str]],
    directory: Optional[str],
    include_roles: Optional[List[str]],
    include_stems: Optional[List[str]],
    restart_files: Optional[Dict[str, str]],
) -> List[SimulationStage]:
    kinds = {"prmtop", "inpcrd", "mdin", "mdout", "mdcrd"}
    stages: List[SimulationStage] = []
    for entry in _normalize_manifest(manifest):
        name = entry.get("name")
        if not name:
            raise ValueError("Each manifest entry must include a 'name'.")
        stage_role = entry.get("stage_role")

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
                resolved[kind] = os.path.join(directory, path)
            else:
                resolved[kind] = path

        stage = SimulationStage(name=name, stage_role=stage_role)

        if "prmtop" in resolved:
            stage.prmtop = PrmtopParser(resolved["prmtop"]).parse()
        if "mdin" in resolved:
            stage.mdin = MdinParser(resolved["mdin"]).parse()
            stage.stage_role = stage.stage_role or getattr(stage.mdin.details, "stage_role", None)
        if "mdout" in resolved:
            stage.mdout = MdoutParser(resolved["mdout"]).parse()
        if "mdcrd" in resolved:
            stage.mdcrd = MdcrdParser(resolved["mdcrd"]).parse()
        if "inpcrd" in resolved:
            stage.inpcrd = InpcrdParser(resolved["inpcrd"]).parse()
            stage.restart_path = resolved["inpcrd"]

        restart_source = None
        if restart_files:
            for key in (stage.name, stage.stage_role):
                if key and key in restart_files:
                    restart_source = restart_files[key]
                    break

        if restart_source and "inpcrd" not in resolved:
            stage.inpcrd = InpcrdParser(restart_source).parse()
            stage.restart_path = restart_source

        if include_stems and stage.name not in include_stems:
            continue
        if include_roles and stage.stage_role and stage.stage_role not in include_roles:
            continue
        if include_roles and not stage.stage_role:
            continue

        gap_info = entry.get("gaps") or entry.get("gap")
        notes = entry.get("notes")
        if isinstance(gap_info, dict):
            expected = gap_info.get("expected") or gap_info.get("expected_ps")
            tolerance = gap_info.get("tolerance") or gap_info.get("tolerance_ps")
            if expected is not None:
                stage.expected_gap_ps = float(expected)
            if tolerance is not None:
                stage.gap_tolerance_ps = float(tolerance)
            extra_notes = gap_info.get("notes")
            if isinstance(extra_notes, str):
                stage.validation.append(extra_notes)
            elif isinstance(extra_notes, list):
                stage.validation.extend(str(n) for n in extra_notes)
        elif isinstance(gap_info, (int, float)):
            stage.expected_gap_ps = float(gap_info)
        elif isinstance(gap_info, str):
            stage.validation.append(gap_info)
        elif isinstance(gap_info, list):
            stage.validation.extend(str(n) for n in gap_info)

        if isinstance(notes, str):
            stage.validation.append(notes)
        elif isinstance(notes, list):
            stage.validation.extend(str(n) for n in notes)

        stages.append(stage)

    return stages


def auto_discover(
    directory: str,
    manifest: Optional[Dict[str, Dict[str, str]] | List[Dict[str, str]]] = None,
    grouping_rules: Optional[Dict[str, str]] = None,
    include_roles: Optional[List[str]] = None,
    include_stems: Optional[List[str]] = None,
    restart_files: Optional[Dict[str, str]] = None,
    skip_cross_stage_validation: bool = False,
) -> SimulationProtocol:
    if manifest is not None:
        stages = _manifest_to_stages(
            manifest,
            directory=directory,
            include_roles=include_roles,
            include_stems=include_stems,
            restart_files=restart_files,
        )
        protocol = SimulationProtocol(stages=stages)
        protocol.validate(cross_stage=not skip_cross_stage_validation)
        return protocol

    files = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]
    grouped: Dict[str, Dict[str, str]] = {}
    ext_map = {
        ".prmtop": "prmtop",
        ".top": "prmtop",
        ".inpcrd": "inpcrd",
        ".rst": "inpcrd",
        ".rst7": "inpcrd",
        ".mdin": "mdin",
        ".in": "mdin",
        ".mdout": "mdout",
        ".out": "mdout",
        ".mdcrd": "mdcrd",
        ".nc": "mdcrd",
    }

    for fname in files:
        stem, ext = os.path.splitext(fname)
        kind = ext_map.get(ext.lower())
        if not kind:
            continue
        grouped.setdefault(stem, {})[kind] = os.path.join(directory, fname)

    compiled_rules: List[tuple[Pattern[str], str]] = []
    if grouping_rules:
        for pattern, role in grouping_rules.items():
            try:
                compiled_rules.append((re.compile(pattern), role))
            except re.error:
                compiled_rules.append((re.compile(re.escape(pattern)), role))

    stages: List[SimulationStage] = []
    for stem, kinds in sorted(grouped.items()):
        stage_role: Optional[str] = None
        for pattern, role in compiled_rules:
            if pattern.search(stem):
                stage_role = role
                break

        if include_stems and stem not in include_stems:
            continue

        stage = SimulationStage(name=stem, stage_role=stage_role)
        if "prmtop" in kinds:
            stage.prmtop = PrmtopParser(kinds["prmtop"]).parse()
        if "mdin" in kinds:
            stage.mdin = MdinParser(kinds["mdin"]).parse()
            stage.stage_role = stage.stage_role or getattr(stage.mdin.details, "stage_role", None)
        if "mdout" in kinds:
            stage.mdout = MdoutParser(kinds["mdout"]).parse()
        if "mdcrd" in kinds:
            stage.mdcrd = MdcrdParser(kinds["mdcrd"]).parse()
        if "inpcrd" in kinds:
            stage.inpcrd = InpcrdParser(kinds["inpcrd"]).parse()
            stage.restart_path = kinds["inpcrd"]

        if include_roles and stage.stage_role and stage.stage_role not in include_roles:
            continue
        if include_roles and not stage.stage_role:
            continue

        restart_source = None
        if restart_files:
            for key in (stage.name, stage.stage_role):
                if key and key in restart_files:
                    restart_source = restart_files[key]
                    break

        if restart_source:
            stage.inpcrd = InpcrdParser(restart_source).parse()
            stage.restart_path = restart_source

        stages.append(stage)

    protocol = SimulationProtocol(stages=stages)
    protocol.validate(cross_stage=not skip_cross_stage_validation)
    return protocol


def load_manifest(manifest_path: str | os.PathLike[str]):
    """Load a manifest from YAML or JSON.

    Parameters
    ----------
    manifest_path:
        Path to a YAML or JSON manifest describing simulation stages.
    """

    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise ImportError("PyYAML is required to read YAML manifests. Install with `pip install pyyaml`.")
        manifest = yaml.safe_load(text)  # type: ignore[arg-type]
    else:
        manifest = json.loads(text)

    if manifest is None:
        return {}

    if not isinstance(manifest, (dict, list)):
        raise TypeError("Manifest must be a mapping or list of stage entries.")

    return manifest


def load_protocol_from_manifest(
    manifest_path: str | os.PathLike[str],
    *,
    directory: Optional[str] = None,
    include_roles: Optional[List[str]] = None,
    include_stems: Optional[List[str]] = None,
    restart_files: Optional[Dict[str, str]] = None,
    skip_cross_stage_validation: bool = False,
) -> SimulationProtocol:
    """Build a protocol using a manifest file.

    The manifest can be YAML or JSON. Relative file paths are resolved against
    the provided ``directory`` or the manifest's parent directory when omitted.
    """

    manifest = load_manifest(manifest_path)
    base_dir = directory or str(Path(manifest_path).parent)

    return auto_discover(
        base_dir,
        manifest=manifest,
        include_roles=include_roles,
        include_stems=include_stems,
        restart_files=restart_files,
        skip_cross_stage_validation=skip_cross_stage_validation,
    )


__all__ = [
    "SimulationProtocol",
    "SimulationStage",
    "auto_discover",
    "load_manifest",
    "load_protocol_from_manifest",
]
