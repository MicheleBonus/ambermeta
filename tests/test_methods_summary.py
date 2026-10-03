"""The methods summary: a digest of summary.json for writing a Methods section.

Built by `ambermeta.methods_summary.build_methods_summary` from the summary dict alone, so
it is tested two ways: on the bundled sample through the real pipeline, and on synthetic
summary dicts shaped like a multi-phase, multi-replica campaign (and like the older
summary.json that predates the fields the digest prefers).
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from ambermeta.cli import main
from ambermeta.methods_summary import (
    NOT_IN_RUN_FILES, SCHEMA_VERSION, build_methods_summary, dumps_methods_summary,
)
from ambermeta.methods_summary import main as methods_main


# ---------------------------------------------------------------------------
# The sample, through discover + plan
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sample_plan(tmp_path_factory, sample_md_data_dir) -> Path:
    run = tmp_path_factory.mktemp("methods_sample")
    for f in Path(sample_md_data_dir).iterdir():
        shutil.copy(f, run)
    assert main(["discover", str(run), "--write", str(run / "draft.yaml")]) == 0
    assert main(["plan", str(run), "-m", str(run / "draft.yaml"),
                 "--summary-path", str(run / "summary.json"),
                 "--methods-summary-path", str(run / "methods_summary.json")]) == 0
    return run


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_sample_states_what_the_mdout_echoes_and_marks_its_source(sample_plan):
    digest = _load(sample_plan / "methods_summary.json")
    assert digest["schema_version"] == SCHEMA_VERSION
    (phase,) = digest["protocol"]
    settings = phase["settings"]
    # temp0, pres0, taup and comp are not in the sample's mdins: AMBER's values, from the
    # mdout echo, and marked as such.
    assert settings["target_temperature_K"] == {"value": 300.0, "source": "mdout"}
    assert settings["target_pressure_bar"] == {"value": 1.0, "source": "mdout"}
    assert settings["pressure_relaxation_time_ps"] == {"value": 1.0, "source": "mdout"}
    assert settings["compressibility_1e-6_per_bar"] == {"value": 44.6, "source": "mdout"}
    assert settings["barostat"] == {"value": "Berendsen", "source": "mdout"}
    assert settings["thermostat"] == {"value": "Langevin", "source": "mdin"}
    assert settings["collision_frequency_per_ps"] == {"value": 1.0, "source": "mdin"}
    assert settings["time_step_fs"] == {"value": 4.0, "source": "mdin"}
    assert settings["steps_per_run"] == {"value": 5000000, "source": "mdin"}
    assert settings["random_seed"]["source"] == "default"
    assert phase["resolved_seeds"] == {"runs_with_a_seed_in_the_mdout": 5, "distinct": 5}
    assert phase["runs"] == 5 and phase["finished_runs"] == 5
    assert phase["simulated_time_ns"] == 100.0
    assert phase["clock_ps"]["first_run_starts_at"] == 920.0


def test_the_sample_system_counts_protein_residues_without_the_ions(sample_plan):
    (topology,) = _load(sample_plan / "methods_summary.json")["system"]["topologies"]
    residues = topology["residues_by_class"]
    # The old methods summary's `num_solute_residues` (443) counted the 72 ions.
    assert residues["protein"]["residues"] == 362
    assert residues["protein"]["caps"] == {"ACE": 1, "NME": 1}
    assert residues["ions"] == {"Cl-": 38, "K+": 34}
    assert residues["water"]["molecules"] == 14659
    assert residues["water"]["atoms_per_molecule"] == 4
    assert residues["water"]["model_hint"].startswith("4-point")
    assert residues["other"]["4YB"] == {"count": 4, "atoms": 27}
    assert topology["hydrogen_masses"]["repartitioned"] is False
    assert topology["force_field_hints"]["features"] == ["CMAP Correction"]


def test_the_sample_reports_software_gpu_dates_and_grouped_findings(sample_plan):
    digest = _load(sample_plan / "methods_summary.json")
    software = digest["software"]
    assert software["md_engine"] == [{"program": "PMEMD", "version": "22", "runs": 5}]
    assert software["gpus"] == [{"model": "NVIDIA GeForce RTX 2080", "runs": 5}]
    assert software["run_dates"]["first"] == "2023-01-11"
    findings = digest["findings"]
    assert findings["total"] == 5 and findings["patterns"] == 1
    (group,) = findings["grouped"]
    assert group["kind"] == "step_check" and group["occurrences"] == 5
    assert digest["continuity"]["links_measured"] == 4
    assert digest["continuity"]["contiguous"] == 4
    assert digest["not_in_run_files"] == NOT_IN_RUN_FILES


def test_the_sample_digest_is_small_and_names_no_working_directory(sample_plan):
    text = (sample_plan / "methods_summary.json").read_text(encoding="utf-8")
    assert len(text.encode("utf-8")) < 10_000
    assert str(sample_plan) not in text and sample_plan.as_posix() not in text
    assert "null" not in text


def test_the_digest_can_be_rebuilt_from_summary_json(sample_plan, tmp_path):
    summary = _load(sample_plan / "summary.json")
    written = _load(sample_plan / "methods_summary.json")
    assert build_methods_summary(summary) == written
    out = tmp_path / "rebuilt.json"
    assert methods_main([str(sample_plan / "summary.json"), "-o", str(out)]) == 0
    assert _load(out) == written


def test_build_does_not_modify_its_input(sample_plan):
    summary = _load(sample_plan / "summary.json")
    before = copy.deepcopy(summary)
    build_methods_summary(summary)
    assert summary == before


# ---------------------------------------------------------------------------
# Synthetic summaries
# ---------------------------------------------------------------------------

PRMTOP = {
    "filename": "/data/proj/system.prmtop", "natom": 30000, "nres": 9150,
    "total_charge": 1.2e-05, "force_field_type": None,
    "force_field_features": ["CMAP Correction", "Orthorhombic Box"],
    "residue_composition": {"ACE": 1, "ALA": 120, "GLY": 40, "HIE": 3, "HIP": 1, "CYX": 2,
                            "NME": 1, "LIG": 1, "WAT": 8960, "Na+": 12, "Cl-": 9},
    "residue_atom_counts": {"LIG": 40, "WAT": 3, "Na+": 1, "Cl-": 1},
    "hmr_active": True, "hmr_hydrogen_mass_range": [1.008, 3.024],
    "hmr_hydrogen_mass_summary": "1.008-3.024 amu across 15000 H",
    "box_dimensions": [70.0, 70.0, 70.0], "box_angles": [90.0, 90.0, 90.0],
    "solvent_type": "Explicit Solvent",
}


def _stage(name: str, role: str, *, cntrl: Dict[str, Any], control: Dict[str, Any],
           phase: Optional[str] = None, lineage: Optional[str] = None,
           elapsed: Optional[float] = None, continues_from: Optional[str] = None,
           queued: bool = False, wt: Optional[List[Dict[str, Any]]] = None,
           path: Optional[str] = None, mean_t: float = 300.0,
           findings: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    path = path or f"/data/proj/{name}"
    stage: Dict[str, Any] = {"name": name, "stage_role": role, "observed_gap_ps": 0.0,
                             "validation": [f["message"] for f in findings or []],
                             "continuity": [], "load_errors": []}
    if queued:
        stage["status"] = "queued"
    if lineage:
        stage["lineage"] = lineage
    if phase:
        stage["phase"] = phase
    if elapsed is not None:
        stage["elapsed_ps"] = elapsed
    if control:
        stage["mdout_control"] = control
    if findings:
        stage["findings"] = findings
    if continues_from:
        stage["continues_from"] = continues_from
    mdin = {"filename": path + ".mdin", "cntrl_parameters": dict(cntrl, _namelist="cntrl"),
            "wt_schedules": wt or []}
    mdout = None if queued else {
        "filename": path + ".mdout", "program": "PMEMD", "version": "22",
        "run_date": "03/05/2024 at 10:00:00", "gpu_model": "NVIDIA A100",
        "finished_properly": True, "ns_per_day": 500.0, "nstlim": cntrl.get("nstlim", 0),
        "stats": {"time_end": 100.0, "_temps": {"count": 10, "mean": mean_t, "m2": 1.0},
                  "_densities": {"count": 10, "mean": 1.02, "m2": 0.0}},
    }
    stage["files"] = {
        "prmtop": {"filename": PRMTOP["filename"], "details": PRMTOP},
        "inpcrd": {"filename": path + ".rst7",
                   "details": {"time": 0.0, "box_dimensions": [69.5, 69.5, 69.5],
                               "box_angles": [90.0, 90.0, 90.0]}},
        "mdin": {"filename": mdin["filename"], "details": mdin},
        "mdout": None if mdout is None else {"filename": mdout["filename"], "details": mdout},
        "mdcrd": None,
    }
    return stage


MIN = {"imin": 1, "maxcyc": 5000, "ntr": 1, "restraint_wt": 10.0, "restraintmask": ":1-170"}
HEAT = {"irest": 0, "ntx": 1, "ntt": 3, "gamma_ln": 2.0, "tempi": 0.0, "temp0": 300.0,
        "nmropt": 1, "ntb": 1, "dt": 0.002, "nstlim": 50000, "ntc": 2, "ntf": 2}
EQ = {"irest": 1, "ntx": 5, "ntt": 3, "gamma_ln": 2.0, "temp0": 300.0, "ntp": 1,
      "barostat": 2, "dt": 0.002, "nstlim": 250000, "ntc": 2, "ntf": 2, "ntr": 1,
      "restraintmask": ":1-170@CA"}
PROD = {"irest": 1, "ntx": 5, "ntt": 3, "gamma_ln": 2.0, "ntp": 1, "barostat": 2,
        "dt": 0.004, "nstlim": 2500000, "ntwx": 2500, "ntc": 2, "ntf": 2, "ig": -1}
MD_ECHO = {"imin": 0, "ntb": 2, "igb": 0, "cut": 9.0, "ntp": 1, "pres0": 1.0,
           "mcbarint": 100, "comp": 44.6, "taup": 1.0, "ntwx": 2500, "ntpr": 2500,
           "ioutfm": 1, "iwrap": 0, "use_pme": 1, "ntr": 0, "nmropt": 0}


def _campaign() -> Dict[str, Any]:
    """Shared minimisation, heating and a restrained equilibration series, then three
    replicas, each with its own equilibration at its own temperature and four production
    runs; the last production run of rep3 is queued."""
    stages = [
        _stage("min", "minimization", phase="Minimization", cntrl=MIN,
               control={"imin": 1, "maxcyc": 5000, "ncyc": 10, "ntmin": 1, "ntr": 1,
                        "cut": 9.0, "ntb": 1}),
        _stage("heat", "heating", phase="Heating", cntrl=HEAT, elapsed=100.0,
               control=dict(MD_ECHO, ntb=1, ntp=0, irest=0, temp0=300.0, nmropt=1, ig=11),
               wt=[{"quantity": "TEMP0", "istep1": 0, "istep2": 50000,
                    "value1": 0.0, "value2": 300.0}], continues_from="min"),
    ]
    previous = "heat"
    for i, weight in enumerate((5.0, 2.0, 1.0), start=1):
        name = f"eq_restr_{i}"
        stages.append(_stage(name, "equilibration", phase="Equilibration (restrained)",
                             cntrl=dict(EQ, restraint_wt=weight), elapsed=500.0,
                             control=dict(MD_ECHO, ntr=1, temp0=300.0, ig=20 + i),
                             continues_from=previous))
        previous = name
    for r, temp in (("rep1", 299.9), ("rep2", 300.0), ("rep3", 300.1)):
        stages.append(_stage(f"{r}/eq", "equilibration", phase="Equilibration", lineage=r,
                             cntrl=dict(EQ, temp0=temp, ntr=0), elapsed=500.0,
                             control=dict(MD_ECHO, temp0=temp, ig=100 + len(stages)),
                             continues_from="eq_restr_3", mean_t=temp))
        parent = f"{r}/eq"
        for k in range(1, 5):
            name = f"{r}/prod_{k:04d}"
            queued = r == "rep3" and k == 4
            stages.append(_stage(
                name, "production", phase="Production", lineage=r,
                cntrl=dict(PROD, temp0=temp), elapsed=None if queued else 10000.0,
                control={} if queued else dict(MD_ECHO, temp0=temp, ig=1000 + len(stages)),
                continues_from=parent, queued=queued,
                findings=[{"kind": "unfinished_run",
                           "message": "The mdout has no completion marker."}]
                if (r, k) == ("rep2", 3) else None))
            parent = name
    return {
        "totals": {"steps": 0.0, "time_ps": 123600.0, "lineage_count": 3.0,
                   "queued_count": 1.0},
        "stages": stages,
        "findings": [{"kind": "missing_run", "title": "rep3/prod sequence is missing member(s) 5",
                      "lineage": "rep3"}],
        "lineage_findings": [{"severity": "warning", "kind": "parameter",
                              "message": "Members differ in temp0 (rep1: 299.9; rep2: 300.0; "
                                         "rep3: 300.1)."}],
    }


def _phase(digest: Dict[str, Any], name: str) -> Dict[str, Any]:
    (phase,) = [p for p in digest["protocol"] if p["name"] == name]
    return phase


def test_phases_come_in_execution_order_with_their_run_counts():
    digest = build_methods_summary(_campaign())
    assert [p["name"] for p in digest["protocol"]] == [
        "Minimization", "Heating", "Equilibration (restrained)", "Equilibration",
        "Production"]
    production = _phase(digest, "Production")
    assert production["runs"] == 12 and production["queued_runs"] == 1
    assert production["runs_with_output"] == 11
    assert production["replicas"] == 3
    assert production["runs_per_replica"] == {"each": 4, "replicas": 3}
    assert production["simulated_time_ns_per_replica"] == {
        "rep1": 40.0, "rep2": 40.0, "rep3": 30.0}
    assert digest["project"]["queued_runs"] == 1


def test_a_per_replica_equilibration_at_its_own_temperature_names_the_replicas():
    equil = _phase(build_methods_summary(_campaign()), "Equilibration")
    temperature = equil["settings"]["target_temperature_K"]
    values = [temperature["value"]] + [o["value"] for o in temperature["other_values"]]
    assert sorted(values) == [299.9, 300.0, 300.1]
    assert temperature["runs"] == 1
    assert all(len(o["replicas"]) == 1 for o in temperature["other_values"])
    assert equil["replicas"] == 3 and "shared_runs" not in equil


def test_a_restraint_series_is_given_in_run_order():
    restrained = _phase(build_methods_summary(_campaign()), "Equilibration (restrained)")
    restraints = restrained["settings"]["positional_restraints"]
    assert restraints["sequence_in_run_order"] == [
        "5.0 kcal/mol/A^2 on :1-170@CA", "2.0 kcal/mol/A^2 on :1-170@CA",
        "1.0 kcal/mol/A^2 on :1-170@CA"]
    assert "other_values" not in restraints
    assert restrained["settings"]["barostat"] == {"value": "Monte Carlo", "source": "mdin"}
    assert restrained["settings"]["barostat_interval_steps"] == {"value": 100,
                                                                 "source": "mdout"}
    assert restrained["shared_runs"] == 3


def test_heating_and_minimization_settings():
    digest = build_methods_summary(_campaign())
    heating = _phase(digest, "Heating")["settings"]
    assert heating["temperature_schedule"]["value"] == [
        "TEMP0 0.0 -> 300.0 over steps 0-50000"]
    assert heating["initial_temperature_K"] == {"value": 0.0, "source": "mdin"}
    assert heating["start"]["value"] == "new velocities (irest = 0)"
    assert heating["ensemble"]["value"] == "NVT"
    assert heating["nmr_restraints_or_weight_changes"]["value"] == "nmropt = 1"
    minimization = _phase(digest, "Minimization")["settings"]
    assert minimization["run_type"] == {"value": "energy minimization"}
    assert minimization["max_cycles"] == {"value": 5000, "source": "mdin"}
    assert minimization["minimization_method"]["source"] == "mdout"
    assert minimization["positional_restraints"]["value"] == "10.0 kcal/mol/A^2 on :1-170"


def test_the_replicas_block_says_where_the_replicas_branch():
    replicas = build_methods_summary(_campaign())["replicas"]
    assert replicas["count"] == 3
    assert replicas["basis"] == "declared per run in summary.json"
    assert replicas["shared_runs"] == {"runs": 5, "phases": [
        "Minimization", "Heating", "Equilibration (restrained)"]}
    assert replicas["branch_from"] == [{"run": "eq_restr_3 (shared run)", "replicas": 3}]
    assert replicas["phases_per_replica"] == [
        {"phases": "Equilibration -> Production", "replicas": 3}]


def test_the_system_block_classifies_residues_and_hints_the_water_model():
    (topology,) = build_methods_summary(_campaign())["system"]["topologies"]
    residues = topology["residues_by_class"]
    assert residues["protein"]["residues"] == 166
    assert residues["protein"]["histidine_cysteine_and_protonation_variants"] == {
        "CYX": 2, "HIE": 3, "HIP": 1}
    assert residues["water"]["atoms_per_molecule"] == 3
    assert residues["ions"] == {"Na+": 12, "Cl-": 9}
    assert residues["other"] == {"LIG": {"count": 1, "atoms": 40}}
    assert topology["hydrogen_masses"]["repartitioned"] is True
    assert topology["box_at_start"]["edges_A"] == [69.5, 69.5, 69.5]
    assert topology["net_charge_e"] == 0.0


def test_findings_are_grouped_with_one_example_each():
    findings = build_methods_summary(_campaign())["findings"]
    kinds = {g["kind"]: g for g in findings["grouped"]}
    assert kinds["unfinished_run"]["occurrences"] == 1
    assert kinds["unfinished_run"]["example_run"] == "rep2/prod_0003"
    assert "missing_run" in kinds and "replicas_parameter" in kinds


def test_the_digest_is_json_with_no_empty_values_and_stays_small():
    digest = build_methods_summary(_campaign())
    text = dumps_methods_summary(digest)
    assert json.loads(text) == digest
    assert "null" not in text and "[]" not in text and "{}" not in text
    assert len(text) < 20_000


def test_a_large_campaign_stays_within_about_twenty_kilobytes():
    summary = _campaign()
    template = summary["stages"][-2]
    stages = summary["stages"][:6]          # the shared runs and rep1/eq
    for r in range(1, 9):
        for k in range(1, 501):
            stage = copy.deepcopy(template)
            stage["name"] = f"rep{r}/prod_{k:04d}"
            stage["lineage"] = f"rep{r}"
            stage["mdout_control"]["ig"] = r * 10000 + k
            stage.pop("findings", None)
            stage["validation"] = []
            stages.append(stage)
    summary["stages"] = stages
    text = dumps_methods_summary(build_methods_summary(summary))
    assert len(text) < 20_000
    production = _phase(json.loads(text), "Production")
    assert production["runs"] == 4000
    assert production["resolved_seeds"]["distinct"] == 4000


def test_an_older_summary_without_the_new_fields_still_digests():
    """A summary.json from AmberMeta 1.2 has no per-run replica tags, phase names, mdout
    CONTROL DATA, measured per-run times or residue sizes. Replicas come from the directory
    layout, phases from the roles, times from the stated length of finished runs."""
    summary = _campaign()
    for stage in summary["stages"]:
        name = stage["name"]
        for key in ("lineage", "phase", "mdout_control", "elapsed_ps", "continues_from",
                    "findings"):
            stage.pop(key, None)
        folder = name.split("/")[0] if "/" in name else "prep"
        base = name.split("/")[-1]
        for kind in ("mdin", "mdout"):
            entry = stage["files"][kind]
            if entry:
                entry["filename"] = f"/data/proj/{folder}/{base}.{kind}"
                entry["details"] = dict(entry["details"], filename=entry["filename"])
        stage["files"]["prmtop"]["details"] = {k: v for k, v in PRMTOP.items()
                                               if k != "residue_atom_counts"}
    summary.pop("lineage_findings")

    digest = build_methods_summary(summary)

    assert digest["replicas"]["count"] == 3
    assert digest["replicas"]["basis"].startswith("inferred from the directory layout")
    assert [p["name"] for p in digest["protocol"]] == [
        "minimization", "heating", "equilibration", "production"]
    production = _phase(digest, "production")
    assert production["simulated_time_basis"].startswith("stated length")
    assert production["settings"]["target_temperature_K"]["source"] == "mdin"
    # Not in the mdin and not in the older record: the documented default, marked.
    assert production["settings"]["target_pressure_bar"] == {"value": 1.0,
                                                             "source": "default"}
    water = digest["system"]["topologies"][0]["residues_by_class"]["water"]
    assert "atoms_per_molecule" not in water


def test_an_empty_summary_digests_and_a_non_dict_is_refused():
    digest = build_methods_summary({"totals": {}, "stages": []})
    assert digest["project"]["runs"] == 0
    assert "protocol" not in digest           # empty blocks are left out, not written empty
    assert digest["not_in_run_files"] == NOT_IN_RUN_FILES
    with pytest.raises(TypeError):
        build_methods_summary([])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The fields summary.json gained for it
# ---------------------------------------------------------------------------

def test_the_prmtop_reports_atoms_per_residue_outside_the_polymer_sets(sample_md_data_dir):
    from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
    meta = extract_prmtop_metadata(str(Path(sample_md_data_dir) / "CH3L1_HUMAN_6NAG.top"))
    assert meta.residue_atom_counts["WAT"] == 4
    assert meta.residue_atom_counts["K+"] == 1
    assert "ALA" not in meta.residue_atom_counts


def test_summary_json_carries_phase_elapsed_time_and_findings(sample_plan):
    stages = _load(sample_plan / "summary.json")["stages"]
    assert {s["phase"] for s in stages} == {"Production"}
    assert [s["elapsed_ps"] for s in stages] == [20000.0] * 5
    assert all(s["findings"][0]["kind"] == "step_check" for s in stages)
    assert [s.get("continues_from") for s in stages] == [
        None, "ntp_prod_0001", "ntp_prod_0002", "ntp_prod_0003", "ntp_prod_0004"]


def test_the_scan_path_marks_a_runs_own_restart_and_states_when_the_run_started(
        sample_md_data_dir):
    """`plan --recursive` files `ntp_prod_0002.rst`, which that run WROTE, in its input
    slot. Its clock is the run's end, so the start comes from the measured origin."""
    from ambermeta.protocol import auto_discover
    protocol = auto_discover(str(sample_md_data_dir), recursive=True)
    stages = {s["name"]: s for s in protocol.to_dict()["stages"]}
    assert stages["ntp_prod_0002"]["inpcrd_written_by_this_run"] is True
    assert stages["ntp_prod_0002"]["start_time_ps"] == 20920.0
    (production,) = [p for p in protocol.to_methods_dict()["protocol"]
                     if p["name"] == "production"]
    assert production["clock_ps"]["first_run_starts_at"] == 920.0


# ---------------------------------------------------------------------------
# 1.3.0: numbered repeats of a phase are described once
# ---------------------------------------------------------------------------

def test_the_numbered_phases_of_an_alternating_protocol_are_described_once(tmp_path):
    """`discover` numbers the repeats ("Equilibration 2", ...); the digest folds them into
    one entry per phase, as it did when they shared a name, and says how many there were."""
    from tests.conftest import alternating_runs, write_run_tree

    tree = write_run_tree(tmp_path, alternating_runs("rep1/", [300.0, 299.9, 300.1])
                          + alternating_runs("rep2/", [299.9, 300.1, 300.0]))
    assert main(["discover", str(tree), "--write", str(tree / "sim.yaml")]) == 0
    assert main(["plan", str(tree), "-m", str(tree / "sim.yaml"),
                 "--methods-summary-path", str(tree / "methods.json")]) == 0
    digest = _load(tree / "methods.json")
    assert [(p["name"], p["document_phases"], p["runs"]) for p in digest["protocol"]] == [
        ("Equilibration", 3, 6), ("Production", 3, 6)]
    assert digest["project"]["phases"] == 2
    temperature = _phase(digest, "Equilibration")["settings"]["target_temperature_K"]
    assert temperature["sequence_in_run_order"] == [300.0, 299.9, 300.1]
    assert digest["replicas"]["phases_per_replica"] == [
        {"phases": "Equilibration -> Production", "replicas": 2}]


def test_only_numbered_repeats_of_a_named_phase_of_the_same_role_are_folded():
    stages = [
        _stage("a", "equilibration", phase="NVT 1", cntrl=EQ, control=MD_ECHO, elapsed=1.0),
        _stage("b", "equilibration", phase="NVT 2", cntrl=EQ, control=MD_ECHO, elapsed=1.0),
        _stage("c", "equilibration", phase="Production", cntrl=EQ, control=MD_ECHO,
               elapsed=1.0),
        _stage("d", "production", phase="Production 2", cntrl=PROD, control=MD_ECHO,
               elapsed=1.0),
    ]
    digest = build_methods_summary({"totals": {}, "stages": stages})
    assert [p["name"] for p in digest["protocol"]] == ["NVT 1", "NVT 2", "Production",
                                                       "Production 2"]
    assert all("document_phases" not in p for p in digest["protocol"])


# ---------------------------------------------------------------------------
# 1.3.0: an older summary keeps the ensemble of its NPT runs
# ---------------------------------------------------------------------------

def _legacy_stage(name: str, cntrl: Optional[Dict[str, Any]], barostat: str) -> Dict[str, Any]:
    """A stage as a summary.json without `mdout_control` holds it: the whole-file mdout
    parser's thermostat and barostat names, and the mdin's raw `&cntrl`."""
    mdout = {"filename": f"{name}.mdout", "finished_properly": True, "nstlim": 1000,
             "thermostat": "Langevin", "barostat": barostat, "target_temp": 300.0,
             "cutoff": 9.0, "run_type": "MD"}
    mdin = None if cntrl is None else {"filename": f"{name}.mdin", "cntrl_parameters": cntrl}
    return {"name": name, "stage_role": "equilibration", "validation": [],
            "continuity": [], "load_errors": [],
            "files": {"mdout": {"filename": mdout["filename"], "details": mdout},
                      "mdin": None if mdin is None else {"filename": mdin["filename"],
                                                         "details": mdin},
                      "prmtop": None, "inpcrd": None, "mdcrd": None}}


_LEGACY_NPT = {"imin": 0, "irest": 1, "ntx": 5, "nstlim": 1000, "dt": 0.002, "ntt": 3,
               "ntb": 2, "ntp": 1, "barostat": 2}
_LEGACY_NVT = {"imin": 0, "irest": 1, "ntx": 5, "nstlim": 1000, "dt": 0.002, "ntt": 3,
               "ntb": 1}


def test_an_older_summary_keeps_the_ensemble_of_its_npt_runs():
    """Review round 4: with no `mdout_control`, the legacy echo marks the pressure scaling
    unknown, and that switched off the ensemble too -- an equilibration phase of 14 NPT and
    6 NVT runs read "ensemble NVT, runs 6"."""
    stages = ([_legacy_stage(f"npt_{i}", _LEGACY_NPT, "Monte Carlo") for i in range(14)]
              + [_legacy_stage(f"nvt_{i}", _LEGACY_NVT, "None") for i in range(6)])
    (phase,) = build_methods_summary({"totals": {}, "stages": stages})["protocol"]
    ensemble = phase["settings"]["ensemble"]
    assert ensemble["value"] == "NPT" and ensemble["runs"] == 14
    assert ensemble["sequence_in_run_order"] == ["NPT", "NVT"]
    # the mdin states ntp, so the scaling is known as well
    assert phase["settings"]["pressure_scaling"] == {"value": "isotropic", "source": "mdin",
                                                     "runs": 14}


def test_an_older_mdout_without_its_mdin_still_says_npt():
    (phase,) = build_methods_summary(
        {"totals": {}, "stages": [_legacy_stage("bare", None, "Berendsen")]})["protocol"]
    assert phase["settings"]["ensemble"] == {"value": "NPT", "source": "derived"}
    # how the pressure was scaled is not in the older record
    assert "pressure_scaling" not in phase["settings"]
