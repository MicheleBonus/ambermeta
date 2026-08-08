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
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Protocol, Tuple, TypeVar

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
            values = {_comparable(p[key]) for p in map(_parameters_of, group) if key in p}
            # A member that disagrees with itself has no single value to compare, and
            # saying so is a different finding from saying two members disagree.
            if len(values) == 1:
                held[tag] = values.pop()
        if len(held) == len(members) and len(set(held.values())) > 1:
            axis[key] = held
    return axis


def _comparable(value: Any) -> Any:
    """A value in a form two members can be compared on.

    Numbers are compared as numbers. `cntrl_parameters` is a raw echo of what the user
    wrote, so one member's `temp0 = 300` and another's `temp0 = 300.0` arrive as an int and
    a float — the same temperature, typed two ways. Comparing their reprs reported them as
    an axis the experiment varies, and under ``--strict`` failed the run over a decimal
    point. `bool` is excluded because `True == 1` and `ntt = 1` is not `ntt = true`.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return float(value)


def coherence(stages: Iterable[Any]) -> List[Finding]:
    """What the declared members agree and disagree about.

    Emits graph facts, never statistical ones (decision 4): "3 steps read the restart
    written by st_7 and carry 3 distinct resolved seeds" is a statement about files, and
    whether that makes them independent samples is not a question any file inspection can
    answer.

    Silent for a document with fewer than two declared members — there is nothing to
    compare — which is every untagged document. That gate applies to the within-member
    atom-count check below as well, deliberately: a lone declared member is not a claim
    that anything matches anything, and this function's contract is comparison between
    members.
    """
    stages = list(stages)
    members = {tag: group for tag, group in buckets(stages).items() if tag is not UNTAGGED}
    out: List[Finding] = []
    if len(members) < 2:
        return out

    # --- category errors: the members are not runs of the same thing ------------
    counts = {tag: {c for c in map(_atom_count_of, group) if c is not None}
              for tag, group in members.items()}

    # WITHIN a member, first. A member holding runs of two different systems is not a set of
    # runs of one system, which is the same claim the cross-member check below makes, one
    # level down -- so it carries the same `error` severity and the same `atom_count` kind.
    #
    # This exists because the cross-member check SILENTLY DISABLES ITSELF on exactly the
    # shape that needs it most. `stated` below admits only tags holding ONE distinct count,
    # which is right for that comparison (a member that disagrees with itself has no single
    # value to compare) but means such a member drops out of the comparison entirely rather
    # than being reported. Measured on two independent campaigns that share member labels --
    # `apo/01..03` beside `holo/01..03`, which the layout inference merges into three
    # members each holding one apo run and one holo run:
    #
    #     CORRECT grouping (apo | holo):  error atom_count -- Members do not hold the same
    #                                     number of atoms (apo: 50000; holo: 50800).
    #     MERGED grouping:                (nothing at all)
    #
    # The merge itself is an accepted limitation of cohort reconciliation (it belongs to the
    # P4 decision the spec deferred). Its SILENCE was not accepted: the one check that would
    # have caught the mis-grouping was the one the mis-grouping turned off. Because this
    # fires on a DECLARED member it reaches the CLI's `[applied]` path too, so a user who
    # discovers such a tree gets the tags AND an error saying the tags are wrong.
    #
    # Reported before the cross-member finding because it is the more fundamental one: a
    # member that disagrees with itself makes its own contribution to that comparison
    # meaningless. Neither masks the other -- both are appended, and a tree with one mixed
    # member beside two consistent members that differ raises both findings.
    mixed = {tag: values for tag, values in counts.items() if len(values) > 1}
    if mixed:
        spelled = "; ".join(
            f"{tag}: {', '.join(str(c) for c in sorted(mixed[tag]))}"
            for tag in sorted(mixed))
        out.append(Finding(
            "error", "atom_count",
            f"Runs within one member hold different numbers of atoms ({spelled}). "
            "These are not runs of one system, so the grouping is wrong."))

    stated = {tag: values for tag, values in counts.items() if len(values) == 1}
    if len({next(iter(v)) for v in stated.values()}) > 1:
        spelled = "; ".join(f"{tag}: {next(iter(stated[tag]))}"
                            for tag in sorted(stated))
        out.append(Finding("error", "atom_count",
                           f"Members do not hold the same number of atoms ({spelled})."))

    # Only members that STATED what they ran take part. A member whose mdins are missing or
    # unreadable has said nothing, and reading that silence as "ran no dynamics" turns an
    # absence into a fatal claim — which on `plan` would also break the fault tolerance
    # Spec 1 exists for, since a skipped file is supposed to cost a note and exit 0.
    # `imin` absent from a stated mdin is AMBER's own default of 0, i.e. dynamics.
    dynamics: Dict[str, bool] = {}
    for tag, group in members.items():
        stated = [p for p in map(_parameters_of, group) if p]
        if stated:
            dynamics[tag] = any(p.get("imin", 0) == 0 for p in stated)
    if len(dynamics) > 1 and len(set(dynamics.values())) > 1:
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
      are grouped into a cohort together. ``common/{min,heat,equil}`` beside
      ``rep1..3/prod_*`` matches nothing and stays untagged. Without this, the canonical
      campaign reports four members for three and hands ``lineage_count`` the prep runs
      as a replica.

      Bases, not whole run names, because **a replica that died early is the single most
      important thing this feature has to catch**. ``rep1/prod_0001..0003`` beside
      ``rep2/prod_0001`` is one crashed member, not two unrelated directories; keying the
      predicate on exact run-name sets refuses to tag it, and a refusal here silently
      disables the very sequence-hole finding that would have reported the crash.

      Cohorts are keyed on ``(bases, depth)``, not bases alone, for exactly the same
      reason: a stray directory whose runs happen to share an entire OTHER cohort's base
      set — ``rerun/deep/here/prod_0001`` beside ``prod/01..03``'s ``prod_0001``, both base
      ``{prod}`` — used to fall into that cohort rather than one of its own, and its
      mismatched depth silently dropped the whole cohort, replicas included: ``equil``
      tagged, every ``prod`` run gone, reported as success. Folding depth into the key means
      a directory can never merge into a cohort it does not belong to in the first place;
    * two rival families whose tag sets are **disjoint** are two experiments in one
      manifest, which this model does not represent. Neither is tagged. Sets that
      **nest**, though, are one campaign with a short member: ``equil/01..05`` beside
      ``prod/02..05`` is a replica that never reached production, and refusing it would
      disable the very finding that reports the crash. The reconciled tag set is the
      largest; every cohort's set must be a subset of it;
    * cohorts each report their **own** varying segment and must agree on the segment
      **index**. A cohort that cannot name one segment contributes nothing rather than
      refusing the whole tree, so a prep directory at another depth cannot veto the
      replicas;
    * contributing cohorts must run **disjoint** sets of run bases. A temperature sweep
      where one arm ran one extra minimisation splits into a ``{prod}`` cohort and a
      ``{prod, min}`` cohort that still *share* ``prod`` — usually two arms of one sweep
      rather than two phases of a pipeline — and reconciling them would merge two
      different temperatures into one lineage. ``equil/*`` and ``prod/*`` share no base at
      all, which is what makes them phases rather than rivals.

      Sharing a base is not *proof* of a sweep, though: a genuine two-phase pipeline whose
      phases happen to reuse one run name — ``equil/01..02/{min,heat}`` beside
      ``prod/01..02/{heat,nvt_prod}``, both cohorts running ``heat`` — is refused here too,
      even though each phase has its own multiple replicas and would otherwise reconcile
      cleanly. That is the safe failure — untagged, not a merged claim — but a user staring
      at an untagged tree is not told *why* by this rule alone.

      This cannot, by directory layout alone, distinguish a shared base from deliberately
      parallel arms that use their *own* run names throughout — cross-system
      (``apo/*`` beside ``holo/*``) or, more easily missed, same system under two
      conditions with condition-specific run names (``300K/*/prodA`` beside
      ``310K/*/prodB``): those bases are disjoint too and still merge today — a known,
      accepted limitation of this reconciliation model, not fixed here;
    * a directory left **alone** in its cohort — ``prod/01``, whose stray ``cpptraj.in``
      gives it a run-base set of its own — is absorbed only when it sits at a depth some
      reporting cohort actually used **and** its segment at the agreed index is one of the
      reconciled tags. ``common/`` is not absorbed: its segment is ``common``, not a tag.
      The depth check keeps an unrelated directory that merely happens to spell a tag at
      the right *index* (``analysis/01/rmsd/calc``, three segments deep) from being
      absorbed by coincidence; it does not, and cannot, catch a coincidence at the *same*
      depth the reporting cohorts used (``scratch/01`` beside a ``rep/01``-shaped tree);
    * the tag must be **one** segment: a nested sweep (``300K/rep1``, ``310K/rep2``)
      varies in two places at once *within its cohort* and there is no way to tell which
      one names the member.

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

    # Cohorts are keyed on `(bases, depth)`, not on `bases` alone. A directory whose runs
    # happen to share an ENTIRE unrelated tree's base set -- `rerun/deep/here/prod_0001`
    # beside `prod/01..03`'s `prod_0001`, both base `{prod}` -- used to land in `prod/01..03`'s
    # own cohort rather than one of its own, and if that pulled the cohort out of depth
    # uniformity the WHOLE cohort, replicas included, silently reported nothing: `equil`
    # tagged, every `prod` run gone, with the tree still calling it a success. That is worse
    # than the refusal this rule otherwise gives, and it disables the very sequence-hole
    # finding this rule exists to protect -- on the exact tree shape (a single-base cohort)
    # the real campaign this feature was built for actually has. Folding depth into the key
    # means a directory at a foreign depth can never merge into a cohort it does not belong
    # to in the first place: it forms (or joins) its OWN cohort at its own depth, where it is
    # either a contributor in its own right or, alone, a candidate for absorption below --
    # never a silent vote against directories it has nothing to do with.
    cohorts: Dict[Tuple[FrozenSet[str], int], List[str]] = {}
    for directory, runs in candidates.items():
        bases = frozenset(_run_base(r) for r in runs)
        cohorts.setdefault((bases, len(directory.split("/"))), []).append(directory)

    # Each cohort of more than one directory reports its OWN varying segment, and a cohort
    # that cannot report one contributes nothing rather than refusing the whole tree -- a
    # prep directory at a different depth must not be able to veto the replicas. This is
    # why the canonical layout (a prep tree beside a production tree) can be tagged at all:
    # `equil/*` and `prod/*` run different run bases, so they are two cohorts, not one, and
    # each is free to name its own member without the other's shape constraining it.
    #
    # Per cohort, never on the union: `equil/01..05` unioned with `prod/01..05` varies in
    # TWO segments at once (equil|prod at index 0, 01..05 at index 1), and the
    # single-varying-segment rule below would refuse it one line later. Reconciled per
    # cohort, each cohort varies in exactly one segment and the two agree on which one.
    #
    # `bases` and `depth` travel with each report because two later checks need them: the
    # disjointness check below needs the bases, and absorption needs to know which depths
    # the tree actually agreed on. Depth is no longer re-derived here -- every directory in
    # `dirs` already sits at `depth`, by construction of the cohort key above.
    reports: List[Tuple[FrozenSet[str], int, int, Dict[str, str]]] = []
    for (bases, depth), dirs in cohorts.items():
        if len(dirs) < 2:
            continue
        segments = {d: d.split("/") for d in dirs}
        varying = [i for i in range(depth)
                   if len({segments[d][i] for d in dirs}) > 1]
        if len(varying) != 1:
            continue
        reports.append((bases, depth, varying[0],
                         {d: segments[d][varying[0]] for d in dirs}))

    if not reports:
        return {}
    # Two cohorts naming their member at different segment indices are not one campaign --
    # merging them would tag two unrelated axes as though they were the same replica.
    if len({index for _, _, index, _ in reports}) != 1:
        return {}
    index = reports[0][2]

    # Contributing cohorts must run genuinely DISJOINT sets of run bases. Two cohorts that
    # SHARE a base are the same kind of thing running in parallel, not two phases of one
    # pipeline: a temperature sweep where one arm happened to run one extra minimisation
    # splits into a `{prod}` cohort and a `{prod, min}` cohort that still share `prod`, and
    # their matching replica numbering (`rep1`, `rep2` in both) would otherwise nest into
    # one lineage that silently crosses the temperature axis -- two different temperatures
    # reported as one member. `equil/*` (many prep run names) beside `prod/*` (`nvt_prod`),
    # by contrast, share no base at all: they are different PHASES of one pipeline, which
    # is exactly the shape this rule exists to reconcile, not refuse.
    #
    # This does not, and cannot, catch deliberately parallel arms that use DISTINCT run
    # names of their own -- `apo/01../prod_apo` beside `holo/01../prod_holo`, or `wt/*`
    # beside `mut/*` -- their bases are disjoint too, on purpose, and directory layout
    # alone cannot tell that apart from a pipeline's phases. Accepted, not fixed here: see
    # manifest.md §9.1 for the deferred multi-axis design this belongs to.
    for i, (bases_a, _, _, _) in enumerate(reports):
        for bases_b, _, _, _ in reports[i + 1:]:
            if bases_a & bases_b:
                return {}

    # Nested, not equal. A member that never reached production appears in the equil
    # cohort and not the prod one, and that is one campaign with a short member -- exactly
    # the crashed replica this feature exists to surface. Two DISJOINT sets are still two
    # experiments and are still refused, because neither contains the other.
    tag_sets = [set(mapping.values()) for _, _, _, mapping in reports]
    reconciled = max(tag_sets, key=len)
    if any(not tags <= reconciled for tags in tag_sets):
        return {}

    tagged = {d: tag for _, _, _, mapping in reports for d, tag in mapping.items()}

    # A directory alone in its cohort was dropped above -- `len(dirs) < 2` -- so it never
    # got a chance to report a varying segment of its own. It is absorbed only when the
    # tree has already decided what the tags are, this directory sits at a depth some
    # reporting cohort actually used, AND its segment at the agreed index is one of the
    # reconciled tags. The depth check earns its keep on its own: without it,
    # `analysis/01/rmsd/calc` (depth 3, nothing to do with either replica tree) would be
    # absorbed into lineage "01" purely because its third segment happens to spell a tag --
    # a coincidence the layout gives no support for, not a claim. This is how a stray
    # `cpptraj.in` stops costing `prod/01` its membership -- its segment ("01") is a
    # reconciled tag AND `prod/01` sits at the same depth `prod/02..05` itself reported --
    # while a genuine `common/` prep directory at that SAME depth is still not absorbed:
    # its segment is "common", which is not a tag anybody's cohort reported.
    #
    # What the depth check does NOT catch: two directories at the SAME depth the tree
    # agreed on, coincidentally sharing a segment spelling (`scratch/01` beside a
    # `rep/01`-shaped tree). Depth alone cannot distinguish a genuine sibling from a same-
    # depth coincidence. Left as a residual gap; see manifest.md §9.1.
    reporting_depths = {depth for _, depth, _, _ in reports}
    for dirs in cohorts.values():
        if len(dirs) != 1:
            continue
        parts = dirs[0].split("/")
        if len(parts) in reporting_depths and parts[index] in reconciled:
            tagged[dirs[0]] = parts[index]

    return {f"{d}/{run}": tag for d, tag in tagged.items() for run in candidates[d]}
