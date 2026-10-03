# ambermeta/run_order.py
"""Which run each run continued, and the order the runs ran in, from what AMBER recorded.

Every mdout names the coordinate file its run read (the INPCRD row of File Assignments,
see :mod:`ambermeta.mdout_header`). Read over a whole tree, those records say which run
continued which, whatever the file names: `eq_0002` read `prod_0001.restrt`, so it ran
after `prod_0001` although it sorts before it.

Two callers read a tree for the same purpose and must agree: ``discover``
(:func:`ambermeta.gui.api.core_bridge.discover_draft`), which writes the chain into a
manifest, and the directory scan of :func:`ambermeta.protocol.auto_discover`
(``plan DIR --recursive``), which measures continuity without one. This module is the one
rule both use. Deliberately outside ``gui/api/`` and free of FastAPI, like
:mod:`ambermeta.lineages`.

The inputs are the scan's own shapes: ``run_stems`` are the path-prefixed posix stems
``smart_group_files`` builds (``rep1/prod_0001``), ``grouped`` maps each stem to its files
by kind (absolute paths), ``tags`` maps a stem to its lineage, and ``headers`` maps a stem
to its :class:`~ambermeta.mdout_header.MdoutHeader`.
"""
from __future__ import annotations

import filecmp
import heapq
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional

__all__ = ["RECORDED_START", "ROLE_RANK", "same_file", "same_content",
           "recorded_producers", "execution_order", "chain_runs"]


#: A run whose mdout records a coordinate file no run in the tree wrote: it starts the
#: simulation (or a branch of it) rather than continuing a run.
RECORDED_START = object()

#: Role order, for ordering directories that no recorded input orders.
ROLE_RANK = {"minimization": 0, "heating": 1, "equilibration": 2, "production": 3}


def same_file(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def same_content(a, b):
    """Whether two files hold the same bytes: a copy, not merely a namesake."""
    try:
        return filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def recorded_producers(run_stems, grouped, tags, headers):
    """Which run each run continued, by the INPCRD its mdout records.

    Returns {consumer stem: producer stem, or RECORDED_START}. A run is absent when its
    mdout says nothing usable (no mdout, a clipped path, a name no file in the tree has, a
    name several runs wrote that nothing below tells apart, its own restart), and
    `chain_runs` then chains it by file order.

    The record is a path as typed where the run executed: relative to a working directory,
    or absolute on another machine. Resolved in order:

    * as a path from the run's own directory; a hit that some run wrote is that run; a
      hit that is a byte-for-byte copy of a restart some run wrote is that run (replica
      directories often hold a copy of the equilibration's last restart, and the mdout
      names the copy); any other hit (the system's coordinates) makes the run a start;
    * by file name among the restarts the runs wrote: one candidate is that run; among
      several, the one whose path shares the most trailing directories with the record
      (at least one beyond the name), then the one in the run's own directory, then the
      one in the run's own replica. On the campaign the handoff proposal was written
      against, all five replicas record the bare name `18_ntp_equi.restrt`; the replica
      is what tells them apart, as it is in `_propose_handoffs`.

    A record that points into another replica is not followed. No automatic link may
    cross a declared boundary (`crosses_lineage`); the run is chained by file order and
    `validate` then reports that the recorded input differs from the declared one.
    """
    rst_by_key = {}
    rst_by_name = defaultdict(list)
    for stem in run_stems:
        rst = grouped[stem].get("inpcrd")
        if rst:
            rst_by_key[os.path.normcase(os.path.abspath(rst))] = stem
            rst_by_name[os.path.basename(rst)].append(stem)

    def trailing_match(record_parts, stem):
        rst = grouped[stem]["inpcrd"]
        parts = stem.split("/")[:-1] + [os.path.basename(rst)]
        n = 0
        for a, b in zip(reversed(record_parts), reversed(parts)):
            if a != b:
                break
            n += 1
        return n

    out = {}
    for stem in run_stems:
        header = headers.get(stem)
        if header is None:
            continue
        named = header.assignment("INPCRD")
        if not named:
            continue
        mdout = grouped[stem]["mdout"]
        record_parts = [part for part in named.replace("\\", "/").split("/") if part]
        if not record_parts:
            continue
        candidate = named if os.path.isabs(named) else os.path.join(os.path.dirname(mdout), named)
        candidate = os.path.normpath(candidate)
        producer = None
        if os.path.isfile(candidate):
            producer = rst_by_key.get(os.path.normcase(os.path.abspath(candidate)))
            if producer is None:
                producer = next((s for s in rst_by_name.get(os.path.basename(candidate), [])
                                 if same_file(grouped[s]["inpcrd"], candidate)), None)
            if producer is None:
                copied = [s for s in rst_by_name.get(os.path.basename(candidate), [])
                          if s != stem and same_content(grouped[s]["inpcrd"], candidate)]
                if len(copied) > 1:
                    copied = [s for s in copied if tags.get(stem) and tags.get(s) == tags.get(stem)]
                producer = copied[0] if len(copied) == 1 else None
            if producer is None:
                out[stem] = RECORDED_START
                continue
        else:
            names = [s for s in rst_by_name.get(record_parts[-1], []) if s != stem]
            if len(names) == 1:
                producer = names[0]
            elif names:
                scores = {s: trailing_match(record_parts, s) for s in names}
                best = max(scores.values())
                top = [s for s in names if scores[s] == best]
                directory = stem.rpartition("/")[0]
                same_dir = [s for s in top if s.rpartition("/")[0] == directory]
                same_tag = [s for s in top if tags.get(stem) and tags.get(s) == tags.get(stem)]
                if len(top) == 1 and best >= 2:
                    producer = top[0]
                elif len(same_dir) == 1:
                    producer = same_dir[0]
                elif len(same_tag) == 1:
                    producer = same_tag[0]
        if producer is None or producer == stem:
            continue
        if tags.get(stem) and tags.get(producer) and tags[stem] != tags[producer]:
            continue
        out[stem] = producer
    return out


def execution_order(run_stems, recorded, roles):
    """The runs in an order where every recorded producer precedes its consumer.

    Among runs free to go next, directories go by the earliest role they hold
    (minimisation, heating, equilibration, production, then the rest), and runs keep their
    scan order. `minimization/` therefore precedes `equilibration/` although it sorts after
    it, and within one directory a run follows the run it read, whatever their names: on
    one deposited project `min_ntr_h` ran first and sorts after `md_nvt_red_06`.

    Records that form a cycle are dropped from `recorded` (the runs keep scan order and
    are chained by file order), since no order satisfies them.
    """
    index = {stem: i for i, stem in enumerate(run_stems)}
    dir_rank = {}
    for stem in run_stems:
        directory = stem.rpartition("/")[0]
        rank = ROLE_RANK.get(roles.get(stem) or "", len(ROLE_RANK))
        dir_rank[directory] = min(dir_rank.get(directory, rank), rank)

    def key(stem):
        return (dir_rank[stem.rpartition("/")[0]], index[stem], stem)

    consumers = defaultdict(list)
    waiting = {stem: 0 for stem in run_stems}
    for consumer, producer in recorded.items():
        if producer is not RECORDED_START and producer in index:
            consumers[producer].append(consumer)
            waiting[consumer] += 1
    heap = [key(stem) for stem in run_stems if waiting[stem] == 0]
    heapq.heapify(heap)
    order = []
    while heap:
        stem = heapq.heappop(heap)[2]
        order.append(stem)
        for consumer in consumers[stem]:
            waiting[consumer] -= 1
            if waiting[consumer] == 0:
                heapq.heappush(heap, key(consumer))
    if len(order) < len(run_stems):
        placed = set(order)
        stuck = sorted((s for s in run_stems if s not in placed), key=key)
        stuck_set = set(stuck)
        for stem in stuck:
            if recorded.get(stem) in stuck_set:
                del recorded[stem]
        order.extend(stuck)
    return order


def chain_runs(order: List[str], recorded: Dict[str, Any],
               grouped: Dict[str, Dict[str, str]]) -> Dict[str, Optional[str]]:
    """Which run each run continued: its recorded producer, else the run before it in its
    directory, else none (it reads the starting structure).

    Returns ``{stem: producer stem or None}`` for every stem of ``order``, which must be
    an order :func:`execution_order` returned, so that every recorded producer comes
    before its consumer. Call it after :func:`execution_order`, which drops records that
    form a cycle from ``recorded``.

    A run whose record names a file no run wrote (``RECORDED_START``) starts there. A
    run whose record names a run is chained to it, which is also how a run continues a run
    in another directory. A run with no usable record is chained by FILE ORDER, within its
    DIRECTORY only: a directory boundary is the only boundary file order can justify.
    Within one, the chunked chain ``prod_0001 -> prod_0002`` is what the numbering means.
    Across one, file order is not evidence: keyed on the lineage bucket instead, an
    untagged tree once chained ``equil/05`` to ``prod/01`` and one replica's tail to the
    next replica's head -- edges nobody asserted, self-validating because the consumer is
    handed the producer's own restart and the gap is always 0.0.

    A run becomes the file-order predecessor of the next run in its directory only if it
    wrote a restart itself (a coordinate file in its own group), OR its directory holds no
    restart at all. Restart absence is evidence that a run did not run -- and so cannot
    hand anything on -- only where the directory shows restarts are kept: a stray
    ``cpptraj.in`` read as an mdin, or a queued run between two chunks that ran, drops out
    as a producer there. A directory with no restart anywhere is a planned campaign (every
    run just an mdin), where the chain IS the plan, and demanding restart proof that could
    never exist would unchain every one of them.
    """
    with_restarts = {stem.rpartition("/")[0] for stem in order if grouped[stem].get("inpcrd")}
    previous_in: Dict[str, str] = {}
    placed = set()
    out: Dict[str, Optional[str]] = {}
    for stem in order:
        directory = stem.rpartition("/")[0]
        producer = recorded.get(stem)
        if producer is RECORDED_START:
            out[stem] = None
        elif producer is not None and producer in placed:
            out[stem] = producer
        else:
            out[stem] = previous_in.get(directory)
        placed.add(stem)
        if grouped[stem].get("inpcrd") or directory not in with_restarts:
            previous_in[directory] = stem
    return out
