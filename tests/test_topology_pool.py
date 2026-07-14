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


def test_hmr_swap_uses_0002_boundary(monkeypatch):
    import ambermeta.protocol as proto

    class _MdinDetails:
        def __init__(self, dt): self.dt = dt
    class _Mdin:
        def __init__(self, dt): self.details = _MdinDetails(dt)

    stages = [proto.SimulationStage(name="prod", mdin=_Mdin(0.0025))]
    monkeypatch.setattr(proto, "_safe_parse", lambda *a, **k: "HMR_TOPO")
    monkeypatch.setattr(proto.os.path, "exists", lambda p: True)
    proto._apply_global_and_hmr_prmtop(
        stages, ".", global_prmtop=None, hmr_prmtop="wt_hmr.prmtop", strict=False)
    assert stages[0].prmtop == "HMR_TOPO"   # 2.5 fs now triggers HMR
