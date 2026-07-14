# tests/test_continuity_p1.py
from ambermeta.protocol import SimulationStage, SimulationProtocol


class _D:
    def __init__(self, **kw): self.__dict__.update(kw)
class _F:
    def __init__(self, **kw): self.details = _D(**kw)


def _stage(name, *, end=None, start=None, avg_dt=None):
    s = SimulationStage(name=name)
    if end is not None:
        s.mdcrd = _F(time_end=end, avg_dt=avg_dt)
    if start is not None:
        s.inpcrd = _F(time=start)
    return s


def test_real_gap_in_long_run_is_not_snapped_to_zero():
    prev = _stage("a", end=1_000_000.0, avg_dt=0.2)
    curr = _stage("b", start=1_000_060.0)          # a real 60 ps gap at 1 us
    proto = SimulationProtocol(stages=[prev, curr])
    proto.validate()
    assert curr.observed_gap_ps == 60.0
    assert any("60" in n for n in curr.continuity)


def test_frame_interval_noise_is_still_tolerated():
    prev = _stage("a", end=100.0, avg_dt=2.0)
    curr = _stage("b", start=100.05)               # 0.05 ps < half a 2 ps frame
    proto = SimulationProtocol(stages=[prev, curr])
    proto.validate()
    assert curr.observed_gap_ps == 0.0


from ambermeta.protocol import detect_sequence_gaps


def test_missing_member_is_detected():
    names = ["ntp_prod_0001.mdin", "ntp_prod_0002.mdin", "ntp_prod_0004.mdin"]
    assert detect_sequence_gaps(names) == {"ntp_prod": [3]}


def test_complete_sequence_has_no_gaps():
    names = ["prod_1.mdin", "prod_2.mdin", "prod_3.mdin"]
    assert detect_sequence_gaps(names) == {}


def test_single_member_is_not_a_sequence():
    assert detect_sequence_gaps(["prod_1.mdin"]) == {}
