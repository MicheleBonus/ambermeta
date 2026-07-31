import csv
import json
import os
import shutil

import pytest

from ambermeta.cli import main

V2_MANIFEST = """\
version: 2
simulation:
  topologies:
    - id: top_wt
      path: wt.prmtop
      kind: normal
  starting_structure: wt.inpcrd
phases:
  - { id: ph_min, name: Minimization, role: minimization, order: 0 }
  - { id: ph_prod, name: Production, role: production, order: 1 }
steps:
  - id: st_min
    name: minimize
    phase: ph_min
    order: 0
    topology: top_wt
    input_coords: { source: starting_structure }
    mdin: min.in
    mdout: min.out
  - id: st_prod_001
    name: prod_001
    phase: ph_prod
    order: 0
    topology: top_wt
    input_coords: { source: step, ref: st_min }
    mdin: prod_001.in
    mdout: prod_001.out
"""


def test_plan_v2_manifest_prints_structure(tmp_path, capsys):
    m = tmp_path / "sim.yaml"
    m.write_text(V2_MANIFEST, encoding="utf-8")
    rc = main(["plan", str(tmp_path), "--manifest", str(m)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Simulation summary" in out
    assert "Phase: Minimization [minimization]" in out
    assert "Phase: Production [production]" in out
    assert "prod_001" in out                        # step name is printed
    # The chain is reported by the NAME of the step it continues from. Printing the raw
    # input_coords.ref showed the reader an internal id instead.
    assert "input=restart of minimize" in out
    assert "st_min" not in out


def test_plan_v1_manifest_still_uses_flat_path(tmp_path, capsys):
    # a v1 flat manifest must NOT be routed to the v2 presenter
    m = tmp_path / "v1.yaml"
    m.write_text("stages:\n  - name: prod\n    stage_role: production\n", encoding="utf-8")
    rc = main(["plan", str(tmp_path), "--manifest", str(m)])
    out = capsys.readouterr().out
    assert "Simulation summary" not in out          # flat path prints "Protocol summary"
    assert rc in (0, 1)


import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_core_bridge_imports_without_the_gui_extra():
    """`plan`, `discover` and `validate --manifest` all import core_bridge.

    Eagerly importing .routes in the package __init__ made every one of those
    commands require the `gui` extra, which the base install does not have.
    """
    script = textwrap.dedent("""
        import sys, importlib.abc
        class _NoFastAPI(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name == "fastapi" or name.startswith("fastapi."):
                    raise ImportError("No module named 'fastapi'")
                return None
        sys.meta_path.insert(0, _NoFastAPI())
        from ambermeta.gui.api import core_bridge
        assert hasattr(core_bridge, "build_protocol")
        print("ok")
    """)
    proc = subprocess.run([sys.executable, "-c", script],
                          cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


V2_MD_TEST_FILES = """\
version: 2
simulation:
  topologies:
    - id: top_wt
      path: CH3L1_HUMAN_6NAG.top
      kind: normal
  starting_structure: CH3L1_HUMAN_6NAG.crd
phases:
  - { id: ph_prod, name: Production, role: production, order: 0 }
steps:
  - id: st_0001
    name: ntp_prod_0001
    phase: ph_prod
    order: 0
    topology: top_wt
    input_coords: { source: starting_structure }
    mdin: ntp_prod_0001.mdin
    mdout: ntp_prod_0001.mdout
    rst: ntp_prod_0001.rst
  - id: st_0002
    name: ntp_prod_0002
    phase: ph_prod
    order: 1
    topology: top_wt
    input_coords: { source: step, ref: st_0001 }
    mdin: ntp_prod_0002.mdin
    mdout: ntp_prod_0002.mdout
    rst: ntp_prod_0002.rst
"""


@pytest.fixture
def v2_run(tmp_path, sample_md_data_dir):
    """The real sample run, plus a v2 manifest describing two of its steps."""
    for f in sample_md_data_dir.iterdir():
        shutil.copy(f, tmp_path)
    (tmp_path / "sim.yaml").write_text(V2_MD_TEST_FILES, encoding="utf-8")
    return tmp_path


def test_plan_writes_every_requested_artifact(v2_run, capsys):
    rc = main(["plan", str(v2_run), "--manifest", str(v2_run / "sim.yaml"),
               "--summary-path", str(v2_run / "reports" / "summary.json"),
               "--methods-summary-path", str(v2_run / "methods.json"),
               "--stats-csv", str(v2_run / "stats.csv")])
    assert rc == 0
    # All three landed, and the missing parent directory was created, not an error.
    assert (v2_run / "reports" / "summary.json").is_file()
    assert (v2_run / "methods.json").is_file()
    assert (v2_run / "stats.csv").is_file()
    out = capsys.readouterr().out
    assert "summary.json" in out and "methods.json" in out and "stats.csv" in out


def test_plan_summary_matches_the_protocol_the_gui_would_build(v2_run):
    """One engine, one parse: the CLI must not write a different summary than the GUI."""
    from ambermeta.gui.api import core_bridge
    from ambermeta.protocol import to_plain
    from ambermeta.simulation import load_simulation

    main(["plan", str(v2_run), "--manifest", str(v2_run / "sim.yaml"),
          "--summary-path", str(v2_run / "s.json"),
          "--methods-summary-path", str(v2_run / "m.json")])
    sim = load_simulation(str(v2_run / "sim.yaml"))
    protocol = core_bridge.build_protocol(
        core_bridge._flatten_simulation(sim),
        {"strict_validation": True, "allow_gaps": False, "use_relative_paths": True},
        str(v2_run))
    assert json.loads((v2_run / "s.json").read_text(encoding="utf-8")) \
        == to_plain(protocol.to_dict())
    assert json.loads((v2_run / "m.json").read_text(encoding="utf-8")) \
        == to_plain(protocol.to_methods_dict())


def test_plan_stats_csv_has_a_row_per_step(v2_run):
    from ambermeta.protocol import STATS_CSV_COLUMNS

    rc = main(["plan", str(v2_run), "--manifest", str(v2_run / "sim.yaml"),
               "--stats-csv", str(v2_run / "stats.csv")])
    assert rc == 0
    rows = list(csv.DictReader((v2_run / "stats.csv").open(encoding="utf-8")))
    assert [r["stage_name"] for r in rows] == ["ntp_prod_0001", "ntp_prod_0002"]
    assert list(rows[0]) == STATS_CSV_COLUMNS
    assert float(rows[1]["time_end_ps"]) > float(rows[0]["time_end_ps"])


def test_plan_summary_format_follows_the_extension(v2_run):
    main(["plan", str(v2_run), "--manifest", str(v2_run / "sim.yaml"),
          "--summary-path", str(v2_run / "s.yaml")])
    text = (v2_run / "s.yaml").read_text(encoding="utf-8")
    assert not text.lstrip().startswith("{")      # YAML, not JSON in a .yaml
    assert "stages:" in text


def test_plan_strict_fails_cleanly_on_a_missing_file(v2_run, capsys):
    (v2_run / "ntp_prod_0002.mdout").unlink()
    rc = main(["plan", str(v2_run), "--manifest", str(v2_run / "sim.yaml"), "--strict"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "ntp_prod_0002.mdout" in err
    assert "Traceback" not in err


def test_plan_honours_the_global_prmtop_flag(v2_run):
    manifest = v2_run / "no_topo.yaml"
    manifest.write_text(
        V2_MD_TEST_FILES.replace("    topology: top_wt\n", ""), encoding="utf-8")
    main(["plan", str(v2_run), "--manifest", str(manifest),
          "--prmtop", "CH3L1_HUMAN_6NAG.top",
          "--summary-path", str(v2_run / "s.json")])
    summary = json.loads((v2_run / "s.json").read_text(encoding="utf-8"))
    assert summary["stages"][0]["files"]["prmtop"] is not None


def test_plan_refuses_two_outputs_aimed_at_one_file(v2_run, capsys):
    rc = main(["plan", str(v2_run), "--manifest", str(v2_run / "sim.yaml"),
               "--summary-path", str(v2_run / "same.json"),
               "--methods-summary-path", str(v2_run / "same.json")])
    assert rc == 2
    assert "own file" in capsys.readouterr().err
    assert not (v2_run / "same.json").exists()


def test_plan_refuses_two_outputs_aimed_at_one_file_case_insensitively(v2_run, capsys):
    """cli.py's duplicate-target guard keys off os.path.normcase, which folds case on
    Windows/NTFS (so S.json and s.json name one file and must be rejected — two
    artifacts writing to it in sequence would leave one silently clobbered while rc
    stayed 0) and is the identity on POSIX (so they are genuinely different files and
    both should land normally). Assert the property normcase actually reports, not a
    platform guess, so this exercises the real contract on either OS instead of
    skipping one of them."""
    folds_case = os.path.normcase("A") == os.path.normcase("a")
    rc = main(["plan", str(v2_run), "--manifest", str(v2_run / "sim.yaml"),
               "--summary-path", str(v2_run / "S.json"),
               "--methods-summary-path", str(v2_run / "s.json")])
    if folds_case:
        assert rc == 2
        assert "own file" in capsys.readouterr().err
        assert not (v2_run / "S.json").exists()
        assert not (v2_run / "s.json").exists()
    else:
        assert rc == 0
        assert (v2_run / "S.json").exists()
        assert (v2_run / "s.json").exists()
