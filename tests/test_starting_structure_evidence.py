"""The starting-structure card says why that file was chosen.

Its evidence was always "single-frame coordinates; feeds the first run", which every
restart in a tree is. Since 1.3.0 Discover prefers the file the first run's mdout records
as its INPCRD, and that record is the reason worth showing; where nothing records it, the
generic line is still the honest one.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ambermeta.gui.api import routes  # noqa: E402
from tests.conftest import write_run_tree  # noqa: E402


def _evidence(base):
    routes.set_base_directory(str(base))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    body = TestClient(app).post("/api/document/discover", json={"recursive": True}).json()
    card, = [s for s in body["suggestions"] if s["kind"] == "starting_structure"]
    return card["evidence"]


def test_the_card_names_the_run_whose_mdout_records_the_file(sample_md_data_dir):
    evidence = _evidence(sample_md_data_dir)
    assert "ntp_prod_0001" in evidence
    assert "INPCRD" in evidence


def test_without_a_record_the_card_does_not_claim_one(tmp_path):
    write_run_tree(tmp_path, ["prod_0001", "prod_0002"])
    (tmp_path / "system.inpcrd").write_text("title\n     2\n   0.0   0.0   0.0   1.0   1.0   1.0\n",
                                            encoding="utf-8")
    evidence = _evidence(tmp_path)
    assert "INPCRD" not in evidence
    assert evidence
