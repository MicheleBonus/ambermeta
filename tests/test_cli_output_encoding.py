"""CLI output on a stream whose encoding cannot spell every character.

On Windows a redirected or piped stdout is encoded with the ANSI code page (cp1252 on a
Western install), not UTF-8. `ambermeta --help | more`, `ambermeta plan ... > report.txt`
and every CI log on a Windows runner are that case. A character outside the code page
used to raise `UnicodeEncodeError` out of `print`, so the help crashed with a traceback
before the user had read a word of it.

Each test runs the same command twice, once into a UTF-8 stream and once into a strict
cp1252 one, and compares what the reader receives.
"""
from __future__ import annotations

import io
import shutil
import sys

import numpy as np
import pytest

import ambermeta.cli as cli
from ambermeta import netcdf_backend


def _run_into(encoding, argv, monkeypatch):
    """Run the CLI with stdout encoded as `encoding`, strict; return (exit code, text)."""
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding=encoding, errors="strict", newline="\n")
    monkeypatch.setattr(sys, "stdout", stream)
    try:
        code = cli.main(argv)
    except SystemExit as exc:  # argparse leaves through SystemExit after --help
        code = exc.code
    stream.flush()
    return code, raw.getvalue().decode(encoding)


@pytest.mark.parametrize("command", [
    [], ["plan"], ["discover"], ["validate"], ["export"], ["init"], ["info"], ["gui"],
    ["completion"],
], ids=lambda c: c[0] if c else "root")
def test_help_reads_the_same_through_a_cp1252_pipe(command, monkeypatch):
    _, intended = _run_into("utf-8", command + ["--help"], monkeypatch)

    code, received = _run_into("cp1252", command + ["--help"], monkeypatch)

    assert code == 0
    assert received == intended


def test_a_file_name_outside_the_code_page_does_not_crash_info(
        tmp_path, monkeypatch, sample_md_data_dir):
    # Greek, Polish and CJK directory names are common on the machines that hold the
    # runs, and cp1252 has no glyph for them. The tool echoes the name back, so the
    # echo must degrade, not raise.
    target = tmp_path / "prod_β.mdin"
    shutil.copy(sample_md_data_dir / "ntp_prod_0001.mdin", target)

    code, received = _run_into("cp1252", ["info", str(target)], monkeypatch)

    assert code == 0
    assert "File Information" in received
    assert "nstlim" in received


@pytest.mark.skipif(
    not netcdf_backend.HAS_NETCDF or netcdf_backend.NETCDF_BACKEND != "netCDF4",
    reason="needs the netCDF4 backend to build an AMBER trajectory fixture",
)
def test_trajectory_statistics_read_the_same_through_a_cp1252_pipe(tmp_path, monkeypatch):
    # The verbose stage summary reports a trajectory's mean frame interval and box
    # volume as approximations.
    ds = netcdf_backend.nc.Dataset(str(tmp_path / "prod.nc"), "w",
                                   format="NETCDF3_64BIT_OFFSET")
    ds.Conventions = "AMBER"
    for name, size in (("frame", None), ("atom", 4), ("spatial", 3),
                       ("cell_spatial", 3), ("cell_angular", 3)):
        ds.createDimension(name, size)
    ds.createVariable("time", "f4", ("frame",))[:] = 1000.0 + np.arange(5, dtype="f4") * 20
    ds.createVariable("coordinates", "f4", ("frame", "atom", "spatial"))[:] = (
        np.zeros((5, 4, 3), dtype="f4"))
    ds.createVariable("cell_lengths", "f8", ("frame", "cell_spatial"))[:] = np.full((5, 3), 30.0)
    ds.createVariable("cell_angles", "f8", ("frame", "cell_angular"))[:] = np.full((5, 3), 90.0)
    ds.close()
    argv = ["plan", str(tmp_path), "--recursive", "-v"]

    _, intended = _run_into("utf-8", argv, monkeypatch)
    code, received = _run_into("cp1252", argv, monkeypatch)

    assert "mdcrd:" in intended  # the line under test is really printed
    assert code == 0
    assert received == intended
