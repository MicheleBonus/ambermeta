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
