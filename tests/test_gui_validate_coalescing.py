"""`POST /validate` runs one at a time, and answers a duplicate burst from one pass.

Every route is a synchronous `def`, so Starlette runs each in an anyio worker thread and
several genuinely overlap. The GUI fires Validate at itself -- `App.tsx` re-validates on
every document change, and opening the Validation panel fires another -- so Discover
followed by a click on Validate was two full re-parses of the campaign running at once,
each holding a worker thread for tens of seconds.
"""
from __future__ import annotations

import threading
import time

import pytest

from ambermeta.gui.api import core_bridge, routes


@pytest.fixture
def store(tmp_path):
    (tmp_path / "prod_0001.mdin").write_text(
        "md\n &cntrl\n  imin = 0, nstlim = 1000, dt = 0.002,\n /\n")
    routes.set_base_directory(str(tmp_path))
    out = core_bridge.discover_draft(str(tmp_path), apply_tags=False)
    s = routes.get_store()
    s.replace(simulation=out["simulation"], settings=s.get().settings,
              manifest_path=None, dirty=True, reset_history=True)
    yield s
    routes.set_base_directory(str(tmp_path))     # drop the reusable report


def _count_calls(monkeypatch, delay=0.0):
    calls = []
    real = core_bridge.validate_simulation

    def counted(sim, settings, base_directory, protocol=None):
        calls.append(base_directory)
        if delay:
            time.sleep(delay)
        return real(sim, settings, base_directory, protocol=protocol)

    monkeypatch.setattr(core_bridge, "validate_simulation", counted)
    return calls


def test_a_burst_of_identical_requests_costs_one_pass(store, monkeypatch):
    calls = _count_calls(monkeypatch, delay=0.15)

    reports = [None] * 6
    threads = [threading.Thread(target=lambda i=i: reports.__setitem__(i, routes.validate_protocol()))
               for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert all(r is not None for r in reports), "a request never returned"
    assert len(calls) == 1, f"the engine ran {len(calls)} times for one document"
    # Every caller got the same answer, not an empty stand-in.
    assert {r.totals["stage_count"] for r in reports} == {1}


def test_a_changed_document_is_validated_again(store, monkeypatch):
    calls = _count_calls(monkeypatch)

    routes.validate_protocol()
    phase = store.get().simulation.phases[0]
    store.add_step(phase.id, {"name": "prod_0002", "notes": []})
    routes.validate_protocol()

    assert len(calls) == 2, "an edited document reused the previous report"


def test_the_reuse_window_expires_so_a_finished_run_can_change_the_answer(store, monkeypatch):
    """The reusable report is not a cache.

    The fingerprint covers the document, not the files it names, so holding the answer
    indefinitely would hide a run that finished on disk under an unchanged document.
    """
    calls = _count_calls(monkeypatch)
    monkeypatch.setattr(routes, "_REUSE_WINDOW_S", 0.0)

    routes.validate_protocol()
    time.sleep(0.01)
    routes.validate_protocol()

    assert len(calls) == 2, "the report outlived its window"
