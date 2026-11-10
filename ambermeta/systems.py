"""Telling separate simulations apart before they are scanned into one.

A campaign folder (`wt/`, `mut/`, each with its own topology and runs) used to be scanned
into a single simulation: one starting structure for both systems, the two systems proposed
as replicas of each other, and nothing louder than "confirm normal vs HMR" to say so. The
result looked plausible and was wrong, which is the worst kind of wrong for a provenance
tool.

The rule here is physical rather than a guess about folder names: a restart written by a
run of N atoms cannot be read by a run of M atoms, so runs whose mdouts report different
atom counts cannot belong to one chain, and therefore not to one simulation. Runs that
state no atom count (an mdout without its `RESOURCE USE` block) are left out of the
comparison rather than guessed at.

Two systems of the same size (the same protein under two force fields, say) are not caught
by this. Telling those apart needs the topology each run records, which AMBER prints in a
column that is usually clipped; that is a later step.

Both scans use it: `core_bridge.discover_draft` (`ambermeta discover`, the GUI's Discover)
and `protocol.auto_discover` (`plan --recursive`). A manifest is never checked: it is the
user's own declaration of what one simulation is.
"""
from __future__ import annotations

import posixpath
from typing import Dict, List, Mapping, NamedTuple, Optional

from ambermeta.errors import AmberMetaError


class SystemGroup(NamedTuple):
    """The runs of one size, and what to call them in a message."""

    label: str        # the folder the runs share ("wt"), else the first run's name
    is_folder: bool   # whether `label` is a folder (it can be handed to a command)
    natom: int
    runs: List[str]   # run stems, posix paths relative to the scanned directory

    @property
    def shown(self) -> str:
        """`wt/` for a folder, so it reads as one; a run's name as it is."""
        return self.label + "/" if self.is_folder else self.label


class SeparateSystemsError(AmberMetaError):
    """The scanned folder holds runs of more than one size: several simulations.

    The message states the problem and lists the systems. What to do next differs
    between the CLI (run each folder) and the GUI (start in one folder), so each front end
    adds its own advice from `systems`.
    """

    def __init__(self, systems: List[SystemGroup]):
        self.systems = systems
        width = max(len(s.shown) for s in systems)
        lines = [f"This folder holds {len(systems)} separate simulations: their runs report "
                 "different atom counts, and a run can only continue a run of the same "
                 "size."]
        lines += [f"  {s.shown:<{width}}  {len(s.runs)} run(s), {s.natom} atoms"
                  for s in systems]
        super().__init__("\n".join(lines))

    @property
    def folders(self) -> List[str]:
        """Each system's folder, when every system has one of its own; else empty."""
        if all(s.is_folder for s in self.systems):
            return [s.label for s in self.systems]
        return []


def separate_systems(natom_by_run: Mapping[str, Optional[int]]) -> List[SystemGroup]:
    """Group runs by the atom count their mdout reports.

    Returns one group per size, the group with the most runs first, or an empty list when
    every run that states a size states the same one (or none states any): one
    simulation, as far as the files can tell.
    """
    by_size: Dict[int, List[str]] = {}
    for run, natom in natom_by_run.items():
        if natom:
            by_size.setdefault(int(natom), []).append(run)
    if len(by_size) < 2:
        return []
    folders = {natom: _own_folder(runs, [r for n, rs in by_size.items() if n != natom
                                          for r in rs])
               for natom, runs in by_size.items()}
    # Two sizes in one folder (a vacuum minimisation beside the solvated runs), or one
    # inside the other's folder, cannot be separated by folder: "discover wt" would take
    # both again. Every group is then named by its first run instead.
    by_folder = all(folders.values())
    groups = [SystemGroup(folders[natom] if by_folder else sorted(runs)[0], by_folder,
                          natom, sorted(runs))
              for natom, runs in by_size.items()]
    return sorted(groups, key=lambda g: (-len(g.runs), g.label))


def _own_folder(runs: List[str], others: List[str]) -> str:
    """The shortest folder holding every one of `runs` and none of `others`, or "".

    The shortest, not the deepest: a system whose runs all sit in `mut/prod/` keeps its
    topology and starting structure in `mut/setup/`, and `discover mut/prod` would leave
    them out. Deeper only when it has to be, as for `campaign/wt` scanned from above.
    """
    dirs = [posixpath.dirname(r) for r in runs]
    if not all(dirs):
        return ""
    parts = posixpath.commonpath(dirs).split("/")
    for depth in range(1, len(parts) + 1):
        prefix = "/".join(parts[:depth])
        if not any(o.startswith(prefix + "/") for o in others):
            return prefix
    return ""
