"""A `.crd` file is typed by what it holds, not by its extension alone.

AMBER uses `.crd` for two different things: LEaP's coordinate file (`saveamberparm ...
system.crd`, a single frame with an atom-count line) and, by the `mdcrd` default name,
a trajectory. The GUI typed every `.crd` as a trajectory, so the sample's
`CH3L1_HUMAN_6NAG.crd` was listed as one and went into a step's trajectory slot without a
word, while the engine's own content sniffer (`coords.sniff_coordinate_kind`, which
Discover uses) calls it input coordinates.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ambermeta.gui.api import routes  # noqa: E402
from ambermeta.gui.api.files import detect_file_type  # noqa: E402
from ambermeta.gui.api.schemas import FileType  # noqa: E402

LEAP_CRD = "default_name\n     3\n   1.0000000   2.0000000   3.0000000   4.0000000   5.0000000   6.0000000\n   7.0000000   8.0000000   9.0000000\n"
TRAJECTORY_CRD = "trajectory title\n   1.000   2.000   3.000   4.000   5.000   6.000   7.000   8.000   9.000   1.000\n   2.000   3.000\n"


def test_a_leap_coordinate_file_named_crd_is_input_coordinates(tmp_path):
    path = tmp_path / "system.crd"
    path.write_text(LEAP_CRD, encoding="utf-8")
    assert detect_file_type(str(path)) == FileType.INPCRD


def test_an_ascii_trajectory_named_crd_is_still_a_trajectory(tmp_path):
    path = tmp_path / "prod.crd"
    path.write_text(TRAJECTORY_CRD, encoding="utf-8")
    assert detect_file_type(str(path)) == FileType.MDCRD


def test_the_file_list_types_the_sample_leap_crd_as_input_coordinates(sample_md_data_dir):
    routes.set_base_directory(str(sample_md_data_dir))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    r = TestClient(app).get("/api/files", params={"recursive": False})

    types = {f["name"]: f["file_type"] for f in r.json()}
    assert types["CH3L1_HUMAN_6NAG.crd"] == "inpcrd"
