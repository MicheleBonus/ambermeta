from __future__ import annotations

import json

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


def test_manifest_bypasses_inference_and_preserves_order(tmp_path, monkeypatch):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()

    for stem in ("beta", "alpha"):
        (stage_dir / f"{stem}.mdin").write_text("")
        (stage_dir / f"{stem}.mdout").write_text("")
    (stage_dir / "beta.rst").write_text("")

    mdin_parser = _make_parser({"stage_role": "placeholder"})
    mdout_parser = _make_parser({"natoms": 10, "dt": 0.1})
    inpcrd_parser = _make_parser({"natoms": 10})

    monkeypatch.setattr(protocol, "MdinParser", mdin_parser)
    monkeypatch.setattr(protocol, "MdoutParser", mdout_parser)
    monkeypatch.setattr(protocol, "InpcrdParser", inpcrd_parser)

    manifest = [
        {
            "name": "beta",
            "stage_role": "equilibration",
            "files": {"mdin": "beta.mdin", "mdout": "beta.mdout", "inpcrd": "beta.rst"},
        },
        {
            "name": "alpha",
            "stage_role": "production",
            "files": {"mdin": "alpha.mdin", "mdout": "alpha.mdout"},
        },
    ]

    proto = auto_discover(str(stage_dir), manifest=manifest, skip_cross_stage_validation=True)

    assert [stage.name for stage in proto.stages] == ["beta", "alpha"]
    assert all(stage.validation is not None for stage in proto.stages)
    assert proto.stages[0].inpcrd is not None


def test_manifest_backfills_restart_when_missing(tmp_path, monkeypatch):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()

    (stage_dir / "prod.mdin").write_text("")
    restart_file = stage_dir / "prod.rst"
    restart_file.write_text("")

    monkeypatch.setattr(protocol, "MdinParser", _make_parser({"stage_role": "production"}))
    monkeypatch.setattr(protocol, "InpcrdParser", _make_parser({"natoms": 42}))

    manifest = [{"name": "prod_stage", "stage_role": "production", "files": {"mdin": "prod.mdin"}}]

    proto = auto_discover(
        str(stage_dir),
        manifest=manifest,
        restart_files={"prod_stage": str(restart_file)},
        skip_cross_stage_validation=True,
    )

    assert len(proto.stages) == 1
    stage = proto.stages[0]
    assert stage.inpcrd is not None
    assert stage.restart_path == str(restart_file)


def test_manifest_notes_are_preserved(tmp_path, monkeypatch):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()

    (stage_dir / "stage.mdin").write_text("")
    (stage_dir / "stage.mdout").write_text("")

    monkeypatch.setattr(protocol, "MdinParser", _make_parser({"stage_role": "prep"}))
    monkeypatch.setattr(protocol, "MdoutParser", _make_parser({"natoms": 5, "dt": 0.1}))

    manifest = [
        {
            "name": "stage",
            "files": {"mdin": "stage.mdin", "mdout": "stage.mdout"},
            "notes": ["prmtop intentionally omitted"],
        }
    ]

    proto = auto_discover(str(stage_dir), manifest=manifest, skip_cross_stage_validation=True)

    assert proto.stages[0].validation
    assert "prmtop intentionally omitted" in proto.stages[0].validation


def test_load_protocol_from_manifest_uses_parent_directory(tmp_path, monkeypatch):
    stage_dir = tmp_path / "inputs"
    stage_dir.mkdir()

    (stage_dir / "alpha.mdin").write_text("")
    manifest_path = tmp_path / "protocol.json"
    manifest_path.write_text(
        json.dumps({"alpha": {"files": {"mdin": "inputs/alpha.mdin"}, "stage_role": "prep"}})
    )

    monkeypatch.setattr(protocol, "MdinParser", _make_parser({"stage_role": "prep"}))

    proto = protocol.load_protocol_from_manifest(manifest_path, skip_cross_stage_validation=True)

    assert len(proto.stages) == 1
    assert proto.stages[0].mdin.filename == str(stage_dir / "alpha.mdin")
