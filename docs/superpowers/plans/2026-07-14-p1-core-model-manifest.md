# P1 — Core Model & Manifest v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Simulation → Phase → Step data model + topology pool + manifest v2 (with tolerant v1 auto-migration), a single shared role classifier, corrected continuity/sequence-gap logic, and content-based `.crd` sniffing — the correctness substrate for the redesign.

**Architecture:** New structural model and helpers land as **focused new modules** (`roles.py`, `topology_pool.py`, `coords.py`, `simulation.py`) that coexist with the current `SimulationStage`/`SimulationProtocol` during transition; P2–P4 rewire consumers (GUI/API/CLI) onto them. Where an audit fix improves code the current CLI/GUI already use (continuity tolerance, role delegation, HMR threshold), we fix it in place so the benefit is immediate. Every audit failure mode gets a regression test built on the real fixtures in `tests/data/amber/md_test_files/`.

**Tech Stack:** Python 3.11+ (dataclasses, `tomllib`), pytest. Optional deps `pyyaml`/`tomli` already handled in `manifest.py`. No new third-party dependencies.

## Global Constraints

- **Canonical role tokens (verbatim):** `minimization`, `heating`, `equilibration`, `production`, and `""` (unknown). No other role strings may be written to `stage_role`/`Phase.role`.
- **HMR timestep rule (verbatim from Amber manual):** non-HMR SHAKE max `dt = 0.002` ps; `dt > 0.002` implies HMR. Use `implies_hmr(dt)` everywhere; never re-hardcode `0.003`.
- **Charge / detection facts are already correct** — do not touch the mass-based HMR detection in `legacy_extractors/prmtop.py` (that is out of scope here; parser bug-fixes are the sibling plan **P1-fixes**).
- **No third-party deps added.** Standard library + existing optional yaml/tomllib only.
- **Branch:** all work commits to `phase-step-redesign` (already created).
- **Tests:** every task ends green on the **full** suite (`pytest -q`), not just the new test.
- **Manifest v2 top-level shape (verbatim, from the design spec §4):** `{version: 2, simulation: {topologies: [...], starting_structure: ...}, phases: [...], steps: [...]}`.

---

## File Structure

**Create:**
- `ambermeta/roles.py` — the single canonical role classifier (`classify_role`).
- `ambermeta/topology_pool.py` — `Topology`, `TopologyPool`, `implies_hmr`, `classify_topology_pool`.
- `ambermeta/coords.py` — `sniff_coordinate_kind` (content-based inpcrd-vs-trajectory).
- `ambermeta/simulation.py` — structural v2 model (`Topology`/`InputCoords`/`Step`/`Phase`/`Simulation`), payload (de)serialization, `load_simulation`/`write_simulation`, `migrate_v1_manifest`.
- Tests: `tests/test_roles.py`, `tests/test_topology_pool.py`, `tests/test_continuity_p1.py`, `tests/test_coords.py`, `tests/test_simulation.py`, `tests/test_migration.py`.

**Modify:**
- `ambermeta/protocol.py` — `_check_continuity` tolerance; `infer_stage_role_from_path`/`infer_stage_role_from_content` delegate to `classify_role`; `_manifest_to_stages` role assignment; `_apply_global_and_hmr_prmtop` HMR threshold; add `detect_sequence_gaps`.
- `ambermeta/cli.py` — `_suggest_stage_role` delegates to `classify_role`.
- `ambermeta/manifest.py` — extract `_read_raw_manifest` (raw read, no normalization) so v2 can bypass v1 key-normalization.

**Note on `Topology`:** `topology_pool.Topology` (a discovery/classification value with `n_atoms`) and `simulation.Topology` (a persisted pool entry) are deliberately distinct — one classifies files on disk, the other is the manifest record. Keep them separate; do not merge.

---

## Group A — Unified role classifier (audit cluster 1)

### Task A1: `classify_role` — the single source of truth

**Files:**
- Create: `ambermeta/roles.py`
- Test: `tests/test_roles.py`

**Interfaces:**
- Produces: `classify_role(name: Optional[str] = None, *, mdin_details: Any = None, mdout_details: Any = None) -> str` returning a canonical token or `""`; and `CANONICAL_ROLES: tuple[str, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roles.py
from ambermeta.roles import classify_role, CANONICAL_ROLES


class _Details:
    def __init__(self, cntrl=None, imin=None):
        self.cntrl_parameters = cntrl or {}
        self.imin = imin


def test_canonical_tokens_only():
    assert CANONICAL_ROLES == ("minimization", "heating", "equilibration", "production")


def test_name_matching_is_word_bounded_and_path_aware():
    # standard recursive tree — the divergence case from the audit
    assert classify_role("min/step1") == "minimization"
    assert classify_role("equil/step1") == "equilibration"
    assert classify_role("prod/run") == "production"
    # startswith false positives are gone
    assert classify_role("minor_tweak") == ""
    assert classify_role("product_notes") == ""


def test_ambiguous_bare_tokens_are_not_forced():
    # bare md/run are too ambiguous to be roles from the name alone
    assert classify_role("md") == ""
    assert classify_role("run_1") == ""
    # therm/anneal DO map to heating
    assert classify_role("therm") == "heating"


def test_content_imin_is_authoritative_over_name():
    d = _Details(cntrl={"imin": 1})
    assert classify_role("prod_001", mdin_details=d) == "minimization"


def test_content_heuristics_are_reachable():
    assert classify_role("run", mdin_details=_Details(cntrl={"ntr": 1})) == "equilibration"
    assert classify_role("run", mdin_details=_Details(cntrl={"tempi": 0, "temp0": 300})) == "heating"
    assert classify_role("run", mdin_details=_Details(cntrl={"nstlim": 1_000_000})) == "production"
    assert classify_role("run") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_roles.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ambermeta.roles'`

- [ ] **Step 3: Write minimal implementation**

```python
# ambermeta/roles.py
from __future__ import annotations

import re
from typing import Any, Optional

CANONICAL_ROLES = ("minimization", "heating", "equilibration", "production")

# Word-boundary cues per path component. First match wins. Separators: start/end
# of a component and any of _ . - . Bare ambiguous tokens (md, run) are excluded
# on purpose; content heuristics catch those when the parameters are available.
_NAME_CUES = [
    (re.compile(r"(?:^|[_.\-])(?:min|minim|em)(?:[_.\-]|$)"), "minimization"),
    (re.compile(r"(?:^|[_.\-])(?:heat|warm|therm|anneal)(?:[_.\-]|$|ing\b)"), "heating"),
    (re.compile(r"(?:^|[_.\-])(?:equil|eq|nvt|npt)(?:[_.\-]|$)"), "equilibration"),
    (re.compile(r"(?:^|[_.\-])(?:prod|production)(?:[_.\-]|$)"), "production"),
]


def _role_from_name(name: str) -> str:
    lowered = name.lower().replace("\\", "/")
    for part in lowered.split("/"):
        for pattern, role in _NAME_CUES:
            if pattern.search(part):
                return role
    return ""


def _role_from_content(mdin_details: Any, mdout_details: Any) -> str:
    cntrl = getattr(mdin_details, "cntrl_parameters", None) or {}
    if cntrl.get("ntr") == 1 or cntrl.get("ibelly") == 1:
        return "equilibration"
    tempi = cntrl.get("tempi")
    temp0 = cntrl.get("temp0")
    if isinstance(tempi, (int, float)) and isinstance(temp0, (int, float)):
        if tempi < temp0 and tempi <= 50:
            return "heating"
    nstlim = cntrl.get("nstlim")
    if isinstance(nstlim, (int, float)) and nstlim > 500000:
        return "production"
    return ""


def classify_role(
    name: Optional[str] = None,
    *,
    mdin_details: Any = None,
    mdout_details: Any = None,
) -> str:
    """Return the canonical stage role for a run, or '' if unknown.

    Precedence: (1) authoritative content (imin==1 -> minimization);
    (2) filename/path cues (word-boundary, path-aware);
    (3) other content heuristics (restraints/temperature ramp/length).
    Shared by GUI discover and CLI init so they never diverge.
    """
    cntrl = getattr(mdin_details, "cntrl_parameters", None) or {}
    if cntrl.get("imin") == 1 or getattr(mdout_details, "imin", None) == 1:
        return "minimization"
    if name:
        by_name = _role_from_name(name)
        if by_name:
            return by_name
    return _role_from_content(mdin_details, mdout_details)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_roles.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add ambermeta/roles.py tests/test_roles.py
git commit -m "feat(core): add unified classify_role (canonical tokens, path-aware, content-first)"
```

### Task A2: Route all three legacy guessers through `classify_role`

**Files:**
- Modify: `ambermeta/protocol.py:1115-1201` (`infer_stage_role_from_path`, `infer_stage_role_from_content`) and `:976-979` (`_manifest_to_stages` role assignment)
- Modify: `ambermeta/cli.py:202-215` (`_suggest_stage_role`)
- Test: `tests/test_roles.py` (add a parity test)

**Interfaces:**
- Consumes: `classify_role` from Task A1.
- Produces: `infer_stage_role_from_path` and `cli._suggest_stage_role` now return identical roles for identical inputs.

- [ ] **Step 1: Write the failing parity test**

```python
# append to tests/test_roles.py
from ambermeta.protocol import infer_stage_role_from_path
from ambermeta.cli import _suggest_stage_role


def test_gui_and_cli_agree_on_the_same_stems():
    for stem in ["min/step1", "equil/step1", "prod/run", "minor_tweak",
                 "product_notes", "md", "therm", "01_min", "heat"]:
        gui = infer_stage_role_from_path(stem) or ""
        cli = _suggest_stage_role(stem)
        assert gui == cli, f"divergence on {stem!r}: gui={gui!r} cli={cli!r}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_roles.py::test_gui_and_cli_agree_on_the_same_stems -q`
Expected: FAIL (e.g. `prod/run`: gui='production' cli='') — the audit divergence.

- [ ] **Step 3: Rewrite the three functions to delegate**

In `ambermeta/protocol.py`, add near the top-level imports (after line 18): `from ambermeta.roles import classify_role`. Replace the **body** of `infer_stage_role_from_path` (lines 1121-1153, keep the signature/docstring) with:

```python
    return classify_role(path) or None
```

Replace the **body** of `infer_stage_role_from_content` (lines 1164-1201, keep signature/docstring) with:

```python
    mdin_details = getattr(mdin_data, "details", None)
    mdout_details = getattr(mdout_data, "details", None)
    return classify_role(mdin_details=mdin_details, mdout_details=mdout_details) or None
```

In `_manifest_to_stages`, replace lines 976-979 with:

```python
            inferred_role = classify_role(mdin_details=getattr(stage.mdin, "details", None)) if stage.mdin else ""
            if not stage.stage_role and inferred_role:
                stage.stage_role = inferred_role
                stage.validation.append(f"INFO: stage_role '{inferred_role}' inferred from mdin content")
```

In `ambermeta/cli.py`, add `from ambermeta.roles import classify_role` near the other imports, and replace the body of `_suggest_stage_role` (lines 204-215) with:

```python
    return classify_role(name)
```

- [ ] **Step 4: Run the full suite to verify parity + no regressions**

Run: `pytest -q`
Expected: PASS. (If a pre-existing test asserted the old `md`/`run`→production behavior, update it to the canonical result and note it in the commit.)

- [ ] **Step 5: Commit**

```bash
git add ambermeta/protocol.py ambermeta/cli.py tests/test_roles.py
git commit -m "fix(core): route GUI/CLI/content role inference through classify_role (audit cluster 1)"
```

---

## Group B — Topology pool + HMR threshold (audit clusters 4 & 5)

### Task B1: `topology_pool` — keep every topology, label each

**Files:**
- Create: `ambermeta/topology_pool.py`
- Test: `tests/test_topology_pool.py`

**Interfaces:**
- Produces: `implies_hmr(dt) -> bool`; `Topology(id, path, kind, n_atoms)`; `TopologyPool` with `.normal()`, `.hmr()`, `.distinct_systems()`; `classify_topology_pool(directory: str, prmtop_rels: list[str]) -> TopologyPool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_topology_pool.py
from ambermeta.topology_pool import (
    implies_hmr, Topology, TopologyPool, classify_topology_pool,
)


def test_implies_hmr_boundary():
    assert implies_hmr(0.004) is True
    assert implies_hmr(0.0025) is True     # 2.5 fs -> HMR (was missed at >=0.003)
    assert implies_hmr(0.002) is False
    assert implies_hmr(0.001) is False
    assert implies_hmr(None) is False


def test_pool_keeps_all_and_reports_distinct_systems():
    pool = TopologyPool(topologies=[
        Topology(id="a", path="wt.prmtop", kind="normal", n_atoms=42318),
        Topology(id="b", path="wt_hmr.prmtop", kind="hmr", n_atoms=42318),
        Topology(id="c", path="mut.prmtop", kind="normal", n_atoms=42310),
    ])
    assert len(pool.topologies) == 3            # nothing collapsed
    assert [t.id for t in pool.normal()] == ["a", "c"]
    assert [t.id for t in pool.hmr()] == ["b"]
    assert pool.distinct_systems() == [42310, 42318]


def test_classify_real_topology(sample_md_data_dir):
    pool = classify_topology_pool(str(sample_md_data_dir), ["CH3L1_HUMAN_6NAG.top"])
    assert len(pool.topologies) == 1
    t = pool.topologies[0]
    assert t.path == "CH3L1_HUMAN_6NAG.top"
    assert t.kind in ("normal", "hmr")
    assert t.n_atoms and t.n_atoms > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_topology_pool.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ambermeta.topology_pool'`

- [ ] **Step 3: Write the implementation**

```python
# ambermeta/topology_pool.py
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata

# Non-HMR SHAKE runs top out at dt = 0.002 ps; anything larger implies HMR.
HMR_MIN_TIMESTEP_PS = 0.002


def implies_hmr(dt) -> bool:
    return isinstance(dt, (int, float)) and dt > HMR_MIN_TIMESTEP_PS


@dataclass
class Topology:
    id: str
    path: str
    kind: str = "normal"          # "normal" | "hmr"
    n_atoms: Optional[int] = None


@dataclass
class TopologyPool:
    topologies: List[Topology] = field(default_factory=list)

    def _by_kind(self, kind: str) -> List[Topology]:
        return [t for t in self.topologies if t.kind == kind]

    def normal(self) -> List[Topology]:
        return self._by_kind("normal")

    def hmr(self) -> List[Topology]:
        return self._by_kind("hmr")

    def distinct_systems(self) -> List[int]:
        return sorted({t.n_atoms for t in self.topologies if t.n_atoms})


def _slug(path: str, idx: int) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    return f"top_{base}" if base else f"top_{idx}"


def classify_topology_pool(directory: str, prmtop_rels: List[str]) -> TopologyPool:
    """Classify every prmtop into a labeled pool entry, keeping all of them.

    Distinct chemical systems (differing atom counts) are preserved — the old
    two-bucket classify_topologies collapsed them into one global prmtop.
    """
    pool = TopologyPool()
    for idx, rel in enumerate(sorted(prmtop_rels)):
        kind, n_atoms = "normal", None
        try:
            md = extract_prmtop_metadata(os.path.join(directory, rel))
            kind = "hmr" if getattr(md, "hmr_active", False) else "normal"
            n_atoms = getattr(md, "n_atoms", None) or getattr(md, "natom", None)
        except (IOError, OSError, ValueError, LookupError):
            pass
        pool.topologies.append(Topology(id=_slug(rel, idx), path=rel, kind=kind, n_atoms=n_atoms))
    return pool
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_topology_pool.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ambermeta/topology_pool.py tests/test_topology_pool.py
git commit -m "feat(core): topology pool keeps N labeled topologies + implies_hmr(dt>0.002)"
```

### Task B2: Use `implies_hmr` in the stage HMR-swap

**Files:**
- Modify: `ambermeta/protocol.py:853-865` (`_apply_global_and_hmr_prmtop`)
- Test: `tests/test_topology_pool.py` (add a unit check via a stub)

**Interfaces:**
- Consumes: `implies_hmr` from Task B1.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_topology_pool.py
def test_hmr_swap_uses_0002_boundary(monkeypatch):
    import ambermeta.protocol as proto

    class _MdinDetails:
        def __init__(self, dt): self.dt = dt
    class _Mdin:
        def __init__(self, dt): self.details = _MdinDetails(dt)

    stages = [proto.SimulationStage(name="prod", mdin=_Mdin(0.0025))]
    monkeypatch.setattr(proto, "_safe_parse", lambda *a, **k: "HMR_TOPO")
    monkeypatch.setattr(proto.os.path, "exists", lambda p: True)
    proto._apply_global_and_hmr_prmtop(
        stages, ".", global_prmtop=None, hmr_prmtop="wt_hmr.prmtop", strict=False)
    assert stages[0].prmtop == "HMR_TOPO"   # 2.5 fs now triggers HMR
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_topology_pool.py::test_hmr_swap_uses_0002_boundary -q`
Expected: FAIL — at `dt=0.0025` the current `>= 0.003` check leaves `prmtop` unset (`None`).

- [ ] **Step 3: Apply the fix**

In `ambermeta/protocol.py`, add to the imports: `from ambermeta.topology_pool import implies_hmr`. Replace line 862 `if isinstance(dt, (int, float)) and dt >= HMR_TIMESTEP_THRESHOLD_PS:` with:

```python
                if implies_hmr(dt):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_topology_pool.py -q && pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ambermeta/protocol.py tests/test_topology_pool.py
git commit -m "fix(core): auto-HMR at dt>0.002 not >=0.003 (audit cluster 5)"
```

---

## Group C — Continuity tolerance + sequence holes (audit cluster 3)

### Task C1: Continuity tolerance from the frame interval, not elapsed time

**Files:**
- Modify: `ambermeta/protocol.py:383-388` (inside `_check_continuity`)
- Test: `tests/test_continuity_p1.py`

**Interfaces:**
- Consumes: `SimulationStage`, `SimulationProtocol` from `protocol.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_continuity_p1.py
from ambermeta.protocol import SimulationStage, SimulationProtocol


class _D:
    def __init__(self, **kw): self.__dict__.update(kw)
class _F:
    def __init__(self, **kw): self.details = _D(**kw)


def _stage(name, *, end=None, start=None, avg_dt=None):
    s = SimulationStage(name=name)
    if end is not None:
        s.mdcrd = _F(time_end=end, avg_dt=avg_dt)
    if start is not None:
        s.inpcrd = _F(time=start)
    return s


def test_real_gap_in_long_run_is_not_snapped_to_zero():
    prev = _stage("a", end=1_000_000.0, avg_dt=0.2)
    curr = _stage("b", start=1_000_060.0)          # a real 60 ps gap at 1 us
    proto = SimulationProtocol(stages=[prev, curr])
    proto.validate()
    assert curr.observed_gap_ps == 60.0
    assert any("60" in n for n in curr.continuity)


def test_frame_interval_noise_is_still_tolerated():
    prev = _stage("a", end=100.0, avg_dt=2.0)
    curr = _stage("b", start=100.05)               # 0.05 ps < half a 2 ps frame
    proto = SimulationProtocol(stages=[prev, curr])
    proto.validate()
    assert curr.observed_gap_ps == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_continuity_p1.py -q`
Expected: FAIL on `test_real_gap...` — current tolerance `max(1.0, 1e6*1e-4)=100 ps` snaps the 60 ps gap to 0.

- [ ] **Step 3: Apply the fix**

In `ambermeta/protocol.py`, replace lines 383-388:

```python
                # Robust tolerance calculation for numerical precision and unit issues
                # Use a tolerance that scales with the magnitude of the times involved
                # Default: 1 ps or 0.01% of end_time, whichever is larger
                default_tolerance = max(1.0, abs(end_time) * 1e-4) if end_time else 1.0
                prior_dt = getattr(prev.mdcrd.details, "avg_dt", None)
                if isinstance(prior_dt, (int, float)) and prior_dt > 0:
                    # Also consider the frame interval as a tolerance factor
                    default_tolerance = max(default_tolerance, float(prior_dt) * 0.5)
```

with:

```python
                # Tolerance is a small absolute floor plus half a frame interval —
                # NOT scaled by elapsed time, which would hide real gaps in long runs.
                prior_dt = getattr(prev.mdcrd.details, "avg_dt", None)
                default_tolerance = 0.1
                if isinstance(prior_dt, (int, float)) and prior_dt > 0:
                    default_tolerance = max(default_tolerance, float(prior_dt) * 0.5)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_continuity_p1.py -q && pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ambermeta/protocol.py tests/test_continuity_p1.py
git commit -m "fix(core): continuity tolerance from frame interval, not elapsed time (audit cluster 3)"
```

### Task C2: `detect_sequence_gaps` — flag a missing numbered member

**Files:**
- Modify: `ambermeta/protocol.py` (add function near `detect_numeric_sequences`, ~line 1113)
- Test: `tests/test_continuity_p1.py`

**Interfaces:**
- Produces: `detect_sequence_gaps(names: List[str]) -> Dict[str, List[int]]` mapping a sequence base to the missing integer indices.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_continuity_p1.py
from ambermeta.protocol import detect_sequence_gaps


def test_missing_member_is_detected():
    names = ["ntp_prod_0001.mdin", "ntp_prod_0002.mdin", "ntp_prod_0004.mdin"]
    assert detect_sequence_gaps(names) == {"ntp_prod": [3]}


def test_complete_sequence_has_no_gaps():
    names = ["prod_1.mdin", "prod_2.mdin", "prod_3.mdin"]
    assert detect_sequence_gaps(names) == {}


def test_single_member_is_not_a_sequence():
    assert detect_sequence_gaps(["prod_1.mdin"]) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_continuity_p1.py -q`
Expected: FAIL with `ImportError: cannot import name 'detect_sequence_gaps'`

- [ ] **Step 3: Add the function**

Insert after `detect_numeric_sequences` (after line 1112) in `ambermeta/protocol.py`:

```python
def detect_sequence_gaps(names: List[str]) -> Dict[str, List[int]]:
    """Return, per numbered-sequence base, the integer indices that are missing.

    e.g. ['prod_0001', 'prod_0002', 'prod_0004'] -> {'prod': [3]}.
    Only bases with 2+ present members are considered; pure-numeric bases skipped.
    """
    suffix_pattern = re.compile(r'^(.+?)[-_.]?(\d+)$')
    present: Dict[str, set] = {}
    for name in names:
        stem = Path(name).stem
        match = suffix_pattern.match(stem)
        if not match:
            continue
        base = match.group(1)
        if base.isdigit():
            continue
        present.setdefault(base, set()).add(int(match.group(2)))

    gaps: Dict[str, List[int]] = {}
    for base, nums in present.items():
        if len(nums) < 2:
            continue
        missing = [i for i in range(min(nums), max(nums) + 1) if i not in nums]
        if missing:
            gaps[base] = missing
    return gaps
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_continuity_p1.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ambermeta/protocol.py tests/test_continuity_p1.py
git commit -m "feat(core): detect_sequence_gaps flags missing numbered runs (audit cluster 3)"
```

---

## Group D — `.crd` content sniffing (audit cluster 2)

### Task D1: `sniff_coordinate_kind`

**Files:**
- Create: `ambermeta/coords.py`
- Test: `tests/test_coords.py`

**Interfaces:**
- Produces: `sniff_coordinate_kind(path: str) -> str` returning `"inpcrd"`, `"mdcrd"`, or `"unknown"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_coords.py
from ambermeta.coords import sniff_coordinate_kind


def test_real_crd_is_a_starting_structure(sample_md_data_dir):
    # tleap saveamberparm output — a single-frame starting structure, not a trajectory
    path = sample_md_data_dir / "CH3L1_HUMAN_6NAG.crd"
    assert sniff_coordinate_kind(str(path)) == "inpcrd"


def test_ascii_trajectory_is_mdcrd(tmp_path):
    traj = tmp_path / "run.crd"
    # classic ASCII trajectory: title then coordinate rows (no NATOM header line)
    traj.write_text("TITLE\n" + ("  1.000  2.000  3.000  4.000  5.000  6.000\n" * 4))
    assert sniff_coordinate_kind(str(traj)) == "mdcrd"


def test_inpcrd_header_with_time(tmp_path):
    rst = tmp_path / "x.crd"
    rst.write_text("default_name\n     6  0.0010000E+03\n" + "  1.0  2.0  3.0  4.0  5.0  6.0\n" * 3)
    assert sniff_coordinate_kind(str(rst)) == "inpcrd"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coords.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ambermeta.coords'`

- [ ] **Step 3: Write the implementation**

```python
# ambermeta/coords.py
from __future__ import annotations


def sniff_coordinate_kind(path: str) -> str:
    """Decide whether a coordinate file is single-frame input/restart coords
    ('inpcrd') or a multi-frame trajectory ('mdcrd') by content, not extension.

    Amber ASCII restart/inpcrd files carry an atom-count header on line 2
    (``NATOM`` and an optional ``TIME`` float). ASCII trajectories have no such
    header — line 2 is already coordinate data. NetCDF files keep their
    unambiguous extensions (.nc / .ncrst); a NetCDF-magic file here defaults to
    trajectory. Returns 'unknown' if the file cannot be read.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
    except OSError:
        return "unknown"

    if head[:3] == b"CDF" or head == b"\x89HDF":
        return "mdcrd"

    try:
        with open(path, "r", errors="replace") as fh:
            fh.readline()                      # title
            second = fh.readline().split()
    except OSError:
        return "unknown"

    if second and second[0].isdigit() and len(second) <= 2:
        if len(second) == 1:
            return "inpcrd"
        try:
            float(second[1])                   # the optional TIME token
            return "inpcrd"
        except ValueError:
            return "mdcrd"
    return "mdcrd"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coords.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ambermeta/coords.py tests/test_coords.py
git commit -m "feat(core): content-based sniff_coordinate_kind so a .crd can be a starting structure (audit cluster 2)"
```

---

## Group E — v2 model, serialization, migration

### Task E1: The structural Simulation model

**Files:**
- Create: `ambermeta/simulation.py`
- Test: `tests/test_simulation.py`

**Interfaces:**
- Produces dataclasses: `Topology(id, path, kind="normal")`; `InputCoords(source="starting_structure", ref=None, path=None)`; `Step(id, name, topology=None, input_coords=<InputCoords>, mdin=None, mdout=None, mdcrd=None, expected_gap_ps=None, gap_tolerance_ps=None, notes=[])`; `Phase(id, name, role="", steps=[])`; `Simulation(version=2, topologies=[], starting_structure=None, phases=[])`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_simulation.py
from ambermeta.simulation import Topology, InputCoords, Step, Phase, Simulation


def test_build_a_two_phase_simulation():
    sim = Simulation(
        topologies=[Topology(id="top_wt", path="wt.prmtop", kind="normal"),
                    Topology(id="top_hmr", path="wt_hmr.prmtop", kind="hmr")],
        starting_structure="wt.inpcrd",
        phases=[
            Phase(id="ph_0", name="Minimization", role="minimization", steps=[
                Step(id="st_0", name="min", topology="top_wt",
                     input_coords=InputCoords(source="starting_structure"), mdin="min.in")]),
            Phase(id="ph_1", name="Production", role="production", steps=[
                Step(id="st_1", name="prod_001", topology="top_hmr",
                     input_coords=InputCoords(source="step", ref="st_0"), mdin="prod_001.in")]),
        ],
    )
    assert sim.version == 2
    assert [p.role for p in sim.phases] == ["minimization", "production"]
    assert sim.phases[1].steps[0].input_coords.ref == "st_0"
    assert sim.phases[0].steps[0].input_coords.source == "starting_structure"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_simulation.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ambermeta.simulation'`

- [ ] **Step 3: Write the dataclasses**

```python
# ambermeta/simulation.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Topology:
    id: str
    path: str
    kind: str = "normal"          # "normal" | "hmr"


@dataclass
class InputCoords:
    source: str = "starting_structure"   # "starting_structure" | "step" | "path"
    ref: Optional[str] = None             # Step.id when source == "step"
    path: Optional[str] = None            # explicit path when source == "path"


@dataclass
class Step:
    id: str
    name: str
    topology: Optional[str] = None        # Topology.id
    input_coords: InputCoords = field(default_factory=InputCoords)
    mdin: Optional[str] = None
    mdout: Optional[str] = None
    mdcrd: Optional[str] = None
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class Phase:
    id: str
    name: str
    role: str = ""
    steps: List[Step] = field(default_factory=list)


@dataclass
class Simulation:
    version: int = 2
    topologies: List[Topology] = field(default_factory=list)
    starting_structure: Optional[str] = None
    phases: List[Phase] = field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_simulation.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ambermeta/simulation.py tests/test_simulation.py
git commit -m "feat(core): structural Simulation/Phase/Step/Topology model"
```

### Task E2: Payload (de)serialization round-trip

**Files:**
- Modify: `ambermeta/simulation.py`
- Test: `tests/test_simulation.py`

**Interfaces:**
- Consumes: the dataclasses from E1.
- Produces: `simulation_to_payload(sim: Simulation) -> dict` (v2 shape) and `payload_to_simulation(payload: dict) -> Simulation`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_simulation.py
from ambermeta.simulation import simulation_to_payload, payload_to_simulation


def test_payload_shape_and_round_trip():
    sim = Simulation(
        topologies=[Topology(id="top_wt", path="wt.prmtop", kind="normal")],
        starting_structure="wt.inpcrd",
        phases=[Phase(id="ph_0", name="Min", role="minimization", steps=[
            Step(id="st_0", name="min", topology="top_wt",
                 input_coords=InputCoords(source="starting_structure"),
                 mdin="min.in", expected_gap_ps=5.0)])],
    )
    payload = simulation_to_payload(sim)
    assert payload["version"] == 2
    assert payload["simulation"]["topologies"][0]["kind"] == "normal"
    assert payload["simulation"]["starting_structure"] == "wt.inpcrd"
    assert payload["phases"][0]["role"] == "minimization"
    assert payload["steps"][0]["phase"] == "ph_0"
    assert payload["steps"][0]["gaps"] == {"expected": 5.0, "tolerance": None}

    back = payload_to_simulation(payload)
    assert back == sim          # dataclass equality: full round trip
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_simulation.py::test_payload_shape_and_round_trip -q`
Expected: FAIL with `ImportError: cannot import name 'simulation_to_payload'`

- [ ] **Step 3: Add the serialization functions**

Append to `ambermeta/simulation.py`:

```python
from typing import Any, Dict   # add to the existing typing import at the top


def _step_payload(step: Step, phase_id: str, order: int) -> Dict[str, Any]:
    ic: Dict[str, Any] = {"source": step.input_coords.source}
    if step.input_coords.ref is not None:
        ic["ref"] = step.input_coords.ref
    if step.input_coords.path is not None:
        ic["path"] = step.input_coords.path
    data: Dict[str, Any] = {
        "id": step.id, "name": step.name, "phase": phase_id, "order": order,
        "topology": step.topology, "input_coords": ic,
        "mdin": step.mdin, "mdout": step.mdout, "mdcrd": step.mdcrd,
        "notes": list(step.notes),
    }
    if step.expected_gap_ps is not None or step.gap_tolerance_ps is not None:
        data["gaps"] = {"expected": step.expected_gap_ps, "tolerance": step.gap_tolerance_ps}
    return data


def simulation_to_payload(sim: Simulation) -> Dict[str, Any]:
    return {
        "version": sim.version,
        "simulation": {
            "topologies": [{"id": t.id, "path": t.path, "kind": t.kind} for t in sim.topologies],
            "starting_structure": sim.starting_structure,
        },
        "phases": [
            {"id": p.id, "name": p.name, "role": p.role, "order": i}
            for i, p in enumerate(sim.phases)
        ],
        "steps": [
            _step_payload(s, p.id, j)
            for p in sim.phases for j, s in enumerate(p.steps)
        ],
    }


def payload_to_simulation(payload: Dict[str, Any]) -> Simulation:
    sim = Simulation(version=payload.get("version", 2))
    block = payload.get("simulation", {}) or {}
    for t in block.get("topologies", []) or []:
        sim.topologies.append(Topology(id=t["id"], path=t["path"], kind=t.get("kind", "normal")))
    sim.starting_structure = block.get("starting_structure")

    phases_by_id: Dict[str, Phase] = {}
    for p in sorted(payload.get("phases", []) or [], key=lambda x: x.get("order", 0)):
        phase = Phase(id=p["id"], name=p.get("name", ""), role=p.get("role", ""))
        sim.phases.append(phase)
        phases_by_id[p["id"]] = phase

    for s in sorted(payload.get("steps", []) or [], key=lambda x: (x.get("phase", ""), x.get("order", 0))):
        ic = s.get("input_coords", {}) or {}
        gaps = s.get("gaps", {}) or {}
        step = Step(
            id=s["id"], name=s.get("name", ""), topology=s.get("topology"),
            input_coords=InputCoords(source=ic.get("source", "starting_structure"),
                                     ref=ic.get("ref"), path=ic.get("path")),
            mdin=s.get("mdin"), mdout=s.get("mdout"), mdcrd=s.get("mdcrd"),
            expected_gap_ps=gaps.get("expected"), gap_tolerance_ps=gaps.get("tolerance"),
            notes=list(s.get("notes", []) or []),
        )
        phase = phases_by_id.get(s.get("phase"))
        if phase is not None:
            phase.steps.append(step)
    return sim
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_simulation.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ambermeta/simulation.py tests/test_simulation.py
git commit -m "feat(core): v2 payload serialization round-trip for Simulation"
```

### Task E3: `write_simulation` / `load_simulation` (v2 files) + raw-read refactor

**Files:**
- Modify: `ambermeta/manifest.py` (extract `_read_raw_manifest`)
- Modify: `ambermeta/simulation.py` (add file read/write)
- Test: `tests/test_simulation.py`

**Interfaces:**
- Consumes: `simulation_to_payload`/`payload_to_simulation` from E2.
- Produces: `manifest._read_raw_manifest(path, expand_env=True) -> Any`; `simulation.write_simulation(sim, path, fmt)` and `simulation.load_simulation(path) -> Simulation`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_simulation.py
from ambermeta.simulation import write_simulation, load_simulation


def test_write_then_load_v2_yaml_and_json(tmp_path):
    sim = Simulation(
        topologies=[Topology(id="top_wt", path="wt.prmtop", kind="normal")],
        starting_structure="wt.inpcrd",
        phases=[Phase(id="ph_0", name="Min", role="minimization", steps=[
            Step(id="st_0", name="min", topology="top_wt", mdin="min.in")])],
    )
    for fmt, ext in [("json", ".json"), ("yaml", ".yaml")]:
        target = tmp_path / f"sim{ext}"
        write_simulation(sim, str(target), fmt)
        loaded = load_simulation(str(target))
        assert loaded == sim
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_simulation.py::test_write_then_load_v2_yaml_and_json -q`
Expected: FAIL with `ImportError: cannot import name 'write_simulation'`

- [ ] **Step 3a: Refactor the raw read out of `load_manifest`**

In `ambermeta/manifest.py`, add this function (before `load_manifest`, ~line 347) and re-point `load_manifest` at it:

```python
def _read_raw_manifest(manifest_path: Any, expand_env: bool = True) -> Any:
    """Read + parse a manifest file to its raw container, WITHOUT v1 key
    normalization. v2 loaders need the untouched structure; v1 callers normalize
    afterwards via _normalize_container."""
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise ImportError("PyYAML is required to read YAML manifests. Install with `pip install pyyaml`.")
        manifest = yaml.safe_load(text)
    elif suffix == ".toml":
        manifest = _parse_toml_manifest(text)
    elif suffix == ".csv":
        manifest = _parse_csv_manifest(text)
    else:
        manifest = json.loads(text)
    if manifest is None:
        return {}
    if not isinstance(manifest, (dict, list)):
        raise TypeError("Manifest must be a mapping or list of stage entries.")
    if expand_env:
        manifest = _expand_env_vars(manifest)
    return manifest
```

Then replace the body of `load_manifest` (lines 368-399) with:

```python
    manifest = _read_raw_manifest(manifest_path, expand_env=expand_env)
    if manifest == {}:
        return {}
    return _normalize_container(manifest)
```

Add `"_read_raw_manifest"` to `__all__`.

- [ ] **Step 3b: Add the v2 file read/write to `simulation.py`**

Append to `ambermeta/simulation.py`:

```python
import json

from ambermeta.manifest import _read_raw_manifest, _normalize_container

try:  # optional dependency, mirrors manifest.py
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def _is_v2(raw: Any) -> bool:
    return isinstance(raw, dict) and (raw.get("version") == 2 or "phases" in raw or "simulation" in raw)


def write_simulation(sim: Simulation, path: str, fmt: str) -> None:
    """Write a Simulation as a v2 manifest. JSON and YAML are lossless; TOML/CSV
    flat export is deferred (documented lossy view, a later task)."""
    payload = simulation_to_payload(sim)
    if fmt == "json":
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        return
    if fmt == "yaml":
        if yaml is None:
            raise RuntimeError("PyYAML is required for YAML output")
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, sort_keys=False)
        return
    raise ValueError(f"v2 write supports json/yaml only, got: {fmt}")


def load_simulation(path: str) -> Simulation:
    """Load a Simulation from a manifest file, auto-migrating v1 manifests."""
    raw = _read_raw_manifest(path)
    if _is_v2(raw):
        return payload_to_simulation(raw)
    return migrate_v1_manifest(_normalize_container(raw))
```

(`migrate_v1_manifest` is added in Task E4; until then this import-time reference is fine because it is only called at runtime. Implement E4 before running the v1 path.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_simulation.py::test_write_then_load_v2_yaml_and_json -q && pytest tests/test_manifest.py -q`
Expected: PASS (v2 round-trip works; existing manifest tests still green after the refactor)

- [ ] **Step 5: Commit**

```bash
git add ambermeta/manifest.py ambermeta/simulation.py tests/test_simulation.py
git commit -m "feat(core): v2 write_simulation/load_simulation + raw-read refactor"
```

### Task E4: `migrate_v1_manifest` — flat stages → phases/steps/pool

**Files:**
- Modify: `ambermeta/simulation.py`
- Test: `tests/test_migration.py`

**Interfaces:**
- Consumes: `Simulation`/`Phase`/`Step`/`Topology`/`InputCoords`; `classify_role` (A1); `manifest._normalize_manifest`.
- Produces: `migrate_v1_manifest(container: Any) -> Simulation`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration.py
from ambermeta.simulation import migrate_v1_manifest


def test_migrate_flat_v1_to_phases_pool_and_input_chain():
    v1 = {
        "global_prmtop": "wt.prmtop",
        "hmr_prmtop": "wt_hmr.prmtop",
        "initial_coordinates": "wt.inpcrd",
        "stages": [
            {"name": "min", "stage_role": "minimization", "mdin": "min.in"},
            {"name": "heat", "stage_role": "heating", "mdin": "heat.in"},
            {"name": "prod_001", "stage_role": "production", "mdin": "prod_001.in"},
            {"name": "prod_002", "stage_role": "production", "mdin": "prod_002.in"},
        ],
    }
    sim = migrate_v1_manifest(v1)

    # topology pool: both prmtops preserved and labeled
    assert {(t.path, t.kind) for t in sim.topologies} == {
        ("wt.prmtop", "normal"), ("wt_hmr.prmtop", "hmr")}
    assert sim.starting_structure == "wt.inpcrd"

    # contiguous roles -> phases
    assert [p.role for p in sim.phases] == ["minimization", "heating", "production"]
    assert [len(p.steps) for p in sim.phases] == [1, 1, 2]

    # first step reads the starting structure; later steps chain from the previous
    first = sim.phases[0].steps[0]
    assert first.input_coords.source == "starting_structure"
    second = sim.phases[1].steps[0]
    assert second.input_coords.source == "step"
    assert second.input_coords.ref == first.id


def test_migrate_infers_role_when_absent():
    v1 = [{"name": "prod/run", "mdin": "run.in"}]   # audit divergence stem
    sim = migrate_v1_manifest(v1)
    assert sim.phases[0].role == "production"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migration.py -q`
Expected: FAIL with `ImportError: cannot import name 'migrate_v1_manifest'`

- [ ] **Step 3: Implement the migration**

Append to `ambermeta/simulation.py`:

```python
from ambermeta.manifest import _normalize_manifest
from ambermeta.roles import classify_role


def _v1_globals(container: Any) -> Dict[str, Any]:
    return container if isinstance(container, dict) and "stages" in container else {}


def migrate_v1_manifest(container: Any) -> Simulation:
    """Convert a v1 manifest container (flat stages) into a v2 Simulation.

    - global_prmtop -> normal pool entry; hmr_prmtop -> hmr pool entry.
    - initial_coordinates -> starting_structure.
    - each stage -> a Step; contiguous same-role stages -> one Phase.
    - first step reads the starting structure; each later step chains from the
      previous step's restart (the explicit input-coords source).
    """
    globals_ = _v1_globals(container)
    sim = Simulation()

    topo_by_path: Dict[str, str] = {}

    def _topref(path: Optional[str], kind: str) -> Optional[str]:
        if not path:
            return None
        if path not in topo_by_path:
            tid = f"top_{len(sim.topologies)}"
            sim.topologies.append(Topology(id=tid, path=path, kind=kind))
            topo_by_path[path] = tid
        return topo_by_path[path]

    global_prmtop = globals_.get("global_prmtop")
    hmr_prmtop = globals_.get("hmr_prmtop")
    _topref(global_prmtop, "normal")
    _topref(hmr_prmtop, "hmr")
    sim.starting_structure = globals_.get("initial_coordinates")

    prev_step_id: Optional[str] = None
    for idx, entry in enumerate(_normalize_manifest(container)):
        name = entry.get("name") or f"step_{idx}"
        role = entry.get("stage_role") or classify_role(name) or ""
        files = entry.get("files", {}) if isinstance(entry.get("files"), dict) else {}

        def _f(kind: str) -> Optional[str]:
            return entry.get(kind) or files.get(kind)

        stage_prmtop = _f("prmtop")
        if stage_prmtop:
            topology = _topref(stage_prmtop, "normal")
        else:
            topology = topo_by_path.get(global_prmtop) if global_prmtop else None

        if prev_step_id is None:
            if sim.starting_structure:
                ic = InputCoords(source="starting_structure")
            elif _f("inpcrd"):
                ic = InputCoords(source="path", path=_f("inpcrd"))
            else:
                ic = InputCoords(source="starting_structure")
        else:
            ic = InputCoords(source="step", ref=prev_step_id)

        gaps = entry.get("gaps") or {}
        step = Step(
            id=f"st_{idx}", name=name, topology=topology, input_coords=ic,
            mdin=_f("mdin"), mdout=_f("mdout"), mdcrd=_f("mdcrd"),
            expected_gap_ps=gaps.get("expected"), gap_tolerance_ps=gaps.get("tolerance"),
            notes=list(entry.get("notes") or []),
        )

        if not sim.phases or sim.phases[-1].role != role:
            sim.phases.append(Phase(id=f"ph_{len(sim.phases)}",
                                    name=(role.title() if role else "Stage"), role=role))
        sim.phases[-1].steps.append(step)
        prev_step_id = step.id

    return sim
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_migration.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add ambermeta/simulation.py tests/test_migration.py
git commit -m "feat(core): migrate_v1_manifest -> phases/steps/topology pool with input-coords chain"
```

### Task E5: End-to-end v1 file → `load_simulation` migration

**Files:**
- Test: `tests/test_migration.py`

**Interfaces:**
- Consumes: `write_manifest` (v1) and `load_simulation` (E3) + `migrate_v1_manifest` (E4).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_migration.py
import json
from ambermeta.simulation import load_simulation


def test_open_a_v1_json_file_yields_a_migrated_simulation(tmp_path):
    v1 = {
        "global_prmtop": "wt.prmtop",
        "stages": [
            {"name": "min", "stage_role": "minimization", "mdin": "min.in"},
            {"name": "prod_001", "stage_role": "production", "mdin": "prod_001.in"},
        ],
    }
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(v1))
    sim = load_simulation(str(path))
    assert sim.version == 2
    assert [p.role for p in sim.phases] == ["minimization", "production"]
    assert sim.topologies[0].path == "wt.prmtop"
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `pytest tests/test_migration.py::test_open_a_v1_json_file_yields_a_migrated_simulation -q`
Expected: PASS (E3+E4 already wire this) — this task is the **integration guard** proving `load_simulation` routes a real v1 file through migration. If it fails, the defect is in E3's `_is_v2`/dispatch; fix there.

- [ ] **Step 3: (only if Step 2 failed) fix the dispatch**

Confirm `_is_v2` returns `False` for a `{"global_prmtop", "stages"}` dict (it has no `version`/`phases`/`simulation` keys) so `load_simulation` calls `migrate_v1_manifest`.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS (entire suite green)

- [ ] **Step 5: Commit**

```bash
git add tests/test_migration.py
git commit -m "test(core): end-to-end v1 file -> load_simulation migration guard"
```

---

## Self-Review — spec coverage

- **Cluster 1 (role classifier):** A1 (`classify_role`) + A2 (delegation + parity test). ✓
- **Cluster 2 (`.crd` / shared coords):** D1 (`sniff_coordinate_kind`); the shared-inpcrd→starting-structure structural fix is E4 (`starting_structure` + input-coords chain). Discovery/file-kind wiring is P2. ✓ (core done)
- **Cluster 3 (continuity):** C1 (tolerance) + C2 (sequence gaps); the input-vs-output restart ambiguity is fixed structurally by E1/E4's explicit `InputCoords.source`. ✓
- **Cluster 4 (topology pool):** B1 (`classify_topology_pool` keeps N, distinct systems) + E1/E4 pool persistence. ✓
- **Cluster 5 (HMR threshold):** B1 (`implies_hmr`) + B2 (applied to the swap). ✓
- **Model + manifest v2 + migration (spec §3–§4):** E1–E5. ✓
- **Out of scope here (correctly):** GUI/API wiring (P2/P3), CLI wiring (P4), and the parser robustness fix-list (sibling plan **P1-fixes**). The unified classifier and continuity fixes are applied in place so current consumers benefit immediately.

**Type consistency:** `classify_role` signature is identical across A1/A2/E4; `implies_hmr` identical across B1/B2; `Topology`/`Step`/`Phase`/`Simulation` field names identical across E1–E5; `input_coords.source` values (`starting_structure`/`step`/`path`) consistent across E1/E2/E4. No placeholders.

**Note:** `simulation.py` imports `roles.classify_role`, `manifest._read_raw_manifest`/`_normalize_manifest`/`_normalize_container`. `protocol.py` and `topology_pool.py` both import from each other's neighbours but not circularly (`protocol` imports `roles` and `topology_pool`; neither imports `protocol`). `topology_pool` imports `legacy_extractors.prmtop` only.
