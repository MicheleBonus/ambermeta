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

    `begin_overflowed=True` reproduces the real defect this fixture exists to let a test
    build: AMBER prints `begin time read from input coords` into a fixed-width Fortran
    field, and once a chain's accumulated simulated time passes roughly 1e6 ps the value no
    longer fits, so AMBER prints `**********` in its place instead of a number. `begin_ps`
    is still a real float when this is set -- it is what the frames below are spaced around
    (AMBER's internal clock did not overflow, only the fixed-width field it was printed
    into), so a caller reproducing the real failure passes a `begin_ps` at or past the
    overflow threshold (e.g. `999999.992`, the real tree's own value) alongside it.

    `stated_ps` is what the run said it would do, when that DIFFERS from what it did.
    Left `None` the mdout's `nstlim` is written as `elapsed_ps / dt`, which makes intent and
    execution identical by construction -- and for the whole life of this branch every
    fixture in the repo was built that way, so no test anywhere could tell a rule that reads
    the mdout's elapsed time apart from one that reads its `nstlim x dt`. A run killed at
    60% of its wall clock, or by a node failure, is the commonest way those two come apart
    on real data; `stated_ps=5000.0, elapsed_ps=3000.0` is that run. Keep `stated_ps` equal
    to the `mdin`'s own `nstlim x dt` -- they are the same claim, and `_validate_timing`
    compares them and notes a "Step count differs" if they disagree.

    `irest` is what AMBER was told about the clock, and it decides what the begin-time line
    below MEANS. `irest=1` (the default, a continuation) makes AMBER take the clock from the
    coordinate file, and the header's begin time is authoritative. `irest=0` -- a fresh run
    under `ntx=1` -- makes it take the clock from the mdin's `t` instead and read NO time
    from the coordinates, so it prints `begin time read from input coords = 0.000` while the
    trajectory starts at `t` and it emits an `NSTEP = 0` record carrying that real origin.
    `begin_ps` is that origin in both cases (it is where the frames start); only the printed
    header line differs. This shape is the one the branch's totals over-reported by 1800 ps
    on five real runs, and no fixture modelled it until this field existed.
    """
    mdin: str
    elapsed_ps: Optional[float] = None
    begin_ps: float = 0.0
    dt: float = 0.002
    inpcrd: Optional[str] = None
    frames: int = 5
    begin_overflowed: bool = False
    stated_ps: Optional[float] = None
    irest: int = 1
    natoms: Optional[int] = None
    """The system size AMBER reports in its `RESOURCE USE` block, or None to omit the block.

    This is the ONLY source `lineages.coherence` reads an atom count from
    (`_atom_count_of` -> `mdout.details.natoms`), and no fixture built through this helper
    wrote one, so the whole atom-count half of coherence -- both the cross-member check and
    the within-member one -- was unreachable from a real directory tree. It could be tested
    against hand-built `SimulationStage` objects and nowhere else, which leaves the path
    from files on disk to the finding a user sees entirely unexercised.
    """


def _mdout_text(spec: RunSpec) -> str:
    """The smallest mdout carrying everything the engine reads off one.

    Four blocks, in AMBER's own order: the File Assignments block `read_mdout_header`
    parses, a CONTROL DATA block giving `imin`/`ntx`/`irest`/`nstlim`/`t`/`dt`, the
    `3. ATOMIC COORDINATES` banner with the begin-time line under it, and `frames` NSTEP
    records.

    The CONTROL DATA block is laid out the way real AMBER lays it out -- one field group
    per line, `t` and `dt` sharing the `Molecular dynamics:` line -- rather than compressed
    onto one. `read_mdout_header` reads `irest`/`t`/`dt` from inside this block ONLY,
    because the mdin echo above it carries the same names with the user's unresolved
    values; a fixture that compressed the block would exercise a parse the real files never
    present. The `3.` banner is what closes the block, so the begin-time line under it can
    never be read as control data.

    The NSTEP times are ABSOLUTE, spanning `begin_ps` (exclusive, or INCLUSIVE via the
    extra `NSTEP = 0` record an `irest=0` run prints) to `begin_ps + elapsed_ps`
    (inclusive) -- which is the whole reason `_sum_stages` cannot sum `time_end` directly.
    A fixture that wrote elapsed times here would let the wrong formula pass.

    The final NSTEP is `elapsed_ps / dt` while `nstlim` is `stated_ps / dt`: on a truncated
    run those differ, which is the only way a test can tell "what it did" from "what it
    said it would do".

    Real AMBER pads every File Assignments value with trailing spaces up to a fixed column
    width; `read_mdout_header` treats a value with NO trailing whitespace as possibly
    clipped at that width and refuses to return it (`MdoutHeader.truncated`). Trailing
    padding here is therefore load-bearing, not cosmetic -- without it `INPCRD` would come
    back `None` and the fixture would silently fail to carry the one fact P2.4 reads.

    `spec.begin_overflowed` swaps the begin-time line for AMBER's own overflowed spelling
    (`=**********`, no digits at all) instead of the numeric one -- `mdout_header.py`'s
    `_BEGIN_TIME` regex requires `[\\d.]` and does not match either the real overflow or
    this stand-in, so `begin_time_ps` comes back `None` exactly as it does on the real
    tree's `prod/01/nvt_prod_0201`. The frame times below are still computed from the real
    `spec.begin_ps`, because AMBER's internal clock never overflows -- only the fixed-width
    field it prints the begin time into does.
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
    # What AMBER PRINTS on the begin-time line. An `irest=0` run read no time from its
    # coordinates and says so with a literal 0.000, however far along the clock `t` put it
    # -- reading that 0.000 as the clock origin is the 1800-ps-per-replica over-count.
    printed_begin = 0.0 if spec.irest == 0 else spec.begin_ps
    begin_line = (
        " begin time read from input coords =********** ps\n\n" if spec.begin_overflowed
        else f" begin time read from input coords = {printed_begin:.3f} ps\n\n"
    )
    stated_ps = spec.stated_ps if spec.stated_ps is not None else spec.elapsed_ps
    # AMBER's `RESOURCE USE` block, and only when asked for -- the legacy parser scans the
    # 14 lines after the banner for `NATOM`, stopping at the CONTROL DATA banner, so the
    # two must appear in this order and close together. Omitted by default so every fixture
    # that predates this field keeps parsing to `natoms = 0`, i.e. "not stated", which is
    # what `_atom_count_of` reads as None and what those fixtures have always meant.
    resources = (
        "   1.  RESOURCE   USE: \n"
        f" NATOM  = {spec.natoms:>7} NTYPES =       1 NBONH =       1 MBONA  =       0\n"
        if spec.natoms is not None else ""
    )
    head = (
        f"{assign}\n"
        f"{resources}"
        "   2.  CONTROL  DATA  FOR  THE  RUN\n"
        "General flags:\n"
        "     imin    =       0, nmropt  =       0\n"
        "\n"
        "Nature and format of input:\n"
        f"     ntx     =       {5 if spec.irest else 1}, irest   =       {spec.irest},"
        "  ntrx    =       1\n"
        "\n"
        "Molecular dynamics:\n"
        f"     nstlim  = {int(stated_ps / spec.dt):>9}, nscm    =         0,"
        "  nrespa  =         1\n"
        f"     t       = {spec.begin_ps:.5f}, dt      = {spec.dt:.5f},"
        "  vlimit  =  -1.00000\n"
        "\n"
        "   3.  ATOMIC COORDINATES AND VELOCITIES\n"
        f"{begin_line}"
        "   4.  RESULTS\n\n"
    )

    def frame(nstep: int, t: float) -> str:
        return (
            f" NSTEP = {nstep:>8}   TIME(PS) = {t:>11.3f}"
            f"  TEMP(K) =   300.00  PRESS =     0.0\n"
            " Etot   =    -1000.0000  EKtot   =      200.0000  EPtot      =    -1200.0000\n"
            "  ----------------------------------------------------------------\n"
        )

    step_of = spec.elapsed_ps / spec.frames
    # An `irest=0` run prints its starting energies as an `NSTEP = 0` record before it
    # integrates anything, so its first PRINTED frame is the clock origin itself rather
    # than one output interval past it. That is what makes the fencepost correction
    # (`time_end - time_start + interval`) overshoot by exactly one interval on such a run,
    # and it is why `_origin_time_ps` never routes an irest=0 run through the fencepost.
    body = frame(0, spec.begin_ps) if spec.irest == 0 else ""
    for i in range(1, spec.frames + 1):
        body += frame(int(step_of * i / spec.dt), spec.begin_ps + step_of * i)
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
# The real `equil/NN/18_ntp_equi.in`, field for field: a FRESH run (`ntx=1`, `irest=0`)
# that sets its own clock to `t = 1800.0` and integrates 1600000 x 0.002 = 3200 ps, ending
# at 5000 where production picks up. Every one of those numbers is load-bearing -- this is
# the deck whose mdout says `begin time read from input coords = 0.000` while the
# trajectory runs 1800 -> 5000, and which the branch counted as 5000 ps of dynamics.
_EQUI_MDIN = ("equilibrate\n &cntrl\n  imin = 0, ntx = 1, irest = 0,\n"
              "  nstlim = 1600000, t = 1800.0, dt = 0.002,\n"
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

    A fourth thing is reproduced exactly as of the C1 fix, and it is the one that had been
    wrong here: `equil/NN/18_ntp_equi` is a FRESH run (`irest=0`) that sets its own clock to
    1800 ps and integrates 3200 ps, ending at 5000. This fixture used to encode it as
    `elapsed_ps=5000.0, begin_ps=0.0` -- the defect's OWN arithmetic, baked into the
    fixture -- so no test built on it could see that the engine was over-counting these five
    runs by 1800 ps each. The campaign total is 71,000 ps here (5 x 3200 + 11 x 5000), the
    scaled equivalent of the real campaign's 5,030,000.

    Each prod chunk is 5000 ps, matching the real `nstlim=2500000, dt=0.002`. Times are
    absolute and continuous within a replica, so a totals rule that sums `time_end`
    instead of elapsed time gives a visibly wrong number here.
    """
    runs = []
    for n in ("01", "02", "03", "04", "05"):
        # Equilibration: 3200 ps of dynamics from a self-set clock origin of 1800, ending
        # at 5000 where production picks up. See `_EQUI_MDIN` and `RunSpec.irest`.
        runs.append((f"equil/{n}/18_ntp_equi",
                     RunSpec(mdin=_EQUI_MDIN, elapsed_ps=3200.0, begin_ps=1800.0, irest=0,
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
def truncated_run_tree(tmp_path) -> Path:
    """Two chunks that both RAN: one finished, one was killed at 60%.

    The fixture the whole branch was missing, and the reason C1 was unreachable by any
    test. `_mdout_text` writes `nstlim = elapsed_ps / dt` unless told otherwise, so before
    `RunSpec.stated_ps` existed EVERY fixture in this repo made intent and execution
    identical by construction -- and a rule that (wrongly) counted a ran stage's own
    `nstlim x dt` instead of its measured elapsed time passed all 548 tests.

    Here they differ by 2000 ps on one run and by nothing on the other, in one tree, so a
    test can pin both halves at once: the truncated chunk must contribute 3000 (what it
    did), never 5000 (what it said), and the complete chunk must still contribute its full
    5000 rather than being clipped by whatever rule catches the first.

    `stated_ps` matches `_PROD_MDIN`'s own `nstlim=2500000, dt=0.002` deliberately: the
    mdin and the mdout state the SAME intent, so `_validate_timing` sees no disagreement
    and the only thing that differs is what actually came out -- which is exactly the shape
    a node failure or a wall-clock kill leaves behind, and is not a mis-declared deck.
    """
    return write_run_tree(tmp_path, [
        ("prod_0001", RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0, begin_ps=0.0)),
        ("prod_0002", RunSpec(mdin=_PROD_MDIN, elapsed_ps=3000.0, stated_ps=5000.0,
                              begin_ps=5000.0)),
    ])


@pytest.fixture
def fresh_start_tree(tmp_path) -> Path:
    """A fresh run that set its own clock, and the continuation that follows it.

    `equi` is `equil/NN/18_ntp_equi`'s shape reduced to one directory: `irest=0`, so AMBER
    took the clock from the mdin's `t = 1800.0` rather than from the coordinates, printed
    `begin time read from input coords = 0.000` because it read none, emitted an
    `NSTEP = 0` record at 1800.000, and ran to 5000.000. It did 3200 ps. Reading that
    printed 0.000 as the origin says 5000, which is what the branch published for five real
    runs; applying the fencepost correction instead says 3220, because the `NSTEP = 0`
    record means the first printed frame IS the origin and there is no missing interval to
    add back. Only `t` gives 3200.

    `prod` beside it is an ordinary `irest=1` continuation from 5000 to 10000, whose header
    begin time IS authoritative -- so one tree holds both routes and a rule that fixed one
    by breaking the other cannot pass.
    """
    return write_run_tree(tmp_path, [
        ("equi", RunSpec(mdin=_EQUI_MDIN, elapsed_ps=3200.0, begin_ps=1800.0, irest=0,
                         frames=160)),
        ("prod_0001", RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0, begin_ps=5000.0,
                              frames=250)),
    ])


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
