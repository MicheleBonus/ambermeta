# tests/test_gui_schemas_sim.py
from ambermeta.gui.api.schemas import (
    SimulationModel, PhaseModel, StepModel, TopologyModel, InputCoordsModel,
    DocumentResponse, RuntimeSettings, AssignRequest, DiscoverResult, ValidationReport,
)


def test_simulation_model_nests_phases_and_steps():
    sim = SimulationModel(
        topologies=[TopologyModel(id="t0", path="wt.prmtop", kind="hmr")],
        starting_structure="wt.inpcrd",
        phases=[PhaseModel(id="p0", name="Min", role="minimization", steps=[
            StepModel(id="s0", name="min", topology="t0",
                      input_coords=InputCoordsModel(source="starting_structure"), mdin="min.in")])],
    )
    dumped = sim.model_dump()
    assert dumped["version"] == 2
    assert dumped["topologies"][0]["kind"] == "hmr"
    assert dumped["phases"][0]["role"] == "minimization"
    assert dumped["phases"][0]["steps"][0]["input_coords"]["source"] == "starting_structure"


def test_document_response_defaults():
    doc = DocumentResponse(base_directory="/x")
    assert doc.simulation.version == 2 and doc.simulation.phases == []
    assert doc.settings.strict_validation is True


def test_assign_request_and_reports():
    a = AssignRequest(path="wt.prmtop", target_type="pool", kind="normal")
    assert a.target_type == "pool"
    r = ValidationReport(ok=True)
    assert r.suggestions == []
    d = DiscoverResult(document=DocumentResponse(base_directory="/x"))
    assert d.suggestions == [] and d.warnings == []
