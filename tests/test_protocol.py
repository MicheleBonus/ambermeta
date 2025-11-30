from __future__ import annotations

from ambermeta.protocol import auto_discover
import ambermeta.protocol as protocol


def _make_parser(details):
    class _Parser:
        def __init__(self, filename):
            self.filename = filename

        def parse(self):
            from types import SimpleNamespace

            return SimpleNamespace(details=SimpleNamespace(**details), filename=self.filename)

    return _Parser


def test_auto_discover_filters_by_role(sample_md_data_dir):
    protocol = auto_discover(
        str(sample_md_data_dir),
        grouping_rules={"CH3L1": "equilibration", "^ntp_prod": "production"},
        include_roles=["production"],
        skip_cross_stage_validation=True,
    )

    assert protocol.stages
    assert all(stage.stage_role == "production" for stage in protocol.stages)
    assert all(stage.name.startswith("ntp_prod") for stage in protocol.stages)


def test_auto_discover_restart_override_for_subset(sample_md_data_dir):
    restart_file = sample_md_data_dir / "ntp_prod_0000.rst"

    protocol = auto_discover(
        str(sample_md_data_dir),
        grouping_rules={"^ntp_prod": "production"},
        include_stems=["ntp_prod_0001"],
        restart_files={"production": str(restart_file)},
        skip_cross_stage_validation=True,
    )

    assert len(protocol.stages) == 1
    stage = protocol.stages[0]
    assert stage.stage_role == "production"
    assert stage.inpcrd is not None
    assert stage.inpcrd.filename == str(restart_file)
    assert stage.restart_path == str(restart_file)


def test_auto_discover_can_isolate_equilibration(sample_md_data_dir):
    protocol = auto_discover(
        str(sample_md_data_dir),
        grouping_rules={"CH3L1": "equilibration", "^ntp_prod": "production"},
        include_roles=["equilibration"],
        skip_cross_stage_validation=True,
    )

    assert len(protocol.stages) == 1
    assert protocol.stages[0].name.startswith("CH3L1_HUMAN_6NAG")
    assert protocol.stages[0].stage_role == "equilibration"


def test_auto_discover_validates_each_stage_once(tmp_path, monkeypatch):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()

    for ext in ("prmtop", "inpcrd"):
        (stage_dir / f"stage1.{ext}").write_text("")

    monkeypatch.setattr(protocol, "PrmtopParser", _make_parser({"natom": 10}))
    monkeypatch.setattr(protocol, "InpcrdParser", _make_parser({"natoms": 12}))

    proto = auto_discover(str(stage_dir), skip_cross_stage_validation=True)

    assert len(proto.stages) == 1
    validation = proto.stages[0].validation
    expected = "Atom count mismatch across ['prmtop', 'inpcrd']: [10, 12]"

    assert validation.count(expected) == 1
