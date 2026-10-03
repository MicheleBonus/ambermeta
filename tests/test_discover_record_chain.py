"""`discover` builds the chain from the input each run's mdout records.

The shapes are the deposited corpus' own: a continuation across directories, a directory
whose names do not sort in the order its runs ran, stage directories whose names do not
sort in role order, a record that points into another replica, and several topologies.
"""
from __future__ import annotations

from ambermeta.gui.api import core_bridge
from ambermeta.simulation import iter_steps
from tests.conftest import RunSpec, write_run_tree

_MIN = "min\n &cntrl\n  imin = 1, maxcyc = 1000, ntb = 1,\n /\n"
_MD = "md\n &cntrl\n  imin = 0, irest = 1, nstlim = 2500, dt = 0.002, ntb = 2,\n /\n"


def _edges(directory):
    sim = core_bridge.discover_draft(str(directory), recursive=True)["simulation"]
    by_id = {s.id: s for _, s in iter_steps(sim)}
    edges = {s.name: (by_id[s.input_coords.ref].name if s.input_coords.source == "step"
                      else s.input_coords.source)
             for _, s in iter_steps(sim)}
    return sim, edges


def _run(inpcrd, begin, mdin=_MD, **kw):
    return RunSpec(mdin=mdin, elapsed_ps=5.0, begin_ps=begin, inpcrd=inpcrd, **kw)


def test_a_run_continues_a_run_in_another_directory_as_its_mdout_records(tmp_path):
    tree = write_run_tree(tmp_path, [
        ("minimization/04_min_all", _run("03_min_wat.restrt", 0.0, mdin=_MIN)),
        # recorded as an absolute path of the machine the run was on
        ("equilibration/05_nvt_heat", _run("/l/home/user/proj/04_min_all.restrt", 0.0)),
        ("equilibration/06_ntp", _run("05_nvt_heat.restrt", 5.0)),
    ])
    _, edges = _edges(tree)
    assert edges["equilibration/05_nvt_heat"] == "minimization/04_min_all"
    assert edges["equilibration/06_ntp"] == "equilibration/05_nvt_heat"


def test_the_chain_follows_the_record_where_names_do_not_sort_in_run_order(tmp_path):
    (tmp_path / "struc").mkdir()
    (tmp_path / "struc" / "sys_solv.inpcrd").write_text("start\n    10\n")
    tree = write_run_tree(tmp_path, [
        ("equi1/md_nvt_ntr", _run("min_ntr_n.restrt", 0.0)),
        ("equi1/md_nvt_red_01", _run("md_nvt_ntr.restrt", 5.0)),
        ("equi1/min_ntr_h", _run("../struc/sys_solv.inpcrd", 0.0, mdin=_MIN)),
        ("equi1/min_ntr_n", _run("min_ntr_h.restrt", 0.0, mdin=_MIN)),
    ])
    sim, edges = _edges(tree)
    assert edges == {"equi1/min_ntr_h": "starting_structure",
                     "equi1/min_ntr_n": "equi1/min_ntr_h",
                     "equi1/md_nvt_ntr": "equi1/min_ntr_n",
                     "equi1/md_nvt_red_01": "equi1/md_nvt_ntr"}
    order = [s.name for _, s in iter_steps(sim)]
    assert order.index("equi1/min_ntr_h") < order.index("equi1/md_nvt_ntr")


def test_minimization_comes_first_although_its_directory_sorts_later(tmp_path):
    tree = write_run_tree(tmp_path, [
        ("equilibration/run1/05_npt", _run(None, 0.0)),
        ("minimization/run1/01_min", _run(None, 0.0, mdin=_MIN)),
    ])
    sim = core_bridge.discover_draft(str(tree), recursive=True)["simulation"]
    assert [p.role for p in sim.phases][:2] == ["minimization", "equilibration"]


def test_a_record_that_points_into_another_replica_is_not_followed(tmp_path):
    runs = []
    for rep in ("rep1", "rep2"):
        runs += [(f"{rep}/prod_0001", _run("start.rst", 0.0)),
                 (f"{rep}/prod_0002", _run("prod_0001.restrt", 5.0)),
                 (f"{rep}/prod_0003", _run("prod_0002.restrt", 10.0))]
    # rep2's third segment read rep1's restart: the job script's path was copied over
    runs[-1] = ("rep2/prod_0003", _run("/scratch/run/rep1/prod_0002.restrt", 10.0))
    tree = write_run_tree(tmp_path, runs)
    sim, edges = _edges(tree)
    assert edges["rep2/prod_0003"] == "rep2/prod_0002"     # file order, not the record
    report = core_bridge.validate_simulation(sim, {"strict_validation": True}, str(tree))
    found = [s for s in report["suggestions"] if s["kind"] == "input_mismatch"]
    assert len(found) == 1 and "rep1/prod_0002.restrt" in found[0]["evidence"]


def test_a_copy_of_a_runs_restart_links_to_that_run(tmp_path):
    """Replica directories often hold a copy of the equilibration's last restart, and the
    mdout names the copy. The copy is that run's restart: the content decides, which also
    tells the replicas' equilibrations apart."""
    runs = []
    for rep in ("run1", "run2"):
        runs += [(f"equil/{rep}/07_eq", _run("06_eq.restrt", 0.0)),
                 (f"prod/{rep}/prod_0001", _run("07_eq.restrt", 5.0))]
    tree = write_run_tree(tmp_path, runs)
    for rep in ("run1", "run2"):
        (tree / "prod" / rep / "07_eq.restrt").write_bytes(
            (tree / "equil" / rep / "07_eq.restrt").read_bytes())
    sim, edges = _edges(tree)
    assert edges["prod/run1/prod_0001"] == "equil/run1/07_eq"
    assert edges["prod/run2/prod_0001"] == "equil/run2/07_eq"
    assert sim.starting_structure is None       # the copies are not where it began
    report = core_bridge.validate_simulation(sim, {"strict_validation": True}, str(tree))
    names = {s.id: s.name for _, s in iter_steps(sim)}
    mismatched = {names[s["step_id"]] for s in report["suggestions"]
                  if s["kind"] == "input_mismatch"}
    # the equilibrations declare no starting structure, so they have nothing to compare
    assert mismatched == set()


def test_a_script_that_never_ran_makes_no_branch(tmp_path):
    """An analysis script typed as an mdin is drafted as a step and chained by file order,
    but it read nothing: no branch is reported for it."""
    tree = write_run_tree(tmp_path, [
        ("prod/npt_prod_0050", _run("npt_prod_0049.restrt", 0.0)),
        ("prod/npt_prod_0051", _run("npt_prod_0050.restrt", 5.0)),
    ])
    (tree / "prod" / "rep_1_cpptraj_input.in").write_text("trajin npt_prod_0050.nc\n")
    sim, _ = _edges(tree)
    report = core_bridge.validate_simulation(sim, {"strict_validation": True}, str(tree))
    assert not any("continue the same restart" in s["evidence"]
                   for s in report["suggestions"] if s["kind"] == "continuity_gap")


def test_records_that_form_a_cycle_fall_back_to_file_order(tmp_path):
    tree = write_run_tree(tmp_path, [
        ("prod_0001", _run("prod_0002.restrt", 0.0)),
        ("prod_0002", _run("prod_0001.restrt", 5.0)),
    ])
    _, edges = _edges(tree)
    assert edges == {"prod_0001": "starting_structure", "prod_0002": "prod_0001"}


def _prmtop(path, natom):
    names = ["C", "H1"] * (natom // 2) + ["C"] * (natom % 2)
    masses = [12.01 if n == "C" else 1.008 for n in names]
    lines = ["%VERSION VERSION_STAMP = V0001.000",
             "%FLAG POINTERS", "%FORMAT(10I8)", f"{natom:8d}",
             "%FLAG ATOM_NAME", "%FORMAT(20a4)", "".join(f"{n:<4}" for n in names),
             "%FLAG MASS", "%FORMAT(5E16.8)", "".join(f"{m:16.8E}" for m in masses)]
    path.write_text("\n".join(lines) + "\n")


def test_each_run_is_bound_to_the_topology_of_its_own_size(tmp_path):
    _prmtop(tmp_path / "a_vacuum.prmtop", 4)       # first in the pool
    _prmtop(tmp_path / "b_solvated.prmtop", 10)
    tree = write_run_tree(tmp_path, [
        ("prod_0001", _run(None, 0.0, natoms=10)),
        ("prod_0002", _run("prod_0001.restrt", 5.0, natoms=10)),
    ])
    sim = core_bridge.discover_draft(str(tree), recursive=True)["simulation"]
    path_of = {t.id: t.path for t in sim.topologies}
    assert {path_of[s.topology] for _, s in iter_steps(sim)} == {"b_solvated.prmtop"}


_LEAP_CRD = "complex\n     2\n   1.0000000   2.0000000   3.0000000   4.0000000   5.0000000   6.0000000\n"
_START_RST = ("start\n     2  0.0000000\n"
              "   1.0000000   2.0000000   3.0000000   4.0000000   5.0000000   6.0000000\n")


def _replicas_with_copied_start(root, *, crd_at_root=True):
    """Facts round 2, scenario S5: the tLEaP coordinates at the root, and in every replica
    directory a byte-identical copy of the restart its first run read."""
    runs = []
    for rep in ("rep1", "rep2"):
        runs += [(f"{rep}/prod_0001", _run("start.rst", 0.0)),
                 (f"{rep}/prod_0002", _run("prod_0001.restrt", 5.0))]
    tree = write_run_tree(root, runs)
    for rep in ("rep1", "rep2"):
        (tree / rep / "start.rst").write_text(_START_RST)
    if crd_at_root:
        (tree / "complex.crd").write_text(_LEAP_CRD)
    return tree


def test_byte_identical_copies_of_the_recorded_start_are_one_starting_structure(tmp_path):
    tree = _replicas_with_copied_start(tmp_path)
    sim, edges = _edges(tree)
    assert sim.starting_structure == "rep1/start.rst"
    assert edges["rep1/prod_0001"] == edges["rep2/prod_0001"] == "starting_structure"
    report = core_bridge.validate_simulation(sim, {"strict_validation": True}, str(tree))
    assert [s for s in report["suggestions"] if s["kind"] == "input_mismatch"] == []


def test_copies_that_differ_are_still_two_candidates(tmp_path):
    """Two replicas that started from different coordinates have no one starting
    structure; the recorded start is not used, as before."""
    tree = _replicas_with_copied_start(tmp_path)
    (tree / "rep2" / "start.rst").write_text(_START_RST.replace("6.0000000", "7.0000000"))
    sim, _ = _edges(tree)
    assert sim.starting_structure == "complex.crd"
