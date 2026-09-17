"""The one place this package opens a NetCDF file, and the lock that makes it safe.

`libhdf5` is built without ``--enable-threadsafe`` in the wheels and conda packages
AmberMeta actually runs on, and ``netCDF4``-python does no locking of its own -- its
own documentation says the module is not thread-safe. Two threads inside ``nc_open``
at the same moment race on HDF5's global property-list skip list and the process dies
with SIGSEGV:

    thread A: nc_open -> NC_infermodel -> H5Pcreate -> H5SL_insert -> H5SL__insert_common
    thread B: nc_open -> NC_infermodel -> H5Fis_accessible -> H5FD__sec2_open
    thread C: netCDF4 Variable.__getitem__

That is the real stack, off two core dumps taken from `ambermeta gui` while it was
validating a 1021-trajectory campaign, and it reproduces 5 runs out of 5 from a plain
``ThreadPoolExecutor``. Nothing about it is specific to the GUI -- but the GUI is where
it fires, because every route in ``ambermeta.gui.api.routes`` is a synchronous ``def``
and Starlette runs those in anyio's worker threadpool, so two HTTP requests really do
run in parallel. Clicking a ``.nc`` in the file tree while Validate is walking the
trajectories is enough.

`open_dataset` therefore holds one process-wide lock for the WHOLE session, not just
for the open. Thread C above was in ``Variable.__getitem__`` -- reading a variable
re-enters the same C library and crashes in its own right -- so unlocking after the
open would make the crash rarer rather than impossible.

The lock is per-file, though, not per-caller: it is taken when a dataset is opened and
dropped when it is closed. A Validate walking a thousand trajectories therefore yields
between files, and a concurrent request for one file's metadata waits milliseconds
rather than minutes.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator

HAS_NETCDF = False
NETCDF_BACKEND = "None"
nc: Any = None

try:  # pragma: no cover - optional dependency
    import netCDF4 as nc  # type: ignore[no-redef]

    HAS_NETCDF = True
    NETCDF_BACKEND = "netCDF4"
except ImportError:  # pragma: no cover - optional dependency
    try:
        from scipy.io import netcdf as nc  # type: ignore[no-redef]

        HAS_NETCDF = True
        NETCDF_BACKEND = "scipy"
    except ImportError:
        nc = None


# Re-entrant so that a caller already holding it -- a parser that consults another
# parser, say -- deadlocks nowhere. The failure this guards against is cross-thread, and
# an RLock excludes other threads exactly as a Lock does.
_LOCK = threading.RLock()


def netcdf_lock() -> "threading.RLock":
    """The process-wide lock guarding every NetCDF/HDF5 call.

    Exported for code that has to touch the C library outside `open_dataset` (a test
    that builds a fixture file with ``Dataset(path, "w")``, for instance). Anything
    that opens a dataset for READING should use `open_dataset` instead.
    """
    return _LOCK


@contextmanager
def open_dataset(filepath: str) -> Iterator[Any]:
    """Open `filepath` read-only under the lock; close it on the way out.

    Raises whatever the backend raises -- callers already translate those into
    warnings, and swallowing them here would turn an unreadable file into a
    confidently empty one.
    """
    if not HAS_NETCDF:
        raise ImportError("no NetCDF backend available (install netCDF4 or scipy)")
    with _LOCK:
        if NETCDF_BACKEND == "netCDF4":
            ds = nc.Dataset(filepath, "r")
        else:
            ds = nc.netcdf_file(filepath, "r", mmap=False)
        try:
            yield ds
        finally:
            ds.close()


__all__ = ["HAS_NETCDF", "NETCDF_BACKEND", "nc", "netcdf_lock", "open_dataset"]
