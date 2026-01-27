from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Pattern

import re

from ambermeta.parsers.inpcrd import InpcrdData, InpcrdParser
from ambermeta.parsers.mdcrd import MdcrdData, MdcrdParser
from ambermeta.parsers.mdin import MdinData, MdinParser
from ambermeta.parsers.mdout import MdoutData, MdoutParser
from ambermeta.parsers.prmtop import PrmtopData, PrmtopParser
from ambermeta.legacy_extractors.prmtop import ION_RESNAMES, WATER_RESNAMES

try:  # pragma: no cover - optional dependency
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

try:  # pragma: no cover - optional dependency
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover - optional dependency
    try:
        import tomli as tomllib  # Fallback for older Python
    except ImportError:
        tomllib = None

import csv
from io import StringIO


def _serialize_value(value: Any, _visited: Optional[set] = None) -> Any:
    """Serialize a value to JSON-compatible types with circular reference detection."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value

    # Initialize visited set for circular reference detection
    if _visited is None:
        _visited = set()

    # Check for circular references using object id
    obj_id = id(value)
    if obj_id in _visited:
        return "<circular reference>"
    _visited.add(obj_id)

    try:
        if isinstance(value, (list, tuple, set)):
            return [_serialize_value(v, _visited) for v in value]
        if isinstance(value, dict):
            return {k: _serialize_value(v, _visited) for k, v in value.items()}
        if is_dataclass(value):
            return {k: _serialize_value(v, _visited) for k, v in asdict(value).items()}
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict()
            except TypeError:
                pass
        if hasattr(value, "__dict__"):
            return {k: _serialize_value(v, _visited) for k, v in value.__dict__.items() if not k.startswith("_")}
        return str(value)
    finally:
        # Remove from visited when done processing this branch
        _visited.discard(obj_id)


def _serialize_metadata(metadata: Any) -> Optional[Dict[str, Any]]:
    if metadata is None:
        return None

    return {
        "filename": getattr(metadata, "filename", None),
        "warnings": list(getattr(metadata, "warnings", []) or []),
        "details": _serialize_value(getattr(metadata, "details", None)),
    }


def _prune_methods_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        pruned = {}
        for key, val in value.items():
            cleaned = _prune_methods_value(val)
            if cleaned is None:
                continue
            # Only skip empty containers, not falsy values like 0 or False
            if isinstance(cleaned, (dict, list)) and len(cleaned) == 0:
                continue
            pruned[key] = cleaned
        return pruned
    if isinstance(value, list):
        pruned_list = []
        for item in value:
            cleaned = _prune_methods_value(item)
            if cleaned is None:
                continue
            # Only skip empty containers, not falsy values like 0 or False
            if isinstance(cleaned, (dict, list)) and len(cleaned) == 0:
                continue
            pruned_list.append(cleaned)
        return pruned_list
    return value


def _sanitize_identifier(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    normalized = value.strip()
    if not normalized or normalized.lower() in {"unknown", "none", "n/a"}:
        return None
    return normalized


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
        # Use standardized n_atoms property across all metadata classes
        if self.prmtop and self.prmtop.details and getattr(self.prmtop.details, "n_atoms", None):
            counts.append(self.prmtop.details.n_atoms)
            labels.append("prmtop")
        if self.inpcrd and self.inpcrd.details and getattr(self.inpcrd.details, "n_atoms", None):
            counts.append(self.inpcrd.details.n_atoms)
            labels.append("inpcrd")
        if self.mdout and self.mdout.details and getattr(self.mdout.details, "n_atoms", None):
            counts.append(self.mdout.details.n_atoms)
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

        # Only validate box consistency if multiple sources report box info
        # A single source having box info is not a validation issue
        if len(boxes) >= 2:
            # Could add box dimension comparison here if needed
            pass
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
            default_tolerance = 1e-6
            mdcrd_timestep = (
                getattr(self.mdcrd.details, "avg_dt", None) if self.mdcrd and self.mdcrd.details else None
            )

            for label, duration in expected_durations.items():
                if not isinstance(duration, (int, float)):
                    continue

                tolerance = default_tolerance
                if isinstance(mdcrd_timestep, (int, float)):
                    tolerance = max(tolerance, float(mdcrd_timestep))
                if isinstance(timesteps.get(label), (int, float)):
                    tolerance = max(tolerance, float(timesteps[label]))

                if abs(duration - mdcrd_duration) > tolerance:
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "stage_role": self.stage_role,
            "expected_gap_ps": self.expected_gap_ps,
            "gap_tolerance_ps": self.gap_tolerance_ps,
            "observed_gap_ps": self.observed_gap_ps,
            "restart_path": self.restart_path,
            "summary": self.summary(),
            "validation": list(self.validation),
            "continuity": list(self.continuity),
            "files": {
                "prmtop": _serialize_metadata(self.prmtop),
                "inpcrd": _serialize_metadata(self.inpcrd),
                "mdin": _serialize_metadata(self.mdin),
                "mdout": _serialize_metadata(self.mdout),
                "mdcrd": _serialize_metadata(self.mdcrd),
            },
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
            prev_mdcrd = prev.mdcrd and prev.mdcrd.details
            curr_inpcrd = current.inpcrd and current.inpcrd.details

            if not prev_mdcrd or not curr_inpcrd:
                # Add informational note when continuity check is skipped
                missing = []
                if not prev_mdcrd:
                    missing.append(f"mdcrd from {prev.name}")
                if not curr_inpcrd:
                    missing.append(f"inpcrd from {current.name}")
                current._add_continuity_note(
                    f"INFO: Cannot verify continuity between {prev.name} and {current.name} "
                    f"(missing {', '.join(missing)})"
                )
                continue

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "totals": self.totals(),
            "stages": [stage.to_dict() for stage in self.stages],
        }

    def to_methods_dict(self) -> Dict[str, Any]:
        def _collect_software(stage: SimulationStage) -> List[Dict[str, str]]:
            tools: List[Dict[str, str]] = []

            def _add_tool(source: str, program: Any, version: Any = None) -> None:
                program_clean = _sanitize_identifier(program)
                version_clean = _sanitize_identifier(version)
                if not program_clean and not version_clean:
                    return
                entry: Dict[str, str] = {"source": source}
                if program_clean:
                    entry["program"] = program_clean
                if version_clean:
                    entry["version"] = version_clean
                tools.append(entry)

            if stage.mdout and stage.mdout.details:
                _add_tool(
                    "mdout",
                    getattr(stage.mdout.details, "program", None),
                    getattr(stage.mdout.details, "version", None),
                )
            if stage.inpcrd and stage.inpcrd.details:
                _add_tool(
                    "inpcrd",
                    getattr(stage.inpcrd.details, "program", None),
                    getattr(stage.inpcrd.details, "program_version", None),
                )
            if stage.mdcrd and stage.mdcrd.details:
                _add_tool(
                    "mdcrd",
                    getattr(stage.mdcrd.details, "program", None),
                    None,
                )
            return tools

        def _collect_md_engine(stage: SimulationStage) -> Dict[str, Any]:
            md_engine: Dict[str, Any] = {}

            def _collect_pme_indicators(
                cntrl_parameters: Dict[str, Any], mdout_details: Optional[Any]
            ) -> Dict[str, Any]:
                indicators: Dict[str, Any] = {}
                pme_keys = (
                    "ew_type",
                    "pme",
                    "pme_enabled",
                    "use_pme",
                    "pme_grid",
                    "fft_grid",
                    "fft_grid_x",
                    "fft_grid_y",
                    "fft_grid_z",
                    "ewald",
                )
                for key in pme_keys:
                    if key in cntrl_parameters and cntrl_parameters[key] is not None:
                        indicators[key] = cntrl_parameters[key]
                if mdout_details is not None:
                    for key in pme_keys:
                        value = getattr(mdout_details, key, None)
                        if value is not None:
                            indicators.setdefault(key, value)
                return indicators

            if stage.mdin and stage.mdin.details:
                details = stage.mdin.details
                cntrl_parameters = getattr(details, "cntrl_parameters", {}) or {}
                md_engine.update(
                    {
                        "ensemble": getattr(details, "ensemble", None),
                        "thermostat": getattr(details, "temp_control", None),
                        "barostat": getattr(details, "press_control", None),
                        "temp_control": getattr(details, "temp_control", None),
                        "press_control": getattr(details, "press_control", None),
                        "cutoff": getattr(details, "cutoff", None),
                        "constraints": getattr(details, "constraints", None),
                        "pbc": getattr(details, "pbc", None),
                        "timestep_ps": getattr(details, "dt", None),
                        "run_length_steps": getattr(details, "length_steps", None),
                        "cntrl_parameters": cntrl_parameters or None,
                    }
                )
                pme_indicators = _collect_pme_indicators(cntrl_parameters, None)
                if pme_indicators:
                    md_engine["pme"] = pme_indicators
            if stage.mdout and stage.mdout.details:
                details = stage.mdout.details
                md_engine.setdefault("thermostat", getattr(details, "thermostat", None))
                md_engine.setdefault("barostat", getattr(details, "barostat", None))
                md_engine.setdefault("timestep_ps", getattr(details, "dt", None))
                md_engine.setdefault("run_length_steps", getattr(details, "nstlim", None))
                if getattr(details, "cutoff", None) is not None:
                    md_engine.setdefault("cutoff", getattr(details, "cutoff", None))
                    md_engine["cutoff_mdout"] = getattr(details, "cutoff", None)
                if getattr(details, "shake_active", None) is not None:
                    md_engine["shake_active"] = getattr(details, "shake_active", None)
                pme_indicators = _collect_pme_indicators({}, details)
                if pme_indicators:
                    existing_pme = md_engine.get("pme")
                    if isinstance(existing_pme, dict):
                        for key, value in pme_indicators.items():
                            existing_pme.setdefault(key, value)
                    else:
                        md_engine["pme"] = pme_indicators
            if md_engine.get("run_length_steps") and md_engine.get("timestep_ps"):
                try:
                    md_engine["run_length_ps"] = float(md_engine["run_length_steps"]) * float(md_engine["timestep_ps"])
                except (TypeError, ValueError):
                    pass
            return md_engine

        def _collect_restraints(stage: SimulationStage) -> Dict[str, Any]:
            if not stage.mdin or not stage.mdin.details:
                return {}

            details = stage.mdin.details
            cntrl = getattr(details, "cntrl_parameters", {}) or {}
            wt_schedules = getattr(details, "wt_schedules", []) or []
            definitions = getattr(details, "restraint_definitions", []) or []

            ntr_value = cntrl.get("ntr")
            restraint_weight = cntrl.get("restraint_wt")

            mask_keys = [
                key
                for key in cntrl.keys()
                if isinstance(key, str)
                and (
                    "restraintmask" in key.lower()
                    or key.lower().startswith("restraint_mask")
                    or key.lower().startswith("restraintmask")
                )
            ]
            mask_primary = cntrl.get("restraintmask")
            if mask_primary is None and mask_keys:
                mask_primary = cntrl.get(sorted(mask_keys, key=str.lower)[0])

            mask_variants = {
                key: cntrl.get(key)
                for key in sorted(mask_keys, key=str.lower)
                if key != "restraintmask"
            }

            schedule = []
            for entry in wt_schedules:
                quantity = getattr(entry, "quantity", None)
                if not quantity:
                    continue
                quantity_upper = str(quantity).upper()
                if not quantity_upper.startswith("REST"):
                    continue
                schedule.append(
                    {
                        "type": quantity_upper,
                        "start_step": getattr(entry, "istep1", None),
                        "end_step": getattr(entry, "istep2", None),
                        "start_value": getattr(entry, "value1", None),
                        "end_value": getattr(entry, "value2", None),
                        "increment": getattr(entry, "iinc", None),
                        "multiplier": getattr(entry, "imult", None),
                    }
                )

            active = getattr(details, "restraints_active", None)
            if active is None and ntr_value is not None:
                active = str(ntr_value) not in {"0", "0.0", "False", "false"}

            return {
                "active": active,
                "ntr": ntr_value,
                "weight": restraint_weight,
                "mask": {"primary": mask_primary, "variants": mask_variants},
                "definitions": list(definitions) if definitions else None,
                "schedule": schedule,
            }

        def _collect_system(stage: SimulationStage) -> Dict[str, Any]:
            atom_counts: Dict[str, Any] = {}
            if stage.prmtop and stage.prmtop.details:
                atom_counts["prmtop"] = getattr(stage.prmtop.details, "natom", None)
            if stage.inpcrd and stage.inpcrd.details:
                atom_counts["inpcrd"] = getattr(stage.inpcrd.details, "natoms", None)
            if stage.mdout and stage.mdout.details:
                atom_counts["mdout"] = getattr(stage.mdout.details, "natoms", None)
            if stage.mdcrd and stage.mdcrd.details:
                atom_counts["mdcrd"] = getattr(stage.mdcrd.details, "n_atoms", None)

            box_type = None
            if stage.mdout and stage.mdout.details:
                box_type = getattr(stage.mdout.details, "box_type", None) or box_type
            if stage.mdcrd and stage.mdcrd.details:
                box_type = getattr(stage.mdcrd.details, "box_type", None) or box_type

            box_dimensions = None
            box_angles = None
            if stage.inpcrd and stage.inpcrd.details:
                box_dimensions = getattr(stage.inpcrd.details, "box_dimensions", None) or box_dimensions
                box_angles = getattr(stage.inpcrd.details, "box_angles", None) or box_angles
            if stage.prmtop and stage.prmtop.details:
                box_dimensions = getattr(stage.prmtop.details, "box_dimensions", None) or box_dimensions
                box_angles = getattr(stage.prmtop.details, "box_angles", None) or box_angles

            box: Dict[str, Any] = {
                "type": box_type,
                "dimensions": box_dimensions,
                "angles": box_angles,
            }
            composition: Dict[str, Any] = {}
            if stage.prmtop and stage.prmtop.details:
                details = stage.prmtop.details
                residue_composition = getattr(details, "residue_composition", None)
                composition.update(
                    {
                        "residue_composition": residue_composition,
                        "num_solvent_molecules": getattr(details, "num_solvent_molecules", None),
                        "num_solute_residues": getattr(details, "num_solute_residues", None),
                        "total_charge": getattr(details, "total_charge", None),
                        "is_neutral": getattr(details, "is_neutral", None),
                        "initial_density": getattr(details, "density", None),  # From prmtop - initial value
                        "solvent_type": getattr(details, "solvent_type", None),
                        "simulation_category": getattr(details, "simulation_category", None),
                        "hmr_active": getattr(details, "hmr_active", None),
                        "hmr_hydrogen_mass_range": getattr(details, "hmr_hydrogen_mass_range", None),
                        "hmr_hydrogen_mass_summary": getattr(details, "hmr_hydrogen_mass_summary", None),
                    }
                )

            # Add observed density from mdout if available (actual simulation values)
            if stage.mdout and stage.mdout.details:
                mdout_details = stage.mdout.details
                density_stats = getattr(mdout_details, "density_stats", None)
                if density_stats:
                    avg, std = density_stats.get_stats()
                    if avg is not None:
                        composition["observed_density_mean"] = avg
                        composition["observed_density_std"] = std
                        # Use observed as the primary density if available
                        composition["density"] = avg
                    else:
                        # Fall back to initial density if no observed
                        composition["density"] = composition.get("initial_density")
                else:
                    composition["density"] = composition.get("initial_density")
            else:
                composition["density"] = composition.get("initial_density")

            # Add observed box dimensions from mdcrd if available
            if stage.mdcrd and stage.mdcrd.details:
                mdcrd_details = stage.mdcrd.details
                volume_stats = getattr(mdcrd_details, "volume_stats", None)
                if volume_stats:
                    composition["observed_volume_mean"] = volume_stats[2] if len(volume_stats) > 2 else None
                    composition["observed_volume_min"] = volume_stats[0] if len(volume_stats) > 0 else None
                    composition["observed_volume_max"] = volume_stats[1] if len(volume_stats) > 1 else None

            # Add water and ion information from residue composition
            if stage.prmtop and stage.prmtop.details:
                residue_composition = getattr(stage.prmtop.details, "residue_composition", None)
                if residue_composition:
                    water_residues = {
                        residue: count
                        for residue, count in residue_composition.items()
                        if residue in WATER_RESNAMES
                    }
                    ion_residues = {
                        residue: count
                        for residue, count in residue_composition.items()
                        if residue in ION_RESNAMES
                    }
                    composition.update(
                        {
                            "water_residue_counts": water_residues or None,
                            "ion_residue_counts": ion_residues or None,
                            "water_molecule_count": sum(water_residues.values()) if water_residues else None,
                            "ion_count": sum(ion_residues.values()) if ion_residues else None,
                        }
                    )

            return {"atom_counts": atom_counts, "box": box, "composition": composition}

        def _collect_trajectory(stage: SimulationStage) -> Dict[str, Any]:
            trajectory: Dict[str, Any] = {}
            if stage.mdin and stage.mdin.details:
                details = stage.mdin.details
                trajectory.update(
                    {
                        "coord_write_interval_steps": getattr(details, "coord_freq", None),
                        "traj_format": getattr(details, "traj_format", None),
                    }
                )
            if stage.mdcrd and stage.mdcrd.details:
                details = stage.mdcrd.details
                trajectory.setdefault("frame_interval_ps", getattr(details, "avg_dt", None))
                trajectory.setdefault("n_frames", getattr(details, "n_frames", None))
            return trajectory

        stages_payload = []
        stage_sequence = []
        for stage in self.stages:
            stage_sequence.append({"name": stage.name, "role": stage.stage_role})
            stage_payload = {
                "name": stage.name,
                "role": stage.stage_role,
                "software": _collect_software(stage),
                "md_engine": _collect_md_engine(stage),
                "restraints": _collect_restraints(stage),
                "system": _collect_system(stage),
                "trajectory_output": _collect_trajectory(stage),
            }
            stages_payload.append(_prune_methods_value(stage_payload))

        payload = {
            "stage_sequence": stage_sequence,
            "stages": stages_payload,
        }
        return _prune_methods_value(payload)


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


def validate_manifest(
    manifest: Dict[str, Dict[str, str]] | List[Dict[str, str]],
    directory: Optional[str] = None,
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
                resolved[kind] = os.path.join(directory, path)
            else:
                resolved[kind] = path

        for kind, path in resolved.items():
            if not os.path.exists(path):
                missing.append(f"stage '{name}', {kind}: {path}")

    if missing:
        message = "Manifest references missing files:\n" + "\n".join(missing)
        raise FileNotFoundError(message)


def _manifest_to_stages(
    manifest: Dict[str, Dict[str, str]] | List[Dict[str, str]],
    directory: Optional[str],
    include_roles: Optional[List[str]],
    include_stems: Optional[List[str]],
    restart_files: Optional[Dict[str, str]],
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> List[SimulationStage]:
    """Convert manifest entries to SimulationStage objects.

    Parameters
    ----------
    manifest:
        Manifest dictionary or list of stage entries.
    directory:
        Base directory for resolving relative paths.
    include_roles:
        Only include stages with these roles.
    include_stems:
        Only include stages with these names.
    restart_files:
        Mapping of stage name/role to restart file paths.
    progress_callback:
        Optional callback function(stage_name, current, total) for progress reporting.
    """
    kinds = {"prmtop", "inpcrd", "mdin", "mdout", "mdcrd"}
    stages: List[SimulationStage] = []
    validate_manifest(manifest, directory)

    # Count total entries for progress reporting
    entries = list(_normalize_manifest(manifest))
    total = len(entries)

    for idx, entry in enumerate(entries):
        name = entry.get("name")
        if not name:
            raise ValueError("Each manifest entry must include a 'name'.")
        stage_role = entry.get("stage_role")

        # Report progress
        if progress_callback:
            progress_callback(name, idx + 1, total)

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
            inferred_role = getattr(stage.mdin.details, "stage_role", None)
            if not stage.stage_role and inferred_role:
                stage.stage_role = inferred_role
                stage.validation.append(f"INFO: stage_role '{inferred_role}' inferred from mdin file")
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


def detect_numeric_sequences(filenames: List[str]) -> Dict[str, List[str]]:
    """Detect numeric sequences in filenames for automatic grouping.

    Identifies patterns in two formats:
    - Suffix format: prod_001, prod_002, etc. (common for production runs)
    - Prefix format: 01_min, 02_nvt, 03_npt, etc. (common for equilibration)

    Parameters
    ----------
    filenames:
        List of filenames to analyze.

    Returns
    -------
    Dictionary mapping base pattern to list of matching files in numeric order.
    """
    import re

    # Pattern to detect numeric suffixes: name_001, name.001, name001, name-001
    suffix_pattern = re.compile(r'^(.+?)[-_.]?(\d{2,})$')

    # Pattern to detect numeric prefixes: 01_name, 01.name, 01-name
    prefix_pattern = re.compile(r'^(\d{2,})[-_.]?(.+)$')

    groups: Dict[str, List[tuple[int, str]]] = {}

    for filename in filenames:
        stem = Path(filename).stem

        # Try suffix pattern first (prod_001, prod_002)
        match = suffix_pattern.match(stem)
        if match:
            base = match.group(1)
            num = int(match.group(2))
            groups.setdefault(f"suffix:{base}", []).append((num, filename))
            continue

        # Try prefix pattern (01_min, 02_nvt)
        match = prefix_pattern.match(stem)
        if match:
            num = int(match.group(1))
            # For prefix patterns, use the parent directory as additional grouping
            parent_dir = str(Path(filename).parent)
            if parent_dir == ".":
                parent_dir = ""
            base = f"prefix:{parent_dir}"
            groups.setdefault(base, []).append((num, filename))

    # Sort each group by numeric value and return just the filenames
    result: Dict[str, List[str]] = {}
    for base, items in groups.items():
        if len(items) >= 2:  # Only consider sequences with 2+ files
            items.sort(key=lambda x: x[0])
            # Clean up the base pattern for display
            clean_base = base.replace("suffix:", "").replace("prefix:", "")
            if not clean_base:
                # For prefix patterns without a parent dir, use a descriptive name
                clean_base = "numbered_sequence"
            result[clean_base] = [filename for _, filename in items]

    return result


def infer_stage_role_from_path(path: str) -> Optional[str]:
    """Infer stage role from the directory or file path.

    Examines path components and filename to detect stage type patterns.
    Common directory names like 'equil', 'prod', 'min' are recognized.
    """
    path_lower = path.lower()
    parts = path_lower.replace("\\", "/").split("/")

    # Check all path parts (directories and filename)
    for part in parts:
        # Minimization patterns
        if part.startswith("min") or "_min" in part or part == "em":
            return "minimization"

        # Heating patterns
        if "heat" in part or "warm" in part:
            return "heating"

        # Equilibration patterns
        if part.startswith("equil") or part == "nvt" or part == "npt" or "_equil" in part:
            return "equilibration"

        # Production patterns
        if part.startswith("prod") or "_prod" in part:
            return "production"

    # Check for common filename patterns
    filename = parts[-1] if parts else ""
    if any(x in filename for x in ("min", "minim", "em")):
        return "minimization"
    if any(x in filename for x in ("heat", "warm")):
        return "heating"
    if any(x in filename for x in ("equil", "nvt_", "npt_")):
        return "equilibration"
    if "prod" in filename:
        return "production"

    return None


def infer_stage_role_from_content(
    mdin_data: Optional[MdinData] = None,
    mdout_data: Optional[MdoutData] = None,
) -> Optional[str]:
    """Infer stage role from parsed file content.

    Uses heuristics based on simulation parameters to determine the stage type.
    """
    # Try mdin first
    if mdin_data and mdin_data.details:
        details = mdin_data.details
        inferred = getattr(details, "stage_role", None)
        if inferred:
            return inferred

        # Check for minimization indicators
        cntrl = getattr(details, "cntrl_parameters", {}) or {}
        imin = cntrl.get("imin")
        if imin == 1:
            return "minimization"

        # Check for heating (increasing temperature)
        tempi = cntrl.get("tempi", 0)
        temp0 = cntrl.get("temp0", 300)
        if isinstance(tempi, (int, float)) and isinstance(temp0, (int, float)):
            if tempi < temp0 and tempi < 50:
                return "heating"

        # Check for equilibration vs production
        ntr = cntrl.get("ntr")
        ibelly = cntrl.get("ibelly")
        if ntr == 1 or ibelly == 1:
            return "equilibration"

        # Check nstlim to distinguish short equilibration from long production
        nstlim = cntrl.get("nstlim", 0)
        if isinstance(nstlim, (int, float)) and nstlim > 500000:
            return "production"

    # Try mdout
    if mdout_data and mdout_data.details:
        details = mdout_data.details
        if getattr(details, "imin", None) == 1:
            return "minimization"

    return None


def auto_detect_restart_chain(
    stages: List[SimulationStage],
    directory: str,
) -> Dict[str, str]:
    """Automatically detect restart file chains between stages.

    Analyzes stages to find restart files that link them together based on:
    - Matching atom counts
    - Timestamp continuity
    - File naming conventions (e.g., prod_001.rst -> prod_002 uses it)

    Parameters
    ----------
    stages:
        List of simulation stages to analyze.
    directory:
        Base directory for finding restart files.

    Returns
    -------
    Dictionary mapping stage names to their restart file paths.
    """
    # Collect all potential restart files
    restart_candidates: List[tuple[str, InpcrdData]] = []

    ext_map = {".rst", ".rst7", ".ncrst", ".restrt", ".inpcrd"}

    # Scan for restart files
    for fname in os.listdir(directory):
        full_path = os.path.join(directory, fname)
        if not os.path.isfile(full_path):
            continue
        _, ext = os.path.splitext(fname)
        if ext.lower() not in ext_map:
            continue
        try:
            data = InpcrdParser(full_path).parse()
            restart_candidates.append((full_path, data))
        except (IOError, OSError, ValueError):
            continue

    if not restart_candidates:
        return {}

    restart_mapping: Dict[str, str] = {}

    # Try to match restarts to stages based on various heuristics
    for i, stage in enumerate(stages):
        if stage.restart_path:
            continue  # Already has a restart

        # Get target atom count for matching
        target_atoms: Optional[int] = None
        if stage.prmtop and stage.prmtop.details:
            target_atoms = getattr(stage.prmtop.details, "n_atoms", None)
        if target_atoms is None and stage.mdin and stage.mdin.details:
            # Some mdin files might reference atom count
            pass

        # Try to find matching restart
        best_match: Optional[tuple[str, float]] = None

        for rst_path, rst_data in restart_candidates:
            if not rst_data or not rst_data.details:
                continue

            # Check atom count match
            rst_atoms = getattr(rst_data.details, "n_atoms", None)
            if target_atoms and rst_atoms and target_atoms != rst_atoms:
                continue

            # Check naming convention match
            rst_stem = Path(rst_path).stem
            stage_stem = stage.name.replace("/", "_")

            # Common patterns: stagename.rst -> next stage, prev_stage.rst7 -> current
            score = 0.0

            # Check if restart name matches previous stage
            if i > 0:
                prev_name = stages[i - 1].name.replace("/", "_")
                if prev_name in rst_stem or rst_stem in prev_name:
                    score += 5.0

            # Check for numeric sequence matching
            stage_match = re.search(r'(\d{2,})', stage_stem)
            rst_match = re.search(r'(\d{2,})', rst_stem)
            if stage_match and rst_match:
                stage_num = int(stage_match.group(1))
                rst_num = int(rst_match.group(1))
                if rst_num == stage_num - 1:
                    score += 10.0  # Previous sequence number is ideal
                elif rst_num == stage_num:
                    score += 3.0

            # Check timestamp if previous stage has end time
            if i > 0 and stages[i - 1].mdcrd and stages[i - 1].mdcrd.details:
                prev_end = getattr(stages[i - 1].mdcrd.details, "time_end", None)
                rst_time = getattr(rst_data.details, "time", None)
                if prev_end is not None and rst_time is not None:
                    if abs(prev_end - rst_time) < 0.1:  # Within 0.1 ps
                        score += 20.0

            if score > 0 and (best_match is None or score > best_match[1]):
                best_match = (rst_path, score)

        if best_match and best_match[1] >= 5.0:  # Minimum confidence threshold
            restart_mapping[stage.name] = best_match[0]

    return restart_mapping


def smart_group_files(
    directory: str,
    pattern: Optional[str] = None,
    recursive: bool = False,
) -> Dict[str, Dict[str, str]]:
    """Smart grouping of simulation files based on patterns and sequences.

    Automatically detects numeric sequences and groups related files together.

    Parameters
    ----------
    directory:
        Directory to scan for files.
    pattern:
        Optional regex pattern to filter files.
    recursive:
        If True, search subdirectories.

    Returns
    -------
    Dictionary mapping stage names to file paths by type.
    """
    discovered: List[tuple[str, str]] = []

    if recursive:
        for root, _, filenames in os.walk(directory):
            for fname in filenames:
                full_path = os.path.join(root, fname)
                if os.path.isfile(full_path):
                    rel_path = os.path.relpath(full_path, directory)
                    discovered.append((rel_path, full_path))
    else:
        for fname in os.listdir(directory):
            full_path = os.path.join(directory, fname)
            if os.path.isfile(full_path):
                discovered.append((fname, full_path))

    # Apply pattern filter if provided
    if pattern:
        compiled = re.compile(pattern)
        discovered = [(rel, full) for rel, full in discovered if compiled.search(rel)]

    ext_map = {
        ".prmtop": "prmtop",
        ".top": "prmtop",
        ".parm7": "prmtop",
        ".inpcrd": "inpcrd",
        ".rst": "inpcrd",
        ".rst7": "inpcrd",
        ".ncrst": "inpcrd",
        ".restrt": "inpcrd",
        ".mdin": "mdin",
        ".in": "mdin",
        ".mdout": "mdout",
        ".out": "mdout",
        ".mdcrd": "mdcrd",
        ".nc": "mdcrd",
        ".crd": "mdcrd",
        ".x": "mdcrd",
    }

    # Group by stem
    grouped: Dict[str, Dict[str, str]] = {}

    for rel_path, full_path in discovered:
        stem = Path(rel_path).with_suffix("").as_posix()
        _, ext = os.path.splitext(rel_path)
        kind = ext_map.get(ext.lower())
        if not kind:
            continue
        grouped.setdefault(stem, {})[kind] = full_path

    # Detect and handle numeric sequences
    all_stems = list(grouped.keys())
    sequences = detect_numeric_sequences(all_stems)

    # Add sequence metadata to groups
    for base_pattern, sequence_stems in sequences.items():
        for idx, stem in enumerate(sequence_stems):
            if stem in grouped:
                grouped[stem]["_sequence_base"] = base_pattern
                grouped[stem]["_sequence_index"] = str(idx)
                grouped[stem]["_sequence_length"] = str(len(sequence_stems))

    return grouped


def auto_discover(
    directory: str,
    manifest: Optional[Dict[str, Dict[str, str]] | List[Dict[str, str]]] = None,
    grouping_rules: Optional[Dict[str, str]] = None,
    include_roles: Optional[List[str]] = None,
    include_stems: Optional[List[str]] = None,
    restart_files: Optional[Dict[str, str]] = None,
    skip_cross_stage_validation: bool = False,
    recursive: bool = False,
    auto_detect_restarts: bool = False,
    pattern_filter: Optional[str] = None,
    global_prmtop: Optional[str] = None,
    hmr_prmtop: Optional[str] = None,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> SimulationProtocol:
    if manifest is not None:
        stages = _manifest_to_stages(
            manifest,
            directory=directory,
            include_roles=include_roles,
            include_stems=include_stems,
            restart_files=restart_files,
            progress_callback=progress_callback,
        )
        # Apply auto restart detection if requested
        if auto_detect_restarts:
            auto_restarts = auto_detect_restart_chain(stages, directory)
            for stage in stages:
                if stage.name in auto_restarts and not stage.restart_path:
                    rst_path = auto_restarts[stage.name]
                    stage.inpcrd = InpcrdParser(rst_path).parse()
                    stage.restart_path = rst_path
                    stage.validation.append(f"INFO: restart file auto-detected: {rst_path}")

        # Apply global prmtop to stages that don't have one
        if global_prmtop:
            global_prmtop_path = os.path.join(directory, global_prmtop) if not os.path.isabs(global_prmtop) else global_prmtop
            if os.path.exists(global_prmtop_path):
                global_prmtop_data = PrmtopParser(global_prmtop_path).parse()
                for stage in stages:
                    if not stage.prmtop:
                        stage.prmtop = global_prmtop_data
                        stage.validation.append(f"INFO: using global prmtop: {global_prmtop}")

        # Apply HMR prmtop to stages with large timesteps (dt >= 0.004 ps)
        if hmr_prmtop:
            hmr_prmtop_path = os.path.join(directory, hmr_prmtop) if not os.path.isabs(hmr_prmtop) else hmr_prmtop
            if os.path.exists(hmr_prmtop_path):
                hmr_prmtop_data = PrmtopParser(hmr_prmtop_path).parse()
                for stage in stages:
                    # Check if stage uses large timestep (HMR typically requires dt >= 0.004 ps)
                    dt = None
                    if stage.mdin and hasattr(stage.mdin, 'dt'):
                        dt = stage.mdin.dt
                    elif stage.mdout and hasattr(stage.mdout, 'dt'):
                        dt = stage.mdout.dt

                    if dt is not None and dt >= 0.004:
                        stage.prmtop = hmr_prmtop_data
                        stage.validation.append(f"INFO: using HMR prmtop (dt={dt} ps): {hmr_prmtop}")

        protocol = SimulationProtocol(stages=stages)
        protocol.validate(cross_stage=not skip_cross_stage_validation)
        return protocol

    # Use smart grouping for file discovery
    grouped = smart_group_files(directory, pattern=pattern_filter, recursive=recursive)

    compiled_rules: List[tuple[Pattern[str], str]] = []
    if grouping_rules:
        for pattern, role in grouping_rules.items():
            try:
                compiled_rules.append((re.compile(pattern), role))
            except re.error:
                compiled_rules.append((re.compile(re.escape(pattern)), role))

    stages: List[SimulationStage] = []
    for stem, kinds in sorted(grouped.items()):
        # Skip internal metadata keys
        file_kinds = {k: v for k, v in kinds.items() if not k.startswith("_")}

        stage_role: Optional[str] = None
        for pattern, role in compiled_rules:
            if pattern.search(stem):
                stage_role = role
                break

        if include_stems and stem not in include_stems:
            continue

        stage = SimulationStage(name=stem, stage_role=stage_role)

        # Add sequence info as validation notes if detected
        if "_sequence_base" in kinds:
            seq_base = kinds["_sequence_base"]
            seq_idx = kinds.get("_sequence_index", "?")
            seq_len = kinds.get("_sequence_length", "?")
            stage.validation.append(
                f"INFO: Part of sequence '{seq_base}' (item {int(seq_idx)+1} of {seq_len})"
            )

        if "prmtop" in file_kinds:
            stage.prmtop = PrmtopParser(file_kinds["prmtop"]).parse()
        if "mdin" in file_kinds:
            stage.mdin = MdinParser(file_kinds["mdin"]).parse()
            # Try mdin-based inference first
            inferred_role = getattr(stage.mdin.details, "stage_role", None)
            if not stage.stage_role and inferred_role:
                stage.stage_role = inferred_role
                stage.validation.append(f"INFO: stage_role '{inferred_role}' inferred from mdin file")
        if "mdout" in file_kinds:
            stage.mdout = MdoutParser(file_kinds["mdout"]).parse()
        if "mdcrd" in file_kinds:
            stage.mdcrd = MdcrdParser(file_kinds["mdcrd"]).parse()
        if "inpcrd" in file_kinds:
            stage.inpcrd = InpcrdParser(file_kinds["inpcrd"]).parse()
            stage.restart_path = file_kinds["inpcrd"]

        # Try content-based role inference if still no role
        if not stage.stage_role:
            inferred = infer_stage_role_from_content(stage.mdin, stage.mdout)
            if inferred:
                stage.stage_role = inferred
                stage.validation.append(f"INFO: stage_role '{inferred}' inferred from file content")

        # Try path-based role inference as final fallback
        if not stage.stage_role:
            inferred = infer_stage_role_from_path(stem)
            if inferred:
                stage.stage_role = inferred
                stage.validation.append(f"INFO: stage_role '{inferred}' inferred from path")

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

    # Apply auto restart detection if requested
    if auto_detect_restarts:
        auto_restarts = auto_detect_restart_chain(stages, directory)
        for stage in stages:
            if stage.name in auto_restarts and not stage.restart_path:
                rst_path = auto_restarts[stage.name]
                stage.inpcrd = InpcrdParser(rst_path).parse()
                stage.restart_path = rst_path
                stage.validation.append(f"INFO: restart file auto-detected: {rst_path}")

    # Apply global prmtop to stages that don't have one
    if global_prmtop:
        global_prmtop_path = os.path.join(directory, global_prmtop) if not os.path.isabs(global_prmtop) else global_prmtop
        if os.path.exists(global_prmtop_path):
            global_prmtop_data = PrmtopParser(global_prmtop_path).parse()
            for stage in stages:
                if not stage.prmtop:
                    stage.prmtop = global_prmtop_data
                    stage.validation.append(f"INFO: using global prmtop: {global_prmtop}")

    protocol = SimulationProtocol(stages=stages)
    protocol.validate(cross_stage=not skip_cross_stage_validation)
    return protocol


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in string values.

    Supports ${VAR} and $VAR syntax. Undefined variables are left unchanged.
    """
    if isinstance(value, str):
        # Expand ${VAR} syntax
        result = value
        import re
        for match in re.finditer(r'\$\{([^}]+)\}', value):
            var_name = match.group(1)
            env_value = os.environ.get(var_name)
            if env_value is not None:
                result = result.replace(match.group(0), env_value)
        # Expand $VAR syntax (only if not followed by {)
        for match in re.finditer(r'\$([A-Za-z_][A-Za-z0-9_]*)(?!\{)', result):
            var_name = match.group(1)
            env_value = os.environ.get(var_name)
            if env_value is not None:
                result = result.replace(match.group(0), env_value)
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
        if stage.get("name"):
            stages.append(stage)

    return stages


def _parse_toml_manifest(text: str) -> Dict[str, Any] | List[Dict[str, Any]]:
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

    # If there's a 'stages' key with a list, return that
    if "stages" in data and isinstance(data["stages"], list):
        return data["stages"]

    # If the data is a dict with stage names as keys
    return data


def load_manifest(
    manifest_path: str | os.PathLike[str],
    expand_env: bool = True,
) -> Dict[str, Any] | List[Dict[str, Any]]:
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
    Manifest data as a list of stage dictionaries or a mapping.
    """

    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise ImportError("PyYAML is required to read YAML manifests. Install with `pip install pyyaml`.")
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

    # Expand environment variables if requested
    if expand_env:
        manifest = _expand_env_vars(manifest)

    return manifest


def load_protocol_from_manifest(
    manifest_path: str | os.PathLike[str],
    *,
    directory: Optional[str] = None,
    include_roles: Optional[List[str]] = None,
    include_stems: Optional[List[str]] = None,
    restart_files: Optional[Dict[str, str]] = None,
    skip_cross_stage_validation: bool = False,
    recursive: bool = False,
    expand_env: bool = True,
    global_prmtop: Optional[str] = None,
    hmr_prmtop: Optional[str] = None,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> SimulationProtocol:
    """Build a protocol using a manifest file.

    The manifest can be YAML, JSON, TOML, or CSV. Relative file paths are
    resolved against the provided ``directory`` or the manifest's parent
    directory when omitted.

    Parameters
    ----------
    manifest_path:
        Path to the manifest file.
    directory:
        Base directory for resolving relative paths in the manifest.
    include_roles:
        Only include stages with these roles.
    include_stems:
        Only include stages with these names.
    restart_files:
        Mapping of stage name/role to restart file paths.
    skip_cross_stage_validation:
        If True, skip continuity checks between stages.
    recursive:
        If True, search subdirectories for files.
    expand_env:
        If True, expand environment variables in file paths.
    global_prmtop:
        Global prmtop file to use for stages without their own prmtop.
    hmr_prmtop:
        HMR prmtop file to use for stages with large timesteps (dt >= 0.004).
    progress_callback:
        Optional callback function(stage_name, current, total) for progress reporting.
    """

    manifest_data = load_manifest(manifest_path, expand_env=expand_env)
    base_dir = directory or str(Path(manifest_path).parent)

    # Extract global settings from manifest if present
    manifest_global_prmtop = None
    manifest_hmr_prmtop = None
    stages_list = manifest_data

    if isinstance(manifest_data, dict):
        # Manifest may contain global settings
        manifest_global_prmtop = manifest_data.get("global_prmtop")
        manifest_hmr_prmtop = manifest_data.get("hmr_prmtop")

        # Extract stages list
        if "stages" in manifest_data and isinstance(manifest_data["stages"], list):
            stages_list = manifest_data["stages"]
        else:
            # It's a dict with stage names as keys
            stages_list = manifest_data

    # CLI parameters override manifest settings
    effective_global_prmtop = global_prmtop or manifest_global_prmtop
    effective_hmr_prmtop = hmr_prmtop or manifest_hmr_prmtop

    return auto_discover(
        base_dir,
        manifest=stages_list,
        include_roles=include_roles,
        include_stems=include_stems,
        restart_files=restart_files,
        skip_cross_stage_validation=skip_cross_stage_validation,
        recursive=recursive,
        global_prmtop=effective_global_prmtop,
        hmr_prmtop=effective_hmr_prmtop,
        progress_callback=progress_callback,
    )


class ProtocolBuilder:
    """Fluent builder for constructing SimulationProtocol objects.

    Provides a chainable API for building protocols step by step with
    built-in validation.

    Example
    -------
    >>> protocol = (
    ...     ProtocolBuilder()
    ...     .from_directory("/path/to/files")
    ...     .with_grouping_rules({"prod": "production"})
    ...     .auto_detect_restarts()
    ...     .skip_validation()
    ...     .build()
    ... )
    """

    def __init__(self) -> None:
        self._directory: Optional[str] = None
        self._manifest: Optional[Dict[str, Any] | List[Dict[str, Any]]] = None
        self._manifest_path: Optional[str] = None
        self._grouping_rules: Optional[Dict[str, str]] = None
        self._include_roles: Optional[List[str]] = None
        self._include_stems: Optional[List[str]] = None
        self._restart_files: Optional[Dict[str, str]] = None
        self._skip_cross_stage_validation: bool = False
        self._recursive: bool = False
        self._auto_detect_restarts: bool = False
        self._pattern_filter: Optional[str] = None
        self._expand_env: bool = True
        self._stages: List[SimulationStage] = []
        self._stage_tolerances: Dict[str, tuple[float, float]] = {}

    def from_directory(self, directory: str, recursive: bool = False) -> "ProtocolBuilder":
        """Set the base directory for file discovery.

        Parameters
        ----------
        directory:
            Path to directory containing simulation files.
        recursive:
            If True, search subdirectories.
        """
        self._directory = os.path.abspath(directory)
        self._recursive = recursive
        return self

    def from_manifest(
        self,
        manifest_path: str,
        directory: Optional[str] = None,
        expand_env: bool = True,
    ) -> "ProtocolBuilder":
        """Load stages from a manifest file.

        Parameters
        ----------
        manifest_path:
            Path to YAML, JSON, TOML, or CSV manifest.
        directory:
            Base directory for relative paths (defaults to manifest location).
        expand_env:
            If True, expand environment variables in paths.
        """
        self._manifest_path = manifest_path
        self._manifest = load_manifest(manifest_path, expand_env=expand_env)
        self._directory = directory or str(Path(manifest_path).parent)
        self._expand_env = expand_env
        return self

    def with_grouping_rules(self, rules: Dict[str, str]) -> "ProtocolBuilder":
        """Set regex-based grouping rules for stage role assignment.

        Parameters
        ----------
        rules:
            Dictionary mapping regex patterns to stage roles.
        """
        self._grouping_rules = rules
        return self

    def with_pattern_filter(self, pattern: str) -> "ProtocolBuilder":
        """Filter discovered files using a regex pattern.

        Parameters
        ----------
        pattern:
            Regex pattern to match against filenames.
        """
        self._pattern_filter = pattern
        return self

    def include_roles(self, roles: List[str]) -> "ProtocolBuilder":
        """Only include stages with specific roles.

        Parameters
        ----------
        roles:
            List of role names to include.
        """
        self._include_roles = roles
        return self

    def include_stems(self, stems: List[str]) -> "ProtocolBuilder":
        """Only include stages with specific names.

        Parameters
        ----------
        stems:
            List of stage names to include.
        """
        self._include_stems = stems
        return self

    def with_restart_files(self, restart_files: Dict[str, str]) -> "ProtocolBuilder":
        """Specify restart files for stages.

        Parameters
        ----------
        restart_files:
            Dictionary mapping stage name/role to restart file path.
        """
        self._restart_files = restart_files
        return self

    def auto_detect_restarts(self, enable: bool = True) -> "ProtocolBuilder":
        """Enable automatic restart chain detection.

        When enabled, the builder will try to automatically link restart
        files between stages based on naming patterns and timestamps.
        """
        self._auto_detect_restarts = enable
        return self

    def skip_validation(self, skip: bool = True) -> "ProtocolBuilder":
        """Skip cross-stage validation checks.

        Parameters
        ----------
        skip:
            If True, skip continuity validation between stages.
        """
        self._skip_cross_stage_validation = skip
        return self

    def with_stage_tolerance(
        self,
        stage_name: str,
        expected_gap_ps: float,
        tolerance_ps: float = 0.1,
    ) -> "ProtocolBuilder":
        """Set per-stage gap tolerance.

        Parameters
        ----------
        stage_name:
            Name of the stage to configure.
        expected_gap_ps:
            Expected gap before this stage in picoseconds.
        tolerance_ps:
            Allowed tolerance for gap validation.
        """
        self._stage_tolerances[stage_name] = (expected_gap_ps, tolerance_ps)
        return self

    def add_stage(
        self,
        name: str,
        stage_role: Optional[str] = None,
        prmtop: Optional[str] = None,
        mdin: Optional[str] = None,
        mdout: Optional[str] = None,
        mdcrd: Optional[str] = None,
        inpcrd: Optional[str] = None,
        expected_gap_ps: Optional[float] = None,
        gap_tolerance_ps: Optional[float] = None,
    ) -> "ProtocolBuilder":
        """Manually add a stage to the protocol.

        Parameters
        ----------
        name:
            Unique stage identifier.
        stage_role:
            Stage type (minimization, equilibration, production, etc.).
        prmtop, mdin, mdout, mdcrd, inpcrd:
            Paths to simulation files.
        expected_gap_ps:
            Expected gap before this stage in picoseconds.
        gap_tolerance_ps:
            Tolerance for gap validation.
        """
        stage = SimulationStage(
            name=name,
            stage_role=stage_role,
            expected_gap_ps=expected_gap_ps,
            gap_tolerance_ps=gap_tolerance_ps,
        )

        base_dir = self._directory or "."

        if prmtop:
            path = prmtop if os.path.isabs(prmtop) else os.path.join(base_dir, prmtop)
            stage.prmtop = PrmtopParser(path).parse()
        if mdin:
            path = mdin if os.path.isabs(mdin) else os.path.join(base_dir, mdin)
            stage.mdin = MdinParser(path).parse()
        if mdout:
            path = mdout if os.path.isabs(mdout) else os.path.join(base_dir, mdout)
            stage.mdout = MdoutParser(path).parse()
        if mdcrd:
            path = mdcrd if os.path.isabs(mdcrd) else os.path.join(base_dir, mdcrd)
            stage.mdcrd = MdcrdParser(path).parse()
        if inpcrd:
            path = inpcrd if os.path.isabs(inpcrd) else os.path.join(base_dir, inpcrd)
            stage.inpcrd = InpcrdParser(path).parse()
            stage.restart_path = path

        self._stages.append(stage)
        return self

    def build(self) -> SimulationProtocol:
        """Build and return the SimulationProtocol.

        Returns
        -------
        SimulationProtocol with all configured stages validated.
        """
        if self._stages:
            # Manual stages were added
            protocol = SimulationProtocol(stages=list(self._stages))
        elif self._manifest is not None and self._directory:
            # Use manifest
            protocol = auto_discover(
                self._directory,
                manifest=self._manifest,
                grouping_rules=self._grouping_rules,
                include_roles=self._include_roles,
                include_stems=self._include_stems,
                restart_files=self._restart_files,
                skip_cross_stage_validation=True,  # We'll validate after applying tolerances
                recursive=self._recursive,
                auto_detect_restarts=self._auto_detect_restarts,
                pattern_filter=self._pattern_filter,
            )
        elif self._directory:
            # Discover from directory
            protocol = auto_discover(
                self._directory,
                grouping_rules=self._grouping_rules,
                include_roles=self._include_roles,
                include_stems=self._include_stems,
                restart_files=self._restart_files,
                skip_cross_stage_validation=True,  # We'll validate after applying tolerances
                recursive=self._recursive,
                auto_detect_restarts=self._auto_detect_restarts,
                pattern_filter=self._pattern_filter,
            )
        else:
            raise ValueError("No directory or manifest specified. Use from_directory() or from_manifest().")

        # Apply per-stage tolerances
        for stage in protocol.stages:
            if stage.name in self._stage_tolerances:
                expected, tolerance = self._stage_tolerances[stage.name]
                stage.expected_gap_ps = expected
                stage.gap_tolerance_ps = tolerance

        # Validate now with proper tolerances applied
        if not self._skip_cross_stage_validation:
            protocol.validate(cross_stage=True)

        return protocol


__all__ = [
    "SimulationProtocol",
    "SimulationStage",
    "ProtocolBuilder",
    "auto_discover",
    "detect_numeric_sequences",
    "infer_stage_role_from_content",
    "auto_detect_restart_chain",
    "smart_group_files",
    "load_manifest",
    "load_protocol_from_manifest",
]
