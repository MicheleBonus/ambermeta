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
