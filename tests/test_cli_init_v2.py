from types import SimpleNamespace

from ambermeta.cli import _init_command
from ambermeta.simulation import load_simulation


def _args(directory, **over):
    base = dict(directory=directory, output="sim.yaml", template="standard",
                auto=False, format=None, validate=False, dry_run=False, force=False, v2=True)
    base.update(over)
    return SimpleNamespace(**base)


def test_init_v2_writes_loadable_v2_manifest(tmp_path):
    rc = _init_command(_args(str(tmp_path)))
    assert rc == 0
    dest = tmp_path / "sim.yaml"
    assert dest.exists()
    text = dest.read_text(encoding="utf-8")
    assert "version: 2" in text
    assert "topologies:" in text
    assert "input_coords:" in text
    # the template is a real, loadable v2 manifest
    sim = load_simulation(str(dest))
    assert sim.version == 2
    assert len(sim.phases) >= 2
    assert any(t.kind == "hmr" for t in sim.topologies)


def test_init_without_v2_is_unchanged(tmp_path):
    # v1 default path still emits a flat stages: manifest
    rc = _init_command(_args(str(tmp_path), output="manifest.yaml", v2=False))
    assert rc == 0
    text = (tmp_path / "manifest.yaml").read_text(encoding="utf-8")
    assert "stages:" in text
    assert "version: 2" not in text
