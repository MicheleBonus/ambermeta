from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Pattern, Tuple

import re

from ambermeta.coords import sniff_coordinate_kind
from ambermeta.parsers.inpcrd import InpcrdData, InpcrdParser
from ambermeta.parsers.mdcrd import MdcrdData, MdcrdParser
from ambermeta.parsers.mdin import MdinData, MdinParser
from ambermeta.mdout_header import MdoutHeader, looks_like_mdout, read_mdout_header
from ambermeta.parsers.mdout import MdoutData, MdoutParser
from ambermeta.parsers.prmtop import PrmtopData, PrmtopParser
from ambermeta.recorded_inputs import compare_recorded_input
from ambermeta.topology_pool import implies_hmr
from ambermeta.errors import AmberMetaError, FileLoadError, classify_exception
from ambermeta.logging_config import get_logger
from ambermeta.roles import classify_role
from ambermeta.lineages import UNTAGGED, buckets, infer_lineages_from_layout
from ambermeta.lineages import coherence as _coherence
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
    # Whether the file in `inpcrd` is one this run WROTE rather than one it read.
    #
    # The scan path groups by stem, so `prod_0002.restrt` -- AMBER's `-r` output, written
    # at the END of the run -- lands in the same group as `prod_0002.mdin`/`.mdout` and
    # fills the `inpcrd` slot. It is still loaded and still cross-checked (atom count, box:
    # either restart answers those equally well), but its clock is the run's finish, not
    # its start, and `_check_stage_pair` reads that slot for the run's START time. Left
    # unmarked, every chunk in a chunked campaign was measured as beginning one whole chunk
    # after the previous one ended -- 20000 ps of phantom gap on the repo's own fixture,
    # about a thousand of them on the campaign this was found on, and a real
    # discontinuity buried under the same constant offset.
    #
    # Serialised only when true, as `inpcrd_written_by_this_run`, so a reader of
    # summary.json does not take that file's clock or box for the run's starting ones.
    inpcrd_is_own_restart: bool = False
    # False for a scanned group that is not a run -- a topology, a starting structure --
    # which the scan path keeps as a stage for what its files say. It continues nothing and
    # is not measured. Not serialised; every stage a document declares is a run.
    is_run: bool = True
    # Scan path only: the run before this one in its member, in execution order, for a run
    # that no recorded input links to a producer. Continuity is then measured against it,
    # as the 1.2 scan measured every neighbour, so a real gap is still reported. Not a
    # claim about which restart was read: not serialised, and not `continues_from`.
    order_predecessor_id: Optional[str] = None
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
    # The name of the document Phase this stage came from; manifest path only. `stage_role`
    # is the phase's role, and two phases may share one (an NVT and an NPT equilibration),
    # so the methods summary groups by this name where it exists.
    phase: Optional[str] = None
    # Whether this stage produced output. The only non-default value is "queued": an mdin
    # with no mdout, set by both engine entry points (the manifest path and the scan path
    # — see `_looks_queued`) rather than derived here, because they are the two places
    # that still have the raw file-presence facts (which kinds were even declared) in
    # front of them; by the time a stage reaches `totals()` that distinction is gone.
    status: Optional[str] = None
    # What the mdout stated before the run started: the resolved seed, the authoritative
    # begin time, and the chain AMBER itself asserts through File Assignments. Kept beside
    # `mdout` rather than on `MdoutData.details`, because that dataclass is serialised with
    # `asdict()` straight into summary.json and every field added to it appears there.
    # `to_dict()` below emits a fixed key list, so this one does not.
    mdout_header: Optional[MdoutHeader] = None
    validation: List[str] = field(default_factory=list)
    continuity: List[str] = field(default_factory=list)
    load_errors: List[FileLoadError] = field(default_factory=list)
    # This run's own problems, as (kind, message) with kind one of `FINDING_KINDS`. Every
    # message is also in `validation`, which is what summary.json shows; this is the
    # structured copy `stage_finding_cards` reads, so the findings block and `--strict`
    # never pattern-match free text to tell a problem from a remark ("No atom counts
    # available" is a remark). Not serialised.
    findings: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        """True when one or more of this stage's files failed to parse."""
        return bool(self.load_errors)

    def validate(self) -> None:
        existing = set(self.validation)

        def _add(msg: str, kind: Optional[str] = None) -> None:
            if msg not in existing:
                self.validation.append(msg)
                existing.add(msg)
            if kind is not None and (kind, msg) not in self.findings:
                self.findings.append((kind, msg))

        if not self._atom_counts():
            _add("No atom counts available for validation.")
        for msg in (self._validate_atoms() + self._validate_timing()
                    + self._validate_sampling() + self._validate_hmr_time_step()):
            _add(msg, "step_check")
        for msg in self._validate_completion():
            _add(msg, "unfinished_run")
        for msg in self._validate_recorded_input():
            _add(msg, "input_mismatch")
        for msg in self._validate_elapsed_time():
            _add(msg)

    def _atom_counts(self) -> List[Tuple[str, int]]:
        """(label, count) for every file that states an atom count.

        A count of 0 is not stated. The ASCII trajectory reader, and the NetCDF readers
        when neither netCDF4 nor SciPy is installed, leave their atom count at its default
        of 0 because the file (or the missing library) gave them none; comparing that 0
        with the topology's count reported a mismatch that was never in the data. No AMBER
        system has zero atoms.
        """
        counts = []
        for label, data in (("prmtop", self.prmtop), ("inpcrd", self.inpcrd),
                            ("mdout", self.mdout), ("mdcrd", self.mdcrd)):
            n_atoms = getattr(data.details, "n_atoms", None) if data and data.details else None
            if n_atoms:
                counts.append((label, n_atoms))
        return counts

    def _validate_atoms(self) -> List[str]:
        counts = self._atom_counts()
        if len({n for _, n in counts}) > 1:
            return [f"Atom count mismatch across {[label for label, _ in counts]}: "
                    f"{[n for _, n in counts]}"]
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
            # The trajectory's duration is first frame to last frame, and AMBER writes its
            # first frame after `ntwx` steps, not at step 0, and its last at the largest
            # multiple of `ntwx` within the run. So a run of `nstlim` steps spans
            # (floor(nstlim/ntwx) - 1) * ntwx steps of trajectory, not `nstlim`: 22 ps for a
            # 12,500-step, 2 fs run writing every 1,000 steps. Comparing with `nstlim * dt`
            # reported 278 healthy runs of the deposited corpus as mismatched.
            ntwx = self._coord_interval_steps()
            mdcrd_timestep = (
                getattr(self.mdcrd.details, "avg_dt", None) if self.mdcrd and self.mdcrd.details else None
            )

            for label, duration in expected_durations.items():
                if not isinstance(duration, (int, float)):
                    continue
                dt = timesteps.get(label)
                expected = _written_span_ps(step_counts.get(label), dt, ntwx)
                if expected is not None:
                    tolerance = max(1e-3, float(dt), 1e-6 * abs(expected))
                    if abs(expected - mdcrd_duration) > tolerance:
                        notes.append(
                            f"Trajectory duration from mdcrd ({mdcrd_duration:g} ps) differs from "
                            f"expected duration from {label} ({expected:g} ps for frames written "
                            f"every {ntwx} steps)."
                        )
                    continue

                # The write interval is not known, so only bounds can be checked: the span
                # can fall short of the run by up to two frame intervals (the first frame,
                # and the remainder after the last), and cannot exceed it by more than one.
                interval = 1e-6
                if isinstance(mdcrd_timestep, (int, float)):
                    interval = max(interval, float(mdcrd_timestep))
                if isinstance(dt, (int, float)):
                    interval = max(interval, float(dt))
                if not (duration - 2 * interval - 1e-6 <= mdcrd_duration <= duration + interval):
                    notes.append(
                        f"Trajectory duration from mdcrd ({mdcrd_duration:g} ps) differs from expected duration from {label} ({duration:g} ps)."
                    )

        return notes

    def _coord_interval_steps(self) -> Optional[int]:
        """`ntwx` as the run used it (the mdout header), else as its mdin asked for it."""
        value = self.mdout_header.control_ntwx if self.mdout_header is not None else None
        if not value and self.mdin and self.mdin.details:
            value = getattr(self.mdin.details, "coord_freq", None)
        return int(value) if isinstance(value, (int, float)) and value > 0 else None

    def _print_interval_steps(self) -> Optional[int]:
        """`ntpr` as the run used it (the mdout header), else as its mdin asked for it."""
        value = self.mdout_header.control_ntpr if self.mdout_header is not None else None
        if not value and self.mdin and self.mdin.details:
            value = getattr(self.mdin.details, "energy_freq", None)
        return int(value) if isinstance(value, (int, float)) and value > 0 else None

    def _run_steps(self) -> Optional[int]:
        """`nstlim` as the run used it: the mdout header, the mdout, then the mdin."""
        for value in (
            self.mdout_header.control_nstlim if self.mdout_header is not None else None,
            getattr(self.mdout.details, "nstlim", None) if (self.mdout and self.mdout.details) else None,
            getattr(self.mdin.details, "length_steps", None) if (self.mdin and self.mdin.details) else None,
        ):
            if isinstance(value, (int, float)) and value > 0:
                return int(value)
        return None

    def _validate_sampling(self) -> List[str]:
        # The mdout side comes from its header's CONTROL DATA block. `MdoutMetadata` has
        # no `ntwx`, so reading it there made this check unable to fire at all.
        freq = []
        if self.mdin and self.mdin.details:
            freq.append(("mdin", getattr(self.mdin.details, "coord_freq", None)))
        if self.mdout_header is not None:
            freq.append(("mdout", self.mdout_header.control_ntwx))
        notes: List[str] = []
        if len(freq) > 1:
            base = freq[0]
            for label, val in freq[1:]:
                if base[1] and val and base[1] != val:
                    notes.append(f"Coordinate write frequency differs between {base[0]} and {label} ({base[1]} vs {val}).")
        return notes

    def _run_dt_ps(self) -> Optional[float]:
        """The time step the run used: the mdout's resolved CONTROL DATA, else the mdin."""
        if self.mdout_header is not None and self.mdout_header.control_dt_ps:
            return self.mdout_header.control_dt_ps
        if self.mdin and self.mdin.details:
            return getattr(self.mdin.details, "dt", None)
        return None

    def _validate_hmr_time_step(self) -> List[str]:
        """A time step above 2 fs on a topology whose hydrogen masses are standard.

        Either the Step is bound to a different topology than the run used, or the run
        integrated hydrogens at a time step they do not support. Both are worth a look, and
        neither is resolved by relabelling the topology as HMR, which is what the methods
        summary used to do. Only a topology whose masses were read and found standard
        (`hmr_active is False`) counts; an unclassified one says nothing.
        """
        details = self.prmtop.details if self.prmtop else None
        if details is None or getattr(details, "hmr_active", None) is not False:
            return []
        dt = self._run_dt_ps()
        if not isinstance(dt, (int, float)) or not implies_hmr(dt):
            return []
        return [f"Time step of {dt * 1000:g} fs, but the topology has standard hydrogen "
                "masses (no hydrogen mass repartitioning); a time step above 2 fs needs "
                "repartitioned hydrogen masses."]

    def _validate_completion(self) -> List[str]:
        """An mdout without AMBER's completion marker: the run stopped early or still runs.

        Queued runs have no mdout and are not this; their `status` says so. A run whose
        mdout could not be parsed at all is a load error, already reported.
        """
        if self.mdout is None or self.mdout.details is None:
            return []
        if getattr(self.mdout.details, "finished_properly", False):
            return []
        return ["The mdout has no completion marker: the run stopped early or is still "
                "running."]

    def _validate_recorded_input(self) -> List[str]:
        """The declared input coordinates against the INPCRD the mdout recorded.

        Skipped where the scan put the run's OWN output restart in the input slot
        (`inpcrd_is_own_restart`): that file is not a claim about what the run read.
        """
        if self.inpcrd is None or self.inpcrd_is_own_restart:
            return []
        if self.mdout is None or self.mdout_header is None:
            return []
        recorded = self.mdout_header.assignment("INPCRD")
        if not recorded:
            return []
        mismatch = compare_recorded_input(
            self.inpcrd.filename, recorded, os.path.dirname(self.mdout.filename))
        return [f"This step {mismatch}."] if mismatch else []

    def _validate_elapsed_time(self) -> List[str]:
        """"Ran, mdout unusable -> contributes nothing, plus a note" — the one run state
        in the design's table that no earlier task gave a voice to. `_elapsed_ps`'s own
        docstring names the note and defers it ("...for the note it writes, but not
        here"); nothing downstream ever picked it up, so a truncated or corrupt mdout
        silently contributed a zero indistinguishable from a stage that never ran at all —
        the exact silence `status="queued"` exists to remove for the *other* zero-
        contributing state, left open for this one.

        Deliberately excludes the two situations `_elapsed_ps` also returns `None` for
        that are NOT "unusable":

        * queued -- `self.mdout is None` covers it (no mdout was ever declared, so nothing
          was attempted), and it already has its own `status`; a note here would say the
          same thing twice in two different vocabularies.
        * minimisation -- checked before `_elapsed_ps` is even called, matching that
          function's own run_type-before-stats order (see
          test_a_minimisation_is_recognised_by_run_type_before_stats_are_ever_read). A min
          mdout legitimately has no elapsed time and never had one; noting it would send a
          user to go investigate a stage with nothing wrong with it, which is the test
          `test_a_minimisation_gets_no_note_despite_never_having_an_elapsed_time` pins.

        A third outcome lives here too, added alongside `_fenced_elapsed_ps`: a stage whose
        elapsed time WAS produced, but not read off the header -- the header's begin time
        overflowed AMBER's fixed-width field and `_elapsed_ps_and_source` fell back to the
        fencepost estimate. That is not "unusable" (a real number reached `totals()`), so
        it must not get the note above; but silently substituting a derived number for a
        stated one would erase precisely the distinction that matters most on a long
        campaign, where the estimate's small error compounds across many overflowed
        chunks. Reusing the established `INFO:` convention here, rather than inventing a
        second mechanism, is what keeps this note showing up in the same places (
        `stage.validation`, `to_dict()`'s `summary.evidence`) a reader already knows to
        check for the first one.
        """
        if self.mdout is None or self.mdout.details is None:
            return []
        if getattr(self.mdout.details, "run_type", None) == "Minimization":
            return []
        elapsed, source = _elapsed_ps_and_source(self)
        if elapsed is None:
            return [f"INFO: Elapsed time for {self.name} could not be measured "
                    "(mdout present but unusable)."]
        if source == ORIGIN_FENCEPOST:
            return [f"INFO: Elapsed time for {self.name} was derived from frame spacing, "
                    "not read from the header (its stated begin time overflowed AMBER's "
                    "fixed-width field)."]
        if source == ORIGIN_FIRST_FRAME:
            # A DIFFERENT inference from the fencepost one above, and it must not borrow
            # that sentence: nothing here was derived from spacing, and the header's begin
            # time did not overflow -- it is present, reads 0.000, and is simply not the
            # clock origin under irest=0. Saying "overflowed" would send a reader looking
            # for a `**********` that is not in the file.
            return [f"INFO: Elapsed time for {self.name} was measured from its first "
                    "printed frame: the run set its own clock (irest = 0) and the CONTROL "
                    "DATA `t` it started from could not be read."]
        return []

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
        out: Dict[str, Any] = {
            "name": self.name,
            "stage_role": self.stage_role,
            "expected_gap_ps": self.expected_gap_ps,
            "gap_tolerance_ps": self.gap_tolerance_ps,
            "observed_gap_ps": self.observed_gap_ps,
            "restart_path": self.restart_path,
        }
        # Emitted only when queued, so an ordinary (non-queued) stage's summary.json block
        # is unchanged from what it was before this field existed — `to_dict()` feeds
        # summary.json, byte-pinned by test_lineage_backcompat.py's `assert_matches_golden`,
        # which fails on any ADDED key path, even a null one. `queued_count` in `totals()`
        # said how many; this is what makes the artifact say WHICH ones, rather than
        # leaving a reader to infer it from `files.mdout: null` plus the absence of a
        # `load_errors` entry — the same silence this whole feature exists to remove, one
        # level down.
        if self.status is not None:
            out["status"] = self.status
        # Provenance and recorded settings the methods summary is built from. Each is
        # emitted only when there is something to say, so a stage that has none of them
        # serialises as it did before they existed.
        if self.lineage:
            out["lineage"] = self.lineage
        if self.phase:
            out["phase"] = self.phase
        elapsed = _elapsed_ps(self)
        if self.inpcrd_is_own_restart:
            out["inpcrd_written_by_this_run"] = True
        if elapsed is not None:
            # The same number `totals()` adds up, so a per-phase or per-replica sum built
            # from summary.json agrees with the totals beside it; and the clock origin it
            # was measured from, which is when the run started.
            out["elapsed_ps"] = elapsed
            stats = getattr(getattr(self.mdout, "details", None), "stats", None)
            end = getattr(stats, "time_end", None)
            if isinstance(end, (int, float)) and not isinstance(end, bool):
                out["start_time_ps"] = round(float(end) - elapsed, 6)
        control = _mdout_control(self.mdout_header)
        if control:
            out["mdout_control"] = control
        if self.findings:
            out["findings"] = [{"kind": kind, "message": message}
                               for kind, message in self.findings]
        out.update({
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
        })
        return out


def _mdout_control(header: Any) -> Dict[str, Any]:
    """The CONTROL DATA settings an mdout header stated, plus the resolved seed as `ig`.

    What AMBER used, defaults filled in, which is what the methods summary reports for a
    setting the mdin did not write. Read defensively: tests and callers build stages with
    stand-in headers that carry only the attributes they need.
    """
    if header is None:
        return {}
    control = getattr(header, "control", None)
    out: Dict[str, Any] = dict(control) if isinstance(control, dict) else {}
    # The header's dedicated readers cover a few of the same fields; where the general
    # reader missed one, theirs stands.
    for key, attr in (("irest", "irest"), ("dt", "control_dt_ps"), ("ntwx", "control_ntwx"),
                      ("ntpr", "control_ntpr"), ("nstlim", "control_nstlim")):
        value = getattr(header, attr, None)
        if key not in out and isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = value
    seed = getattr(header, "resolved_ig", None)
    if isinstance(seed, int) and not isinstance(seed, bool):
        out["ig"] = seed
    return out


def _written_span_ps(nsteps: Any, dt: Any, interval_steps: Optional[int]) -> Optional[float]:
    """First-to-last span, in ps, of a record AMBER writes every `interval_steps` steps.

    AMBER writes after `interval_steps` steps, then every `interval_steps`, and stops at the
    largest multiple within `nsteps`; nothing is written at step 0. None when the inputs do
    not determine it or fewer than two records are written.
    """
    if not interval_steps or not isinstance(nsteps, (int, float)) or not isinstance(dt, (int, float)):
        return None
    if interval_steps <= 0 or nsteps <= 0 or dt <= 0:
        return None
    count = int(nsteps) // int(interval_steps)
    if count < 2:
        return None
    return (count - 1) * int(interval_steps) * float(dt)


def _record_tail_ps(nsteps: Optional[int], dt: Optional[float], interval_steps: Optional[int],
                    count: Any) -> float:
    """How long the run went on after the last record (frame or printed energy), in ps.

    `(nsteps mod interval) * dt` when the record is complete, that is when it holds the
    `floor(nsteps / interval)` records AMBER writes (or one more, where step 0 was written
    too); 0 otherwise. A record that stops short belongs to a run that stopped short, and
    adding a tail there would hide exactly the gap continuity is looking for.
    """
    if not nsteps or not dt or not interval_steps or not isinstance(count, (int, float)):
        return 0.0
    expected = int(nsteps) // int(interval_steps)
    if expected < 1 or int(count) not in (expected, expected + 1):
        return 0.0
    return (int(nsteps) - expected * int(interval_steps)) * float(dt)


def _fenced_elapsed_ps(stats: Optional["ThermoStats"]) -> Optional[float]:
    """The fencepost estimate of `time_end - begin_time_ps`, used only when the header
    itself cannot say what `begin_time_ps` was.

    AMBER prints `begin time read from input coords` into a fixed-width Fortran field.
    Once a restarted chain's accumulated simulated time passes roughly 1e6 ps the value no
    longer fits and AMBER writes `**********` instead of a number -- `mdout_header.py`'s
    `_BEGIN_TIME` requires a digit and simply does not match, so `begin_time_ps` comes back
    `None` for a run that is otherwise perfectly healthy: same file size as its neighbours,
    a full TIMINGS block, both a trajectory and a restart written. Reporting `None` here
    unconditionally would make that run's whole elapsed time vanish from every total --
    exactly the failure this module exists to prevent, pointed the other way, and it gets
    worse with campaign length rather than better.

    `ThermoStats` already carries what is needed to recover the number WITHOUT the header:
    frames print at `begin+iv, begin+2*iv, ..., begin+count*iv = time_end`, so the first
    PRINTED frame is `time_start = begin+iv`, and therefore
    `time_end - time_start + iv = count*iv = time_end - begin` -- the same quantity the
    header would have given, recovered purely from output spacing.

    This is NOT the bare `stats.time_start` substitution `_check_stage_pair` documents and
    rejects elsewhere in this module: using `time_start` alone is short by exactly one
    `+iv`, which is what "manufactures a gap on every chunked run" there (1020.0 against a
    true 920.0). The `+ iv` term is precisely what was missing from that rejected
    substitution -- this is a different, complete formula, not a second attempt at the
    same one.

    `ThermoStats.true_coverage_ns` already computes this fencepost quantity (in ns), so it
    is reused here rather than re-derived in ps -- but only once `count >= 2`, checked
    BEFORE the call: `avg_interval_ps` (and therefore `true_coverage_ns`) returns exactly
    `0.0` for a single-frame chunk, and a `0.0` returned from THIS function would be read
    by every caller as "this stage really did contribute zero elapsed time" -- a false
    zero indistinguishable from "the estimate could not be made" at all, which defeats the
    whole point of falling back instead of reporting `None`. `count < 2` therefore has to
    return `None` here, explicitly, before `true_coverage_ns` is ever asked.

    The result is an INFERENCE, not a reading: it assumes `ntpr` (the coordinate/energy
    print interval) was constant for the life of the run, which is standard AMBER
    behaviour but not something a parser can verify from the file alone. Every caller that
    substitutes this value for a missing header reading is expected to say so -- see the
    "derived from frame spacing" notes in `_validate_elapsed_time` and `_check_stage_pair`.
    """
    if stats is None or getattr(stats, "count", 0) < 2:
        return None
    coverage_ns = stats.true_coverage_ns
    if coverage_ns <= 0:
        return None
    # `true_coverage_ns` is ps/1000; undo that conversion rather than re-deriving
    # `time_end - time_start + interval` in ps ourselves, so there is exactly one place
    # that computes the fencepost quantity and this function only ever converts its units.
    return coverage_ns * 1000.0


def _fenced_begin_time_ps(stats: Optional["ThermoStats"]) -> Optional[float]:
    """The fencepost estimate of the run's ABSOLUTE begin time, for `_check_stage_pair`'s
    own independent read of `begin_time_ps` -- used for the continuity/gap check, separate
    from `_elapsed_ps_and_source`'s read of the same header field for the totals.

    `_fenced_elapsed_ps` already recovers `time_end - begin`; solving for `begin` given
    `time_end` is one subtraction. Reusing it here rather than re-deriving
    `time_start - interval` independently keeps the two call sites -- totals and
    continuity -- agreeing on what "header unavailable" and "single frame" mean, instead
    of risking two guards that quietly drift apart under a future edit to one of them.
    """
    if stats is None:
        return None
    fenced_elapsed = _fenced_elapsed_ps(stats)
    if fenced_elapsed is None:
        return None
    end = getattr(stats, "time_end", None)
    if end is None:
        return None
    return float(end) - fenced_elapsed


# Where a run's ABSOLUTE clock origin came from. Two of these are readings and two are
# inferences, and `_STATED_ORIGINS` is the line between them: a caller substituting an
# inference for a reading has to say so (see `_validate_elapsed_time` and
# `_check_stage_pair`), because on a long campaign the inference's small error compounds
# across every chunk while a reading's does not.
ORIGIN_HEADER = "header"          # `begin time read from input coords` -- irest=1
ORIGIN_CONTROL_T = "control-t"    # CONTROL DATA `t` -- irest=0, where the header is a 0.0
ORIGIN_FIRST_FRAME = "first-frame"  # the NSTEP = 0 record -- irest=0 with `t` unreadable
ORIGIN_FENCEPOST = "fencepost"    # time_start - interval -- the header overflowed
_STATED_ORIGINS = (ORIGIN_HEADER, ORIGIN_CONTROL_T)


def _origin_time_ps(
    header: Optional["MdoutHeader"],
    stats: Optional["ThermoStats"],
    *,
    is_minimisation: bool = False,
) -> Tuple[Optional[float], Optional[str]]:
    """The ABSOLUTE AMBER clock reading this run started from, and where that came from.

    ONE function for both readers of this quantity -- `_elapsed_ps_and_source` (totals) and
    `_check_stage_pair` (continuity). They each used to read `begin_time_ps` and fall back
    independently, and the ledger already records what that costs: the fencepost fallback
    had to be added twice, and a fix to one left the other silently wrong for exactly the
    runs the fix was about.

    **`irest` decides whether the header's begin time means anything at all.** This is the
    regression this function exists to close, measured on the campaign the branch was
    written against:

        equil/NN/18_ntp_equi:  ntx = 1, irest = 0, t = 1800.0, nstlim = 1600000, dt = 0.002
        mdout: `begin time read from input coords =     0.000 ps`
               `NSTEP =        0   TIME(PS) =    1800.000`   <- first frame
               `NSTEP =  1600000   TIME(PS) =    5000.000`   <- last frame

    Under `irest = 0` AMBER does not take the clock from the coordinate file -- it
    initialises from the mdin's `t` -- so it prints "begin time read from input coords =
    0.000" because it genuinely read none, and starts the trajectory at 1800. Reading that
    0.000 as the origin reports 5000 ps of dynamics for a run that did 3200 (`nstlim x dt`,
    the frame span 5000-1800, and 160 intervals x 20 ps all agree on 3200). Five runs, one
    per replica: the campaign reported 5,039,000 ps against a true 5,030,000.

    Verified over all 1091 mdouts of that campaign: `irest = 0` and an `NSTEP = 0` record
    are the same set (10 MD runs, plus 70 minimisations with no TIME(PS) frames at all),
    and `irest = 1` runs (1011 of them) never print one. That is why the `irest = 0` route
    never takes the fencepost below: the fencepost adds one interval to `time_end -
    time_start` on the assumption that the first PRINTED frame is one interval after the
    origin, which is false exactly when an `NSTEP = 0` record exists -- measured 3220
    against a true 3200 on these very runs. Routing `irest = 0` to `t` (or, failing that,
    straight to the un-fenced first frame, which IS the origin) is what keeps that
    overshoot unreachable rather than merely unreached.

    `t` is NOT preferred unconditionally, and must never be: under `irest = 1` AMBER
    ignores it. The repo's own back-compat fixtures say `t = 1000.0` for a run that began
    at 920.0, and the real campaign's `nvt_prod_0201` says `t = 5000.0` for a run that
    began at 1005019.992.

    **`is_minimisation` narrows the `irest = 0` rule above -- it does not hold for a
    minimisation, and this function used to apply it there anyway.** Real counterexample on
    the campaign this branch was written against: `equil/01/07_min_red.out` is
    `imin = 1, ntx = 1, irest = 0`, states no `t` anywhere in CONTROL DATA (a minimisation's
    CONTROL DATA has no `Molecular dynamics:` section to state one in), and prints no
    `NSTEP = 0` / `TIME(PS)` record (a minimisation prints `NSTEP ENERGY RMS GMAX` instead)
    -- yet its header begin time is a perfectly valid, non-zero 1800.000. The `irest = 0`
    rule above is about DYNAMICS specifically: AMBER substitutes the mdin's `t` for the
    coordinate file's time only because it is initialising an MD clock it is about to
    integrate forward, and a minimisation has no such clock to initialise. Nothing in AMBER
    suppresses the coordinate file's stated time for a minimisation, `irest` notwithstanding,
    so the header's `begin_time_ps` remains a READING, not the meaningless 0.000 a dynamics
    run under the same `irest = 0` would print. Before this parameter existed, the two
    routes above both failed here (no stated `t`, no first frame -- a minimisation has
    neither) and this function returned `(None, None)`, discarding a begin time that was
    never untrustworthy in the first place -- a regression this file's own re-review caught:
    the pre-`_origin_time_ps` code used 1800.0 for exactly this file via `begin_time_ps`
    directly, and `_check_stage_pair` started reporting "Cannot verify continuity" instead.
    Costs nothing on the TOTALS path: `_elapsed_ps_and_source` excludes minimisations by
    `run_type` before it ever calls this function (a minimisation has no elapsed dynamics
    time to measure), so this widens only what CONTINUITY (`_check_stage_pair`) can verify.
    A DYNAMICS `irest = 0` run with neither a stated `t` nor a first frame still returns
    `(None, None)`: unlike a minimisation, its header begin remains exactly the untrustworthy
    0.000 the C1 fix this function exists to hold was about, and trusting it would
    reintroduce the over-count on any dynamics mdout whose CONTROL DATA `t` failed to parse.
    """
    if header is None:
        return None, None
    if getattr(header, "irest", None) == 0:
        stated_t = getattr(header, "control_t_ps", None)
        if stated_t is not None:
            return float(stated_t), ORIGIN_CONTROL_T
        # `t` shares AMBER's overflowing fixed-width field with the begin time (the repo's
        # own back-compat fixtures print `t       =**********` from 21000 ps on), so an
        # irest=0 run whose clock was set past ~1e6 states no readable `t` either. The
        # NSTEP = 0 record it printed carries the same number, un-fenced.
        if stats is not None and getattr(stats, "count", 0):
            first = getattr(stats, "time_start", None)
            if first is not None:
                return float(first), ORIGIN_FIRST_FRAME
        # LAST resort, and gated on `is_minimisation` for exactly the reason the docstring
        # above walks through at length: a minimisation's header begin time was never put
        # through the substitution that makes a DYNAMICS irest=0 run's begin time
        # meaningless, so it is safe to trust here where a dynamics run's would not be.
        if is_minimisation:
            begin = getattr(header, "begin_time_ps", None)
            if begin is not None:
                return float(begin), ORIGIN_HEADER
        return None, None
    begin = getattr(header, "begin_time_ps", None)
    if begin is not None:
        return float(begin), ORIGIN_HEADER
    # The header states nothing: either AMBER's fixed-width field overflowed once this
    # chain passed ~1e6 ps of accumulated time (`**********`), or the block is absent
    # entirely. `read_mdout_header` cannot tell those apart and neither can this function.
    fenced = _fenced_begin_time_ps(stats)
    return (fenced, ORIGIN_FENCEPOST) if fenced is not None else (None, None)


def _elapsed_ps_and_source(stage: "SimulationStage") -> Tuple[Optional[float], Optional[str]]:
    """How much simulated time this stage actually produced, and which of
    `_origin_time_ps`'s four routes the clock origin it was measured against came from.

    The `Optional[float]` half is `None` for four different situations that all have to be
    told apart by the caller for the note it writes, but not here:

    * queued -- an mdin with no mdout. The run was set up and never executed. Counting it
      was the bug: on the campaign this was written against it was 25 ns of simulation
      that never happened, reported with ok: true;
    * minimisation -- a min mdout prints `NSTEP ENERGY RMS GMAX`, never `TIME(PS)`, so it
      has no elapsed time and never had one. It contributed 0 under the old rule too
      (no nstlim/dt in the mdin), so this is not a change;
    * unreadable -- `parse_mdout` catches nothing and returns a default-valued object
      rather than raising, so a malformed-but-present mdout arrives as `stats.count == 0`
      rather than as `stage.mdout is None`;
    * no clock origin derivable by ANY of `_origin_time_ps`'s routes -- see there.
      Falling back to 0.0 for any route would make an absolute time look like an
      elapsed one, which is the 304,600-ps-against-100,000 bug, so silence is the only
      truthful answer left.

    `time_end` is ABSOLUTE. `time_end - time_start` is NOT the alternative in general:
    on an `irest = 1` run `time_start` is the first PRINTED frame, one ntpr interval after
    the true begin, which is short by one interval per run -- the trap already documented
    at `_check_stage_pair`. (On an `irest = 0` run it is exactly right, because the
    `NSTEP = 0` record IS the origin; `_origin_time_ps` is where that distinction lives.)

    A STATED origin stays PRIMARY over an inferred one within each `irest` branch: the
    header (or the control-data `t`) says what AMBER used, while the fencepost value is an
    inference from output spacing (see `_fenced_elapsed_ps`'s docstring for why that
    distinction matters and stays load-bearing all the way to the artifact).
    """
    if stage.mdout is None or stage.mdout.details is None:
        return None, None
    details = stage.mdout.details
    if getattr(details, "run_type", None) == "Minimization":
        return None, None
    stats = getattr(details, "stats", None)
    if stats is None or getattr(stats, "count", 0) == 0:
        return None, None
    if stage.mdout_header is None:
        return None, None
    end = getattr(stats, "time_end", None)
    if end is None:
        return None, None

    origin, source = _origin_time_ps(stage.mdout_header, stats)
    if origin is None:
        return None, None
    elapsed = float(end) - origin

    # One guard for every route, run on whichever `elapsed` was produced, rather than a
    # `> 0` check duplicated inside each branch: an estimate that comes out <= 0 is exactly
    # as untrustworthy whichever origin produced it, and must be reported the same way to
    # the caller -- `None`, never a negative or false-zero "elapsed" time. `count < 2` is
    # already `None` before this point, via `_fenced_begin_time_ps`'s inherited guard.
    if elapsed <= 0:
        return None, None
    return elapsed, source


def _timestep_ps(stage: "SimulationStage") -> Optional[float]:
    """This stage's integration timestep in ps, or None when nothing stated one.

    Three sources, in decreasing order of what they actually establish:

    1. the mdout header's CONTROL DATA `dt` -- what AMBER RESOLVED and ran with;
    2. the mdin's `dt` -- what the user ASKED for;
    3. `MdoutMetadata.dt` -- the same control-data line as (1), read by the legacy
       whole-file parser.

    The order exists because (3) alone is not safe to trust and the guard that was supposed
    to protect against that was dead code. `MdoutMetadata.dt` defaults to **0.001**, which
    is truthy and a perfectly ordinary real timestep, so `if not dt: <use the mdin>` never
    fired: an mdout with frames but a CONTROL DATA block the legacy parser did not read
    reported `dt = 0.001` for a 0.002 run and published `steps` at exactly TWICE the truth,
    while the mdin sitting beside it plainly stated 0.002. `MdoutHeader.control_dt_ps` is
    `None` when the file did not state one, which is what makes the fallback reachable at
    all. (3) is kept last rather than deleted so an mdout the header reader stopped short
    of -- it stops at the results banner; the legacy parser does not -- still contributes
    what it has.

    Returns `None`, not a default, when sources (1) and (2) both state nothing AND (3) is
    itself absent (no mdout, or no `.details` on it) -- but NOT, despite the paragraph
    above, whenever "no source states a usable timestep" in the sense a reader would take
    that to mean. (3) is exactly the source this function exists to stop being trusted
    blindly, and it is *still* trusted blindly once reached: `MdoutMetadata.dt`'s truthy
    0.001 default cannot be told apart from a file that genuinely stated 0.001, because the
    legacy parser records no separate "did I actually see a `dt =` line" flag. So a stage
    whose header CONTROL DATA did not parse (1) and whose mdin is missing or unparseable (2)
    reports 0.001 here whether or not ANY source ever stated a timestep -- doubling `steps`
    for a genuine 0.002 run exactly as (3) alone always did, just one fallback further out
    than before. This is PRE-EXISTING, not introduced by the ordering fix above, and not
    closed by it: closing it means giving `MdoutMetadata.dt` an `Optional[float] = None`
    default so "unstated" and "0.001" stop being the same value, and `MdoutMetadata` is the
    exact dataclass `asdict()`-ed verbatim into `summary.json` per stage (see
    `mdout_header.py`'s module docstring) -- so that default is not free to change; every
    golden mdout that never printed a `dt =` line at all would flip its emitted
    `mdout.details.dt` from `0.001` to `null`, and this repo's own goldens are byte-pinned
    against exactly that field. The honest fix available here is this paragraph, not the
    code: source (3) is a source of last resort in name only, and a stage that reaches it
    with no genuine reading is a silent, pre-existing risk, not a closed one.
    """
    for value in (
        getattr(stage.mdout_header, "control_dt_ps", None) if stage.mdout_header else None,
        getattr(stage.mdin.details, "dt", None) if (stage.mdin and stage.mdin.details) else None,
        getattr(stage.mdout.details, "dt", None) if (stage.mdout and stage.mdout.details) else None,
    ):
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def _elapsed_ps(stage: "SimulationStage") -> Optional[float]:
    """`_elapsed_ps_and_source`'s value alone, for the many callers that only need the
    number -- totals, the stats CSV -- and not where the origin came from. Callers that
    DO need to know (`_validate_elapsed_time`, `_check_stage_pair`'s own origin read)
    call `_elapsed_ps_and_source` directly rather than reconstructing the source from this
    function's return value, which cannot be told apart from a value AMBER actually wrote.
    """
    return _elapsed_ps_and_source(stage)[0]


#: The role under which `totals` counts the time of runs that carry none.
UNCLASSIFIED_ROLE = "unclassified"
#: Prefix of the per-role keys in `totals` and in each `lineage_totals` entry.
ROLE_TIME_PREFIX = "time_ps_"
_ROLE_ORDER = ("minimization", "heating", "equilibration", "production")


def _role_sort_key(role: str) -> Tuple[int, str]:
    if role in _ROLE_ORDER:
        return (_ROLE_ORDER.index(role), role)
    return (len(_ROLE_ORDER) + (1 if role == UNCLASSIFIED_ROLE else 0), role)


def _role_keys(times: Dict[str, float], always: bool = False) -> Dict[str, float]:
    """`{role: ps}` as `{"time_ps_<role>": ps}`, or nothing for fewer than two roles."""
    if len(times) < 2 and not always:
        return {}
    return {f"{ROLE_TIME_PREFIX}{role}": ps for role, ps in times.items()}


def role_times(totals: Dict[str, Any]) -> List[Tuple[str, float]]:
    """The per-role simulated times a `totals` (or `lineage_totals` entry) carries, as
    `[(role, ps)]` in protocol order; empty when it carries none."""
    return [(key[len(ROLE_TIME_PREFIX):], float(value)) for key, value in totals.items()
            if isinstance(key, str) and key.startswith(ROLE_TIME_PREFIX)
            and isinstance(value, (int, float))]


@dataclass
class SimulationProtocol:
    stages: List[SimulationStage] = field(default_factory=list)

    def validate(self, cross_stage: bool = True, allow_unexpected_gaps: bool = False) -> None:
        for stage in self.stages:
            stage.validate()
        if cross_stage:
            self._check_continuity(allow_unexpected_gaps=allow_unexpected_gaps)

    def _check_continuity(self, allow_unexpected_gaps: bool = False) -> None:
        if self.stages and all(stage.step_id for stage in self.stages):
            self._check_declared_edges(allow_unexpected_gaps=allow_unexpected_gaps)
            return
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

    def _check_declared_edges(self, allow_unexpected_gaps: bool = False) -> None:
        """Continuity for a document: every stage against the stage it declares it read.

        A document states its edges, so neither document order nor member order is
        consulted. Comparing a stage with its document-order neighbour measured runs that
        never met: a minimisation that starts from the starting structure, filed after an
        equilibration because `equilibration/` sorts before `minimization/`, "overlapped"
        that equilibration by its whole length, on every replica of three deposited
        projects. A stage that declares no producer -- it reads the starting structure or
        an explicit file -- has nothing to be compared with, and says so.

        The one exception keeps an untagged document's first stage without a note, as the
        neighbour zip always left it: its summary.json would otherwise change for nothing.

        Measured against what it declares, a run that read an older restart than it
        should have is consistent in time: segment 4 read segment 2's restart, and
        segment 2 ended when that restart says. What shows it is the branch: segments 3
        and 4 both continue segment 2. Runs of one directory and one member that continue
        the same restart are therefore reported, each of them, since nothing says which
        one went wrong. Only runs with an mdout count: a queued run, or an analysis
        script typed as an mdin (`rep_1_cpptraj_input.in`), read nothing. Replicas that
        branch from a shared equilibration sit in directories (or members) of their own,
        and are not reported.
        """
        by_step_id = {s.step_id: s for s in self.stages}
        multi_member = any(stage.lineage for stage in self.stages)
        # The first RUN: on the scan path a topology or a starting structure may precede it
        # as a stage of its own (`is_run`), and those are never measured.
        first_run = next((s for s in self.stages if s.is_run), None)
        for stage in self.stages:
            if not stage.is_run:
                continue
            producer = by_step_id.get(stage.parent_id) if stage.parent_id else None
            if producer is not None and producer is not stage:
                self._check_stage_pair(producer, stage, allow_unexpected_gaps=allow_unexpected_gaps)
                continue
            previous = (by_step_id.get(stage.order_predecessor_id)
                        if stage.order_predecessor_id else None)
            if previous is not None and previous is not stage:
                stage._add_continuity_note(
                    f"INFO: No recorded input links {stage.name} to a run here; continuity "
                    f"is measured against {previous.name}, the run before it.")
                self._check_stage_pair(previous, stage, allow_unexpected_gaps=allow_unexpected_gaps)
                continue
            if stage is first_run and not multi_member and not stage.parent_id:
                continue
            reason = ("no producing stage resolved" if stage.parent_id
                      else "it declares no producing stage")
            stage._add_continuity_note(
                f"INFO: Continuity for {stage.name} was not measured ({reason})."
            )

        readers: Dict[Tuple[str, str, Optional[str]], List[SimulationStage]] = {}
        for stage in self.stages:
            producer = by_step_id.get(stage.parent_id) if stage.parent_id else None
            if producer is None or producer is stage or stage.mdout is None:
                continue
            key = (producer.step_id, stage.name.rpartition("/")[0], stage.lineage or None)
            readers.setdefault(key, []).append(stage)
        for (producer_id, _, _), group in readers.items():
            if len(group) < 2:
                continue
            producer = by_step_id[producer_id]
            for stage in group:
                others = [s.name for s in group if s is not stage]
                stage._add_continuity_note(
                    f"Continues from {producer.name}, as {', '.join(others)} "
                    f"{'does' if len(others) == 1 else 'do'}: {len(group)} runs in one "
                    "directory continue the same restart."
                )

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
        # The end is the producer's last trajectory frame, or its last printed energy, plus
        # whatever the run did after that record: up to one write interval when `nstlim` is
        # not a multiple of it. Without that tail, a 62,500-step run printing every 1,000
        # steps "ended" 1 ps before it did, and every such pair reported a gap.
        end_time = None
        run_steps = prev._run_steps()
        run_dt = _timestep_ps(prev)
        if prev.mdcrd and prev.mdcrd.details:
            end_time = getattr(prev.mdcrd.details, "time_end", None)
            if end_time is not None:
                end_time += _record_tail_ps(run_steps, run_dt, prev._coord_interval_steps(),
                                            getattr(prev.mdcrd.details, "n_frames", None))
        if end_time is None and prev.mdout and prev.mdout.details:
            stats = getattr(prev.mdout.details, "stats", None)
            if stats is not None and getattr(stats, "count", 0):
                end_time = getattr(stats, "time_end", None)
                if end_time is not None:
                    end_time += _record_tail_ps(run_steps, run_dt, prev._print_interval_steps(),
                                                getattr(stats, "count", None))

        start_time = None
        # `inpcrd_is_own_restart` is the scan path saying "that file is this run's output,
        # not its input" -- reading its clock here would measure when the run FINISHED and
        # call it when the run began. See the field's own comment; the fall-through below
        # (the mdout header's stated begin time) is the reading that is actually about the
        # start, and on the scan path it is always available where the mdout parsed.
        if current.inpcrd and current.inpcrd.details and not current.inpcrd_is_own_restart:
            start_time = getattr(current.inpcrd.details, "time", None)
        start_time_source = None
        if start_time is None and current.mdout_header is not None:
            # The mdout says when the run began, and says it whether or not the restart it
            # read is machine-readable here. On a bare install `netCDF4`/`scipy` are
            # optional extras, so a NetCDF restart parses to `time=None` and continuity was
            # simply not checked — the header is the only reading left.
            #
            # Fallback rather than preference: where both exist they agree, and the inpcrd
            # is what the existing goldens were generated from. Note the mdout's *stats*
            # are not an alternative on their own — on an `irest = 1` run `stats.time_start`
            # is the first printed frame, one `ntpr` interval later (1020.0 against a true
            # 920.0), so reaching for it manufactures a gap on every chunked run.
            #
            # Routed through `_origin_time_ps`, the SAME function `_elapsed_ps_and_source`
            # uses, rather than reading `begin_time_ps` here independently. This used to be
            # its own read with its own fallback, and the ledger records what that cost:
            # the fencepost fallback had to be written twice, and the `irest = 0` fix would
            # otherwise correct the totals while leaving continuity comparing against a
            # begin time of 0.000 for exactly the runs it had just corrected — a phantom
            # multi-nanosecond "overlap" reported on five healthy runs.
            #
            # `current.inpcrd`'s own time still wins above, also under `irest = 0`, where
            # AMBER ignores it: there it is read as the time the coordinate file was
            # written, which is what says whether the run read its producer's final
            # restart. Where only the run's own clock is left (`t`, or its first frame),
            # nothing is measured; see below.
            stats = None
            run_type = None
            if current.mdout and current.mdout.details:
                stats = getattr(current.mdout.details, "stats", None)
                run_type = getattr(current.mdout.details, "run_type", None)
            # `is_minimisation` is what lets `_origin_time_ps` trust a valid header begin
            # time under `irest = 0` here without reintroducing the over-count on a DYNAMICS
            # run whose CONTROL DATA `t` failed to parse -- see that function's own
            # docstring for the real counterexample (`equil/01/07_min_red.out`) this closes.
            start_time, start_time_source = _origin_time_ps(
                current.mdout_header, stats,
                is_minimisation=(run_type == "Minimization"),
            )

        if start_time_source in (ORIGIN_CONTROL_T, ORIGIN_FIRST_FRAME):
            # The run set its own clock (`irest = 0`, new velocities): AMBER started it at
            # the mdin's `t`, whatever the coordinates it read say, so its start time says
            # nothing about the run before it. A production restarted with new velocities
            # and `t = 0` after 5000 ps of equilibration was reported as a 5000-ps overlap
            # wherever the restart's own time could not be read (a NetCDF restart on an
            # install without a NetCDF backend). Which coordinates it read is what links the
            # two, and the recorded-input check compares exactly that.
            current._add_continuity_note(
                f"INFO: {current.name} set its own clock (irest = 0); continuity with "
                f"{prev.name} follows the recorded input coordinates, not the clock."
            )
            return

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

        if start_time_source == ORIGIN_FENCEPOST:
            # Same "derived from frame spacing" convention `_validate_elapsed_time` uses
            # for the totals -- follow it here too rather than inventing a second way to
            # say the same thing, so a reader who has already learned to look for this
            # phrase in `summary.evidence` finds it for continuity as well.
            current._add_continuity_note(
                f"INFO: Start time for {current.name} was derived from frame spacing, "
                "not read from the header (its stated begin time overflowed AMBER's "
                "fixed-width field)."
            )

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
        # Frame times are single precision in AMBER's NetCDF files, so a gap of exactly the
        # tolerance arrives as 1.000000000007; that is the tolerance, not more than it.
        noise = 1e-6

        # When no explicit gap expectation is provided, treat small
        # differences as numerical noise instead of real gaps/overlaps.
        if current.expected_gap_ps is None:
            if abs(gap) <= default_tolerance + noise:
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
            if abs(gap) > default_tolerance + noise:
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
        """`steps` and `time_ps` over any set of stages, counting only what ran.

        Sourced from the mdout, not the mdin: the mdin states intent and a run that was
        queued and never started, or started and was killed at 60%, states the same
        intent as one that finished. See `_elapsed_ps_and_source` for what "ran" means,
        for why the primary formula is `time_end - begin_time_ps`, and for the
        frame-spacing fallback used when the header's `begin_time_ps` overflowed.

        Accumulated with ``+=`` rather than ``sum()`` on purpose: CPython 3.12 made
        ``builtins.sum`` compensated, and CI's matrix is 3.9 *and* 3.12, so a float total
        built with ``sum()`` can differ in its last bits between the two jobs -- on the one
        artifact every lineage change is told to keep byte-stable.
        """
        total_steps = 0.0
        total_time = 0.0
        for stage in stages:
            elapsed = _elapsed_ps(stage)
            if elapsed is None:
                continue
            total_time += elapsed
            dt = _timestep_ps(stage)
            if dt is not None:
                total_steps += elapsed / dt
        return {"steps": total_steps, "time_ps": total_time}

    @staticmethod
    def _role_times(stages: List[SimulationStage]) -> Dict[str, float]:
        """Simulated time per role, over the stages that ran (the `time_ps` of
        `_sum_stages`, split by `stage_role`), in protocol order: minimization, heating,
        equilibration, production, then any other role by name, then runs without a role
        as `unclassified`."""
        times: Dict[str, float] = {}
        for stage in stages:
            elapsed = _elapsed_ps(stage)
            if elapsed is None:
                continue
            role = stage.stage_role or UNCLASSIFIED_ROLE
            times[role] = times.get(role, 0.0) + elapsed
        return {role: times[role] for role in sorted(times, key=_role_sort_key)}

    def _members(self) -> Dict[Any, List[SimulationStage]]:
        """This protocol's membership buckets, sentinel included.

        `buckets` is structurally typed on ``.lineage``, so the same grouping the document
        uses applies to the flat stage list without either side re-deriving it.
        """
        return buckets(self.stages)

    def totals(self) -> Dict[str, float]:
        out = self._sum_stages(self.stages)
        # Simulated time per role, as flat `time_ps_<role>` keys (`totals` is a flat
        # `Dict[str, float]` on the GUI's models), emitted only when the runs that ran hold
        # more than one role -- so a single-role document's summary.json is the file it
        # always was, and `time_ps` alone says it. `time_ps` counts equilibration as well
        # as production; this is what tells them apart.
        out.update(_role_keys(self._role_times(self.stages)))
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
        # Emitted only when the document holds at least one queued run, so a document with
        # none reports the totals it always did. `queued_count` is what makes a "smaller
        # total than before" report distinguishable from "something broke": this many runs
        # contributed nothing because they never ran, not because the arithmetic changed.
        queued = sum(1 for s in self.stages if s.status == "queued")
        if queued:
            out["queued_count"] = float(queued)
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
        # Per role too, under the same keys and the same condition as `totals`: every
        # member lists every role the document ran, 0.0 where it ran none of it, so a
        # replica that never reached production says so.
        roles = list(_role_keys(self._role_times(self.stages)))
        out: Dict[str, Dict[str, float]] = {}
        for tag, stages in members.items():
            if tag is UNTAGGED:
                continue
            entry: Dict[str, float] = dict(self._sum_stages(stages))
            entry["step_count"] = len(stages)
            if roles:
                own = _role_keys(self._role_times(stages), always=True)
                for key in roles:
                    entry[key] = own.get(key, 0.0)
            out[tag] = entry
        return out

    def sequence_findings(self) -> List[Dict[str, Any]]:
        """The numbered-sequence holes in this protocol, as ``missing_run`` cards.

        The same finding `validate --manifest` reports, reachable from a protocol — which
        is what `plan --recursive` has and a `Simulation` is what it does not have.
        """
        return sequence_findings([s.name for s in self.stages],
                                 [s.lineage for s in self.stages])

    def stage_findings(self, start_index: int = 1) -> List[Dict[str, Any]]:
        """Every stage's own problems, as cards; see :func:`stage_finding_cards`."""
        return stage_finding_cards(self.stages, start_index=start_index)

    def continuity_findings(self, start_index: int = 1) -> List[Dict[str, Any]]:
        """Every stage's continuity problems (its non-INFO continuity notes) as
        ``continuity_gap`` cards, in the shape `validate --manifest` gives them.

        `plan --recursive` printed these notes per stage only, so its Findings block and
        `--strict` never saw a gap; the manifest path has always reported them as cards.
        """
        out: List[Dict[str, Any]] = []
        for stage in self.stages:
            seen = set()
            for note in stage.continuity:
                if str(note).startswith("INFO") or note in seen:
                    continue
                seen.add(note)
                out.append({
                    "id": f"sug_c_{start_index + len(out)}", "kind": "continuity_gap",
                    "severity": "needs_you", "title": "Continuity note",
                    "evidence": f"{stage.name}: {note}",
                    "actions": ["Set as expected", "Investigate"], "step_id": stage.step_id,
                })
        return out

    def to_dict(self) -> Dict[str, Any]:
        stages = []
        names = {s.step_id: s.name for s in self.stages if s.step_id}
        for stage in self.stages:
            entry = stage.to_dict()
            # The run this one continues from, by name: the document's own edge, which the
            # flattened input path cannot recover once several runs share a restart.
            parent = names.get(stage.parent_id) if stage.parent_id else None
            if parent:
                entry["continues_from"] = parent
            stages.append(entry)
        out: Dict[str, Any] = {
            "totals": self.totals(),
            "stages": stages,
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
        # What the declared replicas agree and disagree about (atom counts, settings,
        # seeds at a branch point): the findings `plan` prints, kept in the artifact.
        # Silent for a document with fewer than two declared members.
        coherent = [{"severity": f.severity, "kind": f.kind, "message": f.message}
                    for f in _coherence(self.stages)]
        if coherent:
            out["lineage_findings"] = coherent
        return out

    def to_methods_dict(self) -> Dict[str, Any]:
        """The methods summary: :func:`ambermeta.methods_summary.build_methods_summary`
        applied to :meth:`to_dict`. See that module for the fields."""
        from ambermeta.methods_summary import build_methods_summary
        return build_methods_summary(self.to_dict())


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


def _parse_mdout(path, stage, *, strict):
    """Parse an mdout and read its header, recording both on `stage`.

    One call site for both so the header can never be attached on one path into the engine
    and not the other — the failure mode `lineage` itself hit in PR 2a, where a field set
    in one constructor was silently absent from every stage built by the other.

    The header read is not routed through `_safe_parse`: it is a best-effort extra, and a
    file that failed to parse has already recorded its FileLoadError. A second error for
    the same file would double-count the same problem.
    """
    parsed = _safe_parse(MdoutParser, path, "mdout", stage, strict=strict)
    if parsed is not None:
        try:
            stage.mdout_header = read_mdout_header(path)
        except (OSError, UnicodeDecodeError, ValueError):
            stage.mdout_header = None
    return parsed


def _looks_queued(mdin_details: Any, has_mdin: bool, has_mdout: bool) -> bool:
    """Whether a run built from these facts is queued: set up and never executed.

    Takes `mdin_details` -- an `MdinMetadata`-shaped object (specifically, anything with a
    `.cntrl_parameters` attribute), or `None` -- rather than a whole `SimulationStage`, so
    the ONE rule can be called from three places that do not all have a `SimulationStage`
    to hand: both engine entry points already hold `stage.mdin.details` at the point they
    call this, but `core_bridge.discover_draft` builds `ambermeta.simulation.Step` objects
    and never constructs a `SimulationStage` at all -- it parses the mdin straight to its
    `.details` (`mdin_details` in that function) to decide the step's role. A second,
    forked copy of this predicate for `discover_draft` is exactly the kind of drift
    `crosses_lineage`'s import note above already warns about for a different chaining
    rule, so this function's signature bent to fit the odd caller out rather than being
    duplicated for it.

    Called together with the same two file-presence facts (was an mdin declared, was an
    mdout declared) every caller already has on hand while it is building the run.

    `has_mdin and not has_mdout` alone is not enough. `sys021_tree`'s stray `cpptraj.in`
    satisfies exactly that and is not a run: it is a leftover cpptraj post-processing
    script that the extension-based file typing reads as an mdin. `MdinParser` never
    raises on content it does not recognise — same tolerant-parsing shape as
    `parse_mdout`, documented on `_elapsed_ps` — so a non-AMBER file with a `.in`/`.mdin`
    extension parses to a `MdinMetadata` with an empty `cntrl_parameters`, because nothing
    in it ever matched a `&cntrl` namelist. A genuine AMBER mdin, minimisation or
    dynamics, always has one — `nstlim`-based production and `maxcyc`-based minimisation
    both populate it, which is why this checks `cntrl_parameters` rather than the
    production-specific `length_steps` alone (a queued *minimisation* would otherwise be a
    false negative too: a min mdin never sets `nstlim`, so `length_steps` stays 0 for a
    genuine one exactly as it does for `cpptraj`). That refinement is what keeps `cpptraj`
    out of `test_a_stem_with_an_mdin_and_no_mdout_is_marked_queued`'s five-name list.

    A declared mdin that fails to parse at all (`mdin_details is None` — a missing or
    unreadable file, recorded elsewhere as a `FileLoadError`) reads as NOT queued: that is
    a broken reference, already flagged through `degraded`/`load_errors`, and a status
    implying "a real run is waiting to happen" would be a second, misleading claim about
    the same file.
    """
    return has_mdin and not has_mdout and bool(getattr(mdin_details, "cntrl_parameters", None))


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
            stage.mdout = _parse_mdout(resolved["mdout"], stage, strict=strict)
        if "mdcrd" in resolved:
            stage.mdcrd = _safe_parse(MdcrdParser, resolved["mdcrd"], "mdcrd", stage, strict=strict)
        if "inpcrd" in resolved:
            stage.inpcrd = _safe_parse(InpcrdParser, resolved["inpcrd"], "inpcrd", stage, strict=strict)
            if stage.inpcrd is not None:
                stage.restart_path = resolved["inpcrd"]

        if _looks_queued(getattr(stage.mdin, "details", None), "mdin" in resolved, "mdout" in resolved):
            stage.status = "queued"

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
        stage.phase = entry.get("phase") or None

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


def _coords_are_run_output(kinds: Dict[str, str]) -> bool:
    """Whether a scanned group's coordinate file is what a run WROTE rather than read.

    Stem grouping puts `prod_0002.restrt` -- AMBER's `-r` output, written at the END of the
    run -- beside the rest of that run's files. An mdin or an mdout in the group says a run
    is there. So does a trajectory (#87): `prod_0002.nc` is that run's `-x` output, and a
    deposit that kept only trajectories and restarts is still a campaign of runs.

    "Trajectory" is decided by content, never by the `.crd`/`.nc` extension alone. tLEaP's
    `saveamberparm` is routinely given a `.crd` name, and a bare `system.prmtop` /
    `system.crd` / `system.inpcrd` group names starting coordinates: its time is exactly
    what continuity should measure against. A file the sniffer cannot read is not evidence
    either way, and the group keeps the older reading.
    """
    if kinds.get("mdin") or kinds.get("mdout"):
        return True
    trajectory = kinds.get("mdcrd")
    return bool(trajectory) and sniff_coordinate_kind(trajectory) == "mdcrd"


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

    **A dot after a digit is a decimal point, not a separator.** `win_0.1`, `win_0.2`,
    `win_0.4` are three TI lambda windows, not chunks 1, 2 and 4 of a family called
    `win_0` — reading them that way reports a missing window 0.3 that was never meant to
    exist, and under `--strict` fails the run. So a numeric final suffix is an index only
    when what precedes it is not itself a digit, which is exactly the case `prod.0001`
    (`d`) is and `win_0.1` (`0`) is not.
    """
    run = name.rpartition("/")[2].rpartition("\\")[2]
    head, _, tail = run.rpartition(".")
    if not head:
        return run
    if tail.isdigit() and not head[-1].isdigit():
        return run
    return head


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


#: Per-run finding kinds, and the title each card carries. `step_check`: the run's own
#: files disagree (atom counts, mdin against mdout, time step against topology masses).
#: `unfinished_run`: the mdout has no completion marker. `input_mismatch`: the Step
#: declares other input coordinates than the INPCRD its mdout recorded.
FINDING_KINDS: Dict[str, str] = {
    "step_check": "Run check",
    "unfinished_run": "Run did not finish",
    "input_mismatch": "Declared input differs from the recorded one",
}


def stage_finding_cards(stages: List[SimulationStage],
                        start_index: int = 1) -> List[Dict[str, Any]]:
    """Each stage's `findings` as suggestion cards, in stage order.

    One producer for the three surfaces that report them, for the same reason as
    :func:`sequence_findings`: `validate --manifest` and `plan --manifest` reach it through
    ``validate_simulation``, and `plan --recursive` calls it on its own stages. The card is
    scoped to its step (``step_id``) where the stage came from a document.
    """
    out: List[Dict[str, Any]] = []
    for stage in stages:
        for kind, message in stage.findings:
            out.append({
                "id": f"sug_r_{start_index + len(out)}",
                "kind": kind,
                "severity": "needs_you",
                "title": FINDING_KINDS[kind],
                "evidence": f"{stage.name}: {message}",
                "actions": ["Investigate"],
                "step_id": stage.step_id,
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
        if kind == "mdout" and ext.lower() == ".out" and not looks_like_mdout(full_path):
            continue
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


def _order_by_recorded_inputs(stages: List[SimulationStage],
                              grouped: Dict[str, Dict[str, str]],
                              tags: Dict[str, str]) -> List[SimulationStage]:
    """A scanned tree's stages in the order its runs ran, each run linked to the run it
    continued, by the input coordinates the mdouts recorded.

    The scan used to order stages by file name and compare each with its neighbour, so a
    protocol whose names do not sort in run order was measured between runs that never
    met: `eq_0001..0003` before `prod_0001..0003` reported +20,000 ps gaps and a
    -42,000 ps overlap on a chain that was continuous, and a starting structure named
    `start.rst`, sorted after them, "overlapped" everything. This is the rule ``discover``
    uses (:mod:`ambermeta.run_order`): each run is linked to the run whose restart its mdout
    records, else to the run before it in its directory, and every stage gets a
    ``step_id`` (its name) so continuity measures the declared edges, as on the manifest
    path. Groups that are not runs (a topology, a starting structure) come first and are
    not measured.

    A tree where no mdout records a usable input keeps the name order and the
    neighbour comparison it always had.
    """
    from ambermeta.run_order import chain_runs, execution_order, recorded_producers

    runs = [stage for stage in stages if stage.is_run]
    names = [stage.name for stage in runs]
    headers = {stage.name: stage.mdout_header for stage in runs
               if stage.mdout_header is not None}
    recorded = recorded_producers(names, grouped, tags, headers)
    if not recorded:
        return stages
    order = execution_order(names, recorded, {stage.name: stage.stage_role for stage in runs})
    chain = chain_runs(order, recorded, grouped)
    by_name = {stage.name: stage for stage in runs}
    for stage in stages:
        stage.step_id = stage.name
    for name in order:
        by_name[name].parent_id = chain[name]
    _link_unrecorded_runs_by_order(order, by_name, recorded)
    return [stage for stage in stages if not stage.is_run] + [by_name[n] for n in order]


def _link_unrecorded_runs_by_order(order: List[str], by_name: Dict[str, SimulationStage],
                                   recorded: Dict[str, Any]) -> None:
    """Give each scanned run that no record links to a producer the run before it in its
    member, in execution order, to be measured against (`order_predecessor_id`).

    The 1.2 scan compared every run with its neighbour and so caught real gaps that the
    recorded inputs cannot: a job script that copies each restart to one fixed name
    (`-c restart.rst`, then `cp prod_$i.restrt restart.rst`) has every mdout record a file
    no run wrote, and a deposit without its restarts has records that name nothing here.
    Linked by the records alone, such runs were each a fresh start and were not measured.

    A run that records a file no run wrote, at the same start time as another run that
    records the same file, is a fan-out from one structure (several replicas started from
    it) and keeps no predecessor.
    """
    from ambermeta.run_order import RECORDED_START

    def origin(stage: SimulationStage) -> Optional[float]:
        stats = getattr(getattr(stage.mdout, "details", None), "stats", None)
        return _origin_time_ps(stage.mdout_header, stats)[0]

    starts: Dict[Tuple[str, Optional[float]], int] = {}
    for name in order:
        stage = by_name[name]
        if recorded.get(name) is RECORDED_START and stage.mdout_header is not None:
            key = (stage.mdout_header.assignment("INPCRD") or "", origin(stage))
            starts[key] = starts.get(key, 0) + 1

    last_in_member: Dict[Any, str] = {}
    for name in order:
        stage = by_name[name]
        member = stage.lineage or UNTAGGED
        previous = last_in_member.get(member)
        if stage.mdout is not None:
            # Only a run that ran ends anywhere: a queued run is skipped over.
            last_in_member[member] = name
        if stage.parent_id or previous is None or stage.mdout is None:
            continue
        if recorded.get(name) is RECORDED_START and stage.mdout_header is not None:
            key = (stage.mdout_header.assignment("INPCRD") or "", origin(stage))
            if starts.get(key, 0) > 1:
                continue
        stage.order_predecessor_id = previous


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
                                lineage=lineage_by_stem.get(stem),
                                is_run=_coords_are_run_output(file_kinds))

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
            stage.mdout = _parse_mdout(file_kinds["mdout"], stage, strict=strict)
        if "mdcrd" in file_kinds:
            stage.mdcrd = _safe_parse(MdcrdParser, file_kinds["mdcrd"], "mdcrd", stage, strict=strict)
        if "inpcrd" in file_kinds:
            stage.inpcrd = _safe_parse(InpcrdParser, file_kinds["inpcrd"], "inpcrd", stage, strict=strict)
            if stage.inpcrd is not None:
                stage.restart_path = file_kinds["inpcrd"]
                # Same stem as this run's own files, so this is what the run WROTE
                # (`-r prod_0002.restrt`), not what it read (`-c prod_0001.restrt`, a
                # different stem and therefore a different group). A bare
                # `system.prmtop` / `system.inpcrd` pair is not a run at all, and its
                # coordinates really are an input.
                stage.inpcrd_is_own_restart = _coords_are_run_output(file_kinds)

        if _looks_queued(getattr(stage.mdin, "details", None), "mdin" in file_kinds, "mdout" in file_kinds):
            stage.status = "queued"

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
                # A caller-supplied restart names coordinates the run READ, so it replaces
                # the same-stem output above in every sense -- including this flag, which
                # would otherwise stay set from it and suppress a reading that is now real.
                stage.inpcrd_is_own_restart = False

        stages.append(stage)

    stages = _order_by_recorded_inputs(stages, grouped, lineage_by_stem)

    # Apply auto restart detection if requested
    if auto_detect_restarts:
        auto_restarts = auto_detect_restart_chain(stages, directory, recursive=recursive)
        for stage in stages:
            if stage.name in auto_restarts and not stage.restart_path:
                rst_path = auto_restarts[stage.name]
                stage.inpcrd = _safe_parse(InpcrdParser, rst_path, "inpcrd", stage, strict=strict)
                if stage.inpcrd is not None:
                    stage.restart_path = rst_path
                    # The predecessor's restart: coordinates this run read.
                    stage.inpcrd_is_own_restart = False
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

    # A `lineage` column after `stage_role`, only when some stage carries a lineage: the
    # replica of a row was otherwise readable only from its run name, and a CSV for a
    # document that declares none keeps the columns it always had.
    columns = list(STATS_CSV_COLUMNS)
    if any(stage.lineage for stage in protocol.stages):
        columns.insert(columns.index("stage_role") + 1, "lineage")

    rows: List[Dict[str, Any]] = []
    for stage in protocol.stages:
        row: Dict[str, Any] = {"stage_name": stage.name, "stage_role": stage.stage_role or "",
                               "lineage": stage.lineage or ""}
        stats = getattr(stage.mdout.details, "stats", None) if (
            stage.mdout and stage.mdout.details) else None
        if stats:
            row["time_start_ps"] = getattr(stats, "time_start", "")
            row["time_end_ps"] = getattr(stats, "time_end", "")
            row["frame_count"] = getattr(stats, "count", "")
            for prefix, attr in (("temp", "temp_stats"), ("pressure", "pressure_stats"),
                                 ("density", "density_stats"), ("etot", "etot_stats")):
                series = getattr(stats, attr, None)
                if series:
                    mean, std = series.get_stats()
                    row[f"{prefix}_avg"] = mean if mean is not None else ""
                    row[f"{prefix}_std"] = std if std is not None else ""
        # `duration_ns` used to read `stats.duration_ns`, i.e. `(time_end - time_start) /
        # 1000` -- and `time_start` is the first PRINTED frame, one ntpr interval after the
        # true begin (the same trap documented at `_check_stage_pair`). That made this CSV
        # disagree with `summary.json`'s `time_ps` for the identical run: 99.5 ns here
        # against a true 100.0 ns there on the back-compat fixture, both shipped in the
        # same artifact bundle. `_elapsed_ps` is the one place `time_end -
        # mdout_header.begin_time_ps` is computed now; calling it here, rather than
        # re-deriving the number from `stats` alone, is what keeps this column and
        # `summary.json`'s total from drifting apart again -- the agreement is structural,
        # not two formulas that happen to match today.
        #
        # `None` covers four situations -- queued, minimisation, unreadable, no elapsed
        # time derivable by either the header or the frame-spacing fallback (see
        # `_elapsed_ps_and_source`'s docstring) -- that are all truthfully "unknown", not
        # zero, so the column is left blank rather than filled with a `0.0` that would
        # read as "this stage ran no time" instead of "this stage's time could not be
        # determined".
        elapsed = _elapsed_ps(stage)
        if elapsed is not None:
            row["duration_ns"] = elapsed / 1000.0
        rows.append(row)

    with open(filepath, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in columns})


PLAN_ARTIFACTS = ("summary", "methods_summary", "stats_csv")


def read_prior_summary(path: str, summary_format: str = "json") -> Any:
    """Whatever the summary artifact at `path` currently says, or `{}` if it says nothing.

    **Must be called BEFORE the artifact is rewritten.** Reading afterwards sees the file
    this very run just wrote — new totals compared against themselves — so `totals_delta`
    would return `None` forever, silently disabling the whole feature rather than reporting
    anything. That ordering trap is the reason this lives beside the writer.

    Read with the format the caller is about to WRITE this path in, not unconditionally as
    JSON: `plan` writes YAML summaries when the path ends `.yaml`/`.yml`, and `json.load`
    on a YAML document raises `JSONDecodeError` — a `ValueError` the guard below would
    swallow into "no prior claim". Read blindly as JSON that swallow would be PERMANENT:
    every future run against a YAML summary path would report nothing, not just this once.

    The guard is broad on purpose, not `(OSError, ValueError)`: `yaml.YAMLError` is neither,
    and any genuinely unreadable or malformed prior artifact — missing file, truncated
    write, a document from an unrelated tool at the same path — is "no prior claim", never a
    reason to fail a plan that is otherwise about to succeed.

    Returns whatever the file parsed to, which is deliberately NOT narrowed to a dict —
    `totals_delta` is typed `Any` for its first argument and does the `isinstance` itself.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            if summary_format == "yaml":
                import yaml as _yaml
                return _yaml.safe_load(fh)
            return json.load(fh)
    except Exception:
        return {}


def totals_delta(previous: Any, current: Dict[str, float], path: str) -> Optional[str]:
    """A line for each of `steps`/`time_ps` that moved since the summary at `path`, or
    None if nothing did (including: there was no readable prior summary).

    Lives here, beside `write_protocol_outputs`, rather than in `cli.py` where it started:
    the GUI's Plan action goes through `core_bridge.write_plan_outputs` and had no
    equivalent at all, so a user who pressed Plan in the browser had `summary.json`
    overwritten with a materially different total and was told nothing — and that is the
    user this whole feature was written for. Two copies of this logic drifting apart is the
    exact class of defect the surrounding work spent six commits removing.

    Reports the CHANGE and refuses to name its cause. Two `summary.json` artifacts carry
    totals, not a per-stage ledger, so which runs moved and why is not in evidence here —
    see the comment on the note lines below for what was claimed before and why it was
    wrong in both directions.

    Compared against a prior `summary.json`-shaped artifact rather than against the v2
    manifest, because the manifest stores no totals to compare against —
    `simulation_to_payload` emits version/simulation/phases/steps and nothing else — and
    this is not adding any; the manifest format stays exactly as it is.

    `previous` is deliberately typed `Any`, not `Dict[str, Any]`: it is whatever
    `json.load`/`yaml.safe_load` handed back from a file this function does not control
    the contents of. A prior artifact that is missing, unreadable, or parses to something
    that is not an object at all (a bare JSON string or list, emptied mid-write, a
    document from a wholly different tool at the same path) carries no claim about totals
    — `isinstance` below turns all of those into "no prior claim" rather than an
    AttributeError from calling `.get` on a non-dict, which is exactly what the naive
    `(previous or {}).get("totals")` does when `previous` is a truthy non-dict.

    `path` names the file this call actually read, not a fixed "this directory" — it is
    whatever the caller passed as its summary target, which is free to be `s.json`,
    `reports/summary.json`, or an absolute path outside the scanned tree altogether. A
    message that assumes a fixed location would point the user at a file that both isn't
    there and isn't the one that was actually compared against.
    """
    before = previous.get("totals") if isinstance(previous, dict) else None
    before = before if isinstance(before, dict) else {}
    lines = []
    for key in ("steps", "time_ps"):
        old, new = before.get(key), current.get(key)
        if isinstance(old, (int, float)) and isinstance(new, (int, float)) and old != new:
            lines.append(f"  {key:<9} {float(old):.3f} -> {float(new):.3f}")
    if not lines:
        return None
    # NOT a causal claim, and it used to be one it had not established. The line read
    # "{queued_count} queued run(s) no longer counted", built from the CURRENT ABSOLUTE
    # queued count rather than from any decomposition of the delta -- so a single run that
    # changed still got "5 queued run(s) no longer counted" attached to it (observed live),
    # and a total that ROSE because new chunks finished got the same sentence, which is a
    # non-sequitur. It is attached to the one sentence a researcher reads before quoting a
    # number, which is exactly where a plausible-sounding wrong cause does the most damage.
    #
    # Nothing here CAN decompose the delta: two `summary.json` artifacts carry totals, not
    # a per-stage ledger, so which runs moved and why is not in evidence. So the two things
    # that are honestly available are said instead -- what the numbers MEAN (which is what
    # makes "smaller than before" legible as something other than broken arithmetic), and
    # the one component both artifacts really do carry, stated as a transition rather than
    # as a cause.
    lines.append("  note      totals count what each run's mdout shows it RAN, not what "
                 "its mdin declared")
    before_queued, current_queued = before.get("queued_count"), current.get("queued_count")
    if isinstance(before_queued, (int, float)) or isinstance(current_queued, (int, float)):
        # `queued_count` is emitted only when there is at least one, so an absent key on
        # either side means zero rather than "unknown" -- but only once the OTHER side has
        # stated one, which is what this guard is for. Two artifacts that both omit it say
        # nothing about queued runs and get no line at all.
        lines.append(f"  queued    {int(before_queued or 0)} -> "
                     f"{int(current_queued or 0)} run(s) with an mdin and no mdout")
    return (f"totals changed since the last summary.json ({path}):\n"
            + "\n".join(lines))


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

    # One serialisation for both summaries: the methods summary is built from exactly the
    # dict summary.json is written from, so the two cannot disagree.
    record: Dict[str, Any] = {}

    def _record() -> Dict[str, Any]:
        if not record:
            record.update(protocol.to_dict())
        return record

    if "summary" in targets:
        _attempt("summary", lambda p: _dump(_record(), p, summary_format))
    if "methods_summary" in targets:
        # Always JSON; see `ambermeta.methods_summary`.
        from ambermeta.methods_summary import build_methods_summary, dumps_methods_summary

        def _methods(path: str) -> None:
            digest = build_methods_summary(to_plain(_record()))
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(dumps_methods_summary(digest))
        _attempt("methods_summary", _methods)
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
