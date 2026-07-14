# ambermeta/simulation.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
from typing import Any, Dict   # add to the existing typing import at the top


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
            expected_gap_ps=gaps.get("expected"), gap_tolerance_ps=gaps.get("tolerance"),
            notes=list(s.get("notes", []) or []),
        )
        phase = phases_by_id.get(s.get("phase"))
        if phase is not None:
            phase.steps.append(step)
    return sim


import json

from ambermeta.manifest import _read_raw_manifest, _normalize_container

try:  # optional dependency, mirrors manifest.py
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def _is_v2(raw: Any) -> bool:
    return isinstance(raw, dict) and (raw.get("version") == 2 or "phases" in raw or "simulation" in raw)


def write_simulation(sim: Simulation, path: str, fmt: str) -> None:
    """Write a Simulation as a v2 manifest. JSON and YAML are lossless; TOML/CSV
    flat export is deferred (documented lossy view, a later task)."""
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


def load_simulation(path: str) -> Simulation:
    """Load a Simulation from a manifest file, auto-migrating v1 manifests."""
    raw = _read_raw_manifest(path)
    if _is_v2(raw):
        return payload_to_simulation(raw)
    return migrate_v1_manifest(_normalize_container(raw))


from ambermeta.manifest import _normalize_manifest
from ambermeta.roles import classify_role


def _v1_globals(container: Any) -> Dict[str, Any]:
    return container if isinstance(container, dict) and "stages" in container else {}


def migrate_v1_manifest(container: Any) -> Simulation:
    """Convert a v1 manifest container (flat stages) into a v2 Simulation.

    - global_prmtop -> normal pool entry; hmr_prmtop -> hmr pool entry.
    - initial_coordinates -> starting_structure.
    - each stage -> a Step; contiguous same-role stages -> one Phase.
    - first step reads the starting structure; each later step chains from the
      previous step's restart (the explicit input-coords source).
    """
    globals_ = _v1_globals(container)
    sim = Simulation()

    topo_by_path: Dict[str, str] = {}

    def _topref(path: Optional[str], kind: str) -> Optional[str]:
        if not path:
            return None
        if path not in topo_by_path:
            tid = f"top_{len(sim.topologies)}"
            sim.topologies.append(Topology(id=tid, path=path, kind=kind))
            topo_by_path[path] = tid
        return topo_by_path[path]

    global_prmtop = globals_.get("global_prmtop")
    hmr_prmtop = globals_.get("hmr_prmtop")
    _topref(global_prmtop, "normal")
    _topref(hmr_prmtop, "hmr")
    sim.starting_structure = globals_.get("initial_coordinates")

    prev_step_id: Optional[str] = None
    for idx, entry in enumerate(_normalize_manifest(container)):
        name = entry.get("name") or f"step_{idx}"
        role = entry.get("stage_role") or classify_role(name) or ""
        files = entry.get("files", {}) if isinstance(entry.get("files"), dict) else {}

        def _f(kind: str) -> Optional[str]:
            return entry.get(kind) or files.get(kind)

        stage_prmtop = _f("prmtop")
        if stage_prmtop:
            topology = _topref(stage_prmtop, "normal")
        else:
            topology = topo_by_path.get(global_prmtop) if global_prmtop else None

        if prev_step_id is None:
            if sim.starting_structure:
                ic = InputCoords(source="starting_structure")
            elif _f("inpcrd"):
                ic = InputCoords(source="path", path=_f("inpcrd"))
            else:
                ic = InputCoords(source="starting_structure")
        else:
            ic = InputCoords(source="step", ref=prev_step_id)

        gaps = entry.get("gaps") or {}
        step = Step(
            id=f"st_{idx}", name=name, topology=topology, input_coords=ic,
            mdin=_f("mdin"), mdout=_f("mdout"), mdcrd=_f("mdcrd"),
            expected_gap_ps=gaps.get("expected"), gap_tolerance_ps=gaps.get("tolerance"),
            notes=list(entry.get("notes") or []),
        )

        if not sim.phases or sim.phases[-1].role != role:
            sim.phases.append(Phase(id=f"ph_{len(sim.phases)}",
                                    name=(role.title() if role else "Stage"), role=role))
        sim.phases[-1].steps.append(step)
        prev_step_id = step.id

    return sim
