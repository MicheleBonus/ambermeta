"""The GUI segfault: two threads inside libhdf5 at once.

`libhdf5` is not built thread-safe in the wheels/conda packages this runs on, and
netCDF4-python adds no locking. Every route in ambermeta.gui.api.routes is a sync `def`,
so Starlette runs them in anyio's worker threadpool -- clicking a `.nc` in the file tree
while Validate walked a 1021-trajectory campaign put three threads inside the C library
and killed the server with SIGSEGV in H5SL__insert_common. Two core dumps, same stack.

The concurrency test runs in a SUBPROCESS on purpose: a regression here is a segfault,
which would take the whole pytest session down with it and report nothing useful. A
subprocess turns it into an exit code the test can assert on.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from ambermeta import netcdf_backend

np = pytest.importorskip("numpy")
pytestmark = pytest.mark.skipif(
    not netcdf_backend.HAS_NETCDF or netcdf_backend.NETCDF_BACKEND != "netCDF4",
    reason="needs the netCDF4 backend to build AMBER NetCDF fixtures",
)

ROOT = Path(__file__).resolve().parent.parent


def _write_trajectory(path: Path, frames: int = 4, atoms: int = 6) -> None:
    nc = netcdf_backend.nc
    ds = nc.Dataset(str(path), "w", format="NETCDF3_64BIT_OFFSET")
    ds.Conventions = "AMBER"
    ds.program = "pmemd"
    ds.createDimension("frame", None)
    ds.createDimension("atom", atoms)
    ds.createDimension("spatial", 3)
    ds.createDimension("cell_spatial", 3)
    ds.createDimension("cell_angular", 3)
    t = ds.createVariable("time", "f4", ("frame",))
    t[:] = np.arange(frames, dtype="f4") * 2.0
    xyz = ds.createVariable("coordinates", "f4", ("frame", "atom", "spatial"))
    xyz[:] = np.zeros((frames, atoms, 3), dtype="f4")
    cl = ds.createVariable("cell_lengths", "f8", ("frame", "cell_spatial"))
    cl[:] = np.full((frames, 3), 30.0)
    ca = ds.createVariable("cell_angles", "f8", ("frame", "cell_angular"))
    ca[:] = np.full((frames, 3), 90.0)
    ds.close()


def _write_restart(path: Path, atoms: int = 6) -> None:
    nc = netcdf_backend.nc
    ds = nc.Dataset(str(path), "w", format="NETCDF3_64BIT_OFFSET")
    ds.Conventions = "AMBERRESTART"
    ds.createDimension("atom", atoms)
    ds.createDimension("spatial", 3)
    ds.createDimension("cell_spatial", 3)
    ds.createDimension("cell_angular", 3)
    t = ds.createVariable("time", "f8", ())
    t[...] = 8.0
    ds.createVariable("coordinates", "f8", ("atom", "spatial"))[:] = np.zeros((atoms, 3))
    ds.createVariable("cell_lengths", "f8", ("cell_spatial",))[:] = np.full(3, 30.0)
    ds.createVariable("cell_angles", "f8", ("cell_angular",))[:] = np.full(3, 90.0)
    ds.close()


_WORKER = textwrap.dedent(
    """
    import sys, glob
    from concurrent.futures import ThreadPoolExecutor
    sys.path.insert(0, {root!r})
    from ambermeta.legacy_extractors.mdcrd import parse_mdcrd
    from ambermeta.legacy_extractors.inpcrd import parse_inpcrd

    trajectories = sorted(glob.glob({d!r} + "/*.nc"))
    restarts = sorted(glob.glob({d!r} + "/*.ncrst"))
    assert trajectories and restarts

    # Mixed and interleaved on purpose: the crash was one thread in nc_open while
    # another was in Variable.__getitem__, the two parsers are different call sites,
    # and distinct files in flight at once is what widens the race window. Measured
    # against the pre-fix code (a bare nc.Dataset per thread) this shape segfaults
    # about four runs in five; batching one file at a time detects it far less often.
    work = []
    for _ in range(60):
        for traj, rst in zip(trajectories, restarts):
            work.append((parse_mdcrd, traj))
            work.append((parse_inpcrd, rst))

    with ThreadPoolExecutor(max_workers=16) as ex:
        out = list(ex.map(lambda pair: pair[0](pair[1]), work))
    assert len(out) == len(work)
    print("ok")
    """
)


def test_concurrent_netcdf_parsing_does_not_segfault(tmp_path):
    for i in range(6):
        _write_trajectory(tmp_path / f"prod_{i:04d}.nc")
        _write_restart(tmp_path / f"prod_{i:04d}.ncrst")

    script = _WORKER.format(root=str(ROOT), d=str(tmp_path))
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True,
                          text=True, timeout=300)
    # -11 is SIGSEGV: the exact regression. Report it as such rather than as "non-zero".
    assert proc.returncode == 0, (
        f"exit={proc.returncode}"
        + (" (SIGSEGV -- netCDF/HDF5 was re-entered from two threads)"
           if proc.returncode == -11 else "")
        + f"\nstdout: {proc.stdout}\nstderr: {proc.stderr[-2000:]}"
    )
    assert "ok" in proc.stdout


def test_open_dataset_holds_the_lock_for_the_whole_session(tmp_path):
    """Not just for the open. Reading a variable re-enters the same C library."""
    path = tmp_path / "traj.nc"
    _write_trajectory(path)

    held_inside = []
    released_after = []

    def probe(sink):
        # acquire(blocking=False) from ANOTHER thread: an RLock is re-entrant for the
        # thread that owns it, so probing from this one would always succeed.
        got = netcdf_backend.netcdf_lock().acquire(blocking=False)
        if got:
            netcdf_backend.netcdf_lock().release()
        sink.append(got)

    with netcdf_backend.open_dataset(str(path)) as ds:
        assert ds.variables["time"].shape == (4,)
        t = threading.Thread(target=probe, args=(held_inside,))
        t.start(); t.join()

    t = threading.Thread(target=probe, args=(released_after,))
    t.start(); t.join()

    assert held_inside == [False], "another thread could enter the C library mid-session"
    assert released_after == [True], "the lock outlived the dataset"


def test_the_lock_is_dropped_between_files(tmp_path):
    """Per-file, not per-caller.

    A Validate walking a thousand trajectories must not make a concurrent request for one
    file's metadata wait for all of them -- that is a hang traded for a crash.
    """
    paths = []
    for i in range(3):
        p = tmp_path / f"t{i}.nc"
        _write_trajectory(p)
        paths.append(str(p))

    from ambermeta.legacy_extractors.mdcrd import parse_mdcrd

    seen_free = threading.Event()
    stop = threading.Event()

    def watcher():
        while not stop.is_set():
            if netcdf_backend.netcdf_lock().acquire(blocking=False):
                netcdf_backend.netcdf_lock().release()
                seen_free.set()
                return
            time.sleep(0.001)

    w = threading.Thread(target=watcher)
    w.start()
    for _ in range(40):
        for p in paths:
            parse_mdcrd(p)
    stop.set()
    w.join(timeout=5)

    assert seen_free.is_set(), "the lock was never released while files were being parsed"
