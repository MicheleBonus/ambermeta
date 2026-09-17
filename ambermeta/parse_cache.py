"""Memoised file parses, keyed on what a file IS rather than on what it is called.

A Validate re-reads every run file the document names. On a real campaign -- 1097 runs,
1021 NetCDF trajectories, 253 GB -- that is about ninety seconds, and the GUI fires a
Validate after *every* document change (App.tsx re-runs it whenever the document identity
changes), so a single drag-and-drop used to cost another ninety seconds of re-parsing
files that had not moved. `plan` then builds the protocol a second time on top of that.

Within one Validate the same file is also read more than once by construction: a restart
is the producing step's output and the consuming step's input coordinates, so a chained
campaign parses every ``.restrt`` twice, and an mdout is read once by `MdoutParser` and
again by `read_mdout_header`.

The key is ``(kind, path, st_dev, st_ino, st_mtime_ns, st_size)`` -- identity plus
mtime plus size, so a file edited between two Validates is re-read, and a run still
being written by AMBER is re-read on the next pass. The file is stat'ed again *after*
the parse and the result is only stored if nothing moved underneath it; that is what
keeps a half-written mdout from being memoised as though it were the finished one.

Parsed metadata is shared by reference, not copied. Nothing in the engine mutates a
parsed object -- `_apply_topologies` has always handed one `PrmtopData` to every stage
that needs it -- and keeping that true is the condition on this module being correct.

Set ``AMBERMETA_PARSE_CACHE=0`` to turn it off, or ``AMBERMETA_PARSE_CACHE_SIZE`` to
change how many entries it holds (default 8192, enough for the campaign above).
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Any, Callable, Optional, Tuple

_DEFAULT_SIZE = 8192


def _configured_size() -> int:
    raw = os.environ.get("AMBERMETA_PARSE_CACHE_SIZE")
    if raw is None:
        return 0 if os.environ.get("AMBERMETA_PARSE_CACHE") == "0" else _DEFAULT_SIZE
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_SIZE


class _LRU:
    """A small bounded LRU. Locked, because the GUI parses from anyio's worker threads."""

    def __init__(self, maxsize: int) -> None:
        self.maxsize = maxsize
        self._data: "OrderedDict[Any, Any]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Any) -> Tuple[bool, Any]:
        if self.maxsize <= 0:
            return False, None
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return True, self._data[key]
            self.misses += 1
            return False, None

    def put(self, key: Any, value: Any) -> None:
        if self.maxsize <= 0:
            return
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0

    def resize(self, maxsize: int) -> None:
        with self._lock:
            self.maxsize = maxsize
            while self.maxsize > 0 and len(self._data) > self.maxsize:
                self._data.popitem(last=False)
            if self.maxsize <= 0:
                self._data.clear()


_CACHE = _LRU(_configured_size())


def _identity(path: str) -> Optional[Tuple[Any, ...]]:
    """The file's identity-and-version, or None if it cannot be stat'ed."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    # ctime as well as mtime: on a filesystem whose timestamps are coarse (some network
    # mounts round to the second), a rewrite of the same length inside one tick leaves
    # mtime and size unchanged. ctime moves on any inode change, so it closes that window
    # without costing a second stat.
    return (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size)


def cached_parse(kind: str, path: str, produce: Callable[[], Any]) -> Any:
    """`produce()`'s result for `path`, reused while the file is unchanged.

    `kind` separates readers that disagree about the same bytes -- an mdout is read both
    as full metadata and as a header-only record, and a ``.restrt`` is offered to both the
    restart reader and the trajectory reader.

    A file that cannot be stat'ed is parsed and not cached: `produce` is still the
    authority on what that means (usually a FileNotFoundError the caller wants raised).
    """
    if _CACHE.maxsize <= 0:
        return produce()

    before = _identity(path)
    if before is None:
        return produce()

    key = (kind, os.path.abspath(path)) + before
    found, value = _CACHE.get(key)
    if found:
        return value

    value = produce()

    # Re-stat: if the file moved under us while it was being read, what we just parsed is
    # not what `before` describes, and storing it there would pin a torn read until the
    # next write. Dropping it costs one re-parse next time and nothing else.
    if _identity(path) == before:
        _CACHE.put(key, value)
    return value


def clear_cache() -> None:
    """Forget everything. For tests, and for a caller that has reason to distrust mtime."""
    _CACHE.clear()


def cache_stats() -> dict:
    return {"hits": _CACHE.hits, "misses": _CACHE.misses,
            "size": len(_CACHE._data), "maxsize": _CACHE.maxsize}


def set_cache_size(maxsize: int) -> None:
    """Resize (0 disables and empties). For tests and for callers that know better."""
    _CACHE.resize(maxsize)


__all__ = ["cached_parse", "clear_cache", "cache_stats", "set_cache_size"]
