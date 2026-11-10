"""Two steps that share a name keep their own missing-file errors.

The validation report's missing-file pass was keyed by step name, so in a document with
two phases that each hold a step called "step 1" (the name the GUI gives a new step),
a missing mdout on one was reported on both: the complete step showed `ok=false` and the
panel counted two failing stages for one missing file. Every step of a document has its
own id, and the engine stage carries it, so that is the key.
"""
from __future__ import annotations

from ambermeta.gui.api.core_bridge import validate_simulation
from ambermeta.simulation import InputCoords, Phase, Simulation, Step


def _twins():
    complete = Step(id="a1", name="twin", input_coords=InputCoords(source="starting_structure"),
                    mdin="ntp_prod_0001.mdin", mdout="ntp_prod_0001.mdout")
    broken = Step(id="b1", name="twin", input_coords=InputCoords(source="starting_structure"),
                  mdin="ntp_prod_0002.mdin", mdout="missing_twin.mdout")
    return Simulation(phases=[Phase(id="pa", name="A", role="production", steps=[complete]),
                              Phase(id="pb", name="B", role="production", steps=[broken])])


def _issues(sample_md_data_dir):
    report = validate_simulation(_twins(), {"strict_validation": True}, str(sample_md_data_dir))
    return [s for s in report["stage_issues"] if s["name"] == "twin"]


def test_only_the_step_with_the_missing_file_reports_it(sample_md_data_dir):
    issues = _issues(sample_md_data_dir)

    assert len(issues) == 2
    missing = [[m["path"] for m in s["missing_files"]] for s in issues]
    assert sorted(missing) == [[], ["missing_twin.mdout"]]


def test_the_complete_twin_is_not_counted_as_failing(sample_md_data_dir):
    complete = [s for s in _issues(sample_md_data_dir) if not s["missing_files"]]

    assert len(complete) == 1
    assert not any("missing_twin.mdout" in e for e in complete[0]["errors"])
