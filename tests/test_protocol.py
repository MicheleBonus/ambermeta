from __future__ import annotations

import json

import pytest

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

    # Add at least an mdin file so the stage isn't skipped (prmtop/inpcrd only stages are valid)
    for ext in ("prmtop", "inpcrd", "mdin"):
        (stage_dir / f"stage1.{ext}").write_text("")

    # Use n_atoms attribute to match what the validation code expects
    monkeypatch.setattr(protocol, "PrmtopParser", _make_parser({"n_atoms": 10}))
    monkeypatch.setattr(protocol, "InpcrdParser", _make_parser({"n_atoms": 12}))
    monkeypatch.setattr(protocol, "MdinParser", _make_parser({"length_steps": 100}))

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
    assert all(isinstance(stage.validation, list) for stage in proto.stages)
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


def test_mdcrd_frame_spacing_not_treated_as_timestep(tmp_path, monkeypatch):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()

    for ext in ("mdin", "mdout", "mdcrd"):
        (stage_dir / f"stage.{ext}").write_text("")

    monkeypatch.setattr(protocol, "MdinParser", _make_parser({"length_steps": 1000, "dt": 0.002, "natoms": 10}))
    monkeypatch.setattr(protocol, "MdoutParser", _make_parser({"nstlim": 1000, "dt": 0.002, "natoms": 10}))
    monkeypatch.setattr(
        protocol,
        "MdcrdParser",
        _make_parser({"avg_dt": 0.004, "total_duration": 2.0, "n_frames": 501, "n_atoms": 10}),
    )

    proto = auto_discover(str(stage_dir), skip_cross_stage_validation=True)
    stage = proto.stages[0]

    assert not any("Timestep" in note for note in stage.validation)


def test_mdcrd_duration_compared_to_expected_length(tmp_path, monkeypatch):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()

    for ext in ("mdin", "mdout", "mdcrd"):
        (stage_dir / f"stage.{ext}").write_text("")

    monkeypatch.setattr(protocol, "MdinParser", _make_parser({"length_steps": 1000, "dt": 0.002, "natoms": 10}))
    monkeypatch.setattr(protocol, "MdoutParser", _make_parser({"nstlim": 1000, "dt": 0.002, "natoms": 10}))
    monkeypatch.setattr(
        protocol, "MdcrdParser", _make_parser({"avg_dt": 0.004, "total_duration": 4.0, "n_frames": 1001, "n_atoms": 10})
    )

    proto = auto_discover(str(stage_dir), skip_cross_stage_validation=True)
    stage = proto.stages[0]

    duration_notes = [note for note in stage.validation if "Trajectory duration from mdcrd" in note]

    assert duration_notes
    assert any("mdout" in note for note in duration_notes)


def test_mdcrd_duration_matches_expected(tmp_path, monkeypatch):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()

    for ext in ("mdin", "mdout", "mdcrd"):
        (stage_dir / f"stage.{ext}").write_text("")

    monkeypatch.setattr(protocol, "MdinParser", _make_parser({"length_steps": 1000, "dt": 0.002, "natoms": 10}))
    monkeypatch.setattr(protocol, "MdoutParser", _make_parser({"nstlim": 1000, "dt": 0.002, "natoms": 10}))
    monkeypatch.setattr(
        protocol, "MdcrdParser", _make_parser({"avg_dt": 0.002, "total_duration": 2.0, "n_frames": 1001, "n_atoms": 10})
    )

    proto = auto_discover(str(stage_dir), skip_cross_stage_validation=True)
    stage = proto.stages[0]

    duration_notes = [note for note in stage.validation if "Trajectory duration from mdcrd" in note]

    assert not duration_notes


def test_mdcrd_duration_within_one_timestep_is_accepted(tmp_path, monkeypatch):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()

    for ext in ("mdin", "mdout", "mdcrd"):
        (stage_dir / f"stage.{ext}").write_text("")

    monkeypatch.setattr(protocol, "MdinParser", _make_parser({"length_steps": 1000, "dt": 0.002, "natoms": 10}))
    monkeypatch.setattr(protocol, "MdoutParser", _make_parser({"nstlim": 1000, "dt": 0.002, "natoms": 10}))
    monkeypatch.setattr(
        protocol,
        "MdcrdParser",
        _make_parser({"avg_dt": 0.002, "total_duration": 2.002, "n_frames": 1002, "n_atoms": 10}),
    )

    proto = auto_discover(str(stage_dir), skip_cross_stage_validation=True)
    stage = proto.stages[0]

    duration_notes = [note for note in stage.validation if "Trajectory duration from mdcrd" in note]

    assert not duration_notes


def test_load_protocol_from_gui_export_inherits_global_prmtop(tmp_path, monkeypatch):
    base_dir = tmp_path / "protocol"
    base_dir.mkdir()

    global_prmtop = base_dir / "system.prmtop"
    mdin_file = base_dir / "prod.mdin"
    global_prmtop.write_text("")
    mdin_file.write_text("")

    monkeypatch.setattr(protocol, "PrmtopParser", _make_parser({"n_atoms": 10}))
    monkeypatch.setattr(protocol, "MdinParser", _make_parser({"stage_role": "production", "length_steps": 100}))

    # Mirrors GUI export shape: top-level global_prmtop + stages list, fed straight
    # to auto_discover's in-memory door (the file-reading upgrade path is gone).
    proto = auto_discover(
        str(base_dir),
        manifest=[{"name": "prod", "stage_role": "production", "mdin": "prod.mdin"}],
        global_prmtop="system.prmtop",
        skip_cross_stage_validation=True,
    )

    assert len(proto.stages) == 1
    assert proto.stages[0].prmtop is not None
    assert proto.stages[0].prmtop.filename == str(global_prmtop)


def test_manifest_stage_role_rules_are_applied(tmp_path, monkeypatch):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()

    (stage_dir / "heat_01.mdin").write_text("")

    monkeypatch.setattr(protocol, "MdinParser", _make_parser({"stage_role": None}))

    proto = auto_discover(
        str(stage_dir),
        manifest=[{"name": "heat_01", "mdin": "heat_01.mdin"}],
        grouping_rules={"^heat": "heating"},
        skip_cross_stage_validation=True,
    )

    assert len(proto.stages) == 1
    stage = proto.stages[0]
    assert stage.stage_role == "heating"
    assert any("stage_role_rules" in note for note in stage.validation)


def test_manifest_settings_strict_validation_controls_cross_stage_checks(tmp_path, monkeypatch):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()

    (stage_dir / "stage1.mdcrd").write_text("")
    (stage_dir / "stage2.rst").write_text("")

    monkeypatch.setattr(protocol, "MdcrdParser", _make_parser({"time_end": 20.0}))
    monkeypatch.setattr(protocol, "InpcrdParser", _make_parser({"time": 15.0}))

    stages = [
        {"name": "stage1", "mdcrd": "stage1.mdcrd"},
        {"name": "stage2", "inpcrd": "stage2.rst"},
    ]

    # settings.strict_validation True/False used to translate to
    # skip_cross_stage_validation False/True inside load_protocol_from_manifest;
    # exercise that translation directly against auto_discover.
    strict_proto = auto_discover(str(stage_dir), manifest=stages, skip_cross_stage_validation=False)
    relaxed_proto = auto_discover(str(stage_dir), manifest=stages, skip_cross_stage_validation=True)

    assert any("overlap" in note.lower() for note in strict_proto.stages[1].continuity)
    assert relaxed_proto.stages[1].continuity == []


def test_manifest_settings_allow_gaps_marks_unexpected_gap_as_allowed(tmp_path, monkeypatch):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()

    (stage_dir / "stage1.mdcrd").write_text("")
    (stage_dir / "stage2.rst").write_text("")

    monkeypatch.setattr(protocol, "MdcrdParser", _make_parser({"time_end": 10.0}))
    monkeypatch.setattr(protocol, "InpcrdParser", _make_parser({"time": 15.0}))

    stages = [
        {"name": "stage1", "mdcrd": "stage1.mdcrd"},
        {"name": "stage2", "inpcrd": "stage2.rst"},
    ]

    proto = auto_discover(
        str(stage_dir), manifest=stages,
        skip_cross_stage_validation=False, allow_unexpected_gaps=True,
    )
    assert any("allowed by manifest settings.allow_gaps" in note for note in proto.stages[1].continuity)


def test_gap_expectations_are_reported(tmp_path, monkeypatch):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()

    mdcrd_file = stage_dir / "stage1.mdcrd"
    mdcrd_file.write_text("")
    inpcrd_file = stage_dir / "stage2.rst"
    inpcrd_file.write_text("")

    monkeypatch.setattr(protocol, "MdcrdParser", _make_parser({"time_end": 10.0}))
    monkeypatch.setattr(protocol, "InpcrdParser", _make_parser({"time": 15.0}))

    manifest = [
        {"name": "stage1", "files": {"mdcrd": "stage1.mdcrd"}},
        {
            "name": "stage2",
            "files": {"inpcrd": "stage2.rst"},
            "gaps": {"expected_ps": 5, "tolerance_ps": 1},
        },
    ]

    proto = auto_discover(str(stage_dir), manifest=manifest)

    stage2 = proto.stages[1]

    assert stage2.observed_gap_ps == 5.0
    assert any("within expected window" in note for note in stage2.continuity)
    summary = stage2.summary()
    assert summary["expected_gap_ps"]
    assert summary["observed_gap_ps"]


def test_overlap_detection_adds_clear_message(tmp_path, monkeypatch):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()

    (stage_dir / "stage1.mdcrd").write_text("")
    (stage_dir / "stage2.rst").write_text("")

    monkeypatch.setattr(protocol, "MdcrdParser", _make_parser({"time_end": 20.0}))
    monkeypatch.setattr(protocol, "InpcrdParser", _make_parser({"time": 15.0}))

    manifest = [
        {"name": "stage1", "files": {"mdcrd": "stage1.mdcrd"}},
        {"name": "stage2", "files": {"inpcrd": "stage2.rst"}},
    ]

    proto = auto_discover(str(stage_dir), manifest=manifest)

    stage2 = proto.stages[1]

    assert any("overlap" in note.lower() for note in stage2.continuity)
    assert "overlap" in stage2.summary()["continuity"].lower()


def test_tiny_gap_without_expectation_is_ignored(tmp_path, monkeypatch):
    stage_dir = tmp_path / "protocol"
    stage_dir.mkdir()

    (stage_dir / "stage1.mdcrd").write_text("")
    (stage_dir / "stage2.rst").write_text("")

    monkeypatch.setattr(protocol, "MdcrdParser", _make_parser({"time_end": 10.0, "avg_dt": 0.004}))
    monkeypatch.setattr(protocol, "InpcrdParser", _make_parser({"time": 10.0000001}))

    manifest = [
        {"name": "stage1", "files": {"mdcrd": "stage1.mdcrd"}},
        {"name": "stage2", "files": {"inpcrd": "stage2.rst"}},
    ]

    proto = auto_discover(str(stage_dir), manifest=manifest)

    stage2 = proto.stages[1]

    assert stage2.observed_gap_ps == 0.0
    assert not stage2.continuity


def test_methods_summary_prunes_stats_and_includes_reproducibility_metadata():
    from types import SimpleNamespace

    stage = protocol.SimulationStage(name="stage1", stage_role="equilibration")
    stage.mdin = SimpleNamespace(
        details=SimpleNamespace(
            ensemble="NPT",
            temp_control="Langevin",
            press_control="Monte Carlo",
            dt=0.002,
            length_steps=5000,
            coord_freq=500,
            traj_format="NetCDF",
        )
    )
    stage.mdout = SimpleNamespace(
        details=SimpleNamespace(
            program="PMEMD",
            version="22",
            thermostat="Langevin",
            barostat="Monte Carlo",
            dt=0.002,
            nstlim=5000,
            natoms=1000,
            box_type="Cubic",
            stats=SimpleNamespace(temps=[300.0, 301.0], etots=[-1.0, -2.0]),
        )
    )
    stage.inpcrd = SimpleNamespace(
        details=SimpleNamespace(
            natoms=1000,
            has_box=True,
            box_dimensions=[10.0, 10.0, 10.0],
            box_angles=[90.0, 90.0, 90.0],
            program="sander",
            program_version="20",
        )
    )
    stage.prmtop = SimpleNamespace(
        details=SimpleNamespace(
            natom=1000,
            box_dimensions=[10.0, 10.0, 10.0],
            box_angles=[90.0, 90.0, 90.0],
        )
    )
    stage.mdcrd = SimpleNamespace(
        details=SimpleNamespace(
            n_atoms=1000,
            avg_dt=1.0,
            n_frames=100,
            box_type="Orthogonal",
            program="cpptraj",
        )
    )

    proto = protocol.SimulationProtocol(stages=[stage])
    methods = proto.to_methods_dict()

    assert methods["stages"][0]["md_engine"]["timestep_ps"] == 0.002
    assert methods["stages"][0]["trajectory_output"]["coord_write_interval_steps"] == 500
    assert methods["stages"][0]["system"]["atom_counts"]["prmtop"] == 1000
    assert methods["stage_sequence"] == [{"name": "stage1", "role": "equilibration"}]

    methods_json = json.dumps(methods)
    assert "stats" not in methods_json


def test_to_plain_converts_numpy_scalars_and_tuples_for_yaml():
    """`plan --summary-format yaml` died on a numpy box dimension partway through a file."""
    import yaml
    from ambermeta.protocol import to_plain
    np = pytest.importorskip("numpy")

    payload = {"box": (np.float64(91.8), np.float64(91.8)),
               "count": np.int64(7), "name": "prod", "nested": [{"x": np.float32(1.5)}],
               "untouched": None}
    plain = to_plain(payload)
    assert plain["box"] == [91.8, 91.8] and isinstance(plain["box"], list)
    assert plain["count"] == 7 and type(plain["count"]) is int
    assert plain["name"] == "prod" and plain["untouched"] is None
    # The point of the exercise: it now round-trips through safe_dump.
    assert yaml.safe_load(yaml.safe_dump(plain))["nested"][0]["x"] == 1.5


def test_write_protocol_outputs_creates_parent_directories(tmp_path):
    """The CLI's old writer raised FileNotFoundError on a missing parent."""
    from ambermeta.protocol import write_protocol_outputs
    sim_protocol = protocol.SimulationProtocol()
    target = tmp_path / "reports" / "deep" / "summary.json"

    result = write_protocol_outputs(sim_protocol, {"summary": str(target)})

    assert target.is_file()
    assert result["written"] == [{"artifact": "summary", "path": str(target)}]
    assert result["failed"] == []


def test_write_protocol_outputs_rejects_an_unknown_artifact(tmp_path):
    from ambermeta.protocol import write_protocol_outputs
    with pytest.raises(ValueError, match="unknown plan artifact"):
        write_protocol_outputs(protocol.SimulationProtocol(), {"nope": str(tmp_path / "x")})


def test_write_protocol_outputs_rejects_an_unsupported_summary_format(tmp_path):
    from ambermeta.protocol import write_protocol_outputs
    with pytest.raises(ValueError, match="json or yaml"):
        write_protocol_outputs(protocol.SimulationProtocol(),
                               {"summary": str(tmp_path / "s.toml")},
                               summary_format="toml")
