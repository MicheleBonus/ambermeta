"""`export` keeps `$VARS` as written, and `init` refuses a name its template cannot have.

- `export` loaded the manifest with environment expansion on (the reader's default), so
  `$MYDATA/prod1.out` came out as `C:/Users/alice/scratch/run7/prod1.out`: exit 0,
  "Wrote v2 manifest", and a file that no longer worked on any other machine. Expansion
  is for reading the run files a manifest names, not for rewriting the manifest.
- `init -o tmpl.json` wrote the commented YAML template into a `.json` name and said
  "Created tmpl.json (v2)"; the next `validate --manifest tmpl.json` failed with "JSON
  syntax error at line 1, column 1". The template's value is its comments, which JSON
  cannot carry, so a name other than .yaml/.yml is refused before anything is written.
"""
from __future__ import annotations

import json

import pytest

from ambermeta.cli import main

DOC = {
    "version": 2,
    "simulation": {"topologies": [{"id": "t", "path": "$AM_DATA/system.prmtop", "kind": "normal"}],
                   "starting_structure": "${AM_DATA}/start.rst"},
    "phases": [{"id": "p", "name": "Production", "role": "production", "order": 0}],
    "steps": [{"id": "s1", "name": "prod_1", "phase": "p", "order": 0, "topology": "t",
               "input_coords": {"source": "starting_structure"}, "mdin": "$AM_DATA/prod_1.mdin"}],
}


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("AM_DATA", "/scratch/alice/run7")
    path = tmp_path / "sim.json"
    path.write_text(json.dumps(DOC), encoding="utf-8")
    return path


def test_export_to_a_file_keeps_variables_unexpanded(manifest, tmp_path):
    out = tmp_path / "out.json"

    assert main(["export", str(manifest), "-o", str(out)]) == 0

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["simulation"]["topologies"][0]["path"] == "$AM_DATA/system.prmtop"
    assert written["simulation"]["starting_structure"] == "${AM_DATA}/start.rst"
    assert written["steps"][0]["mdin"] == "$AM_DATA/prod_1.mdin"


def test_export_to_stdout_keeps_variables_unexpanded(manifest, capsys):
    assert main(["export", str(manifest)]) == 0

    assert "/scratch/alice/run7" not in capsys.readouterr().out


@pytest.mark.parametrize("name", ["tmpl.json", "tmpl.txt"])
def test_init_refuses_a_name_the_yaml_template_cannot_have(tmp_path, capsys, name):
    rc = main(["init", str(tmp_path), "-o", name])

    assert rc == 1
    assert not (tmp_path / name).exists()
    assert ".yaml" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["tmpl.yaml", "tmpl.yml"])
def test_init_still_writes_yaml_names(tmp_path, name):
    assert main(["init", str(tmp_path), "-o", name]) == 0
    assert (tmp_path / name).read_text(encoding="utf-8").startswith("# AmberMeta Manifest")
