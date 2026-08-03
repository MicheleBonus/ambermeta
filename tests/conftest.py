from __future__ import annotations

import sys
from pathlib import Path

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


def write_run_tree(root: Path, runs) -> Path:
    """Write one mdin per entry of `runs` (posix stems), creating directories as needed.

    mdin only: `discover_draft` counts a group holding an mdin *or* an mdout as a run and
    parses only the mdin, so a real 160 kB mdout and a 12 MB prmtop would slow the suite
    down without changing a single assertion here.
    """
    for stem in runs:
        path = root / (stem + ".mdin")
        path.parent.mkdir(parents=True, exist_ok=True)
        kind = next(k for k in _REPLICA_MDIN if k in Path(stem).name)
        path.write_text(_REPLICA_MDIN[kind], encoding="utf-8")
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
    """
    return write_run_tree(tmp_path, [
        *(f"{rep}/prod_{i:04d}" for rep in ("rep1", "rep3") for i in (1, 2, 3)),
        "rep2/prod_0001",
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
