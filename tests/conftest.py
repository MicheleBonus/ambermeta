from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple, Optional

import pytest


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def sample_md_data_dir() -> Path:
    return ROOT / "tests" / "data" / "amber" / "md_test_files"


# The three runs a replica performs, as the smallest mdin each role is recognised from.
# `classify_role` reads `imin` and the tempi/temp0 ramp before it falls back to the name,
# so these classify the same way whatever the directory is called.
_REPLICA_MDIN = {
    "min": "minimise\n &cntrl\n  imin = 1, maxcyc = 1000, ntb = 1,\n /\n",
    "heat": ("heat\n &cntrl\n  imin = 0, nstlim = 10000, dt = 0.002,\n"
             "  tempi = 0.0, temp0 = 300.0, ntb = 1,\n /\n"),
    "equil": ("equilibrate\n &cntrl\n  imin = 0, nstlim = 50000, dt = 0.002,\n"
              "  temp0 = 300.0, ntb = 2,\n /\n"),
    "prod": ("production\n &cntrl\n  imin = 0, irest = 1, nstlim = 500000,\n"
             "  dt = 0.002, ntb = 2,\n /\n"),
}


class RunSpec(NamedTuple):
    """What to write on disk for one run.

    `elapsed_ps=None` writes NO mdout, which is how a queued run -- an mdin that was set
    up and never executed -- is expressed. Every other field only matters when an mdout is
    written. `inpcrd` becomes the File Assignments line AMBER itself records, which is the
    evidence P2.4's handoff proposal reads; None omits the whole block, which is what a
    clipped or absent assignment looks like.
    """
    mdin: str
    elapsed_ps: Optional[float] = None
    begin_ps: float = 0.0
    dt: float = 0.002
    inpcrd: Optional[str] = None
    frames: int = 5


def _mdout_text(spec: RunSpec) -> str:
    """The smallest mdout carrying everything the engine reads off one.

    Three blocks, in AMBER's own order: the File Assignments block `read_mdout_header`
    parses, a CONTROL DATA block giving `imin`/`nstlim`/`dt`, and `frames` NSTEP records.

    The NSTEP times are ABSOLUTE, spanning `begin_ps` (exclusive) to
    `begin_ps + elapsed_ps` (inclusive) -- which is the whole reason `_sum_stages` cannot
    sum `time_end` directly. A fixture that wrote elapsed times here would let the wrong
    formula pass.

    Real AMBER pads every File Assignments value with trailing spaces up to a fixed column
    width; `read_mdout_header` treats a value with NO trailing whitespace as possibly
    clipped at that width and refuses to return it (`MdoutHeader.truncated`). Trailing
    padding here is therefore load-bearing, not cosmetic -- without it `INPCRD` would come
    back `None` and the fixture would silently fail to carry the one fact P2.4 reads.
    """
    assign = ""
    if spec.inpcrd is not None:
        assign = (
            "File Assignments:\n"
            "|   MDIN: mdin                                                                   \n"
            "|  MDOUT: mdout                                                                  \n"
            f"| INPCRD: {spec.inpcrd:<74}\n"
            "|   PARM: prmtop                                                                 \n"
        )
    head = (
        f"{assign}\n"
        "   2.  CONTROL  DATA  FOR  THE  RUN\n"
        f"     imin    = 0, nstlim  = {int(spec.elapsed_ps / spec.dt)}, dt = {spec.dt:.5f}\n"
        f" begin time read from input coords = {spec.begin_ps:.3f} ps\n\n"
        "   4.  RESULTS\n\n"
    )
    step_of = spec.elapsed_ps / spec.frames
    body = ""
    for i in range(1, spec.frames + 1):
        t = spec.begin_ps + step_of * i
        body += (
            f" NSTEP = {int(step_of * i / spec.dt):>8}   TIME(PS) = {t:>11.3f}"
            f"  TEMP(K) =   300.00  PRESS =     0.0\n"
            " Etot   =    -1000.0000  EKtot   =      200.0000  EPtot      =    -1200.0000\n"
            "  ----------------------------------------------------------------\n"
        )
    return head + body + "\n      5.  TIMINGS\n"


_RESTART_NATOM = 2


def _restart_text(end_ps: float) -> str:
    """A minimal ASCII restart -- real enough for `InpcrdParser` to read without raising.

    The same three-line shape `test_continuity_p1.py`'s `_rst` already proved safe: a
    title, `natom time`, and one line of six coordinates (two atoms' worth). Nothing that
    consumes this fixture ever reads the coordinates -- `smart_group_files` types the file
    "inpcrd" by extension alone, and `discover_draft`'s restart-producer rule only checks
    that the file EXISTS beside a run's own stem -- so the coordinates are placeholders and
    only `end_ps` (the one field a continuity check might read) is real.
    """
    return ("restart\n%6d %14.7f\n"
            "   1.0000000   2.0000000   3.0000000   4.0000000   5.0000000   6.0000000\n"
            % (_RESTART_NATOM, end_ps))


def write_run_tree(root: Path, runs) -> Path:
    """Write the files for each entry of `runs`, creating directories as needed.

    An entry is either a bare posix stem -- the original behaviour, one role-matched mdin
    and nothing else -- or a `(stem, RunSpec)` pair spelling out exactly what to write.

    The bare form still writes mdin ONLY. That was a deliberate speed choice and it stays
    the default, but it means every tree built from it reads as entirely `queued` once
    totals come from the mdout, so a fixture asserting on time MUST use the pair form.

    The bare form also picks its mdin by substring, which raises StopIteration for a stem
    named after neither min/heat/equil/prod (`18_ntp_equi`, `cpptraj`). That is why the
    pair form exists: real campaign stems do not follow this repo's fixture naming.

    The pair form ALSO writes a restart (`<stem>.restrt`) whenever `elapsed_ps is not
    None`: a real AMBER run that produced output always writes one (`-r`), unconditionally,
    unless it crashed outright -- and a crash is what an entry simply missing from `runs`
    already models, not an mdout with no restart beside it. This is what makes
    `core_bridge.py`'s restart-producer rule (P1.3: a step that wrote nothing cannot hand
    a restart to whatever comes after it in its directory) testable at all: without a real
    file here, no fixture built through this helper could ever show "this run wrote
    something" and "this run wrote nothing" both, in the same directory, to prove the rule
    tells them apart. The BARE-stem form is unaffected -- its `RunSpec` defaults to
    `elapsed_ps=None`, so it never enters this branch, and stays exactly the mdin-only
    fixture every other consumer of it already depends on.
    """
    for entry in runs:
        stem, spec = entry if isinstance(entry, tuple) else (entry, None)
        if spec is None:
            kind = next(k for k in _REPLICA_MDIN if k in Path(stem).name)
            spec = RunSpec(mdin=_REPLICA_MDIN[kind])
        path = root / (stem + ".mdin")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(spec.mdin, encoding="utf-8")
        if spec.elapsed_ps is not None:
            (root / (stem + ".mdout")).write_text(_mdout_text(spec), encoding="utf-8")
            (root / (stem + ".restrt")).write_text(
                _restart_text(spec.begin_ps + spec.elapsed_ps), encoding="utf-8")
    return root


@pytest.fixture
def replica_tree(tmp_path) -> Path:
    """Three replicas x three roles, one role chunked into two runs.

    The repo has no replica fixture — every committed tree is a single flat production
    chain, which is precisely the shape in which a cross-replica chain edge cannot appear.

    Three roles rather than two is load-bearing for the phase-count assertions:
    `discover_draft` opens a new phase on every role *change*, so a two-role tree yields
    six phases and a fix that merges nine into three would be indistinguishable from one
    that merged six into three by accident. The chunked `prod_0001`/`prod_0002` pair gives
    each member a genuine within-lineage edge that must survive.
    """
    return write_run_tree(tmp_path, [
        f"{rep}/{run}"
        for rep in ("rep1", "rep2", "rep3")
        for run in ("min_0001", "heat_0001", "prod_0001", "prod_0002")
    ])


@pytest.fixture
def recurring_role_tree(tmp_path) -> Path:
    """Two replicas whose role sequence returns to minimisation after heating.

    A staged relaxation, which is an ordinary thing to run: minimise with the solute
    restrained, heat, minimise again with the restraints released, then produce. The
    prefix numbering is the convention `detect_numeric_sequences` already documents
    (`01_min`, `02_nvt`, ...), and it is what makes the recurrence *non-contiguous* in
    natural stem order — with `min_0001`/`min_0002` the two minimisations sort next to
    each other and the ordering bug cannot appear.
    """
    return write_run_tree(tmp_path, [
        f"{rep}/{run}"
        for rep in ("rep1", "rep2")
        for run in ("01_min", "02_heat", "03_min", "04_prod")
    ])


@pytest.fixture
def campaign_tree(tmp_path) -> Path:
    """The canonical layout of design section 6: shared prep beside three replicas.

    `common/` runs a different set of things from `rep*/`, so the membership predicate
    keeps it out of the family and it stays untagged — which makes this the one tree where
    tagged and untagged steps have to chain side by side without touching.
    """
    return write_run_tree(tmp_path, [
        "common/min_0001", "common/heat_0001", "common/equil_0001",
        *(f"{rep}/prod_{i:04d}"
          for rep in ("rep1", "rep2", "rep3") for i in (1, 2)),
    ])


@pytest.fixture
def crashed_replica_tree(tmp_path) -> Path:
    """Three replicas, one of which stopped after its first production chunk.

    The failure mode replicas exist to expose, and the one the sequence detector saw
    nothing of while it pooled every member's indices into a single `prod` family. rep2 has
    no hole of its own to find — it simply ends — so it is only short relative to its
    siblings, which is what the family frame is for.

    Written through the `RunSpec` pair form rather than the bare-stem shorthand. Totals
    now come from the mdout (Task 2's `_sum_stages`), and the bare form writes an mdin and
    NO mdout — which, post-Task-2, reads as entirely `queued`. Every member's `time_ps`
    would collapse to 0.0 and `rep2 shorter than rep1` would degenerate to `0.0 < 0.0`,
    true for the wrong reason and passing even if the totals rule broke. Each chunk here is
    a real 5000 ps -- matching `_PROD_MDIN`'s own `nstlim=2500000, dt=0.002`, the same
    pairing `sys021_tree` uses -- so the three-chunk members genuinely outran the one-chunk
    member rather than merely reporting a `nstlim x dt` that does not match what the mdout
    the run actually produced would say. An earlier version of this fixture used 1000.0,
    which does not match `_PROD_MDIN`'s stated duration and made every chunk validate as
    `Simulation duration differs` / `result: Unclear`.
    """
    return write_run_tree(tmp_path, [
        *((f"{rep}/prod_{i:04d}",
           RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0, begin_ps=5000.0 * i))
          for rep in ("rep1", "rep3") for i in (1, 2, 3)),
        ("rep2/prod_0001", RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0, begin_ps=5000.0)),
    ])


@pytest.fixture
def dot_numbered_crashed_tree(tmp_path) -> Path:
    """The same crash, numbered `prod.0001` instead of `prod_0001`.

    Every other fixture in this file and every committed one under `tests/data/` uses an
    underscore, which is how the dot spelling stayed broken through two PRs: it was tagged
    correctly, grouped correctly on the canvas, and silently produced no sequence at all.

    Built through `write_run_tree`, which concatenates strings. Do not reach for
    `Path.with_suffix` here — `Path("prod.0001").with_suffix(".mdin")` is `prod.mdin`, so
    the fixture would write the wrong files and pass for the wrong reason.
    """
    return write_run_tree(tmp_path, [
        *(f"{rep}/prod.{i:04d}" for rep in ("rep1", "rep3") for i in (1, 2, 3)),
        "rep2/prod.0001",
    ])


@pytest.fixture
def nested_sweep_tree(tmp_path) -> Path:
    """A temperature sweep crossed with replicas: two segments vary at once.

    The failure-mode row of design section 6 that has no defensible answer — neither
    segment can be shown to name the member — so the inference refuses it and every path
    downstream must behave exactly as it did before lineages existed.
    """
    return write_run_tree(tmp_path, [
        f"{temperature}/{rep}/prod_0001"
        for temperature in ("300K", "310K") for rep in ("rep1", "rep2")
    ])


_PROD_MDIN = ("production\n &cntrl\n  imin = 0, irest = 1, nstlim = 2500000,\n"
              "  dt = 0.002, ntb = 2,\n /\n")
_EQUI_MDIN = ("equilibrate\n &cntrl\n  imin = 0, nstlim = 2500000, dt = 0.002,\n"
              "  temp0 = 300.0, ntb = 2,\n /\n")
_CPPTRAJ_IN = "trajin nvt_prod_0001.nc\nautoimage\ntrajout stripped.nc\n"


@pytest.fixture
def sys021_tree(tmp_path) -> Path:
    """The real campaign this spec was written against, scaled down.

    Five replicas, each an `equil/NN` directory feeding a `prod/NN` directory. Three
    things about the real tree are load-bearing and are reproduced exactly:

    * `prod/01` holds a stray `cpptraj.in`, which the extension-based file typing reads as
      an AMBER mdin. That puts `prod/01` in a run-base cohort of its own, which is what
      made the first draft of the reconciliation rule refuse this tree entirely;
    * every replica has one final chunk with an mdin and no mdout -- queued, never run --
      which is the 25 ns the old totals counted as simulated;
    * replica 01 completed one chunk more than 02-05, which is the only genuine asymmetry
      in the campaign and must survive as a finding rather than as a phantom missing run.

    Each prod chunk is 5000 ps, matching the real `nstlim=2500000, dt=0.002`. Times are
    absolute and continuous within a replica, so a totals rule that sums `time_end`
    instead of elapsed time gives a visibly wrong number here.
    """
    runs = []
    for n in ("01", "02", "03", "04", "05"):
        # Equilibration: one 5000 ps run, ending where production picks up.
        runs.append((f"equil/{n}/18_ntp_equi",
                     RunSpec(mdin=_EQUI_MDIN, elapsed_ps=5000.0, begin_ps=0.0,
                             inpcrd="17_ntp_equi.restrt")))
        ran = 3 if n == "01" else 2
        for i in range(1, ran + 1):
            runs.append((f"prod/{n}/nvt_prod_{i:04d}",
                         RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0,
                                 begin_ps=5000.0 * i,
                                 inpcrd=("18_ntp_equi.restrt" if i == 1
                                         else f"nvt_prod_{i - 1:04d}.restrt"))))
        # The chunk that was queued and never ran: mdin, no mdout.
        runs.append((f"prod/{n}/nvt_prod_{ran + 1:04d}", RunSpec(mdin=_PROD_MDIN)))
    tree = write_run_tree(tmp_path, runs)
    # The stray cpptraj script. Written directly rather than through `write_run_tree` --
    # that helper always appends `.mdin`, but the real campaign file is `cpptraj.in`, and
    # `.in` is the other extension `discover_draft` reads as an mdin candidate (alongside
    # `.mdin`), which is the whole reason this run ends up cohorted with the mdin-typed
    # production runs instead of being ignored as an unrecognised file.
    (tree / "prod" / "01" / "cpptraj.in").write_text(_CPPTRAJ_IN, encoding="utf-8")
    return tree


@pytest.fixture
def mid_directory_queued_tree(tmp_path) -> Path:
    """One directory, three chunks: a queued run sitting between two that actually ran.

    `sys021_tree`'s own queued chunk is always LAST in its directory, which is exactly
    where a non-producer is invisible -- nothing downstream ever has to read past it. This
    fixture puts the queued chunk in the MIDDLE, so `discover_draft`'s restart-producer
    rule has something to actually prove: `prod_0003` has to skip the empty `prod_0002`
    and chain to `prod_0001`, the last run that actually wrote a restart, rather than to
    whichever run happens to sit next to it in document order. `prod_0001` and `prod_0003`
    use the pair form (so they write a real `.restrt` and the directory has restart
    evidence at all); `prod_0002` is a pair too, but with `elapsed_ps` left at its default
    `None`, which is exactly what "declared and never run" means here.
    """
    return write_run_tree(tmp_path, [
        ("prod_0001", RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0, begin_ps=0.0)),
        ("prod_0002", RunSpec(mdin=_PROD_MDIN)),
        ("prod_0003", RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0, begin_ps=10000.0)),
    ])
