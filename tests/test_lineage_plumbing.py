# tests/test_lineage_plumbing.py
"""The lineage tag and the producer link have to survive the trip from the v2 document
to the analysis engine.

Design section 7.1 warns that setting the tag in one place is a silent no-op, and it is
worse than that: `document_to_payload` rebuilds every entry from a closed whitelist, and
`validate_manifest` rejects no unknown key, so a half-plumbed tag fails with no error
anywhere. Every assertion below reads the value off `SimulationStage` at the far end of
`build_protocol`, never off one of the three dicts in between.
"""
import pytest

from ambermeta.gui.api import core_bridge
from ambermeta.simulation import load_simulation

# The canonical campaign of design section 6: one shared equilibration, two replicas, one
# of which is itself chunked. It exercises everything ruling 13.1.2 cares about — an
# untagged stage beside tagged ones, two heads reading one producer, and a within-lineage
# chain — in four steps.
TAGGED_MANIFEST = """\
version: 2
simulation:
  topologies: []
  starting_structure: start.inpcrd
phases:
  - { id: ph_eq, name: Equilibration, role: equilibration, order: 0 }
  - { id: ph_prod, name: Production, role: production, order: 1 }
steps:
  - id: st_eq
    name: equil
    phase: ph_eq
    order: 0
    input_coords: { source: starting_structure }
    mdin: equil.mdin
    rst: equil.rst
  - id: st_a1
    name: rep1/prod_0001
    phase: ph_prod
    order: 0
    lineage: rep1
    input_coords: { source: step, ref: st_eq }
    mdin: rep1/prod_0001.mdin
    rst: rep1/prod_0001.rst
  - id: st_a2
    name: rep1/prod_0002
    phase: ph_prod
    order: 1
    lineage: rep1
    input_coords: { source: step, ref: st_a1 }
    mdin: rep1/prod_0002.mdin
  - id: st_b1
    name: rep2/prod_0001
    phase: ph_prod
    order: 2
    lineage: rep2
    input_coords: { source: step, ref: st_eq }
    mdin: rep2/prod_0001.mdin
"""

_MDIN = "prod\n&cntrl\n  imin=0, nstlim=1000, dt=0.002, ntb=2,\n/\n"

SETTINGS = {"strict_validation": True, "allow_gaps": False, "use_relative_paths": True}


@pytest.fixture
def tagged_run(tmp_path):
    """The manifest above, with a real mdin behind every step.

    mdin is plain text, so the whole fixture parses in milliseconds; no prmtop is needed
    because nothing here asserts on file metadata.
    """
    for rel in ("equil.mdin", "rep1/prod_0001.mdin", "rep1/prod_0002.mdin",
                "rep2/prod_0001.mdin"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_MDIN, encoding="utf-8")
    (tmp_path / "sim.yaml").write_text(TAGGED_MANIFEST, encoding="utf-8")
    return tmp_path


def _stages(run):
    sim = load_simulation(str(run / "sim.yaml"))
    protocol = core_bridge.build_protocol(
        core_bridge._flatten_simulation(sim), dict(SETTINGS), str(run))
    return protocol.stages


def test_the_lineage_tag_reaches_the_analysis_stages(tagged_run):
    stages = _stages(tagged_run)
    assert [s.name for s in stages] == [
        "equil", "rep1/prod_0001", "rep1/prod_0002", "rep2/prod_0001"]
    assert [s.lineage for s in stages] == [None, "rep1", "rep1", "rep2"]


def test_the_producer_link_reaches_the_analysis_stages(tagged_run):
    stages = _stages(tagged_run)
    assert [s.step_id for s in stages] == ["st_eq", "st_a1", "st_a2", "st_b1"]
    # A step reading the starting structure has no producing step, and says so rather
    # than inheriting whichever id happens to sit in input_coords.ref.
    assert stages[0].parent_id is None
    assert [s.parent_id for s in stages[1:]] == ["st_eq", "st_a1", "st_eq"]


def test_a_lineage_head_points_at_its_producer_not_at_its_neighbour(tagged_run):
    """Ruling 13.1.2 in one assertion.

    rep2's head follows rep1's tail in document order, which is exactly the false edge
    this feature removes. Its real producer is the shared equilibration, and continuity
    (Task 8) can only measure the head against that if the link arrives here.
    """
    stages = _stages(tagged_run)
    head = stages[3]
    predecessor_in_document_order = stages[2]
    assert head.parent_id != predecessor_in_document_order.step_id
    assert head.parent_id == stages[0].step_id


def test_an_untagged_step_adds_no_key_to_the_engine_payload(tmp_path):
    """The gate copies provenance only when set, so an untagged document is unmoved."""
    stage = {"id": "deadbeef", "name": "prod_001", "role": "production",
             "step_id": None, "parent_id": None, "lineage": None,
             "prmtop": None, "mdin": "prod_001.in", "mdout": None, "mdcrd": None,
             "inpcrd": None, "expected_gap_ps": None, "gap_tolerance_ps": None,
             "notes": []}
    payload = core_bridge.document_to_payload(
        [stage], dict(SETTINGS), str(tmp_path))
    assert payload["stages"] == [{"name": "prod_001", "stage_role": "production",
                                 "mdin": "prod_001.in"}]


def test_a_queued_status_reaches_the_engine_payload(tmp_path):
    """Adding a field to Step is a six-place change and three of the six fail silently:
    validate_manifest rejects no unknown key and pydantic's `extra='ignore'` drops
    another. This is the test that catches a status that never left the whitelist gate.

    Built from a raw stage dict, like `test_an_untagged_step_adds_no_key_to_the_engine_payload`
    above, rather than through `_flatten_simulation` — the brief's own version of this test
    calls `document_to_payload(sim)` with a bare `Simulation`, which matches neither
    `document_to_payload`'s three-argument signature (stages, settings, base_directory)
    nor takes a `Simulation` at all; it takes the flat stage dicts `_flatten_simulation`
    produces. Brief-originated, fixed here rather than reproduced, matching the pattern of
    prior brief-only defects logged in progress.md for Tasks 1 and 2.
    """
    stage = {"id": "deadbeef", "name": "prod_0002", "role": "production",
             "step_id": None, "parent_id": None, "lineage": None, "status": "queued",
             "prmtop": None, "mdin": "prod_0002.in", "mdout": None, "mdcrd": None,
             "inpcrd": None, "expected_gap_ps": None, "gap_tolerance_ps": None,
             "notes": []}
    payload = core_bridge.document_to_payload(
        [stage], dict(SETTINGS), str(tmp_path))
    assert payload["stages"][0]["status"] == "queued"
