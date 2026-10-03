"""NetCDF text attributes read the same whichever backend opened the file.

SciPy's reader returns global attributes as `bytes`; netCDF4 returns `str`. The restart
reader applied `str()` before testing for bytes, so with SciPy as the backend summary.json
and the methods summary said `"program": "b'pmemd'"` and `"version": "b'Version 22'"`.
"""
from __future__ import annotations

import pytest

from ambermeta import netcdf_backend
from ambermeta.legacy_extractors.inpcrd import _nc_text, parse_inpcrd


def test_bytes_and_text_attributes_decode_to_the_same_string():
    assert _nc_text(b"pmemd") == "pmemd"
    assert _nc_text("pmemd") == "pmemd"
    assert _nc_text(bytearray(b"Version 22")) == "Version 22"


def test_the_scipy_backend_reads_the_program_without_a_bytes_repr(
        monkeypatch, sample_md_data_dir):
    scipy_io = pytest.importorskip("scipy.io")
    netcdf = getattr(scipy_io, "netcdf", None)
    if netcdf is None or not hasattr(netcdf, "netcdf_file"):
        pytest.skip("this SciPy has no scipy.io.netcdf")
    # The backend module is consulted at call time, so this forces SciPy even where
    # netCDF4 is installed -- the state of an install that has only the SciPy extra.
    monkeypatch.setattr(netcdf_backend, "nc", netcdf)
    monkeypatch.setattr(netcdf_backend, "NETCDF_BACKEND", "scipy")
    md = parse_inpcrd(str(sample_md_data_dir / "ntp_prod_0000.rst"))
    assert md.file_format == "NetCDF"
    assert md.program == "pmemd"
    assert md.program_version == "Version 22"
    assert md.conventions == "AMBERRESTART"
    assert not md.title.startswith("b'")
    assert md.time == pytest.approx(920.0)
