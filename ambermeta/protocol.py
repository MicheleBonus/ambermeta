from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Pattern, Tuple

import re

from ambermeta.parsers.inpcrd import InpcrdData, InpcrdParser
from ambermeta.parsers.mdcrd import MdcrdData, MdcrdParser
from ambermeta.parsers.mdin import MdinData, MdinParser
from ambermeta.parsers.mdout import MdoutData, MdoutParser
from ambermeta.parsers.prmtop import PrmtopData, PrmtopParser
from ambermeta.legacy_extractors.prmtop import ION_RESNAMES, WATER_RESNAMES
from ambermeta.topology_pool import implies_hmr
from ambermeta.errors import AmberMetaError, FileLoadError, classify_exception
from ambermeta.logging_config import get_logger
from ambermeta.roles import classify_role
from ambermeta.lineages import UNTAGGED, buckets, infer_lineages_from_layout
# The one spelling of the boundary rule. Its parameters are annotated `Step` but it reads
# nothing except `.lineage`, and `SimulationStage` carries that too — re-stating the rule
# here would make a third copy of it, which is how the two chainers drifted apart already.
from ambermeta.simulation import crosses_lineage
from ambermeta.manifest import (
    validate_manifest,
    _normalize_manifest,
)

logger = get_logger(__name__)

# Timestep threshold (ps) at or above which HMR is assumed to be active.
HMR_TIMESTEP_THRESHOLD_PS = 0.003  # >= 3 fs indicates HMR


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
    # Provenance. `lineage` names the run member this stage belongs to: read from the v2
    # document on the manifest path, inferred from the directory layout on the scan path —
    # both entries into this engine, because a stage the engine cannot place in a member is
    # one it will compare against whatever happens to precede it.
    # `step_id`/`parent_id` are the document's own step ids and exist only where a document
    # does. They are kept because the flatten resolves input_coords down to a bare inpcrd
    # path — after that the edge is unrecoverable, and a lineage head has to be checked
    # against the step it really continues from rather than against its document-order
    # neighbour.
    lineage: Optional[str] = None
    step_id: Optional[str] = None
    parent_id: Optional[str] = None
    validation: List[str] = field(default_factory=list)
    continuity: List[str] = field(default_factory=list)
    load_errors: List[FileLoadError] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        """True when one or more of this stage's files failed to parse."""
        return bool(self.load_errors)

    def validate(self) -> None:
        existing = set(self.validation)
        for msg in (
            self._validate_atoms()
            + self._validate_box()
            + self._validate_timing()
            + self._validate_sampling()
        ):
            if msg not in existing:
                self.validation.append(msg)
                existing.add(msg)

    def _validate_atoms(self) -> List[str]:
        counts = []
        labels = []
        # Use standardized n_atoms property across all metadata classes
        n_atoms = getattr(self.prmtop.details, "n_atoms", None) if self.prmtop and self.prmtop.details else None
        if n_atoms is not None:
            counts.append(n_atoms)
            labels.append("prmtop")
        n_atoms = getattr(self.inpcrd.details, "n_atoms", None) if self.inpcrd and self.inpcrd.details else None
        if n_atoms is not None:
            counts.append(n_atoms)
            labels.append("inpcrd")
        n_atoms = getattr(self.mdout.details, "n_atoms", None) if self.mdout and self.mdout.details else None
        if n_atoms is not None:
            counts.append(n_atoms)
            labels.append("mdout")
        n_atoms = getattr(self.mdcrd.details, "n_atoms", None) if self.mdcrd and self.mdcrd.details else None
        if n_atoms is not None:
            counts.append(n_atoms)
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
            "degraded": self.degraded,
            "load_errors": [e.to_dict() for e in self.load_errors],
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

    def validate(self, cross_stage: bool = True, allow_unexpected_gaps: bool = False) -> None:
        for stage in self.stages:
            stage.validate()
        if cross_stage:
            self._check_continuity(allow_unexpected_gaps=allow_unexpected_gaps)

    def _check_continuity(self, allow_unexpected_gaps: bool = False) -> None:
        if not any(stage.lineage for stage in self.stages):
            # One member: the partition below reduces to exactly this zip, but the head
            # check would add a note to the document's first stage. `observed_gap_ps` and
            # the note lists are serialised into summary.json, so an untagged document
            # keeps the original path rather than a path that merely ought to agree.
            for prev, current in zip(self.stages, self.stages[1:]):
                self._check_stage_pair(prev, current, allow_unexpected_gaps=allow_unexpected_gaps)
            return

        # Document order is not experiment order once there is more than one member:
        # replicas interleave, and `discover` emits them phase-major, so a neighbour zip
        # compares each member's head against another member's tail and reports an
        # overlap that never happened.
        partitions = buckets(self.stages)
        for member in partitions.values():
            for prev, current in zip(member, member[1:]):
                self._check_stage_pair(prev, current, allow_unexpected_gaps=allow_unexpected_gaps)

        # Partitioning on its own drops a check that was correct: a head genuinely
        # continues the stage it branched from, and leaving it at `observed_gap_ps=None`
        # with no note reads as "checked and fine" rather than "not checked". So every
        # head is measured against its real producer, which is why `parent_id` is carried
        # this far — the flatten resolves input_coords down to a bare path and the edge is
        # unrecoverable afterwards.
        by_step_id = {s.step_id: s for s in self.stages if s.step_id}
        for member in partitions.values():
            head = member[0]
            producer = by_step_id.get(head.parent_id) if head.parent_id else None
            # "resolved" rather than "recorded": the id may be absent, may name a stage
            # this protocol does not hold, or may name the head itself. All three mean the
            # same thing to a reader — nothing was compared.
            #
            # A head that came from `discover` always lands here, and that is deliberate,
            # not a hole to be plugged: `discover_draft` gives every member's first run
            # `starting_structure`, because a restart file sitting beside a replica is not
            # evidence of which run read it. Chaining the head to whatever precedes it in
            # the document is the false continuation this partition exists to remove — so
            # the note IS the answer for a discovered head. A declared producer (a
            # hand-written manifest, an edit in the GUI) is the only thing that earns a
            # real measurement, and it gets one on the line below.
            if producer is None or producer is head:
                head._add_continuity_note(
                    f"INFO: Continuity for {head.name} was not measured "
                    "(no producing stage resolved)."
                )
                continue
            self._check_stage_pair(producer, head, allow_unexpected_gaps=allow_unexpected_gaps)

    def _check_stage_pair(
        self,
        prev: SimulationStage,
        current: SimulationStage,
        allow_unexpected_gaps: bool = False,
    ) -> None:
        """Compare one producer/consumer pair and record what it says about `current`.

        Split out of :meth:`_check_continuity` so the same check can be applied to a pair
        that is *not* adjacent in document order — a lineage head and the stage it really
        continues from. The body is unchanged; only the loop's `continue`s became
        `return`s.
        """
        end_time = None
        if prev.mdcrd and prev.mdcrd.details:
            end_time = getattr(prev.mdcrd.details, "time_end", None)
        if end_time is None and prev.mdout and prev.mdout.details:
            stats = getattr(prev.mdout.details, "stats", None)
            if stats is not None and getattr(stats, "count", 0):
                end_time = getattr(stats, "time_end", None)

        start_time = None
        if current.inpcrd and current.inpcrd.details:
            start_time = getattr(current.inpcrd.details, "time", None)

        if end_time is None or start_time is None:
            # Add informational note when continuity check is skipped
            missing = []
            if end_time is None:
                missing.append(f"end time from {prev.name} (no mdcrd/mdout)")
            if start_time is None:
                missing.append(f"inpcrd time from {current.name}")
            current._add_continuity_note(
                f"INFO: Cannot verify continuity between {prev.name} and {current.name} "
                f"(missing {', '.join(missing)})"
            )
            return

        gap = start_time - end_time

        # Tolerance is a small absolute floor plus half a frame interval —
        # NOT scaled by elapsed time, which would hide real gaps in long runs.
        prior_dt = (
            getattr(prev.mdcrd.details, "avg_dt", None)
            if (prev.mdcrd and prev.mdcrd.details)
            else None
        )
        default_tolerance = 0.1
        if isinstance(prior_dt, (int, float)) and prior_dt > 0:
            default_tolerance = max(default_tolerance, float(prior_dt) * 0.5)

        # When no explicit gap expectation is provided, treat small
        # differences as numerical noise instead of real gaps/overlaps.
        if current.expected_gap_ps is None:
            if abs(gap) <= default_tolerance:
                gap = 0.0

        # Sanity check: massive gaps (> 1e6 ps = 1 µs) are likely errors
        # in unit conversion or file parsing, not real discontinuities
        if abs(gap) > 1e6:
            current._add_continuity_note(
                f"INFO: Implausible gap detected ({gap:g} ps); likely a unit or parsing error. "
                f"Continuity check skipped."
            )
            current.observed_gap_ps = None
            return

        current.observed_gap_ps = gap

        if gap < 0:
            # Small negative gaps within tolerance are likely floating-point noise
            if abs(gap) > default_tolerance:
                current._add_continuity_note(
                    f"Stage appears to overlap previous stage by {abs(gap):g} ps."
                )
        elif gap > 0:
            # Informational: the raw observed gap. The actual judgement (within
            # window / shorter / exceeds / unexpected) is emitted separately below,
            # so this line is INFO-only and must not surface as a continuity problem.
            current._add_continuity_note(f"INFO: Stage starts {gap:g} ps after previous ended.")

        if current.expected_gap_ps is not None:
            tolerance = current.gap_tolerance_ps or default_tolerance
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
                # Healthy: the observed gap matched the stated expectation. This is a
                # positive confirmation, not a problem — INFO so it is never surfaced
                # as a "needs you" continuity suggestion.
                current._add_continuity_note(
                    f"INFO: Observed gap {gap:g} ps is within expected window ({current.expected_gap_ps:g}±{tolerance:g} ps)."
                )
        elif gap != 0:
            if allow_unexpected_gaps:
                current._add_continuity_note("INFO: Gap detected and allowed by manifest settings.allow_gaps.")
            else:
                current._add_continuity_note("Gap detected without stated expectation; verify continuity.")

    @staticmethod
    def _sum_stages(stages: List[SimulationStage]) -> Dict[str, float]:
        """`steps` and `time_ps` over any set of stages.

        Accumulated with ``+=`` rather than ``sum()`` on purpose: CPython 3.12 made
        ``builtins.sum`` compensated, and CI's matrix is 3.9 *and* 3.12, so a float total
        built with ``sum()`` can differ in its last bits between the two jobs — on the one
        artifact every lineage change is told to keep byte-stable.
        """
        total_steps = 0.0
        total_time = 0.0
        for stage in stages:
            if stage.mdin and stage.mdin.details:
                length = getattr(stage.mdin.details, "length_steps", 0) or 0
                dt = getattr(stage.mdin.details, "dt", 0) or 0
                if isinstance(length, (int, float)) and isinstance(dt, (int, float)):
                    total_steps += float(length)
                    total_time += float(length) * float(dt)
        return {"steps": total_steps, "time_ps": total_time}

    def _members(self) -> Dict[Any, List[SimulationStage]]:
        """This protocol's membership buckets, sentinel included.

        `buckets` is structurally typed on ``.lineage``, so the same grouping the document
        uses applies to the flat stage list without either side re-deriving it.
        """
        return buckets(self.stages)

    def totals(self) -> Dict[str, float]:
        out = self._sum_stages(self.stages)
        members = self._members()
        # `lineage_count` counts what the user *declared*: the untagged bucket is a member
        # (it is why a half-tagged document is multi-lineage at all) but it is not a
        # lineage, and counting it reported four members for the canonical three-replica
        # campaign — the miscount the membership predicate exists to prevent, coming back
        # through the totals.
        #
        # Emitted only when the document holds more than one member, so an untagged
        # summary.json is the file it always was. Note the value arrives on the wire as a
        # float: `PlanResult.totals` and `ValidationReport.totals` are `Dict[str, float]`
        # and pydantic coerces, exactly as it already does for `stage_count`.
        if len(members) >= 2:
            out["lineage_count"] = float(len(members) - (1 if UNTAGGED in members else 0))
        return out

    def lineage_totals(self) -> Dict[str, Dict[str, float]]:
        """Per declared member: its own `steps`, `time_ps` and `step_count`.

        Empty for a document that declares nothing, and for one whose only member is the
        untagged bucket — there is no breakdown of a single member, and `totals` already
        says it.

        A member that is all minimisation reports `steps: 0.0`: minimisation stages carry
        no `nstlim`/`dt`, so they contribute nothing to either sum. That is the same
        arithmetic `totals` has always done, made visible per member rather than hidden in
        one number.
        """
        members = self._members()
        if len(members) < 2:
            return {}
        out: Dict[str, Dict[str, float]] = {}
        for tag, stages in members.items():
            if tag is UNTAGGED:
                continue
            entry: Dict[str, float] = dict(self._sum_stages(stages))
            entry["step_count"] = len(stages)
            out[tag] = entry
        return out

    def sequence_findings(self) -> List[Dict[str, Any]]:
        """The numbered-sequence holes in this protocol, as ``missing_run`` cards.

        The same finding `validate --manifest` reports, reachable from a protocol — which
        is what `plan --recursive` has and a `Simulation` is what it does not have.
        """
        return sequence_findings([s.name for s in self.stages],
                                 [s.lineage for s in self.stages])

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "totals": self.totals(),
            "stages": [stage.to_dict() for stage in self.stages],
        }
        # Emitted only when there is something to report, so a summary.json for a document
        # with no holes is the file it always was. `plan` printed this finding on the
        # manifest path and then dropped it: the artifact a user keeps said nothing about
        # the replica that stopped early, and the artifact is the part that outlives the
        # terminal.
        findings = self.sequence_findings()
        if findings:
            out["findings"] = findings
        # Beside `totals`, not inside it: `totals` is a flat `Dict[str, float]` on both
        # pydantic models and a nested dict raises there, which on `/api/plan` — which
        # builds its response only after the files have been written — is an HTTP 500 over
        # artifacts that already landed.
        lineages = self.lineage_totals()
        if lineages:
            out["lineages"] = lineages
        return out

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
                        # Removed duplicate temp_control and press_control
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
                    # Removed redundant cutoff_mdout field
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

            # Infer HMR from timestep if not already detected from prmtop
            # Timestep >= HMR_TIMESTEP_THRESHOLD_PS is a definitive indicator of HMR
            dt = None
            if stage.mdin and stage.mdin.details:
                dt = getattr(stage.mdin.details, "dt", None)
            if dt is None and stage.mdout and stage.mdout.details:
                dt = getattr(stage.mdout.details, "dt", None)
            if dt is not None and isinstance(dt, (int, float)):
                if implies_hmr(dt):
                    # Large timestep indicates HMR is active
                    if composition.get("hmr_active") is None or composition.get("hmr_active") is False:
                        composition["hmr_active"] = True
                        composition["hmr_inferred_from_timestep"] = True

            # Add observed density from mdout if available (actual simulation values)
            if stage.mdout and stage.mdout.details:
                mdout_details = stage.mdout.details
                stats = getattr(mdout_details, "stats", None)
                if stats:
                    density_stats = getattr(stats, "density_stats", None)
                    if density_stats:
                        avg, std = density_stats.get_stats()
                        if avg is not None:
                            composition["average_density"] = avg
                            composition["density_std"] = std
                            # Use average as the primary density if available
                            composition["density"] = avg
                    # Get first and last density from trajectory
                    first_density = getattr(stats, "first_density", None)
                    last_density = getattr(stats, "last_density", None)
                    if first_density is not None:
                        composition["first_density"] = first_density
                    if last_density is not None:
                        composition["final_density"] = last_density

            # Fall back to initial density from prmtop if no observed density
            if "density" not in composition:
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

            # Consolidate density fields to minimize redundancy:
            # If density is constant (e.g., NVT or minimization), only keep 'density'
            # If trajectory shows density variation, keep detailed breakdown
            density_tolerance = 1e-4  # Relative tolerance for density comparison
            initial = composition.get("initial_density")
            avg = composition.get("average_density")
            first = composition.get("first_density")
            final = composition.get("final_density")

            def densities_equal(a, b):
                if a is None or b is None:
                    return a is None and b is None
                return abs(a - b) < max(abs(a), abs(b)) * density_tolerance

            # Check if all density values are effectively the same
            densities_to_check = [d for d in [initial, avg, first, final] if d is not None]
            if densities_to_check:
                all_equal = all(densities_equal(densities_to_check[0], d) for d in densities_to_check)
                if all_equal:
                    # Consolidate to single 'density' field
                    composition["density"] = avg if avg is not None else (first if first is not None else initial)
                    # Remove redundant fields
                    for key in ["initial_density", "average_density", "first_density", "final_density", "density_std"]:
                        composition.pop(key, None)

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
            # A flat ordered list reads as one chain, so a fan-out published here claims
            # rep1 ran, then rep2, then rep3. The tag says which member the run belongs to
            # and nothing else — no count, no independence claim (decision 4). Emitted only
            # when set, like Step.lineage in the manifest, so an untagged document's
            # methods_summary.json is unchanged.
            sequence_entry: Dict[str, Optional[str]] = {
                "name": stage.name,
                "role": stage.stage_role,
            }
            if stage.lineage:
                sequence_entry["lineage"] = stage.lineage
            stage_sequence.append(sequence_entry)
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


def _resolve(directory: Optional[str], path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(directory or ".", path)


def _apply_global_and_hmr_prmtop(stages, directory, *, global_prmtop,
                                 hmr_prmtop, strict) -> None:
    """Apply global and/or HMR prmtop to stages.

    - global_prmtop: applied to every stage that has no prmtop yet.
    - hmr_prmtop: applied to stages whose timestep implies HMR (dt > 0.002,
      via implies_hmr); overrides any previously set prmtop.
    - Missing files: warn (or raise under strict).
    """
    def _load_topology(path, label):
        full = _resolve(directory, path)
        if not os.path.exists(full):
            msg = f"Requested {label} prmtop not found: {full}"
            if strict:
                raise AmberMetaError(msg)
            logger.warning(msg)
            for st in stages:
                st.validation.append(f"WARNING: {msg}")
            return None
        return _safe_parse(PrmtopParser, full, "prmtop", None, strict=strict)

    if global_prmtop:
        data = _load_topology(global_prmtop, "global")
        if data is not None:
            for st in stages:
                if not st.prmtop:
                    st.prmtop = data
                    st.validation.append(f"INFO: using global prmtop: {global_prmtop}")

    if hmr_prmtop:
        data = _load_topology(hmr_prmtop, "HMR")
        if data is not None:
            for st in stages:
                dt = None
                if st.mdin and st.mdin.details:
                    dt = getattr(st.mdin.details, "dt", None)
                if dt is None and st.mdout and st.mdout.details:
                    dt = getattr(st.mdout.details, "dt", None)
                if implies_hmr(dt):
                    st.prmtop = data
                    st.validation.append(
                        f"INFO: using HMR prmtop (dt={dt} ps): {hmr_prmtop}")


def _safe_parse(parser_cls, path, kind, stage, *, strict):
    """Parse one file, isolating failures unless strict.

    On success: return the parsed metadata object.
    On failure (graceful): record a FileLoadError on ``stage`` (when given) and
    return None.
    On failure (strict): raise AmberMetaError.

    ``stage`` may be None for files not tied to a single stage (e.g. a global
    topology applied across stages); in that case no FileLoadError is recorded
    and the caller decides how to surface the skip.
    """
    try:
        return parser_cls(path).parse()
    except (FileNotFoundError, PermissionError, OSError,
            UnicodeDecodeError, ValueError, LookupError) as exc:
        if strict:
            raise AmberMetaError(f"Failed to parse {kind} '{path}': {exc}") from exc
        if stage is not None:
            stage.load_errors.append(
                FileLoadError(kind=kind, path=path,
                              error_type=classify_exception(exc), message=str(exc))
            )
        return None


def _manifest_to_stages(
    manifest: Dict[str, Dict[str, str]] | List[Dict[str, str]],
    directory: Optional[str],
    include_roles: Optional[List[str]],
    include_stems: Optional[List[str]],
    restart_files: Optional[Dict[str, str]],
    stage_role_rules: Optional[Dict[str, str]] = None,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    strict: bool = False,
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

    compiled_rules: List[tuple[Pattern[str], str]] = []
    if stage_role_rules:
        for pattern, role in stage_role_rules.items():
            try:
                compiled_rules.append((re.compile(pattern), role))
            except re.error:
                compiled_rules.append((re.compile(re.escape(pattern)), role))
    validate_manifest(manifest, directory, strict=strict)

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
                resolved[kind] = os.path.normpath(os.path.join(directory, path))
            else:
                resolved[kind] = os.path.normpath(path)

        stage = SimulationStage(name=name, stage_role=stage_role)

        if not stage.stage_role:
            for pattern, role in compiled_rules:
                if pattern.search(stage.name):
                    stage.stage_role = role
                    stage.validation.append(f"INFO: stage_role '{role}' inferred from stage_role_rules")
                    break

        if "prmtop" in resolved:
            stage.prmtop = _safe_parse(PrmtopParser, resolved["prmtop"], "prmtop", stage, strict=strict)
        if "mdin" in resolved:
            stage.mdin = _safe_parse(MdinParser, resolved["mdin"], "mdin", stage, strict=strict)
            inferred_role = classify_role(mdin_details=getattr(stage.mdin, "details", None)) if stage.mdin else ""
            if not stage.stage_role and inferred_role:
                stage.stage_role = inferred_role
                stage.validation.append(f"INFO: stage_role '{inferred_role}' inferred from mdin content")
        if "mdout" in resolved:
            stage.mdout = _safe_parse(MdoutParser, resolved["mdout"], "mdout", stage, strict=strict)
        if "mdcrd" in resolved:
            stage.mdcrd = _safe_parse(MdcrdParser, resolved["mdcrd"], "mdcrd", stage, strict=strict)
        if "inpcrd" in resolved:
            stage.inpcrd = _safe_parse(InpcrdParser, resolved["inpcrd"], "inpcrd", stage, strict=strict)
            if stage.inpcrd is not None:
                stage.restart_path = resolved["inpcrd"]

        restart_source = None
        if restart_files:
            for key in (stage.name, stage.stage_role):
                if key and key in restart_files:
                    restart_source = restart_files[key]
                    break

        if restart_source and "inpcrd" not in resolved:
            stage.inpcrd = _safe_parse(InpcrdParser, restart_source, "inpcrd", stage, strict=strict)
            if stage.inpcrd is not None:
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

        # Provenance, read after construction like `gaps` and `notes`. Empty strings are
        # coerced away so a cleared tag or a cleared id is absent rather than a nameless
        # member, matching how payload_to_simulation ingests Step.lineage.
        stage.lineage = entry.get("lineage") or None
        stage.step_id = entry.get("step_id") or None
        stage.parent_id = entry.get("parent_id") or None

        stages.append(stage)

    return stages


def _ordered_stems(grouped: Dict[str, Any]) -> List[str]:
    """Return stems in natural (numeric-aware) order so prod_2 precedes prod_10."""
    def key(stem: str):
        return [int(tok) if tok.isdigit() else tok.lower()
                for tok in re.split(r'(\d+)', stem)]
    return sorted(grouped.keys(), key=key)


def _run_stems(grouped: Dict[str, Dict[str, str]]) -> List[str]:
    """The groups that are runs — one holding an mdin or an mdout — in natural order.

    The one place that answers "is this group a run?", because the answer is exactly what
    `infer_lineages_from_layout` must be handed, and it now has three callers. A
    topology-only group, or a bare coordinate file, contributes a run name no sibling
    directory can match and so breaks the membership predicate — a rule restated at three
    call sites is a rule that eventually differs at one of them.
    """
    return [stem for stem in _ordered_stems(grouped)
            if grouped[stem].get("mdin") or grouped[stem].get("mdout")]


class _TaggedRun(NamedTuple):
    """A run name with the member it belongs to, the shape `lineages.buckets` groups."""

    name: str
    lineage: Optional[str]


def _numbered_stem(name: str) -> str:
    """The part of a run name a numbered-sequence base is read from.

    Two separate jobs, kept separate because `Path().stem` did both at once and got the
    second one wrong:

    * **Drop the directory.** Two directories are one member until something says
      otherwise, so an untagged document with runs in `rep1/` and `rep2/` groups exactly as
      it always did. The base this yields is bare (`prod`, never `rep1/prod`), which the
      canvas depends on — `PhaseSection.serverBase` strips the directory from the client's
      spelling to match it.
    * **Drop the file extension, unless it is the index.** `Path().stem` cannot tell
      `prod.0001` (chunk one of a dot-numbered chain) from `prod.out` (a file extension),
      and ate the index: `prod.0001/prod.0002/prod.0004` reported no sequence at all, so
      the hole at 3 went unreported, and with it the crashed-replica finding that is the
      whole point of the feature. A purely numeric final suffix is an index and is kept;
      anything else is an extension and goes.

    "Purely numeric" rather than "ends in a digit" because `.rst7` and `.parm7` are real
    AMBER extensions and the regex's separator is optional, so `system.rst7` would split as
    `('system.rst', '7')` and two restarts would be reported as a sequence missing index 6.
    No extension in `ext_map` is purely numeric, so the discriminator holds.

    `prod.0001.out` keeps working: the final suffix `.out` is not numeric and goes, leaving
    `prod.0001` for the regex to split. That case worked before this function existed and
    is why the fix is not simply "stop stripping extensions".
    """
    run = name.rpartition("/")[2].rpartition("\\")[2]
    head, _, tail = run.rpartition(".")
    return run if not head or tail.isdigit() else head


def detect_numeric_sequences(
    filenames: List[str],
    lineages: Optional[List[Optional[str]]] = None,
) -> Dict[Tuple[Any, str], List[str]]:
    """Detect numeric sequences in filenames for automatic grouping, one member at a time.

    Identifies patterns in two formats:
    - Suffix format: prod_001, prod_002, etc. (common for production runs)
    - Prefix format: 01_min, 02_nvt, 03_npt, etc. (common for equilibration)

    Parameters
    ----------
    filenames:
        List of filenames to analyze.
    lineages:
        Read positionally alongside ``filenames`` — one tag per run, ``None`` where a run
        carries none. Omitting it makes every run untagged, which is a single bucket and
        therefore the grouping this function always did.

        Keyed exactly as :func:`detect_sequence_gaps`, down to the sentinel: the two
        detectors have to agree on what counts as the same run in two directories, or one
        reports a family complete while the other reports it short. Pooling was a claim in
        its own right, not just a missed finding — three replicas of a chunked production
        run were published as one six-run sequence, in a note that names the count.

    Returns
    -------
    Dictionary mapping ``(member, base pattern)`` to that member's matching files in
    numeric order. ``member`` is a declared tag or
    :data:`~ambermeta.lineages.UNTAGGED`. The base stays bare — every member of an
    experiment runs the same one, and it is what the note and the canvas display.
    """
    # Pattern to detect numeric suffixes: name_001, name.001, name001, name-001
    # \d+ (not \d{2,}) so single-digit sequences (prod_1, prod_2, prod_3) are detected.
    # The base group (.+?) ensures a stem that is *only* a number never matches here.
    # `name.001` reaches this pattern only because `_numbered_stem` keeps a numeric final
    # suffix; `Path().stem` used to eat it, so the dot spelling matched nothing.
    suffix_pattern = re.compile(r'^(.+?)[-_.]?(\d+)$')

    # Pattern to detect numeric prefixes: 01_name, 01.name, 01-name
    # The trailing group (.+) ensures a stem that is *only* a number never matches here.
    prefix_pattern = re.compile(r'^(\d+)[-_.]?(.+)$')

    tags: List[Optional[str]] = list(lineages) if lineages is not None else []
    tags += [None] * (len(filenames) - len(tags))

    groups: Dict[Tuple[Any, str], List[tuple[int, str]]] = {}

    for member, runs in buckets(_TaggedRun(n, t) for n, t in zip(filenames, tags)).items():
        for run in runs:
            filename = run.name
            stem = _numbered_stem(filename)

            # Try suffix pattern first (prod_001, prod_002)
            match = suffix_pattern.match(stem)
            if match:
                base = match.group(1)
                if base.isdigit():
                    continue  # skip pure-numeric bases (e.g. "0001", "0002")
                num = int(match.group(2))
                groups.setdefault((member, f"suffix:{base}"), []).append((num, filename))
                continue

            # Try prefix pattern (01_min, 02_nvt)
            match = prefix_pattern.match(stem)
            if match:
                num = int(match.group(1))
                # For prefix patterns, use the parent directory as additional grouping
                parent_dir = str(Path(filename).parent)
                if parent_dir == ".":
                    parent_dir = ""
                groups.setdefault((member, f"prefix:{parent_dir}"), []).append((num, filename))

    # Sort each group by numeric value and return just the filenames
    result: Dict[Tuple[Any, str], List[str]] = {}
    for (member, base), items in groups.items():
        if len(items) >= 2:  # Only consider sequences with 2+ files
            items.sort(key=lambda x: x[0])
            # Clean up the base pattern for display
            clean_base = base.replace("suffix:", "").replace("prefix:", "")
            if not clean_base:
                # For prefix patterns without a parent dir, use a descriptive name
                clean_base = "numbered_sequence"
            result[(member, clean_base)] = [filename for _, filename in items]

    return result


def sequence_findings(
    names: List[str],
    lineages: Optional[List[Optional[str]]] = None,
    start_index: int = 1,
) -> List[Dict[str, Any]]:
    """:func:`detect_sequence_gaps`' output as ``missing_run`` cards.

    Lives here rather than in the GUI bridge because three surfaces need the same words
    about the same hole: `validate --manifest` and `plan --manifest` reach it through
    ``build_suggestions``, and `plan --recursive` cannot — it never builds a ``Simulation``
    at all, and ``build_suggestions`` raises on a ``SimulationProtocol``. Two spellings of
    "rep2 stopped early" is how the two plan modes end up saying different things about one
    directory.

    ``start_index`` continues an id sequence a caller has already begun.
    """
    out: List[Dict[str, Any]] = []
    for (member, base), missing in detect_sequence_gaps(names, lineages).items():
        tag = None if member is UNTAGGED else member
        idxs = ", ".join(str(i) for i in missing)
        # The member is named in the prose only when there is one, so an untagged document
        # reads exactly as it always did. `base` stays the bare run base either way: it is
        # what the canvas matches a ghost against, and it is shared by every member.
        scope = f"{tag}/{base}" if tag else base
        # A short member did not skip anything — it stopped. Saying "skip" of a run that
        # crashed would be the same kind of unearned claim this keying exists to remove.
        evidence = (f"'{scope}' has no run at index(es) {idxs}" if tag
                    else f"present members of '{base}' skip index(es) {idxs}")
        out.append({
            "id": f"sug_{start_index + len(out)}",
            "kind": "missing_run",
            "severity": "needs_you",
            "title": f"{scope} sequence is missing member(s) {idxs}",
            "evidence": evidence,
            "actions": ["Mark as expected gap", "Locate file", "Ignore"],
            "base": base,
            "missing": missing,
            "lineage": tag,
        })
    return out


def _overlapping_cohorts(by_member: Dict[Any, set]) -> List[List[Any]]:
    """Split members of one base into groups linked by a shared index.

    Sweeping in ascending order of first index, a member joins the cohort being built when
    it starts at or below the highest index that cohort has reached, and opens a new one
    otherwise — so two members end up together only when a chain of shared indices connects
    them, and a member alone in its cohort is one nothing relates to.

    This is the question ``max(mins) <= min(maxes)`` asked of each part of a base rather
    than of the whole of it. Asked of the whole it was all-or-nothing: one member numbered
    on a scale of its own answered "no" for everybody, so ``rep3`` at 11-12 silently
    excused ``rep2``'s crash from being measured against ``rep1``.

    Sorted on the ranges alone, never on the member — the untagged sentinel does not order
    against a string. Python's sort is stable, so equal ranges keep first-appearance order.
    """
    cohorts: List[List[Any]] = []
    reach = 0
    for member, nums in sorted(by_member.items(), key=lambda kv: (min(kv[1]), max(kv[1]))):
        if cohorts and min(nums) <= reach:
            cohorts[-1].append(member)
            reach = max(reach, max(nums))
        else:
            cohorts.append([member])
            reach = max(nums)
    return cohorts


def detect_sequence_gaps(
    names: List[str],
    lineages: Optional[List[Optional[str]]] = None,
) -> Dict[Tuple[Any, str], List[int]]:
    """Return, per member and numbered-sequence base, the indices missing from it.

    e.g. ``['prod_0001', 'prod_0002', 'prod_0004']`` -> ``{(UNTAGGED, 'prod'): [3]}``.
    Pure-numeric bases are skipped.

    ``lineages`` is read positionally alongside ``names`` — one tag per run, ``None``
    where a run carries none. Omitting it makes every run untagged, which is the shape
    every caller had before members existed. The key's first slot is therefore a declared
    tag or :data:`~ambermeta.lineages.UNTAGGED`, never a directory: a hand-tagged manifest
    may name its members anything, and two members of one experiment number their runs on
    the same scale whatever directories they live in.

    Two rules decide what is missing, and the second is why a member cannot simply be
    measured on its own:

    * within one member, an index between its lowest and its highest that no run occupies
      is missing. This is the original rule, and the only one that can fire when a base
      has just one member — which is every base of an untagged document, so such a
      document reports exactly what it always did;
    * members of one base **whose numbering overlaps** form a cohort, and the cohort's
      full extent frames every member in it, so a member that stopped early is reported
      rather than covered for by its siblings. A crashed replica is the failure mode
      members exist to expose and it has no interior hole of its own to find.

      Overlap is the qualifier that keeps independently-numbered members apart: ``rep1``
      at 1-2 beside ``rep2`` at 11-12 share no index, so nothing relates the two scales
      and neither member is short. Reporting them was the pre-lineage behaviour — one
      card naming eight runs that were never meant to exist.
    """
    suffix_pattern = re.compile(r'^(.+?)[-_.]?(\d+)$')

    tags: List[Optional[str]] = list(lineages) if lineages is not None else []
    tags += [None] * (len(names) - len(tags))

    # base -> member -> the indices that member holds
    present: Dict[str, Dict[Any, set]] = {}
    for member, runs in buckets(_TaggedRun(n, t) for n, t in zip(names, tags)).items():
        for run in runs:
            stem = _numbered_stem(run.name)
            match = suffix_pattern.match(stem)
            if not match:
                continue
            base = match.group(1)
            if base.isdigit():
                continue
            present.setdefault(base, {}).setdefault(member, set()).add(int(match.group(2)))

    gaps: Dict[Tuple[Any, str], List[int]] = {}
    for base, by_member in present.items():
        for cohort in _overlapping_cohorts(by_member):
            frame: Optional[Tuple[int, int]] = None
            if len(cohort) > 1:
                frame = (min(min(by_member[m]) for m in cohort),
                         max(max(by_member[m]) for m in cohort))
            for member in cohort:
                nums = by_member[member]
                if frame is None:
                    if len(nums) < 2:
                        continue
                    low, high = min(nums), max(nums)
                else:
                    low, high = frame
                missing = [i for i in range(low, high + 1) if i not in nums]
                if missing:
                    gaps[(member, base)] = missing
    return gaps


def infer_stage_role_from_path(path: str) -> Optional[str]:
    """Infer stage role from the directory or file path.

    Examines path components and filename to detect stage type patterns.
    Common directory names like 'equil', 'prod', 'min' are recognized.
    """
    return classify_role(path) or None


def infer_stage_role_from_content(
    mdin_data: Optional[MdinData] = None,
    mdout_data: Optional[MdoutData] = None,
) -> Optional[str]:
    """Infer stage role from parsed file content.

    Uses heuristics based on simulation parameters to determine the stage type.
    """
    mdin_details = getattr(mdin_data, "details", None)
    mdout_details = getattr(mdout_data, "details", None)
    return classify_role(mdin_details=mdin_details, mdout_details=mdout_details) or None


def auto_detect_restart_chain(
    stages: List[SimulationStage],
    directory: str,
    recursive: bool = False,
) -> Dict[str, str]:
    """Automatically detect restart file chains between stages.

    Analyzes stages to find restart files that link them together based on:
    - Matching atom counts
    - Timestamp continuity
    - File naming conventions (e.g., prod_001.rst -> prod_002 uses it)

    This is the second, independent chainer — ``discover`` builds its own — so it carries
    the same lineage guard: **no candidate belonging to another declared member may be
    scored, and the document-order predecessor is only consulted when it belongs to the
    same member.** Neither restriction can be expressed by the atom-count check below,
    because replicas of one system agree on every count. "Belonging" is read from the
    declared writer where there is one and from the directory otherwise — see ``_owner``
    below for why a declared writer alone is not enough.

    **The guard is inert wherever a stage is built without a tag**, since an untagged stage
    is the implicit single member and continues into anything. Both paths that read a tree
    now tag what they find — ``auto_discover``'s scan infers from the layout exactly as the
    manifest path reads it from the document — so ``plan --recursive
    --auto-detect-restarts`` over a raw replica tree is protected. What remains untagged,
    and deliberately: ``ProtocolBuilder.add_stage``, which is handed one stage at a time
    with no layout to infer from and no parameter to declare one.

    Parameters
    ----------
    stages:
        List of simulation stages to analyze.
    directory:
        Base directory for finding restart files.
    recursive:
        When True, scan subdirectories recursively (mirrors ``smart_group_files``).

    Returns
    -------
    Dictionary mapping stage names to their restart file paths.
    """
    # Collect all potential restart files, each with a stage that speaks for the member the
    # file belongs to, where the layout names one.
    restart_candidates: List[tuple[str, InpcrdData, Optional[SimulationStage]]] = []
    stage_by_run = {stage.name: stage for stage in stages}

    # Which member each *directory* belongs to, spoken for by one of its own stages. Only a
    # directory whose declared stages agree on a single non-null tag speaks at all: a mixed
    # directory, or one holding nothing but untagged runs, says nothing about membership
    # and leaves its files open to every consumer.
    speaker_by_dir: Dict[str, Optional[SimulationStage]] = {}
    for stage in stages:
        stage_dir = stage.name.rpartition("/")[0]
        if stage_dir not in speaker_by_dir:
            speaker_by_dir[stage_dir] = stage if stage.lineage else None
        else:
            speaking = speaker_by_dir[stage_dir]
            if speaking is not None and (stage.lineage or None) != speaking.lineage:
                speaker_by_dir[stage_dir] = None

    def _owner(path: str) -> Optional[SimulationStage]:
        """A stage that speaks for the member this restart belongs to, if one does.

        A run writes the restart named after it, and stage names are the path-prefixed
        posix stems `smart_group_files` builds, so a *declared* writer is a lookup rather
        than a second layout inference.

        Reading only declared writers is not enough, and the gap is the common case rather
        than the exotic one: `rep1/prod_0001.rst` left behind by a chunk whose mdout was
        never collected is claimed by no stage, and was then scored for rep2 exactly as if
        it were unowned. The directory is evidence in its own right — a restart sitting in
        rep1's directory was written by rep1's run whether or not that run reached the
        document.

        A file that neither a stage nor a directory claims stays a candidate for everyone:
        one shared equilibration in its own directory, feeding N replicas, is a real edge
        and the ordinary way a campaign starts. *Another member's* directory is evidence;
        merely a different one is not.
        """
        try:
            relative = os.path.relpath(path, directory)
        except ValueError:      # different drives on Windows; nothing to place it under
            return None
        run = Path(relative).with_suffix("").as_posix()
        writer = stage_by_run.get(run)
        if writer is not None:
            return writer
        return speaker_by_dir.get(run.rpartition("/")[0])

    ext_map = {".rst", ".rst7", ".ncrst", ".restrt", ".inpcrd"}

    # Scan for restart files
    entries: List[str] = []
    if recursive:
        for root, _, files in os.walk(directory, onerror=lambda e: None):
            entries.extend(os.path.join(root, fn) for fn in files)
    else:
        try:
            entries = [os.path.join(directory, fn) for fn in os.listdir(directory)]
        except (PermissionError, OSError):
            entries = []
    for full_path in entries:
        if not os.path.isfile(full_path):
            continue
        _, ext = os.path.splitext(full_path)
        if ext.lower() not in ext_map:
            continue
        try:
            data = InpcrdParser(full_path).parse()
            restart_candidates.append((full_path, data, _owner(full_path)))
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

        # Both terms below read the *document-order* predecessor, and in a multi-lineage
        # document that neighbour is routinely another member — discover output is
        # phase-major, and a replica-major manifest puts rep2's head straight after rep1's
        # tail. Scoring against it is what assigned rep1's terminal restart to rep2.
        prev_stage = stages[i - 1] if i > 0 else None
        if crosses_lineage(prev_stage, stage):
            prev_stage = None

        # `\d{2,}` is leftmost-matching, so the directory must not be folded into the name
        # here: `rep10/prod_0002` as `rep10_prod_0002` scores against 10, which both misses
        # its real predecessor prod_0001 and matches an unrelated prod_0009.
        stage_base = stage.name.rpartition("/")[2]

        # Try to find matching restart
        best_match: Optional[tuple[str, float]] = None

        for rst_path, rst_data, rst_owner in restart_candidates:
            if not rst_data or not rst_data.details:
                continue

            # A restart belonging to another member was never read here. The atom-count
            # check below cannot refuse it: replicas of one system share every count, which
            # is what makes that guard a no-op exactly where it is needed most.
            if crosses_lineage(rst_owner, stage):
                continue

            # Check atom count match
            rst_atoms = getattr(rst_data.details, "n_atoms", None)
            if target_atoms and rst_atoms and target_atoms != rst_atoms:
                continue

            # Check naming convention match
            rst_stem = Path(rst_path).stem

            # Common patterns: stagename.rst -> next stage, prev_stage.rst7 -> current
            score = 0.0

            # Check if restart name matches previous stage
            if prev_stage is not None:
                prev_name = prev_stage.name.replace("/", "_")
                if prev_name in rst_stem or rst_stem in prev_name:
                    score += 5.0

            # Check for numeric sequence matching
            stage_match = re.search(r'(\d{2,})', stage_base)
            rst_match = re.search(r'(\d{2,})', rst_stem)
            if stage_match and rst_match:
                stage_num = int(stage_match.group(1))
                rst_num = int(rst_match.group(1))
                if rst_num == stage_num - 1:
                    score += 10.0  # Previous sequence number is ideal
                elif rst_num == stage_num:
                    score += 3.0

            # Check timestamp if previous stage has end time
            if prev_stage is not None and prev_stage.mdcrd and prev_stage.mdcrd.details:
                prev_end = getattr(prev_stage.mdcrd.details, "time_end", None)
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
        # onerror keeps an inaccessible subdirectory from propagating out of
        # the walk; the default behaviour skips it, this makes that explicit.
        for root, _, filenames in os.walk(directory, onerror=lambda e: None):
            for fname in filenames:
                full_path = os.path.join(root, fname)
                if os.path.isfile(full_path):
                    rel_path = os.path.relpath(full_path, directory)
                    discovered.append((rel_path, full_path))
    else:
        try:
            entries = os.listdir(directory)
        except (PermissionError, OSError):
            entries = []
        for fname in entries:
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
        ".trj": "mdcrd",
    }
    _DEFAULT_BASENAME_KIND = {
        "prmtop": "prmtop", "parm7": "prmtop",
        "mdin": "mdin", "mdout": "mdout", "mdcrd": "mdcrd",
        "inpcrd": "inpcrd", "restrt": "inpcrd",
    }

    # Group by stem
    grouped: Dict[str, Dict[str, str]] = {}

    for rel_path, full_path in sorted(discovered):   # deterministic order
        stem = Path(rel_path).with_suffix("").as_posix()
        _, ext = os.path.splitext(rel_path)
        kind = ext_map.get(ext.lower())
        if not kind and not ext:
            # Extensionless canonical Amber default filenames.
            kind = _DEFAULT_BASENAME_KIND.get(os.path.basename(rel_path).lower())
        if not kind:
            continue
        group = grouped.setdefault(stem, {})
        if kind in group:
            # Same stem + same kind (e.g. prod.nc and prod.mdcrd): keep the first
            # (sorted) deterministically and record the collision.
            group.setdefault(f"_collision_{kind}", os.path.basename(full_path))
            continue
        group[kind] = full_path

    # Detect and handle numeric sequences, per member. Nothing upstream of discovery has
    # read a manifest, so the tags are inferred here, by the repo's one rule for it. A
    # layout that rule refuses leaves every run untagged, which is the single pooled family
    # this always produced.
    all_stems = list(grouped.keys())
    tags = infer_lineages_from_layout(_run_stems(grouped))
    sequences = detect_numeric_sequences(all_stems, [tags.get(s) for s in all_stems])

    # Add sequence metadata to groups. The member is deliberately not written into
    # `_sequence_base`: it names the family, every member runs the same one, and the stem
    # already carries the directory the tag was inferred from.
    for (_member, base_pattern), sequence_stems in sequences.items():
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
    allow_unexpected_gaps: bool = False,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    strict: bool = False,
) -> SimulationProtocol:
    if manifest is not None:
        stages = _manifest_to_stages(
            manifest,
            directory=directory,
            include_roles=include_roles,
            include_stems=include_stems,
            restart_files=restart_files,
            stage_role_rules=grouping_rules,
            progress_callback=progress_callback,
            strict=strict,
        )
        # Apply auto restart detection if requested
        if auto_detect_restarts:
            auto_restarts = auto_detect_restart_chain(stages, directory, recursive=recursive)
            for stage in stages:
                if stage.name in auto_restarts and not stage.restart_path:
                    rst_path = auto_restarts[stage.name]
                    stage.inpcrd = _safe_parse(InpcrdParser, rst_path, "inpcrd", stage, strict=strict)
                    if stage.inpcrd is not None:
                        stage.restart_path = rst_path
                        stage.validation.append(f"INFO: restart file auto-detected: {rst_path}")

        _apply_global_and_hmr_prmtop(stages, directory,
                                     global_prmtop=global_prmtop,
                                     hmr_prmtop=hmr_prmtop,
                                     strict=strict)

        protocol = SimulationProtocol(stages=stages)
        protocol.validate(
            cross_stage=not skip_cross_stage_validation,
            allow_unexpected_gaps=allow_unexpected_gaps,
        )
        return protocol

    # Use smart grouping for file discovery
    grouped = smart_group_files(directory, pattern=pattern_filter, recursive=recursive)

    # The same layout inference `discover_draft` performs, because this is the same tree
    # read for the same purpose — `plan <dir> --recursive` reaches the engine here instead
    # of through a manifest, and a stage built without a tag is one the continuity
    # partition, the restart-chain guard and `stage_sequence` cannot tell apart from its
    # neighbours. Untagged, a replica tree was one document-order chain: each member's head
    # measured against the previous member's tail, published as an overlap that never
    # happened. Inferred from the whole tree, before `include_stems`/`include_roles` narrow
    # it — membership is a property of the layout, not of what the caller asked to see.
    lineage_by_stem = infer_lineages_from_layout(_run_stems(grouped))

    compiled_rules: List[tuple[Pattern[str], str]] = []
    if grouping_rules:
        for pattern, role in grouping_rules.items():
            try:
                compiled_rules.append((re.compile(pattern), role))
            except re.error:
                compiled_rules.append((re.compile(re.escape(pattern)), role))

    stages: List[SimulationStage] = []
    for stem in _ordered_stems(grouped):
        kinds = grouped[stem]
        # Skip internal metadata keys
        file_kinds = {k: v for k, v in kinds.items() if not k.startswith("_")}

        stage_role: Optional[str] = None
        for pattern, role in compiled_rules:
            if pattern.search(stem):
                stage_role = role
                break

        if include_stems and stem not in include_stems:
            continue

        # A group that is not a run carries no tag: `lineage_by_stem` holds run names only,
        # so a topology or a lone starting structure stays untagged. Untagged is its own
        # member here, not a wildcard — `_check_continuity` buckets it separately, so a
        # shared prep run's edge into each replica is NOT measured on this path; each
        # member's head reports "not measured" instead. That is a deliberate trade: before
        # the partition the prep run was compared against whichever replica happened to
        # follow it in document order, which was the true edge for exactly one member and
        # a fabricated one for the rest. `crosses_lineage` is the looser rule and does let
        # an untagged producer's restart reach any member.
        stage = SimulationStage(name=stem, stage_role=stage_role,
                                lineage=lineage_by_stem.get(stem))

        # Add sequence info as validation notes if detected
        if "_sequence_base" in kinds:
            seq_base = kinds["_sequence_base"]
            seq_idx = kinds.get("_sequence_index", "?")
            seq_len = kinds.get("_sequence_length", "?")
            stage.validation.append(
                f"INFO: Part of sequence '{seq_base}' (item {int(seq_idx)+1} of {seq_len})"
            )

        if "prmtop" in file_kinds:
            stage.prmtop = _safe_parse(PrmtopParser, file_kinds["prmtop"], "prmtop", stage, strict=strict)
        if "mdin" in file_kinds:
            stage.mdin = _safe_parse(MdinParser, file_kinds["mdin"], "mdin", stage, strict=strict)
            # Try mdin-based inference first
            inferred_role = classify_role(mdin_details=getattr(stage.mdin, "details", None)) if stage.mdin else ""
            if not stage.stage_role and inferred_role:
                stage.stage_role = inferred_role
                stage.validation.append(f"INFO: stage_role '{inferred_role}' inferred from mdin file")
        if "mdout" in file_kinds:
            stage.mdout = _safe_parse(MdoutParser, file_kinds["mdout"], "mdout", stage, strict=strict)
        if "mdcrd" in file_kinds:
            stage.mdcrd = _safe_parse(MdcrdParser, file_kinds["mdcrd"], "mdcrd", stage, strict=strict)
        if "inpcrd" in file_kinds:
            stage.inpcrd = _safe_parse(InpcrdParser, file_kinds["inpcrd"], "inpcrd", stage, strict=strict)
            if stage.inpcrd is not None:
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
            stage.inpcrd = _safe_parse(InpcrdParser, restart_source, "inpcrd", stage, strict=strict)
            if stage.inpcrd is not None:
                stage.restart_path = restart_source

        stages.append(stage)

    # Apply auto restart detection if requested
    if auto_detect_restarts:
        auto_restarts = auto_detect_restart_chain(stages, directory, recursive=recursive)
        for stage in stages:
            if stage.name in auto_restarts and not stage.restart_path:
                rst_path = auto_restarts[stage.name]
                stage.inpcrd = _safe_parse(InpcrdParser, rst_path, "inpcrd", stage, strict=strict)
                if stage.inpcrd is not None:
                    stage.restart_path = rst_path
                    stage.validation.append(f"INFO: restart file auto-detected: {rst_path}")

    _apply_global_and_hmr_prmtop(stages, directory,
                                 global_prmtop=global_prmtop,
                                 hmr_prmtop=hmr_prmtop,
                                 strict=strict)

    protocol = SimulationProtocol(stages=stages)
    protocol.validate(
        cross_stage=not skip_cross_stage_validation,
        allow_unexpected_gaps=allow_unexpected_gaps,
    )
    return protocol


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
        self._grouping_rules: Optional[Dict[str, str]] = None
        self._include_roles: Optional[List[str]] = None
        self._include_stems: Optional[List[str]] = None
        self._restart_files: Optional[Dict[str, str]] = None
        self._skip_cross_stage_validation: bool = False
        self._recursive: bool = False
        self._auto_detect_restarts: bool = False
        self._pattern_filter: Optional[str] = None
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
            raise ValueError("No directory specified. Use from_directory().")

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


def to_plain(obj: Any) -> Any:
    """Recursively convert a summary payload to built-in Python types.

    Parsers hand back numpy scalars (a box dimension, a mean), and `yaml.safe_dump`
    refuses anything whose exact type it does not know — so `plan --summary-format yaml`
    died with a RepresenterError partway through, leaving a truncated file behind. JSON
    survived only because `numpy.float64` subclasses `float`. Tuples become lists for the
    same reason, and so that the YAML and JSON forms of one summary agree.
    """
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    if isinstance(obj, (str, bytes, bool)) or obj is None:
        return obj
    item = getattr(obj, "item", None)      # numpy scalars, and nothing built-in
    if callable(item) and hasattr(obj, "dtype"):
        return to_plain(item())
    return obj


STATS_CSV_COLUMNS = [
    "stage_name", "stage_role", "time_start_ps", "time_end_ps", "duration_ns",
    "frame_count", "temp_avg", "temp_std", "pressure_avg", "pressure_std",
    "density_avg", "density_std", "etot_avg", "etot_std",
]


def write_stats_csv(protocol: "SimulationProtocol", filepath: str) -> None:
    """Write one row of per-stage mdout statistics per stage.

    Lives here rather than in the CLI because the GUI writes the same artifact: two
    implementations of "the stats CSV" would drift, and a column order that differed
    between the two would be a silent difference in a file people diff.
    """
    import csv

    rows: List[Dict[str, Any]] = []
    for stage in protocol.stages:
        row: Dict[str, Any] = {"stage_name": stage.name, "stage_role": stage.stage_role or ""}
        stats = getattr(stage.mdout.details, "stats", None) if (
            stage.mdout and stage.mdout.details) else None
        if stats:
            row["time_start_ps"] = getattr(stats, "time_start", "")
            row["time_end_ps"] = getattr(stats, "time_end", "")
            row["duration_ns"] = getattr(stats, "duration_ns", "")
            row["frame_count"] = getattr(stats, "count", "")
            for prefix, attr in (("temp", "temp_stats"), ("pressure", "pressure_stats"),
                                 ("density", "density_stats"), ("etot", "etot_stats")):
                series = getattr(stats, attr, None)
                if series:
                    mean, std = series.get_stats()
                    row[f"{prefix}_avg"] = mean if mean is not None else ""
                    row[f"{prefix}_std"] = std if std is not None else ""
        rows.append(row)

    with open(filepath, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=STATS_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in STATS_CSV_COLUMNS})


PLAN_ARTIFACTS = ("summary", "methods_summary", "stats_csv")


def write_protocol_outputs(protocol: "SimulationProtocol", targets: Dict[str, str],
                           summary_format: str = "json") -> Dict[str, Any]:
    """Write the requested plan artifacts from one already-built protocol.

    ``targets`` maps an artifact name from :data:`PLAN_ARTIFACTS` to an already-resolved
    absolute path; the caller is responsible for containment. Shared by `ambermeta plan`
    and the GUI's Plan action so the two cannot drift.
    """
    unknown = sorted(set(targets) - set(PLAN_ARTIFACTS))
    if unknown:
        raise ValueError(f"unknown plan artifact(s): {', '.join(unknown)}")
    if summary_format not in ("json", "yaml"):
        raise ValueError(f"summary format must be json or yaml, got: {summary_format}")

    written: List[Dict[str, str]] = []
    failed: List[Dict[str, str]] = []
    warnings: List[str] = []
    if not protocol.stages and targets:
        warnings.append("The document has no steps, so the summaries describe nothing.")

    def _dump(payload: Dict[str, Any], path: str, fmt: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        plain = to_plain(payload)     # numpy scalars: safe_dump rejects them outright
        with open(path, "w", encoding="utf-8") as fh:
            if fmt == "yaml":
                import yaml as _yaml
                _yaml.safe_dump(plain, fh, sort_keys=False)
            else:
                json.dump(plain, fh, indent=2)

    def _attempt(artifact: str, write) -> None:
        """Record what each artifact did. One unwritable path must not hide the rest:
        raising here discarded the list of files that had already landed, so the caller
        was told only that something failed, not what survived."""
        path = targets[artifact]
        try:
            write(path)
        except OSError as exc:
            failed.append({"artifact": artifact, "path": path, "error": str(exc)})
        else:
            written.append({"artifact": artifact, "path": path})

    if "summary" in targets:
        _attempt("summary", lambda p: _dump(protocol.to_dict(), p, summary_format))
    if "methods_summary" in targets:
        # Always JSON: it is the publication-facing artifact and the CLI writes JSON.
        _attempt("methods_summary", lambda p: _dump(protocol.to_methods_dict(), p, "json"))
    if "stats_csv" in targets:
        def _stats(path: str) -> None:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            write_stats_csv(protocol, path)
        _attempt("stats_csv", _stats)
        if protocol.stages and not any(s.mdout for s in protocol.stages):
            # Rows are written for every stage either way; what is missing is their content.
            warnings.append("No step has an mdout, so every row in the statistics CSV is empty.")

    return {"written": written, "failed": failed, "warnings": warnings}


__all__ = [
    "SimulationProtocol",
    "write_stats_csv",
    "STATS_CSV_COLUMNS",
    "to_plain",
    "PLAN_ARTIFACTS",
    "write_protocol_outputs",
    "SimulationStage",
    "ProtocolBuilder",
    "auto_discover",
    "detect_numeric_sequences",
    "infer_stage_role_from_content",
    "auto_detect_restart_chain",
    "smart_group_files",
    "HMR_TIMESTEP_THRESHOLD_PS",
]
