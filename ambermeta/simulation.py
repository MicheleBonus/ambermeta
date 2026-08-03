# ambermeta/simulation.py
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ambermeta.errors import AmberMetaError
from ambermeta.manifest import _read_raw_manifest

try:  # optional dependency, mirrors manifest.py
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


@dataclass
class Topology:
    id: str
    path: str
    kind: str = "normal"          # "normal" | "hmr"


@dataclass
class InputCoords:
    source: str = "starting_structure"   # "starting_structure" | "step" | "path"
    ref: Optional[str] = None             # Step.id when source == "step"
    path: Optional[str] = None            # explicit path when source == "path"


@dataclass
class Step:
    id: str
    name: str
    topology: Optional[str] = None        # Topology.id
    input_coords: InputCoords = field(default_factory=InputCoords)
    mdin: Optional[str] = None
    mdout: Optional[str] = None
    mdcrd: Optional[str] = None
    # The restart this run WRITES (-r restrt). It is stored on the step that produces it,
    # not on the step that reads it: a chained step's input_coords is `source="step"` and
    # resolves through here, so the file is recorded once and the two steps stay linked
    # even if either is renamed, reordered, or moved to another phase.
    rst: Optional[str] = None
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class Phase:
    id: str
    name: str
    role: str = ""
    steps: List[Step] = field(default_factory=list)


@dataclass
class Simulation:
    version: int = 2
    topologies: List[Topology] = field(default_factory=list)
    starting_structure: Optional[str] = None
    phases: List[Phase] = field(default_factory=list)


def _step_payload(step: Step, phase_id: str, order: int) -> Dict[str, Any]:
    ic: Dict[str, Any] = {"source": step.input_coords.source}
    if step.input_coords.ref is not None:
        ic["ref"] = step.input_coords.ref
    if step.input_coords.path is not None:
        ic["path"] = step.input_coords.path
    data: Dict[str, Any] = {
        "id": step.id, "name": step.name, "phase": phase_id, "order": order,
        "topology": step.topology, "input_coords": ic,
        "mdin": step.mdin, "mdout": step.mdout, "mdcrd": step.mdcrd,
        "notes": list(step.notes),
    }
    # Emitted only when known, like `gaps`: a document that records no restarts keeps the
    # exact step block it had before this field existed.
    if step.rst is not None:
        data["rst"] = step.rst
    if step.expected_gap_ps is not None or step.gap_tolerance_ps is not None:
        data["gaps"] = {"expected": step.expected_gap_ps, "tolerance": step.gap_tolerance_ps}
    return data


def simulation_to_payload(sim: Simulation) -> Dict[str, Any]:
    return {
        "version": sim.version,
        "simulation": {
            "topologies": [{"id": t.id, "path": t.path, "kind": t.kind} for t in sim.topologies],
            "starting_structure": sim.starting_structure,
        },
        "phases": [
            {"id": p.id, "name": p.name, "role": p.role, "order": i}
            for i, p in enumerate(sim.phases)
        ],
        "steps": [
            _step_payload(s, p.id, j)
            for p in sim.phases for j, s in enumerate(p.steps)
        ],
    }


def payload_to_simulation(payload: Dict[str, Any]) -> Simulation:
    sim = Simulation(version=payload.get("version", 2))
    block = payload.get("simulation", {}) or {}
    for t in block.get("topologies", []) or []:
        sim.topologies.append(Topology(id=t["id"], path=t["path"], kind=t.get("kind", "normal")))
    sim.starting_structure = block.get("starting_structure")

    phases_by_id: Dict[str, Phase] = {}
    for p in sorted(payload.get("phases", []) or [], key=lambda x: x.get("order", 0)):
        phase = Phase(id=p["id"], name=p.get("name", ""), role=p.get("role", ""))
        sim.phases.append(phase)
        phases_by_id[p["id"]] = phase

    for s in sorted(payload.get("steps", []) or [], key=lambda x: (x.get("phase", ""), x.get("order", 0))):
        ic = s.get("input_coords", {}) or {}
        gaps = s.get("gaps", {}) or {}
        step = Step(
            id=s["id"], name=s.get("name", ""), topology=s.get("topology"),
            input_coords=InputCoords(source=ic.get("source", "starting_structure"),
                                     ref=ic.get("ref"), path=ic.get("path")),
            mdin=s.get("mdin"), mdout=s.get("mdout"), mdcrd=s.get("mdcrd"),
            rst=s.get("rst"),
            expected_gap_ps=gaps.get("expected"), gap_tolerance_ps=gaps.get("tolerance"),
            notes=list(s.get("notes", []) or []),
        )
        phase = phases_by_id.get(s.get("phase"))
        if phase is not None:
            phase.steps.append(step)
    _adopt_legacy_restart_paths(sim)
    return sim


def _adopt_legacy_restart_paths(sim: Simulation) -> None:
    """Move a chained step's cached coordinate path onto the step that wrote it.

    Manifests written before ``Step.rst`` existed stored the resolved restart on the
    *consuming* step, as ``input_coords.path`` beside the ``ref``. Reading that as a
    fallback is enough to open such a document, but it leaves the filename living on the
    wrong step, where any edit that rewrites the link would drop it. Normalising once at
    load puts it where it belongs and makes the fallback matter only for refs that cannot
    be resolved at all.
    """
    by_id = {s.id: s for _, s in iter_steps(sim)}
    for _, step in iter_steps(sim):
        ic = step.input_coords
        if ic.source != "step" or not ic.ref or not ic.path:
            continue
        producer = by_id.get(ic.ref)
        if producer is None or producer is step:
            continue
        if producer.rst is None:
            producer.rst = ic.path
        if producer.rst == ic.path:
            step.input_coords = InputCoords(source="step", ref=ic.ref)


def write_simulation(sim: Simulation, path: str, fmt: str) -> None:
    """Write a Simulation as a v2 manifest. JSON and YAML are the only manifest
    formats AmberMeta writes, and both are lossless."""
    payload = simulation_to_payload(sim)
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
    raise ValueError(f"v2 write supports json/yaml only, got: {fmt}")


def load_simulation(path: str, expand_env: bool = True) -> Simulation:
    """Load a Simulation from a v2 manifest file."""
    raw = _read_raw_manifest(path, expand_env=expand_env)
    if not isinstance(raw, dict) or "steps" not in raw:
        # A document that announces itself as v2, or carries a v2-only key, is a v2
        # manifest with a hole in it rather than a foreign format — say which key is
        # missing. Sending its owner off to rebuild from the directory would silently
        # discard the phases and topology pool the file still has.
        if isinstance(raw, dict) and (raw.get("version") == 2
                                      or "simulation" in raw or "phases" in raw):
            raise AmberMetaError(
                f"{path} is a v2 manifest but is missing its 'steps' list. "
                "Restore the steps, or rebuild the file with "
                "`ambermeta discover <dir> --write <path>`."
            )
        raise AmberMetaError(
            f"{path} is not a v2 manifest (no 'steps' key). "
            "Rebuild it with `ambermeta discover <dir> --write <path>`."
        )
    return payload_to_simulation(raw)


# ---------------------------------------------------------------------------
# Restart chain
# ---------------------------------------------------------------------------

def iter_steps(sim: Simulation):
    """Every step in document order, paired with its owning phase."""
    for phase in sim.phases:
        for step in phase.steps:
            yield phase, step


def resolve_input_coords(sim: Simulation, step: Step) -> Optional[str]:
    """The coordinate file ``step`` actually reads, or None if it cannot be resolved.

    A chained step resolves through the restart recorded on the step it continues from.
    ``input_coords.path`` stays honoured as an explicit override and as the fallback for
    documents written before restarts moved to the producing step.
    """
    ic = step.input_coords
    if ic.source == "starting_structure":
        return sim.starting_structure
    if ic.source == "path":
        return ic.path
    if ic.source == "step":
        if ic.ref:
            for _, other in iter_steps(sim):
                if other.id == ic.ref and other.rst:
                    return other.rst
        return ic.path
    return None


def predecessors(sim: Simulation) -> Dict[str, Optional[str]]:
    """Each step's immediate predecessor in document order (None for the first)."""
    out: Dict[str, Optional[str]] = {}
    prev: Optional[str] = None
    for _, step in iter_steps(sim):
        out[step.id] = prev
        prev = step.id
    return out


def relink_restarts(sim: Simulation, before: Dict[str, Optional[str]]) -> None:
    """Follow the order with the links the tool itself derived, and only those.

    ``before`` is the predecessor map from *before* the reorder. It is what separates a
    link this tool inferred from one the user chose, which is otherwise indistinguishable
    — both are ``source="step"``:

    * a step that continued from its immediate predecessor was auto-chained, so it now
      continues from whatever precedes it (or reads the starting structure if it has
      become the first step);
    * a step that was the first and read the starting structure was the head of the chain,
      so if it stops being first it chains onto its new predecessor;
    * everything else is a deliberate choice — an explicit path, a mid-run starting
      structure, or a "continues from" pointing at some step other than the neighbour —
      and is left exactly as it is.

    Steps absent from ``before`` are new and keep whatever they were created with.
    """
    prev_id: Optional[str] = None
    for _, step in iter_steps(sim):
        ic = step.input_coords
        if step.id in before:
            was = before[step.id]
            if ic.source == "step" and ic.ref == was:
                # Auto-chained. Follow the new order, keeping any legacy resolved path so
                # a document written before `rst` existed does not lose its only record.
                step.input_coords = (
                    InputCoords(source="starting_structure") if prev_id is None
                    else InputCoords(source="step", ref=prev_id, path=ic.path)
                )
            elif ic.source == "starting_structure" and was is None and prev_id is not None:
                # It was the head of the chain and no longer is. Without this the demotion
                # above would be one-way: drag a step to the front and back again and the
                # link it used to have would be gone for good.
                step.input_coords = InputCoords(source="step", ref=prev_id)
        prev_id = step.id


def repair_dangling_refs(sim: Simulation) -> None:
    """Re-point steps whose ``input_coords.ref`` names a step that no longer exists.

    Deleting a step used to leave its successor pointing at a dead id, which silently
    resolved to no coordinates at all — the chain looked intact in the GUI while
    validation saw a hole. Each orphan re-chains to whatever now precedes it.
    """
    known = {s.id for _, s in iter_steps(sim)}
    prev_id: Optional[str] = None
    for _, step in iter_steps(sim):
        ic = step.input_coords
        if ic.source == "step" and (not ic.ref or ic.ref not in known):
            if prev_id is None:
                step.input_coords = InputCoords(source="starting_structure")
            else:
                step.input_coords = InputCoords(source="step", ref=prev_id, path=ic.path)
        prev_id = step.id
