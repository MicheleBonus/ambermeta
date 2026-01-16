from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern

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


def _serialize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if is_dataclass(value):
        return {k: _serialize_value(v) for k, v in asdict(value).items()}
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict()
        except TypeError:
            pass
    if hasattr(value, "__dict__"):
        return {k: _serialize_value(v) for k, v in value.__dict__.items() if not k.startswith("_")}
    return str(value)


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
            if isinstance(cleaned, (dict, list)) and not cleaned:
                continue
            pruned[key] = cleaned
        return pruned
    if isinstance(value, list):
        pruned_list = []
        for item in value:
            cleaned = _prune_methods_value(item)
            if cleaned is None:
                continue
            if isinstance(cleaned, (dict, list)) and not cleaned:
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
                        "density": getattr(details, "density", None),
                        "solvent_type": getattr(details, "solvent_type", None),
                        "simulation_category": getattr(details, "simulation_category", None),
                    }
                )

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
) -> List[SimulationStage]:
    kinds = {"prmtop", "inpcrd", "mdin", "mdout", "mdcrd"}
    stages: List[SimulationStage] = []
    validate_manifest(manifest, directory)
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
    recursive: bool = False,
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

    for rel_path, full_path in discovered:
        stem = Path(rel_path).with_suffix("").as_posix()
        _, ext = os.path.splitext(rel_path)
        kind = ext_map.get(ext.lower())
        if not kind:
            continue
        grouped.setdefault(stem, {})[kind] = full_path

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
    recursive: bool = False,
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
        recursive=recursive,
    )


__all__ = [
    "SimulationProtocol",
    "SimulationStage",
    "auto_discover",
    "load_manifest",
    "load_protocol_from_manifest",
]
