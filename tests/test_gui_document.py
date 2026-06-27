# tests/test_gui_document.py
from ambermeta.gui.api.document import DocumentStore


def _new() -> DocumentStore:
    return DocumentStore(base_directory="/base")


def test_add_stage_returns_id_and_marks_dirty():
    store = _new()
    assert store.get().dirty is False
    sid = store.add_stage({"name": "min", "role": "minimization"})
    assert isinstance(sid, str) and len(sid) == 8
    doc = store.get()
    assert doc.dirty is True
    assert [s["name"] for s in doc.stages] == ["min"]
    assert doc.stages[0]["id"] == sid


def test_update_and_delete_stage():
    store = _new()
    sid = store.add_stage({"name": "min"})
    store.update_stage(sid, {"name": "minim", "mdin": "min.in"})
    doc = store.get()
    assert doc.stages[0]["name"] == "minim"
    assert doc.stages[0]["mdin"] == "min.in"
    store.delete_stage(sid)
    assert store.get().stages == []


def test_reorder_rejects_mismatched_ids():
    store = _new()
    a = store.add_stage({"name": "a"})
    b = store.add_stage({"name": "b"})
    store.reorder([b, a])
    assert [s["name"] for s in store.get().stages] == ["b", "a"]
    try:
        store.reorder([a])  # missing b
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_undo_redo_covers_stages_and_settings():
    store = _new()
    store.add_stage({"name": "a"})
    store.patch_settings({"global_prmtop": "sys.prmtop"})
    assert store.get().settings["global_prmtop"] == "sys.prmtop"
    assert len(store.get().stages) == 1

    store.undo()  # revert settings patch
    assert store.get().settings["global_prmtop"] is None
    assert len(store.get().stages) == 1

    store.undo()  # revert add_stage
    assert store.get().stages == []

    store.redo()  # re-add stage
    assert len(store.get().stages) == 1
    assert store.can_redo() is True


def test_mark_saved_clears_dirty_without_history():
    store = _new()
    store.add_stage({"name": "a"})
    could_undo_before = store.can_undo()
    store.mark_saved("/base/protocol.yaml")
    doc = store.get()
    assert doc.dirty is False
    assert doc.manifest_path == "/base/protocol.yaml"
    # mark_saved did not add an undo frame
    assert store.can_undo() == could_undo_before


def test_replace_with_reset_history_clears_undo():
    store = _new()
    store.add_stage({"name": "a"})
    store.replace(stages=[{"id": "x", "name": "b", "role": "",
                           "prmtop": None, "mdin": None, "mdout": None,
                           "mdcrd": None, "inpcrd": None,
                           "expected_gap_ps": None, "gap_tolerance_ps": None,
                           "notes": []}],
                  settings={"global_prmtop": None, "hmr_prmtop": None,
                            "initial_coordinates": None, "auto_link_restarts": True,
                            "strict_validation": True, "allow_gaps": False,
                            "use_relative_paths": True},
                  manifest_path="/base/p.yaml", dirty=False, reset_history=True)
    assert store.can_undo() is False
    assert store.get().manifest_path == "/base/p.yaml"
