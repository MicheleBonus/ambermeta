"""A long request must not stamp its stale reading over an edit that landed while it ran.

Every route in ambermeta.gui.api.routes is a synchronous `def`, so Starlette runs each in
an anyio worker thread and several genuinely overlap. Two of them read the document, work
for a long time OUTSIDE the store's lock, and then write back:

* `POST /document/discover` -- a tree scan; minutes on a 253 GB campaign;
* `POST /document/save` and `POST /plan` -- a manifest write to a network filesystem.

Both used to write back what they had read at the start. The consequences were not
symmetric: settings and the simulation are recoverable with Ctrl+Z, but `manifest_path` is
deliberately excluded from the undo stack (see `DocumentStore._state`), so a reverted save
target sent the next Ctrl+S to a file the user had moved away from -- and a `dirty` flag
cleared for an edit that is not in the file disarms the unsaved-changes guard over real
unsaved work.
"""
from __future__ import annotations

import threading

import pytest

from ambermeta.gui.api import core_bridge, routes
from ambermeta.gui.api.document import DocumentStore
from ambermeta.simulation import Simulation


@pytest.fixture
def tree(tmp_path):
    for i in (1, 2):
        (tmp_path / f"prod_{i:04d}.mdin").write_text(
            "md\n &cntrl\n  imin = 0, nstlim = 1000, dt = 0.002,\n /\n")
    return tmp_path


def test_discover_does_not_revert_a_save_that_landed_while_it_scanned(tree, monkeypatch):
    routes.set_base_directory(str(tree))
    store = routes.get_store()

    scanning = threading.Event()
    release = threading.Event()
    real = core_bridge.discover_draft

    def slow_discover(*a, **kw):
        scanning.set()
        release.wait(timeout=10)
        return real(*a, **kw)

    monkeypatch.setattr(core_bridge, "discover_draft", slow_discover)

    result = {}
    worker = threading.Thread(
        target=lambda: result.update(
            r=routes.discover_document(routes.DiscoverRequest(recursive=True))))
    worker.start()

    assert scanning.wait(timeout=10), "discover never started"
    # The user does Save As and changes a setting while the scan runs.
    store.mark_saved(str(tree / "manifest_v2.yaml"))
    store.patch_settings({"allow_gaps": True})

    release.set()
    worker.join(timeout=30)
    assert result, "discover never finished"

    doc = store.get()
    assert doc.manifest_path == str(tree / "manifest_v2.yaml"), (
        "Discover reverted the save target it read before the scan")
    assert doc.settings["allow_gaps"] is True, (
        "Discover reverted a setting changed while it scanned")


def test_saving_does_not_clear_dirty_for_an_edit_it_did_not_write():
    store = DocumentStore("/base")
    store.replace(simulation=Simulation(), settings=store.get().settings,
                  manifest_path=None, dirty=True, reset_history=True)

    (sim, settings, manifest_path, base), revision = store.snapshot_at()
    # ... the write happens here, and an edit lands during it ...
    store.add_phase("Production", "prod")

    clean = store.mark_saved("/base/manifest.yaml", revision)

    assert clean is False, "dirty was cleared for an edit that is not in the file"
    assert store.get().dirty is True
    # The file WAS written, and where it went is not in doubt.
    assert store.get().manifest_path == "/base/manifest.yaml"


def test_saving_an_unchanged_document_still_marks_it_clean():
    store = DocumentStore("/base")
    store.add_phase("Production", "prod")

    (sim, settings, manifest_path, base), revision = store.snapshot_at()
    clean = store.mark_saved("/base/manifest.yaml", revision)

    assert clean is True
    assert store.get().dirty is False
    assert store.get().manifest_path == "/base/manifest.yaml"


def test_the_revision_moves_for_every_kind_of_change():
    store = DocumentStore("/base")
    seen = [store.revision()]

    store.add_phase("Minimisation", "min")
    seen.append(store.revision())
    store.patch_settings({"allow_gaps": True})
    seen.append(store.revision())
    store.undo()
    seen.append(store.revision())
    store.redo()
    seen.append(store.revision())
    store.mark_saved("/base/m.yaml")
    seen.append(store.revision())
    store.replace(simulation=Simulation(), settings=store.get().settings,
                  manifest_path=None, dirty=False, reset_history=True)
    seen.append(store.revision())

    assert seen == sorted(set(seen)), f"a change did not move the revision: {seen}"
