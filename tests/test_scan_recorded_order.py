"""`plan DIR --recursive` orders runs by the inputs their mdouts recorded.

The scan path ordered stages by file name and compared neighbours. On a protocol whose
names do not sort in run order -- one short equilibration before every production
segment, `eq_0001 -> prod_0001 -> eq_0002 -> ...` -- every `eq_*` sorts before every
`prod_*`, and a continuous chain was reported as +20,000 ps gaps and a -42,000 ps
overlap; a starting structure called `start.rst`, sorted after them, "overlapped" all of
it. The scan now uses the rule `discover` uses (`ambermeta.run_order`).
"""
from __future__ import annotations

from ambermeta.cli import main
from ambermeta.protocol import auto_discover
from tests.conftest import RunSpec, alternating_runs, md_mdin, write_run_tree

_START = "start\n     2  0.0000000\n   1.0   2.0   3.0   4.0   5.0   6.0\n"


def _problems(protocol):
    return {s.name: [n for n in s.continuity if not n.startswith("INFO")]
            for s in protocol.stages if any(not n.startswith("INFO") for n in s.continuity)}


def test_interleaved_names_are_measured_in_the_order_the_runs_ran(tmp_path):
    tree = write_run_tree(tmp_path, alternating_runs("", [300.0, 299.9, 300.1]))
    (tree / "start.rst").write_text(_START)
    protocol = auto_discover(str(tree), recursive=True)
    assert _problems(protocol) == {}
    runs = [s.name for s in protocol.stages if s.is_run]
    assert runs == ["eq_0001", "prod_0001", "eq_0002", "prod_0002", "eq_0003", "prod_0003"]
    gaps = {s.name: s.observed_gap_ps for s in protocol.stages}
    assert gaps["eq_0001"] is None
    assert all(gaps[name] == 0.0 for name in runs[1:])
    # the starting structure is a stage, but not a run, and is not measured
    start = next(s for s in protocol.stages if s.name == "start")
    assert not start.is_run and start.continuity == [] and start.observed_gap_ps is None
    assert protocol.stages[0] is start


def test_the_summary_names_the_run_each_run_continued(tmp_path):
    tree = write_run_tree(tmp_path, alternating_runs("", [300.0, 300.0]))
    stages = auto_discover(str(tree), recursive=True).to_dict()["stages"]
    assert {s["name"]: s.get("continues_from") for s in stages} == {
        "eq_0001": None, "prod_0001": "eq_0001", "eq_0002": "prod_0001",
        "prod_0002": "eq_0002"}


def test_replicas_with_interleaved_names(tmp_path):
    runs = []
    for rep in ("rep1", "rep2", "rep3"):
        runs += alternating_runs(f"{rep}/", [300.0, 299.9, 300.1])
    tree = write_run_tree(tmp_path, runs)
    protocol = auto_discover(str(tree), recursive=True)
    assert _problems(protocol) == {}
    assert {s.lineage for s in protocol.stages} == {"rep1", "rep2", "rep3"}
    measured = [s for s in protocol.stages if s.observed_gap_ps is not None]
    assert len(measured) == 3 * 5 and all(s.observed_gap_ps == 0.0 for s in measured)


def test_a_run_in_another_directory_is_measured_against_the_run_it_read(tmp_path):
    """eq/ and prod/ directories, one chain running back and forth between them."""
    runs = []
    for stem, spec in alternating_runs("", [300.0, 300.0]):
        kind = stem.split("_")[0]
        runs.append((f"{kind}/{stem}", spec))
    tree = write_run_tree(tmp_path, runs)
    protocol = auto_discover(str(tree), recursive=True)
    assert _problems(protocol) == {}
    parents = {s.name: s.parent_id for s in protocol.stages}
    assert parents["eq/eq_0002"] == "prod/prod_0001"
    assert parents["prod/prod_0002"] == "eq/eq_0002"


def test_a_shared_equilibration_feeding_replicas_is_measured(tmp_path):
    runs = [("common/equil_npt", RunSpec(mdin=md_mdin("equil", 500), elapsed_ps=1.0,
                                         begin_ps=0.0, inpcrd="start.rst"))]
    for rep in ("rep1", "rep2"):
        runs.append((f"{rep}/prod_0001",
                     RunSpec(mdin=md_mdin("prod", 10000), elapsed_ps=20.0, begin_ps=1.0,
                             inpcrd="../common/equil_npt.restrt")))
        runs.append((f"{rep}/prod_0002",
                     RunSpec(mdin=md_mdin("prod", 10000), elapsed_ps=20.0, begin_ps=21.0,
                             inpcrd="prod_0001.restrt")))
    tree = write_run_tree(tmp_path, runs)
    protocol = auto_discover(str(tree), recursive=True)
    assert _problems(protocol) == {}
    heads = {s.name: (s.parent_id, s.observed_gap_ps) for s in protocol.stages
             if s.name.endswith("prod_0001")}
    assert heads == {"rep1/prod_0001": ("common/equil_npt", 0.0),
                     "rep2/prod_0001": ("common/equil_npt", 0.0)}


def test_a_tree_without_recorded_inputs_keeps_the_name_order(tmp_path):
    tree = write_run_tree(tmp_path, [
        ("prod_0001", RunSpec(mdin=md_mdin("prod", 10000), elapsed_ps=20.0, begin_ps=0.0)),
        ("prod_0002", RunSpec(mdin=md_mdin("prod", 10000), elapsed_ps=20.0, begin_ps=20.0)),
    ])
    protocol = auto_discover(str(tree), recursive=True)
    assert [s.step_id for s in protocol.stages] == [None, None]
    assert protocol.stages[1].observed_gap_ps == 0.0


def test_plan_recursive_passes_strict_on_the_interleaved_tree(tmp_path, capsys):
    tree = write_run_tree(tmp_path, alternating_runs("", [300.0, 299.9, 300.1]))
    (tree / "start.rst").write_text(_START)
    assert main(["plan", "--recursive", str(tree), "--strict"]) == 0
    out = capsys.readouterr().out
    assert "overlap" not in out and "Gap detected" not in out


# --- PR #93 review, S1: runs the records do not link are still measured ---------------

def _rolling(root, gap_before_3=0.0):
    """A job script that runs `pmemd -c restart.rst -r prod_$i.restrt` and then copies the
    new restart to `restart.rst`: every mdout records `restart.rst`, a file no run wrote."""
    runs, clock = [], 0.0
    for i in (1, 2, 3):
        if i == 3:
            clock += gap_before_3
        runs.append((f"prod_{i:04d}", RunSpec(mdin=md_mdin("prod", 10000), elapsed_ps=20.0,
                                             begin_ps=clock, inpcrd="restart.rst")))
        clock += 20.0
    tree = write_run_tree(root, runs)
    (tree / "restart.rst").write_text(_START)
    return tree


def test_a_rolling_restart_is_measured_run_by_run(tmp_path, capsys):
    tree = _rolling(tmp_path / "ok")
    protocol = auto_discover(str(tree), recursive=True)
    assert _problems(protocol) == {}
    assert [s.observed_gap_ps for s in protocol.stages if s.is_run] == [None, 0.0, 0.0]
    # the order link is not a claim about which restart was read
    assert all("continues_from" not in s for s in protocol.to_dict()["stages"])
    assert main(["plan", "--recursive", str(tree), "--strict"]) == 0


def test_a_gap_in_a_rolling_restart_is_reported_and_fails_strict(tmp_path, capsys):
    tree = _rolling(tmp_path / "gap", gap_before_3=5.0)
    protocol = auto_discover(str(tree), recursive=True)
    assert _problems(protocol) == {
        "prod_0003": ["Gap detected without stated expectation; verify continuity."]}
    capsys.readouterr()
    assert main(["plan", "--recursive", str(tree), "--strict"]) == 1
    out = capsys.readouterr().out
    assert "Continuity note: prod_0003: Gap detected without stated expectation" in out


def test_a_deposit_without_restarts_still_shows_the_gap_between_directories(tmp_path):
    """equil/ then prod/, only the starting structure deposited, a 5-ps gap at the
    handoff. Only the first record resolves; the handoff is measured by order."""
    runs, clock, previous = [], 0.0, "../start.rst"
    for stem in ("equil/eq_0001", "equil/eq_0002", "prod/prod_0001", "prod/prod_0002"):
        if stem == "prod/prod_0001":
            clock += 5.0
        runs.append((stem, RunSpec(mdin=md_mdin("md", 10000), elapsed_ps=20.0,
                                   begin_ps=clock, inpcrd=previous)))
        previous = stem.rpartition("/")[2] + ".restrt"
        clock += 20.0
    tree = write_run_tree(tmp_path, runs)
    for restart in tree.rglob("*.restrt"):
        restart.unlink()
    (tree / "start.rst").write_text(_START)
    protocol = auto_discover(str(tree), recursive=True)
    assert _problems(protocol) == {
        "prod/prod_0001": ["Gap detected without stated expectation; verify continuity."]}
    assert {s.name: s.observed_gap_ps for s in protocol.stages if s.is_run} == {
        "equil/eq_0001": None, "equil/eq_0002": 0.0, "prod/prod_0001": 5.0,
        "prod/prod_0002": 0.0}


def test_runs_that_start_together_from_one_file_are_not_chained_by_order(tmp_path):
    """Two runs recording the same starting structure at the same start time are a
    fan-out, not a sequence: neither is measured against the other."""
    tree = write_run_tree(tmp_path, [
        (name, RunSpec(mdin=md_mdin("md", 10000), elapsed_ps=20.0, begin_ps=0.0,
                       inpcrd="start.rst")) for name in ("run_a", "run_b")])
    (tree / "start.rst").write_text(_START)
    protocol = auto_discover(str(tree), recursive=True)
    assert _problems(protocol) == {}
    assert [s.observed_gap_ps for s in protocol.stages if s.is_run] == [None, None]


def test_the_order_fallback_does_not_cross_between_sibling_replica_directories(tmp_path, capsys):
    """PR #93 verification, N1. A nested sweep (`300K/rep1`, `310K/rep2`) cannot be tagged,
    so its runs are one member; the heads record cluster paths that resolve to nothing
    here. Measuring rep2's first run against rep1's last reported a 40-ps overlap and failed
    `--strict`. Sibling directories of one role are not chained by order."""
    runs = []
    for directory in ("300K/rep1", "310K/rep2"):
        runs.append((f"{directory}/prod_0001",
                     RunSpec(mdin=md_mdin("prod", 10000), elapsed_ps=20.0, begin_ps=0.0,
                             inpcrd=f"/cluster/{directory}/start.rst")))
        runs.append((f"{directory}/prod_0002",
                     RunSpec(mdin=md_mdin("prod", 10000), elapsed_ps=20.0, begin_ps=20.0,
                             inpcrd="prod_0001.restrt")))
    tree = write_run_tree(tmp_path, runs)
    protocol = auto_discover(str(tree), recursive=True)
    assert {s.lineage for s in protocol.stages} == {None}
    assert _problems(protocol) == {}
    assert {s.name: s.observed_gap_ps for s in protocol.stages} == {
        "300K/rep1/prod_0001": None, "300K/rep1/prod_0002": 0.0,
        "310K/rep2/prod_0001": None, "310K/rep2/prod_0002": 0.0}
    assert main(["plan", "--recursive", str(tree), "--strict"]) == 0
    assert "overlap" not in capsys.readouterr().out
