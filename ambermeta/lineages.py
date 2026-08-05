# ambermeta/lineages.py
"""Which steps belong to which member of a set of related runs.

A lineage is one member of an experiment — a replica, a branch off a shared restart, a
pose. The tag itself is just ``Step.lineage``; this module is the single place that
decides what a set of tags *means*, so the CLI, the GUI and the analysis engine read
membership from here instead of each growing its own grouping rule.

Deliberately outside ``gui/api/``, and it imports no FastAPI: ``ambermeta discover``
performs the layout inference below and must keep working without the GUI extra
installed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Protocol, TypeVar

from ambermeta.simulation import Simulation, Step, iter_steps

# The repo's one spelling of "a numbered run's base name": `protocol.detect_sequence_gaps`
# and the canvas's `numericBase` both strip exactly this. Kept identical on purpose — the
# membership predicate below and the sequence-gap detector must agree on what counts as
# the same run in two different directories, or a replica family passes one and fails the
# other.
#
# The regex was always identical; what was not was what reached it. This module applies it
# to the raw run name, while both detectors first ran it through `Path().stem`, which ate a
# dot-numbered index — so `prod.0001` was one member's chunk one here and an unnumbered run
# there, and the agreement this comment claimed was false for exactly the spelling nobody
# had a fixture for. `protocol._numbered_stem` is now the shared answer to "which part of
# the name does the regex see", and it keeps a purely numeric final suffix.
_NUMBERED = re.compile(r"^(.+?)[-_.]?(\d+)$")


def _run_base(run: str) -> str:
    """`prod_0001` -> `prod`; a name with no trailing index is its own base."""
    match = _NUMBERED.match(run)
    if not match or match.group(1).isdigit():
        return run
    return match.group(1)


class _Untagged:
    """The single bucket every untagged step shares.

    An object rather than a string so it cannot collide with a tag a user typed: a
    sentinel spelled ``""``, ``"untagged"`` or ``None`` is either a legal tag already or
    unusable as a mapping key, and the one thing this key must never do is quietly merge
    with a declared lineage.
    """

    __slots__ = ()

    def __repr__(self) -> str:          # pragma: no cover - debugging aid only
        return "<untagged>"


UNTAGGED = _Untagged()


class _Tagged(Protocol):
    """Anything carrying the tag.

    Two classes do: ``Step`` in the document and ``SimulationStage`` in the analysis
    engine, which is handed the tag rather than re-deriving it. Bucketing is the same
    question for both, and stating it structurally keeps it one implementation.
    """

    lineage: Optional[str]


_T = TypeVar("_T", bound=_Tagged)


def buckets(steps: Iterable[_T]) -> Dict[Any, List[_T]]:
    """Group any run of tagged objects into membership buckets, in first-appearance order.

    Takes a plain iterable rather than a ``Simulation`` because membership is asked about
    a *part* of a document as often as the whole: whether one phase holds several members
    decides whether a step appended to it may be chained to its neighbour, and the
    continuity engine asks it of a flat stage list that never was a document.
    """
    out: Dict[Any, List[_T]] = {}
    for step in steps:
        # An empty tag is untagged. payload_to_simulation coerces "" on ingest, but an
        # in-memory edit reaches the model without passing through it, and a nameless
        # member is worse than no member — it counts, and it cannot be named.
        out.setdefault(step.lineage if step.lineage else UNTAGGED, []).append(step)
    return out


def members(sim: Simulation) -> Dict[Any, List[Step]]:
    """Every membership bucket in the document, keyed in first-appearance order.

    Untagged steps share **one** bucket, keyed by :data:`UNTAGGED` — not one bucket each.
    That is what makes a half-tagged document two members rather than one plus however
    many steps nobody got round to labelling.

    The sentinel key is the reason this returns ``Dict[Any, ...]`` and :func:`lineages`
    does not: a caller that wants only what the user declared wants the other function.
    """
    return buckets(step for _, step in iter_steps(sim))


def lineages(sim: Simulation) -> Dict[str, List[Step]]:
    """The declared lineages only, keyed by tag in first-appearance order.

    The untagged bucket is **not** one of them. It forms its own continuity partition and
    it counts toward :func:`is_multi_lineage`, but it is not something the user declared,
    so it is neither named here nor counted in ``lineage_count``. Counting it reported
    four members for the canonical three-replica campaign — the same miscount the
    membership predicate in :func:`infer_lineages_from_layout` exists to prevent.
    """
    return {tag: steps for tag, steps in members(sim).items() if tag is not UNTAGGED}


def is_multi_lineage(sim: Simulation) -> bool:
    """True when the document holds more than one member, sentinel included.

    One declared tag plus untagged steps is **two** members and is multi-lineage. The
    alternative — counting only declared tags — makes a half-tagged document silently
    single-lineage, which is the worst of both behaviours: the user has declared structure
    and the tool ignores it.
    """
    return len(members(sim)) >= 2


# ---------------------------------------------------------------------------
# Coherence: what the declared members do and do not agree on
# ---------------------------------------------------------------------------

#: The mdin `&cntrl` keys compared across members, in the order they are reported.
#: Read from ``cntrl_parameters`` — the raw echo of what the user wrote — and never from
#: the normalized fields beside it. ``MdinMetadata.target_temp`` defaults to 300.0 when the
#: mdin omits ``temp0``, so comparing that field manufactures agreement between two runs
#: neither of which stated a temperature.
COMPARED_PARAMETERS = ("dt", "temp0", "cut", "ntt", "ntp")


@dataclass(frozen=True)
class Finding:
    """One thing the members do or do not agree about.

    ``severity`` is ``error`` only for a category error — a difference that means the
    members are not runs of the same thing at all (decision 5). Everything else is a
    ``warning`` the user may well have intended, escalated by ``--strict``, or an ``info``
    that states a graph fact without judging it.
    """

    severity: str          # error | warning | info
    kind: str              # atom_count | run_type | parameter | seed | fan_out
    message: str


def _parameters_of(stage: Any) -> Dict[str, Any]:
    """One stage's raw `&cntrl` echo, or `{}` when it has no readable mdin.

    A document of mdouts with no mdins is a legitimate `discover` result — a run group
    needs an mdin *or* an mdout — and for those none of these values exists. Inferring
    ``ntt`` back out of the mdout's thermostat name would be a different fact wearing this
    one's label, so such a stage simply contributes nothing.
    """
    details = getattr(getattr(stage, "mdin", None), "details", None)
    return dict(getattr(details, "cntrl_parameters", None) or {})


def _atom_count_of(stage: Any) -> Optional[int]:
    details = getattr(getattr(stage, "mdout", None), "details", None)
    count = getattr(details, "natoms", None)
    return int(count) if isinstance(count, int) and count > 0 else None


def varying_axis(stages: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    """Per compared parameter, the value each declared member holds — when they differ.

    A parameter every member states identically is not an axis and is left out, so the
    result reads as "this is what distinguishes the members" rather than as a dump. A
    parameter some member does not state is left out too: unstated is not a value, and an
    axis built from an absence is an axis the user never varied.

    Takes stages rather than a ``Simulation`` because the values do not exist on a
    ``Step``. ``temp0``/``cut``/``ntt``/``ntp``/``dt`` live in the parsed mdin, which only
    exists after the analysis engine has read the files; the document holds paths.
    """
    members = {tag: group for tag, group in buckets(stages).items() if tag is not UNTAGGED}
    axis: Dict[str, Dict[str, Any]] = {}
    for key in COMPARED_PARAMETERS:
        held: Dict[str, Any] = {}
        for tag, group in members.items():
            values = {p[key] for p in map(_parameters_of, group) if key in p}
            # A member that disagrees with itself has no single value to compare, and
            # saying so is a different finding from saying two members disagree.
            if len(values) == 1:
                held[tag] = values.pop()
        if len(held) == len(members) and len(set(map(repr, held.values()))) > 1:
            axis[key] = held
    return axis


def coherence(stages: Iterable[Any]) -> List[Finding]:
    """What the declared members agree and disagree about.

    Emits graph facts, never statistical ones (decision 4): "3 steps read the restart
    written by st_7 and carry 3 distinct resolved seeds" is a statement about files, and
    whether that makes them independent samples is not a question any file inspection can
    answer.

    Silent for a document with fewer than two declared members — there is nothing to
    compare — which is every untagged document.
    """
    stages = list(stages)
    members = {tag: group for tag, group in buckets(stages).items() if tag is not UNTAGGED}
    out: List[Finding] = []
    if len(members) < 2:
        return out

    # --- category errors: the members are not runs of the same thing ------------
    counts = {tag: {c for c in map(_atom_count_of, group) if c is not None}
              for tag, group in members.items()}
    stated = {tag: values for tag, values in counts.items() if len(values) == 1}
    if len({next(iter(v)) for v in stated.values()}) > 1:
        spelled = "; ".join(f"{tag}: {next(iter(stated[tag]))}"
                            for tag in sorted(stated))
        out.append(Finding("error", "atom_count",
                           f"Members do not hold the same number of atoms ({spelled})."))

    dynamics = {tag: any(p.get("imin") in (0, None) for p in map(_parameters_of, group)
                         if p)
                for tag, group in members.items()}
    if len(set(dynamics.values())) > 1:
        minimisation_only = sorted(tag for tag, has in dynamics.items() if not has)
        out.append(Finding(
            "error", "run_type",
            "Members mix minimisation with dynamics ("
            + ", ".join(minimisation_only) + " ran no dynamics)."))

    # --- differences the user may well have meant --------------------------------
    for key, held in varying_axis(stages).items():
        spelled = "; ".join(f"{tag}: {held[tag]}" for tag in sorted(held))
        out.append(Finding("warning", "parameter",
                           f"Members differ in {key} ({spelled})."))

    # --- seeds, and the branch point they hang off -------------------------------
    out.extend(_seed_findings(stages, members))
    return out


def _seed_findings(stages: List[Any], members: Dict[str, List[Any]]) -> List[Finding]:
    """What the resolved seeds say, per shared producer.

    Scoped to a branch point rather than to the whole document because that is the shape
    of the claim worth making: N runs that read one restart start from identical
    coordinates *and* identical velocities, so the seed is the only thing that separates
    them. Two runs that share no producer have no such relationship and repeating a seed
    between them says nothing.

    A seed is read only where the mdout stated one. Absent is unknown — never "the same".
    """
    out: List[Finding] = []
    tag_of = {id(s): tag for tag, group in members.items() for s in group}
    by_producer: Dict[Any, List[Any]] = {}
    for stage in stages:
        parent = getattr(stage, "parent_id", None)
        if parent and id(stage) in tag_of:
            by_producer.setdefault(parent, []).append(stage)

    names = {getattr(s, "step_id", None): getattr(s, "name", "?") for s in stages}
    for parent, consumers in by_producer.items():
        if len({tag_of[id(s)] for s in consumers}) < 2:
            continue
        seeds = [s.mdout_header.resolved_ig for s in consumers
                 if getattr(s, "mdout_header", None) is not None
                 and s.mdout_header.resolved_ig is not None]
        producer = names.get(parent, parent)
        if len(seeds) < len(consumers):
            out.append(Finding(
                "info", "fan_out",
                f"{len(consumers)} steps read the restart written by {producer}; "
                f"{len(consumers) - len(seeds)} of them state no resolved seed."))
            continue
        distinct = len(set(seeds))
        if distinct == len(seeds):
            out.append(Finding(
                "info", "fan_out",
                f"{len(consumers)} steps read the restart written by {producer} "
                f"and carry {distinct} distinct resolved seeds."))
        else:
            out.append(Finding(
                "warning", "seed",
                f"{len(consumers)} steps read the restart written by {producer} "
                f"but carry only {distinct} distinct resolved seed(s)."))
    return out


def infer_lineages_from_layout(run_names: Iterable[str]) -> Dict[str, str]:
    """Tag runs by the directory segment that distinguishes them, or tag nothing.

    ``run_names`` are the path-prefixed posix stems ``smart_group_files`` builds
    (``rep1/prod_0001``), so the layout is already carried in the name and no second walk
    of the tree is needed. Pass only *run* groups — one holding an mdin or an mdout. A
    topology-only group would contribute a phantom run name and break the predicate below.

    Returns ``{run_name: tag}`` holding only the runs that could be tagged, so a caller
    reads an untagged run as ``.get(name)`` -> ``None``, matching ``Step.lineage``.

    The rule, and everything it refuses:

    * runs at the tree root carry no segment to be tagged by, and one directory has
      nothing to differ from — either way, nothing is tagged;
    * **the membership predicate**: only directories running the same set of *run bases*
      are members of one another. ``common/{min,heat,equil}`` beside ``rep1..3/prod_*``
      matches nothing and stays untagged. Without this, the canonical campaign reports
      four members for three and hands ``lineage_count`` the prep runs as a replica.

      Bases, not whole run names, because **a replica that died early is the single most
      important thing this feature has to catch**. ``rep1/prod_0001..0003`` beside
      ``rep2/prod_0001`` is one crashed member, not two unrelated directories; keying the
      predicate on exact run-name sets refuses to tag it, and a refusal here silently
      disables the very sequence-hole finding that would have reported the crash;
    * two rival families that each pass the predicate are two experiments in one
      manifest, which this model does not represent. Neither is tagged;
    * the tag must be **one** segment: a nested sweep (``300K/rep1``, ``310K/rep2``)
      varies in two places at once and there is no way to tell which one names the member.

    Ambiguity resolves to untagged, never to a guess — an inference reported as
    ``[applied]`` is a claim, and a wrong claim here is exactly what this feature exists
    to stop.

    Only directory segments are read. A replica named inside the *filename*
    (``rep1_prod_0001.mdout`` in a flat tree) is left untagged: splitting a stem into
    tokens has no non-arbitrary rule, and the obvious one tags a plain chunked chain
    ``prod_0001``/``prod_0002`` as two members, which would break every untagged document
    in the process of helping a few.
    """
    by_dir: Dict[str, List[str]] = {}
    for name in run_names:
        directory, _, run = name.rpartition("/")
        by_dir.setdefault(directory, []).append(run)

    candidates = {d: runs for d, runs in by_dir.items() if d}
    if len(candidates) < 2:
        return {}

    cohorts: Dict[FrozenSet[str], List[str]] = {}
    for directory, runs in candidates.items():
        cohorts.setdefault(frozenset(_run_base(r) for r in runs), []).append(directory)
    matched = [dirs for dirs in cohorts.values() if len(dirs) > 1]
    if len(matched) != 1:
        return {}
    family = matched[0]

    segments = {d: d.split("/") for d in family}
    depths = {len(s) for s in segments.values()}
    if len(depths) != 1:
        return {}
    varying = [i for i in range(depths.pop())
               if len({segments[d][i] for d in family}) > 1]
    if len(varying) != 1:
        return {}
    index = varying[0]

    return {f"{d}/{run}": segments[d][index] for d in family for run in candidates[d]}
