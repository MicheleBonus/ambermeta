from ambermeta.topology_pool import (
    implies_hmr, Topology, TopologyPool, classify_topology_pool,
)


def test_implies_hmr_boundary():
    assert implies_hmr(0.004) is True
    assert implies_hmr(0.0025) is True     # 2.5 fs -> HMR (was missed at >=0.003)
    assert implies_hmr(0.002) is False
    assert implies_hmr(0.001) is False
    assert implies_hmr(None) is False


def test_pool_keeps_all_and_reports_distinct_systems():
    pool = TopologyPool(topologies=[
        Topology(id="a", path="wt.prmtop", kind="normal", n_atoms=42318),
        Topology(id="b", path="wt_hmr.prmtop", kind="hmr", n_atoms=42318),
        Topology(id="c", path="mut.prmtop", kind="normal", n_atoms=42310),
    ])
    assert len(pool.topologies) == 3            # nothing collapsed
    assert [t.id for t in pool.normal()] == ["a", "c"]
    assert [t.id for t in pool.hmr()] == ["b"]
    assert pool.distinct_systems() == [42310, 42318]


def test_classify_real_topology(sample_md_data_dir):
    pool = classify_topology_pool(str(sample_md_data_dir), ["CH3L1_HUMAN_6NAG.top"])
    assert len(pool.topologies) == 1
    t = pool.topologies[0]
    assert t.path == "CH3L1_HUMAN_6NAG.top"
    assert t.kind in ("normal", "hmr")
    assert t.n_atoms and t.n_atoms > 0
