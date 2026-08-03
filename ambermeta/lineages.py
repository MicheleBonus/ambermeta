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
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Protocol, TypeVar

from ambermeta.simulation import Simulation, Step, iter_steps

# The repo's one spelling of "a numbered run's base name": `protocol.detect_sequence_gaps`
# and the canvas's `numericBase` both strip exactly this. Kept identical on purpose — the
# membership predicate below and the sequence-gap detector must agree on what counts as
# the same run in two different directories, or a replica family passes one and fails the
# other.
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
