"""The back-compat gate: a document with no lineage tag must keep the output it has.

`Step.lineage` is worth adding only because it costs untagged users nothing, and nothing
pinned that. This module pins it, for the four artifacts a user actually keeps: the v2
manifest payload, `summary.json`, `methods_summary.json` and the statistics CSV.

Two of the four cannot be byte-compared, for two different reasons, both established by
running them rather than by reading:

* **Absolute paths.** `summary.json` embeds the run's own working directory, so two runs
  of identical input into different directories differ. Normalising the directory to a
  sentinel makes them equal.
* **`sum()` changed in CPython 3.12.** `builtins.sum` became compensated (Neumaier)
  summation and three prmtop floats are computed with it (`total_charge`, `total_mass`,
  `density`/`initial_density`). CI's matrix is 3.9 *and* 3.12, so the two jobs legitimately
  write different bytes for identical input: 15 of `summary.json`'s 967 leaves and 10 of
  `methods_summary.json`'s 507, all three of those names and nothing else. A hardcoded hash
  for either JSON would pass on the machine that generated it and fail the other CI job —
  on the one test every lineage change is told to keep green.

So the two JSON artifacts are compared *structurally* against a committed golden: every key
path and every non-float leaf exactly, float leaves with `pytest.approx`. That is not a
weakening. A lineage regression changes key sets, names, refs, roles or counts, all of which
are compared exactly; the only thing tolerated is the last few bits of a float, which is
precisely the thing that is not evidence of anything.

The statistics CSV holds no paths and is computed with pure-Python Welford accumulators, so
it is byte-stable on both interpreters and is hashed.

The regenerated v2 manifest cannot be compared at all — step and phase ids are
`uuid4().hex[:8]`, fresh every run — so the manifest guarantee is pinned on the round-trip
of a hand-written fixture instead.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple

import pytest

from ambermeta.cli import main
from ambermeta.simulation import (
    Phase, Simulation, Step, load_simulation, simulation_to_payload,
)

GOLDEN_DIR = Path(__file__).parent / "data" / "lineage_backcompat"

# The directory the artifacts were produced in, replaced by this before comparing.
RUN_DIR = "<RUNDIR>"

# sha256 of the normalised stats CSV. Regenerate with
# `python tests/data/lineage_backcompat/regenerate.py` and say why in the commit message.
STATS_CSV_SHA256 = "91a3177f22f553c58172e6d7f2e18cd7e12b3241de68c5a68c73f4dc18446217"


# ---------------------------------------------------------------------------
# The pipeline under test
# ---------------------------------------------------------------------------

def run_pipeline(run_dir: Path, sample_dir: Path) -> None:
    """`discover --write` then `plan -m` with all three artifact flags, in `run_dir`.

    Shared with the golden regenerator so the goldens can never be produced by a
    different invocation than the one the tests check.
    """
    for f in sample_dir.iterdir():
        shutil.copy(f, run_dir)
    assert main(["discover", str(run_dir), "--write", str(run_dir / "draft.yaml")]) == 0
    assert main(["plan", str(run_dir), "-m", str(run_dir / "draft.yaml"),
                 "--summary-path", str(run_dir / "summary.json"),
                 "--methods-summary-path", str(run_dir / "methods_summary.json"),
                 "--stats-csv", str(run_dir / "stats.csv")]) == 0


@pytest.fixture(scope="module")
def untagged_run(tmp_path_factory, sample_md_data_dir) -> Path:
    """One discover+plan of the sample data. Module-scoped: it parses a 12 MB prmtop
    five times, and all four assertions read the same artifacts."""
    run_dir = tmp_path_factory.mktemp("backcompat")
    run_pipeline(run_dir, sample_md_data_dir)
    return run_dir


# ---------------------------------------------------------------------------
# Normalisation and structural comparison
# ---------------------------------------------------------------------------

def normalise(text: str, run_dir: Path) -> str:
    """Replace every spelling of ``run_dir`` in ``text`` with :data:`RUN_DIR`.

    Three spellings reach the artifacts and all three have to go: the native one, the
    JSON-escaped one (JSON doubles a Windows separator), and the posix one. Replacing only
    the forward-slash form once produced a false "the artifacts differ" result.

    The separator that follows the directory is folded into the sentinel too, so a golden
    written on Windows reads the same as one written on POSIX — CI runs ubuntu. Longest
    spelling first, or the bare form eats the prefix of the escaped one and leaves a stray
    separator behind.
    """
    native = str(run_dir)
    escaped = native.replace("\\", "\\\\")
    spellings = {
        escaped + "\\\\": RUN_DIR + "/",
        native + os.sep: RUN_DIR + "/",
        run_dir.as_posix() + "/": RUN_DIR + "/",
        escaped: RUN_DIR,
        native: RUN_DIR,
        run_dir.as_posix(): RUN_DIR,
    }
    for spelling in sorted(spellings, key=len, reverse=True):
        text = text.replace(spelling, spellings[spelling])
    return text


def _leaves(obj: Any, path: str = "$") -> Iterator[Tuple[str, Any]]:
    """Every scalar in a JSON document, keyed by its full path, in document order."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _leaves(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from _leaves(value, f"{path}[{i}]")
    else:
        yield path, obj


def load_normalised(run_dir: Path, name: str, *, embeds_paths: bool) -> Dict[str, Any]:
    """Read an artifact with its own working directory replaced, and prove it happened.

    ``summary.json`` names the files it read, so it must contain the sentinel afterwards:
    a normaliser that matched nothing would compare the golden against whatever spelling
    the generating machine used. ``methods_summary.json`` names none — it is the
    publication artifact — so there the assertion runs the other way and catches a
    working directory that starts leaking into it.
    """
    text = normalise((run_dir / name).read_text(encoding="utf-8"), run_dir)
    native = str(run_dir)
    leftover = [s for s in (native, native.replace("\\", "\\\\"), run_dir.as_posix())
                if s in text]
    assert not leftover, f"{name}: normalisation left {leftover[0]!r} behind"
    if embeds_paths:
        assert RUN_DIR in text, f"{name}: normalisation replaced nothing"
    else:
        assert RUN_DIR not in text, f"{name} started naming the working directory"
    return json.loads(text)


def assert_matches_golden(actual: Dict[str, Any], golden_name: str) -> None:
    expected = json.loads((GOLDEN_DIR / golden_name).read_text(encoding="utf-8"))
    got = dict(_leaves(actual))
    want = dict(_leaves(expected))

    assert set(got) - set(want) == set(), "keys the golden does not have"
    assert set(want) - set(got) == set(), "keys that disappeared from the artifact"
    # Order too: a reordered stage list is a lineage regression, not a formatting change.
    assert list(got) == list(want), "the leaves are the same but their order changed"
    for path, value in want.items():
        if isinstance(value, float):
            # The only tolerated difference, and only because CI's 3.9 and 3.12 jobs
            # legitimately disagree here — see the module docstring.
            assert got[path] == pytest.approx(value), path
        else:
            assert got[path] == value, path


def _with_stable_ids(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrite every phase/step id to `<id:N>` by first appearance.

    `discover` mints ids from `uuid4().hex[:8]`, so a discovered manifest can never be
    compared to a golden verbatim. Renumbering by first appearance keeps everything the
    ids *encode* — which step each `input_coords.ref` points at, which phase each step
    belongs to, and the order of both — while dropping the only part that is random.
    A rewired chain moves a ref to a different ordinal and still fails.
    """
    mapping: Dict[str, str] = {}

    def token(value: str) -> str:
        return mapping.setdefault(value, f"<id:{len(mapping)}>")

    for phase in payload.get("phases", []):
        token(phase["id"])
    for step in payload.get("steps", []):
        token(step["id"])

    def rewrite(node: Any, key: str = "") -> Any:
        if isinstance(node, dict):
            return {k: rewrite(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [rewrite(v, key) for v in node]
        if key in ("id", "ref", "phase") and isinstance(node, str) and node in mapping:
            return mapping[node]
        return node

    return rewrite(payload)


# ---------------------------------------------------------------------------
# The artifacts
# ---------------------------------------------------------------------------

def test_the_stats_csv_is_unchanged(untagged_run):
    text = normalise((untagged_run / "stats.csv").read_text(encoding="utf-8"), untagged_run)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert digest == STATS_CSV_SHA256, (
        "the statistics CSV changed for an untagged document:\n" + text)


def test_the_summary_json_is_unchanged(untagged_run):
    assert_matches_golden(
        load_normalised(untagged_run, "summary.json", embeds_paths=True), "summary.json")


def test_the_methods_summary_is_unchanged(untagged_run):
    assert_matches_golden(
        load_normalised(untagged_run, "methods_summary.json", embeds_paths=False),
        "methods_summary.json")


def test_the_discovered_draft_is_unchanged(untagged_run):
    """`discover`'s OWN output, not just what `plan` computes from it.

    The three artifacts above are derived through `plan`, so they pin what the analysis
    engine makes of a document — not the document `discover` wrote. The chaining and
    phase-grouping work in this PR edits `discover_draft` directly, and a change there
    that happens to leave the summaries alone (a phase renamed, a step reordered, an
    `input_coords` source swapped for an equivalent one) would otherwise land unnoticed.
    """
    payload = simulation_to_payload(load_simulation(str(untagged_run / "draft.yaml")))
    assert_matches_golden(_with_stable_ids(payload), "draft_payload.json")


# ---------------------------------------------------------------------------
# The manifest payload
# ---------------------------------------------------------------------------

# Hand-written rather than regenerated: `discover` mints step and phase ids from
# `uuid4().hex[:8]`, so a regenerated manifest differs from itself run to run and can
# never be a golden. This one exercises every optional key a step can carry, including the
# consumer-side `input_coords.path` that `_adopt_legacy_restart_paths` moves onto the
# producing step at load time.
HAND_WRITTEN_MANIFEST = """\
version: 2
simulation:
  topologies:
    - id: top_wt
      path: wt.prmtop
      kind: normal
    - id: top_wt_hmr
      path: wt_hmr.prmtop
      kind: hmr
  starting_structure: wt.inpcrd
phases:
  - { id: ph_min,  name: Minimization, role: minimization, order: 0 }
  - { id: ph_prod, name: Production,   role: production,   order: 1 }
steps:
  - id: st_min
    name: minimize
    phase: ph_min
    order: 0
    topology: top_wt
    input_coords: { source: starting_structure }
    mdin: min.in
    mdout: min.out
    rst: min.rst
    notes: ["kept verbatim"]
  - id: st_prod_001
    name: prod_001
    phase: ph_prod
    order: 0
    topology: top_wt_hmr
    input_coords: { source: step, ref: st_min }
    mdin: prod_001.in
    mdout: prod_001.out
    mdcrd: prod_001.nc
    rst: prod_001.rst
    gaps: { expected: 0.0, tolerance: 1.0 }
  - id: st_prod_002
    name: prod_002
    phase: ph_prod
    order: 1
    topology: top_wt_hmr
    input_coords: { source: step, ref: st_prod_001, path: prod_001.rst }
    mdin: prod_002.in
    mdout: prod_002.out
  - id: st_prod_003
    name: prod_003
    phase: ph_prod
    order: 2
    topology: top_wt_hmr
    input_coords: { source: path, path: elsewhere/other.rst }
    mdin: prod_003.in
"""


def manifest_payload_json(tmp_dir: Path) -> str:
    src = tmp_dir / "sim.yaml"
    src.write_text(HAND_WRITTEN_MANIFEST, encoding="utf-8")
    return json.dumps(simulation_to_payload(load_simulation(str(src))), indent=2)


def test_the_manifest_payload_is_byte_identical(tmp_path):
    golden = (GOLDEN_DIR / "manifest_payload.json").read_text(encoding="utf-8")
    assert manifest_payload_json(tmp_path) == golden.rstrip("\n")


def test_a_step_with_no_lineage_keeps_the_payload_it_always_had():
    """The negative the whole design rests on: emit-when-set, so an untagged step block is
    exactly the block it was before the field existed. Mirrors the `rst` precedent in
    tests/test_simulation.py."""
    sim = Simulation(phases=[Phase(id="ph_0", name="Min", role="", steps=[
        Step(id="st_0", name="min", mdin="min.in")])])
    assert "lineage" not in simulation_to_payload(sim)["steps"][0]
