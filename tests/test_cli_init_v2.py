from types import SimpleNamespace

from ambermeta.cli import _init_command
from ambermeta.simulation import load_simulation


def _args(directory, **over):
    base = dict(directory=directory, output="sim.yaml", force=False)
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


def test_the_init_template_validates_without_an_unexpected_error(tmp_path, capsys):
    # The template's steps carry no `name`, which v2 allows. Validating it used to stop
    # with "Unexpected error (ValueError: Each manifest entry must include a 'name'.)"
    # instead of saying what a fresh template is missing: the files it names.
    from ambermeta.cli import main

    _init_command(_args(str(tmp_path)))

    rc = main(["validate", "--manifest", str(tmp_path / "sim.yaml")])

    captured = capsys.readouterr()
    shown = captured.out + captured.err
    assert "Unexpected error" not in shown
    assert rc == 1  # the files the template names do not exist yet
    assert "system.prmtop" in shown
