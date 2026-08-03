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
    # Which run lineage (replica, branch, pose) this step belongs to. Steps sharing a tag
    # are one member; untagged means the implicit single member. It lives on the Step and
    # not on input_coords because _adopt_legacy_restart_paths and both relink_restarts
    # branches rebuild InputCoords wholesale, which would silently drop it.
    lineage: Optional[str] = None
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
    # Emitted only when known, like `gaps`: a document that records no restarts and
    # declares no lineages keeps the exact step block it had before these fields existed.
    if step.rst is not None:
        data["rst"] = step.rst
    if step.lineage is not None:
        data["lineage"] = step.lineage
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
        # An empty tag means untagged — the convention the GUI already uses to clear a step
        # slot. Kept as "", it would survive the round trip and count as a nameless member.
        # Coerced to str because `lineage: 1` is a reasonable thing to hand-write for a
        # numerically named replica, and YAML hands it back as an int: left alone it would
        # group separately from the "1" the same document might carry elsewhere, and would
        # crash the first caller that sorts or concatenates tags.
        lineage = s.get("lineage")
        lineage = None if lineage is None else (str(lineage) or None)
        step = Step(
            id=s["id"], name=s.get("name", ""), topology=s.get("topology"),
            input_coords=InputCoords(source=ic.get("source", "starting_structure"),
                                     ref=ic.get("ref"), path=ic.get("path")),
            mdin=s.get("mdin"), mdout=s.get("mdout"), mdcrd=s.get("mdcrd"),
            rst=s.get("rst"), lineage=lineage,
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
    """Each step's immediate predecessor **within its own member** (None for a head).

    Untagged steps are one member, so for a single-member document this is exactly the
    document order and the map is unchanged.

    It has to be member-scoped because it is one half of a pair. ``relink_restarts`` asks
    two questions: "was this link auto-derived?" (``ic.ref == before[step.id]``, answered
    from here) and "what should it become?" (its own member-scoped walk backwards). If
    those two disagree the pair is incoherent — and they did. ``discover`` emits
    multi-member documents phase-major, so a genuine auto-link like
    ``rep1/prod_0002 -> rep1/prod_0001`` never equalled its *document-order* predecessor,
    was misclassified as a link the user had chosen by hand, and was frozen while the head
    branch repointed around it. Reversing a phase then left both of a member's chunks
    claiming the same producer, and reversing the phase list closed a cycle
    (``min -> prod -> min``) that saved to disk and validated clean.
    """
    out: Dict[str, Optional[str]] = {}
    prev_by_member: Dict[Optional[str], Optional[str]] = {}
    for _, step in iter_steps(sim):
        member = step.lineage or None
        out[step.id] = prev_by_member.get(member)
        prev_by_member[member] = step.id
    return out


def crosses_lineage(producer: Optional[Step], consumer: Step) -> bool:
    """True when linking ``consumer`` to ``producer`` would cross a declared boundary.

    **No automatic operation may create an input_coords.ref that crosses one.** A restart
    written by replica 2 was never read by replica 1; a tool that says otherwise has
    invented the one fact this model exists to record.

    Both tags must be set for a link to count as crossing. An untagged step is the
    implicit single member and continues into, or out of, anything — one shared
    equilibration feeding N replicas is the commonest layout there is, and it is a real
    edge. Only two *different declared* tags are a boundary.

    An empty tag reads as untagged, matching ``lineages.buckets`` and the ``""``->``None``
    coercion in ``payload_to_simulation``. The rule is repeated here rather than imported
    because ``ambermeta.lineages`` imports this module.
    """
    if producer is None:
        return False
    return (bool(producer.lineage) and bool(consumer.lineage)
            and producer.lineage != consumer.lineage)


def _same_lineage(a: Step, b: Step) -> bool:
    """Whether two steps sit in the same membership bucket, untagged included."""
    return (a.lineage or None) == (b.lineage or None)


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

    "The order" means the document's order in a single-member document and each member's
    own order in a multi-member one — which is the same rule, since one member's steps are
    all of them. Both branches stop at a lineage boundary: measured on an interleaved
    reorder of two replicas the *first* branch manufactured two cross-lineage edges and
    the second none, and on a reorder that puts rep2 in front it is the second branch that
    manufactures one. Neither is safe alone.
    """
    seen: List[Step] = []
    for _, step in iter_steps(sim):
        ic = step.input_coords
        if step.id in before:
            was = before[step.id]
            prev = seen[-1] if seen else None
            # Whoever now precedes this step — but never across a lineage boundary, which
            # would assert that one member continued from another. Where the neighbour is
            # refused the step follows its own member's order instead: rep1's second chunk
            # interleaved behind rep2's first still continues rep1's first chunk, and that
            # link was true before the drag and is true after it. Only when the member has
            # nothing earlier does the step become a head and read the starting structure.
            new_prev = prev
            if crosses_lineage(prev, step):
                new_prev = next((p for p in reversed(seen) if _same_lineage(p, step)), None)
            if ic.source == "step" and ic.ref == was:
                # Auto-chained. Follow the new order, keeping any legacy resolved path so
                # a document written before `rst` existed does not lose its only record.
                step.input_coords = (
                    InputCoords(source="starting_structure") if new_prev is None
                    else InputCoords(source="step", ref=new_prev.id, path=ic.path)
                )
            elif ic.source == "starting_structure" and was is None and new_prev is not None:
                # It was the head of the chain and no longer is. Without this the demotion
                # above would be one-way: drag a step to the front and back again and the
                # link it used to have would be gone for good.
                step.input_coords = InputCoords(source="step", ref=new_prev.id)
        seen.append(step)


def repair_dangling_refs(sim: Simulation) -> List[str]:
    """Re-point steps whose ``input_coords.ref`` names a step that no longer exists.

    Deleting a step used to leave its successor pointing at a dead id, which silently
    resolved to no coordinates at all — the chain looked intact in the GUI while
    validation saw a hole. Each orphan re-chains to the nearest preceding step of its
    **own** lineage, or reads the starting structure if it has none.

    Own lineage, not simply the step before: deleting one shared equilibration that three
    replicas continued from used to splice them into a single six-step serial chain —
    exactly the false claim this model exists to remove, manufactured by the tool while
    tidying up after a delete. Falling back to the neighbour regardless of tag would also
    pick, silently, one member as the successor of another.

    Returns a warning per deleted step that more than one member continued from. No
    re-chain can replace such a step — the fan-out it was is gone, and each consumer falls
    back to its own member's order, which says something different from what the deleted
    step said — so the caller has to be able to say so. An untagged document produces no
    warnings and re-chains exactly as it always did: with one bucket, "the nearest
    preceding step of my own lineage" *is* the step before.
    """
    steps = [s for _, s in iter_steps(sim)]
    known = {s.id for s in steps}

    def orphaned(step: Step) -> bool:
        ic = step.input_coords
        return ic.source == "step" and (not ic.ref or ic.ref not in known)

    # Collected before anything is re-pointed: once an orphan is re-chained its dead ref
    # is gone and there is no way back to how many members shared the deleted producer.
    by_dead_ref: Dict[str, List[Step]] = {}
    for step in steps:
        if orphaned(step) and step.input_coords.ref:
            by_dead_ref.setdefault(step.input_coords.ref, []).append(step)

    seen: List[Step] = []
    for step in steps:
        if orphaned(step):
            parent = next((p for p in reversed(seen) if _same_lineage(p, step)), None)
            step.input_coords = (
                InputCoords(source="starting_structure") if parent is None
                else InputCoords(source="step", ref=parent.id, path=step.input_coords.path)
            )
        seen.append(step)

    notes: List[str] = []
    for consumers in by_dead_ref.values():
        tags = []
        for c in consumers:
            tag = c.lineage or "untagged"
            if tag not in tags:
                tags.append(tag)
        if len(tags) < 2:
            continue
        # Not "they are now heads": a consumer with an earlier run of its own lineage
        # re-chains to that one and is no such thing. The two outcomes are named because
        # which of them happened is exactly what the user has to go and check.
        notes.append(
            "A deleted step was the input of {n} runs in different lineages ({tags}). "
            "Each now continues from the nearest earlier run of its own lineage, or reads "
            "the starting structure where its lineage has none: re-chaining any of them "
            "to another would claim a continuation that never ran.".format(
                n=len(consumers), tags=", ".join(tags))
        )
    return notes
