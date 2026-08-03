import json
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient
from ambermeta.gui.api import routes


def _client(base):
    routes.set_base_directory(str(base))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


def test_get_document_empty(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/document")
    assert r.status_code == 200
    body = r.json()
    assert body["simulation"]["version"] == 2 and body["simulation"]["phases"] == []


def test_open_v1_manifest_returns_a_clean_400(tmp_path):
    """The v1 file format is gone; opening one must surface a clean error, not a 500."""
    v1 = {"global_prmtop": "wt.prmtop",
          "stages": [{"name": "min", "stage_role": "minimization", "mdin": "min.in"},
                     {"name": "prod_001", "stage_role": "production", "mdin": "prod_001.in"}]}
    (tmp_path / "legacy.json").write_text(json.dumps(v1))
    c = _client(tmp_path)
    r = c.post("/api/document/open", json={"path": "legacy.json"})
    assert r.status_code == 400
    assert "not a v2 manifest" in r.json()["detail"]


def test_discover_returns_result_with_suggestions(sample_md_data_dir):
    c = _client(sample_md_data_dir)
    r = c.post("/api/document/discover", json={"recursive": False})
    assert r.status_code == 200
    body = r.json()
    assert "document" in body and "suggestions" in body
    assert body["document"]["simulation"]["phases"]


def test_the_missing_run_card_names_its_member_on_the_wire(crashed_replica_tree):
    """`Suggestion(**s)` is a pydantic model with the default `extra='ignore'`, so a
    `lineage` key that build_suggestions sets but the schema does not declare is dropped
    silently — the card would reach the canvas naming no member and nothing would say
    why. Asserted over the route rather than on the dict for exactly that reason."""
    c = _client(crashed_replica_tree)
    r = c.post("/api/document/discover", json={"recursive": True})
    assert r.status_code == 200
    card, = [s for s in r.json()["suggestions"] if s["kind"] == "missing_run"]
    assert card["lineage"] == "rep2"
    assert card["base"] == "prod" and card["missing"] == [2, 3]


def test_topology_routes(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/topologies", json={"path": "wt.prmtop", "kind": "hmr"})
    assert r.status_code == 200
    tid = r.json()["simulation"]["topologies"][0]["id"]
    assert r.json()["simulation"]["topologies"][0]["kind"] == "hmr"

    r = c.put(f"/api/topologies/{tid}", json={"kind": "normal"})
    assert r.json()["simulation"]["topologies"][0]["kind"] == "normal"

    r = c.put("/api/simulation/starting-structure", json={"path": "wt.inpcrd"})
    assert r.json()["simulation"]["starting_structure"] == "wt.inpcrd"

    r = c.delete(f"/api/topologies/{tid}")
    assert r.json()["simulation"]["topologies"] == []

    assert c.put("/api/topologies/bogus", json={"kind": "hmr"}).status_code == 404


def test_phase_routes(tmp_path):
    c = _client(tmp_path)
    a = c.post("/api/phases", json={"name": "Min", "role": "minimization"}).json()
    pa = a["simulation"]["phases"][0]["id"]
    b = c.post("/api/phases", json={"name": "Prod", "role": "production"}).json()
    pb = b["simulation"]["phases"][1]["id"]

    r = c.post("/api/phases/reorder", json={"phase_ids": [pb, pa]})
    assert [p["id"] for p in r.json()["simulation"]["phases"]] == [pb, pa]

    r = c.put(f"/api/phases/{pa}", json={"name": "Minimization"})
    names = {p["id"]: p["name"] for p in r.json()["simulation"]["phases"]}
    assert names[pa] == "Minimization"

    r = c.delete(f"/api/phases/{pa}")
    assert [p["id"] for p in r.json()["simulation"]["phases"]] == [pb]
    assert c.put("/api/phases/bogus", json={"name": "x"}).status_code == 404


def test_step_routes_and_topology_clear(tmp_path):
    c = _client(tmp_path)
    p = c.post("/api/phases", json={"name": "Prod", "role": "production"}).json()["simulation"]["phases"][0]["id"]
    r = c.post(f"/api/phases/{p}/steps", json={"name": "prod_001", "mdin": "prod_001.in"})
    sid = r.json()["simulation"]["phases"][0]["steps"][0]["id"]

    # set then clear topology (explicit null must clear)
    c.put(f"/api/steps/{sid}", json={"topology": "t0"})
    assert _step(c, sid)["topology"] == "t0"
    c.put(f"/api/steps/{sid}", json={"topology": None})
    assert _step(c, sid)["topology"] is None
    # absent topology must NOT clear
    c.put(f"/api/steps/{sid}", json={"topology": "t9"})
    c.put(f"/api/steps/{sid}", json={"name": "prod_001b"})
    assert _step(c, sid)["topology"] == "t9" and _step(c, sid)["name"] == "prod_001b"

    r = c.request("DELETE", f"/api/steps/{sid}")
    assert r.json()["simulation"]["phases"][0]["steps"] == []


def _step(c, sid):
    doc = c.get("/api/document").json()
    for ph in doc["simulation"]["phases"]:
        for s in ph["steps"]:
            if s["id"] == sid:
                return s
    raise AssertionError("step not found")


def test_assign_and_file_routes(tmp_path):
    (tmp_path / "wt.prmtop").write_text("dummy")
    (tmp_path / "min.in").write_text("&cntrl\nimin=1,\n/\n")
    c = _client(tmp_path)
    p = c.post("/api/phases", json={"name": "Min", "role": "minimization"}).json()["simulation"]["phases"][0]["id"]
    s = c.post(f"/api/phases/{p}/steps", json={"name": "min"}).json()["simulation"]["phases"][0]["steps"][0]["id"]

    r = c.post("/api/assign", json={"path": "wt.prmtop", "target_type": "step_topology", "target_id": s})
    assert r.status_code == 200
    assert c.get("/api/document").json()["simulation"]["topologies"][0]["path"] == "wt.prmtop"

    r = c.post("/api/assign", json={"path": "min.in", "target_type": "step_slot", "target_id": s, "slot": "mdin"})
    assert _step(c, s)["mdin"] == "min.in"

    r = c.get("/api/files")
    assert r.status_code == 200 and any(f["name"] == "wt.prmtop" for f in r.json())

    r = c.get("/api/files/raw", params={"path": "min.in"})
    assert r.status_code == 200 and "imin=1" in r.json()["content"]

    assert c.post("/api/assign", json={"path": "x", "target_type": "bogus"}).status_code == 400


def test_mutation_routes_reject_path_traversal(tmp_path):
    c = _client(tmp_path)
    evil = "../../secret.prmtop"
    # topology pool
    assert c.post("/api/topologies", json={"path": evil, "kind": "normal"}).status_code == 403
    # unified assign
    assert c.post("/api/assign", json={"path": evil, "target_type": "pool", "kind": "normal"}).status_code == 403
    # starting structure
    assert c.put("/api/simulation/starting-structure", json={"path": evil}).status_code == 403
    # a valid topology first (inside base), then a traversal update
    tid = c.post("/api/topologies", json={"path": "ok.prmtop", "kind": "normal"}).json()["simulation"]["topologies"][0]["id"]
    assert c.put(f"/api/topologies/{tid}", json={"path": evil}).status_code == 403
    # step create + update slot
    p = c.post("/api/phases", json={"name": "P", "role": "production"}).json()["simulation"]["phases"][0]["id"]
    assert c.post(f"/api/phases/{p}/steps", json={"name": "s", "mdin": evil}).status_code == 403
    sid = c.post(f"/api/phases/{p}/steps", json={"name": "s2"}).json()["simulation"]["phases"][0]["steps"][-1]["id"]
    assert c.put(f"/api/steps/{sid}", json={"files": {"mdin": evil}}).status_code == 403
    # a legitimate relative path inside base must still WORK (not over-blocked)
    assert c.post("/api/topologies", json={"path": "sys.prmtop", "kind": "normal"}).status_code == 200


# --- restart chain and clearing, over the wire -------------------------------

def _phase(c, pid):
    for ph in c.get("/api/document").json()["simulation"]["phases"]:
        if ph["id"] == pid:
            return ph
    raise AssertionError("phase not found")


def _two_steps(tmp_path):
    for name in ("01_min.mdin", "02_nvt.mdin", "01_min.rst", "wt.prmtop", "wt_hmr.prmtop"):
        (tmp_path / name).write_text("x")
    c = _client(tmp_path)
    p = c.post("/api/phases", json={"name": "Equil", "role": "equilibration"}) \
         .json()["simulation"]["phases"][0]["id"]
    a = c.post(f"/api/phases/{p}/steps",
               json={"name": "01_min", "mdin": "01_min.mdin", "rst": "01_min.rst"}) \
         .json()["simulation"]["phases"][0]["steps"][0]["id"]
    c.post(f"/api/phases/{p}/steps", json={"name": "02_nvt", "mdin": "02_nvt.mdin"})
    b = _phase(c, p)["steps"][1]["id"]
    return c, p, a, b


def test_a_new_step_chains_from_the_one_before_it_and_resolves_its_restart(tmp_path):
    c, _, a, b = _two_steps(tmp_path)
    step = _step(c, b)
    assert step["input_coords"] == {"source": "step", "ref": a, "path": None}
    # The path is not copied onto the consumer; it is resolved from the producer.
    assert step["resolved_input_coords"] == "01_min.rst"
    assert _step(c, a)["rst"] == "01_min.rst"


def test_the_restart_slot_is_writable_and_clearable_over_the_wire(tmp_path):
    c, _, a, b = _two_steps(tmp_path)
    c.put(f"/api/steps/{a}", json={"files": {"rst": "01_min.rst"}})
    assert _step(c, a)["rst"] == "01_min.rst"
    c.put(f"/api/steps/{a}", json={"files": {"rst": ""}})
    assert _step(c, a)["rst"] is None
    assert _step(c, b)["resolved_input_coords"] is None   # link intact, file gone


def test_assigning_a_restart_to_the_rst_slot(tmp_path):
    c, _, a, _ = _two_steps(tmp_path)
    r = c.post("/api/assign", json={"path": "01_min.rst", "target_type": "step_slot",
                                    "target_id": a, "slot": "rst"})
    assert r.status_code == 200
    assert _step(c, a)["rst"] == "01_min.rst"


def test_an_impossible_continues_from_is_a_400_and_not_a_500(tmp_path):
    """PUT /steps/{id} used to take a dead id and a self-reference verbatim, which made
    every guard on the automatic chaining paths bypassable through this one route."""
    c, _, a, b = _two_steps(tmp_path)
    for ref, detail in ((b, "cannot continue from itself"),
                        ("ghost", "no step to continue from")):
        r = c.put(f"/api/steps/{b}", json={"input_coords": {"source": "step", "ref": ref}})
        assert r.status_code == 400 and detail in r.json()["detail"]
    assert _step(c, b)["input_coords"]["ref"] == a          # nothing was written


def test_a_step_is_created_with_its_lineage_and_at_the_index_asked_for(tmp_path):
    c, p, a, _ = _two_steps(tmp_path)
    r = c.post(f"/api/phases/{p}/steps", json={"name": "rep2/prod_0001",
                                               "lineage": "rep2", "index": 0})
    steps = r.json()["simulation"]["phases"][0]["steps"]
    assert [s["name"] for s in steps][0] == "rep2/prod_0001"
    assert steps[0]["lineage"] == "rep2"                    # silently dropped before


def _two_lineages(tmp_path):
    """A phase holding one step of each of two declared members, built over the wire."""
    c = _client(tmp_path)
    p = c.post("/api/phases", json={"name": "Prod", "role": "production"}) \
         .json()["simulation"]["phases"][0]["id"]
    for tag in ("rep1", "rep2"):
        c.post(f"/api/phases/{p}/steps", json={"name": f"{tag}/prod_0001", "lineage": tag})
    a, b = [s["id"] for s in _phase(c, p)["steps"]]
    return c, p, a, b


def test_creating_a_step_applies_the_same_ref_checks_as_updating_one(tmp_path):
    """POST /phases/{id}/steps took a caller-supplied `input_coords` verbatim, so it was a
    second, unguarded way past every check PUT /steps/{id} had just gained.

    Self-reference is absent from this list because the create path cannot express it: the
    id is minted server-side and the caller has never seen it, so the nearest thing it can
    spell is an id the document does not hold — the first case here.
    """
    c, p, _, _ = _two_lineages(tmp_path)
    for ref, detail in (("deadbeef", "no step to continue from"),
                        (None, "must name it"), ("", "must name it")):
        r = c.post(f"/api/phases/{p}/steps",
                   json={"name": "rep1/prod_0002", "lineage": "rep1",
                         "input_coords": {"source": "step", "ref": ref}})
        assert r.status_code == 400 and detail in r.json()["detail"]
    assert len(_phase(c, p)["steps"]) == 2          # none of them was created
    # And none of them was snapshotted either: one undo must reach past the refusals to
    # the last edit that actually happened, not unwind three that reverse nothing.
    c.post("/api/undo")
    assert len(_phase(c, p)["steps"]) == 1


def test_the_create_and_update_routes_refuse_a_bad_ref_identically(tmp_path):
    """One helper rather than two copies of it, so a rule added to the edit path cannot go
    missing from the create path — which is exactly how the hole opened."""
    c, p, _, b = _two_lineages(tmp_path)
    created = c.post(f"/api/phases/{p}/steps",
                     json={"name": "x", "input_coords": {"source": "step", "ref": "ghost"}})
    updated = c.put(f"/api/steps/{b}",
                    json={"input_coords": {"source": "step", "ref": "ghost"}})
    assert created.status_code == updated.status_code == 400
    assert created.json()["detail"] == updated.json()["detail"]


def test_a_step_created_across_two_members_is_kept_and_reported(tmp_path):
    """A hand-written link between two declared lineages is the only way to record a
    genuine branch, so creating one is a finding rather than a refusal — the same answer
    the edit route gives, since a create that refused it would just be edited into place."""
    c, p, a, _ = _two_lineages(tmp_path)
    r = c.post(f"/api/phases/{p}/steps",
               json={"name": "rep2/prod_0002", "lineage": "rep2",
                     "input_coords": {"source": "step", "ref": a}})
    assert r.status_code == 200
    body = r.json()
    made, = [s for s in body["simulation"]["phases"][0]["steps"]
             if s["name"] == "rep2/prod_0002"]
    assert made["input_coords"]["ref"] == a         # kept, not silently dropped
    assert len(body["warnings"]) == 1
    assert "rep1/prod_0001" in body["warnings"][0] and "rep2/prod_0002" in body["warnings"][0]


def test_a_continues_from_that_names_nothing_is_refused_on_both_routes(tmp_path):
    """`source: "step"` with no ref says the run continued from something and declines to
    say what. It used to be stored on both routes, resolving to no coordinates while the
    chain still read as intact; "reads the starting structure" is a source of its own."""
    c, p, _, b = _two_lineages(tmp_path)
    for ref in (None, ""):
        r = c.put(f"/api/steps/{b}", json={"input_coords": {"source": "step", "ref": ref}})
        assert r.status_code == 400 and "must name it" in r.json()["detail"]
        r = c.post(f"/api/phases/{p}/steps",
                   json={"name": "x", "input_coords": {"source": "step", "ref": ref}})
        assert r.status_code == 400 and "must name it" in r.json()["detail"]
    assert _step(c, b)["input_coords"]["source"] == "starting_structure"   # untouched
    assert len(_phase(c, p)["steps"]) == 2


def test_deleting_a_step_does_not_leave_its_successor_pointing_at_a_dead_id(tmp_path):
    c, _, a, b = _two_steps(tmp_path)
    c.request("DELETE", f"/api/steps/{a}")
    assert _step(c, b)["input_coords"]["source"] == "starting_structure"


def test_a_gap_is_cleared_by_an_explicit_null_and_zero_survives(tmp_path):
    c, _, a, _ = _two_steps(tmp_path)
    c.put(f"/api/steps/{a}", json={"expected_gap_ps": 20.0, "gap_tolerance_ps": 1.0})
    assert _step(c, a)["expected_gap_ps"] == 20.0

    c.put(f"/api/steps/{a}", json={"expected_gap_ps": 0.0})
    assert _step(c, a)["expected_gap_ps"] == 0.0        # 0 is a value, not "unset"

    c.put(f"/api/steps/{a}", json={"expected_gap_ps": None})
    assert _step(c, a)["expected_gap_ps"] is None
    assert _step(c, a)["gap_tolerance_ps"] == 1.0       # absent means leave alone


def test_one_request_sets_or_clears_the_topology_of_every_step_in_a_phase(tmp_path):
    c, p, a, b = _two_steps(tmp_path)
    tid = c.post("/api/topologies", json={"path": "wt.prmtop", "kind": "normal"}) \
           .json()["simulation"]["topologies"][0]["id"]

    r = c.put(f"/api/phases/{p}", json={"topology": tid})
    assert r.status_code == 200
    assert [s["topology"] for s in _phase(c, p)["steps"]] == [tid, tid]

    c.put(f"/api/phases/{p}", json={"topology": None})
    assert [s["topology"] for s in _phase(c, p)["steps"]] == [None, None]

    # Absent means leave alone — renaming a phase must not strip its topologies.
    c.put(f"/api/phases/{p}", json={"topology": tid})
    c.put(f"/api/phases/{p}", json={"name": "Equilibration"})
    assert [s["topology"] for s in _phase(c, p)["steps"]] == [tid, tid]


def test_setting_a_phase_topology_that_is_not_in_the_pool_is_a_404(tmp_path):
    c, p, _, _ = _two_steps(tmp_path)
    assert c.put(f"/api/phases/{p}", json={"topology": "nope"}).status_code == 404


def test_the_starting_structure_can_be_cleared(tmp_path):
    (tmp_path / "wt.inpcrd").write_text("x")
    c = _client(tmp_path)
    c.put("/api/simulation/starting-structure", json={"path": "wt.inpcrd"})
    assert c.get("/api/document").json()["simulation"]["starting_structure"] == "wt.inpcrd"
    r = c.put("/api/simulation/starting-structure", json={"path": None})
    assert r.status_code == 200
    assert r.json()["simulation"]["starting_structure"] is None


def test_undo_after_a_save_leaves_the_save_target_alone(tmp_path):
    c, _, a, _ = _two_steps(tmp_path)
    c.post("/api/document/save", json={"path": "b.yaml"})
    assert c.get("/api/document").json()["manifest_path"].endswith("b.yaml")
    c.request("DELETE", f"/api/steps/{a}")
    c.post("/api/undo")
    doc = c.get("/api/document").json()
    assert doc["manifest_path"].endswith("b.yaml")
    assert doc["dirty"] is True      # in memory it no longer matches the file


def test_reassigning_a_phase_to_itself_is_a_400_not_a_crash(tmp_path):
    c = _client(tmp_path)
    p = c.post("/api/phases", json={"name": "Prod", "role": "production"}) \
         .json()["simulation"]["phases"][0]["id"]
    c.post(f"/api/phases/{p}/steps", json={"name": "prod_001"})
    r = c.request("DELETE", f"/api/phases/{p}", params={"reassign_to": p})
    assert r.status_code == 400
    assert len(_phase(c, p)["steps"]) == 1     # and nothing was lost on the way


# --- plan outputs: the artifacts `ambermeta plan` writes, from the GUI --------

def _planned(tmp_path):
    """A discovered document over the real sample data."""
    import shutil
    src = os.path.join(os.path.dirname(__file__), "data", "amber", "md_test_files")
    for name in os.listdir(src):
        shutil.copy(os.path.join(src, name), tmp_path)
    c = _client(tmp_path)
    c.post("/api/document/discover", json={"recursive": False})
    return c


def test_plan_writes_the_manifest_and_both_summaries_in_one_call(tmp_path):
    c = _planned(tmp_path)
    r = c.post("/api/plan", json={
        "save_manifest_path": "manifest.yaml",
        "summary_path": "reports/summary.json",
        "methods_summary_path": "reports/methods_summary.json",
    })
    assert r.status_code == 200
    body = r.json()
    assert [w["artifact"] for w in body["written"]] == \
        ["manifest", "summary", "methods_summary"]
    for w in body["written"]:
        assert os.path.isfile(w["path"]), w
    # Subdirectories are created rather than being an error the user has to pre-empt.
    assert (tmp_path / "reports" / "summary.json").is_file()
    assert body["stage_count"] == 5
    assert body["totals"]["time_ps"] > 0
    assert body["document"]["dirty"] is False       # saving the manifest marked it clean


def test_the_summaries_match_what_the_cli_would_write(tmp_path):
    """One protocol, one parse — the GUI must not produce a different summary."""
    from ambermeta.gui.api import core_bridge
    from ambermeta.protocol import to_plain
    c = _planned(tmp_path)
    c.post("/api/plan", json={"summary_path": "s.json",
                              "methods_summary_path": "m.json"})
    store = routes.get_store()
    sim, settings, _, base = store.snapshot()
    protocol = core_bridge.build_protocol(
        core_bridge._flatten_simulation(sim), dict(settings), base)
    # Compared through to_plain, which is what both writers apply: a JSON round trip
    # turns tuples into lists, so the raw dict is not the right thing to compare against.
    assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8")) \
        == to_plain(protocol.to_dict())
    assert json.loads((tmp_path / "m.json").read_text(encoding="utf-8")) \
        == to_plain(protocol.to_methods_dict())


def test_plan_writes_a_stats_csv_with_the_shared_column_order(tmp_path):
    from ambermeta.protocol import STATS_CSV_COLUMNS
    c = _planned(tmp_path)
    r = c.post("/api/plan", json={"stats_csv_path": "stats.csv"})
    assert r.status_code == 200
    header = (tmp_path / "stats.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == STATS_CSV_COLUMNS


def test_plan_can_write_the_summary_as_yaml_while_methods_stays_json(tmp_path):
    c = _planned(tmp_path)
    c.post("/api/plan", json={"summary_path": "s.yaml", "summary_format": "yaml",
                              "methods_summary_path": "m.json"})
    assert not (tmp_path / "s.yaml").read_text(encoding="utf-8").lstrip().startswith("{")
    json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))   # still JSON


def test_plan_refuses_to_write_nothing(tmp_path):
    assert _client(tmp_path).post("/api/plan", json={}).status_code == 400


def test_plan_rejects_a_path_outside_the_launch_directory(tmp_path):
    c = _planned(tmp_path)
    for key in ("summary_path", "methods_summary_path", "stats_csv_path",
                "save_manifest_path"):
        r = c.post("/api/plan", json={key: "../escaped.json"})
        assert r.status_code == 403, key


def test_plan_rejects_an_unsupported_summary_format(tmp_path):
    c = _planned(tmp_path)
    r = c.post("/api/plan", json={"summary_path": "s.toml", "summary_format": "toml"})
    assert r.status_code == 400
    assert not (tmp_path / "s.toml").exists()


def test_plan_says_so_when_there_is_nothing_to_summarise(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/plan", json={"summary_path": "s.json"})
    assert r.status_code == 200
    assert any("no steps" in w.lower() for w in r.json()["warnings"])


def test_a_yaml_summary_survives_the_numpy_scalars_the_parsers_produce(tmp_path):
    """yaml.safe_dump rejects numpy types outright; it used to leave a truncated file."""
    import yaml
    c = _planned(tmp_path)
    r = c.post("/api/plan", json={"summary_path": "s.yaml", "summary_format": "yaml"})
    assert r.status_code == 200
    loaded = yaml.safe_load((tmp_path / "s.yaml").read_text(encoding="utf-8"))
    assert loaded["totals"]["time_ps"] > 0
    assert len(loaded["stages"]) == 5


def test_plan_refuses_two_outputs_aimed_at_one_file(tmp_path):
    """The loser of the race was silently destroyed and still reported as written."""
    c = _planned(tmp_path)
    r = c.post("/api/plan", json={"save_manifest_path": "out.yaml",
                                  "summary_path": "out.yaml", "summary_format": "yaml"})
    assert r.status_code == 400
    assert "own file" in r.json()["detail"]
    assert not (tmp_path / "out.yaml").exists()      # nothing was written on the way

    r = c.post("/api/plan", json={"summary_path": "b.json", "methods_summary_path": "b.json"})
    assert r.status_code == 400


def test_plan_refuses_two_outputs_aimed_at_one_file_case_insensitively(tmp_path):
    """The GUI's guard keys off os.path.normcase, like the CLI's: on Windows/NTFS S.json
    and s.json are one file, so both artifacts "land" on distinct strings while one is
    silently clobbered and the response still reports both as written. On POSIX they are
    genuinely two files and must both be written. Assert what normcase actually reports
    rather than guessing from the platform, so the real contract is exercised on either
    OS instead of one of them being skipped."""
    folds_case = os.path.normcase("A") == os.path.normcase("a")
    c = _planned(tmp_path)
    r = c.post("/api/plan", json={"summary_path": "S.json",
                                  "methods_summary_path": "s.json"})
    if folds_case:
        assert r.status_code == 400
        assert "own file" in r.json()["detail"]
        assert not (tmp_path / "S.json").exists()
        assert not (tmp_path / "s.json").exists()
    else:
        assert r.status_code == 200
        assert [w["artifact"] for w in r.json()["written"]] == ["summary", "methods_summary"]
        assert (tmp_path / "S.json").is_file() and (tmp_path / "s.json").is_file()


def test_plan_validates_the_format_before_saving_the_manifest(tmp_path):
    """A bad format used to be caught after the manifest had been written and marked saved."""
    c = _planned(tmp_path)
    r = c.post("/api/plan", json={"save_manifest_path": "m.yaml", "summary_path": "s.json",
                                  "summary_format": "toml"})
    assert r.status_code == 400
    assert not (tmp_path / "m.yaml").exists()
    assert c.get("/api/document").json()["manifest_path"] is None


def test_plan_reports_what_landed_when_one_artifact_cannot_be_written(tmp_path):
    c = _planned(tmp_path)
    (tmp_path / "blocked").mkdir()                   # a directory where a file should go
    r = c.post("/api/plan", json={"save_manifest_path": "m.yaml", "summary_path": "s.json",
                                  "methods_summary_path": "blocked"})
    assert r.status_code == 200                      # not a bare 400 that hides the rest
    body = r.json()
    assert [w["artifact"] for w in body["written"]] == ["manifest", "summary"]
    assert [f["artifact"] for f in body["failed"]] == ["methods_summary"]
    assert body["failed"][0]["error"]
    assert (tmp_path / "m.yaml").is_file() and (tmp_path / "s.json").is_file()


def test_plan_does_not_warn_about_summaries_nobody_asked_for(tmp_path):
    c = _client(tmp_path)                            # empty document
    r = c.post("/api/plan", json={"save_manifest_path": "m.yaml"})
    assert r.status_code == 200 and r.json()["warnings"] == []


def test_the_empty_stats_warning_describes_what_is_actually_in_the_file(tmp_path):
    c = _client(tmp_path)
    p = c.post("/api/phases", json={"name": "Prod", "role": "production"}) \
         .json()["simulation"]["phases"][0]["id"]
    (tmp_path / "prod.mdin").write_text("&cntrl\nimin=0, nstlim=10, dt=0.002,\n/\n")
    c.post(f"/api/phases/{p}/steps", json={"name": "prod", "mdin": "prod.mdin"})
    r = c.post("/api/plan", json={"stats_csv_path": "stats.csv"})
    rows = (tmp_path / "stats.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 2                            # a header AND a row for the step
    assert any("every row" in w for w in r.json()["warnings"])
