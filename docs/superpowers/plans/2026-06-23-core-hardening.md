# Core Correctness & Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two reported bugs and the audit-confirmed core/CLI/parser/GUI-security bugs, and introduce one canonical manifest module, so AmberMeta's first release reports correct provenance and never silently loses data.

**Architecture:** Extract manifest read/write into a new `ambermeta/manifest.py` with a *tolerant reader* (loads any prior export) and a *canonical writer* (one documented schema per format). Route the CLI through it, consolidate discovery onto the engine's `smart_group_files`, and factor global/HMR-prmtop application into one shared helper.

**Tech Stack:** Python 3.8+, pytest, optional deps `pyyaml`/`tomli`/`tomllib`, FastAPI (GUI), Textual (TUI — not touched here).

Spec: `docs/superpowers/specs/2026-06-23-core-hardening-design.md`.

## Global Constraints

- **Python floor: 3.8.** New modules start with `from __future__ import annotations`; no `match`, no `X | Y` runtime unions, no `tomllib`-only assumptions (fall back to `tomli`).
- **No new required dependencies.** YAML/TOML stay optional (guard imports as the codebase already does).
- **Public API stays importable:** `ambermeta.auto_discover`, `ambermeta.load_manifest`, `ambermeta.load_protocol_from_manifest`, `ambermeta.ProtocolBuilder`, and the parser classes keep their current signatures.
- **Tolerant reader / canonical writer:** readers accept legacy variants (`stage`→`name`, `role`→`stage_role`, flat `expected_gap_ps`/`gap_tolerance_ps`→nested `gaps`); writers emit only the canonical schema.
- **No silent failures:** wrong/missing/empty results become a logged warning or a non-zero exit; under `--strict` they raise `AmberMetaError`.
- **CI stays green:** `.github/workflows/cli-docs-sync.yml` and `gui-static-check.yml`. Sync `docs/cli.md`, README snippets, and completion scripts for any flag/default change.
- Run the whole suite with `python -m pytest -q` from the repo root.

## Canonical interfaces (locked — every task uses these names verbatim)

`ambermeta/manifest.py` public surface:
- `STAGE_FILE_KINDS = ("prmtop", "mdin", "mdout", "mdcrd", "inpcrd")`
- `load_manifest(manifest_path, expand_env=True) -> dict | list` — parse + env-expand + normalize.
- `normalize_stage_keys(entry: dict) -> dict` — alias normalization for one stage entry.
- `write_manifest(payload: dict, path: str, fmt: str) -> None` — canonical writer; `fmt` in `{"yaml","json","toml","csv"}`.
- `validate_manifest(manifest, directory=None, strict=True) -> None`
- `CSV_COLUMNS = ["name","stage_role","prmtop","mdin","mdout","mdcrd","inpcrd","expected_gap_ps","gap_tolerance_ps","notes"]`

`ambermeta/protocol.py` additions:
- `HMR_TIMESTEP_THRESHOLD_PS = 0.003` — single HMR-by-timestep threshold.
- `_apply_global_and_hmr_prmtop(stages, directory, *, global_prmtop, hmr_prmtop, strict) -> None` — shared application used by both `auto_discover` branches.

---

## Task 1: Create `ambermeta/manifest.py` (tolerant reader + canonical writer)

**Files:**
- Create: `ambermeta/manifest.py`
- Modify: `ambermeta/protocol.py` (re-export; delegate `load_manifest`/`validate_manifest`)
- Modify: `ambermeta/__init__.py` (re-export `load_manifest` from new module path is unchanged for callers)
- Test: `tests/test_manifest.py`

**Interfaces:**
- Produces: `load_manifest`, `write_manifest`, `normalize_stage_keys`, `validate_manifest`, `STAGE_FILE_KINDS`, `CSV_COLUMNS` (signatures above).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_manifest.py
import pytest
from ambermeta import manifest as m


def test_normalize_stage_keys_aliases():
    entry = {"stage": "prod_001", "role": "production",
             "expected_gap_ps": 2.0, "gap_tolerance_ps": 0.1}
    out = m.normalize_stage_keys(entry)
    assert out["name"] == "prod_001"
    assert out["stage_role"] == "production"
    assert out["gaps"] == {"expected": 2.0, "tolerance": 0.1}


@pytest.mark.parametrize("fmt,ext", [("yaml", "yaml"), ("json", "json"),
                                     ("toml", "toml"), ("csv", "csv")])
def test_write_then_load_roundtrip(tmp_path, fmt, ext):
    pytest.importorskip("yaml") if fmt == "yaml" else None
    payload = {"stages": [
        {"name": "min", "stage_role": "minimization", "prmtop": "s.prmtop",
         "mdin": "min.in", "mdout": "min.out"},
        {"name": "prod_001", "stage_role": "production", "prmtop": "s.prmtop",
         "mdin": "prod_001.in", "mdout": "prod_001.out",
         "gaps": {"expected": 2.0, "tolerance": 0.1}},
    ]}
    path = tmp_path / f"manifest.{ext}"
    m.write_manifest(payload, str(path), fmt)
    loaded = m.load_manifest(str(path), expand_env=False)
    stages = loaded["stages"] if isinstance(loaded, dict) else loaded
    names = [s["name"] for s in stages]
    assert names == ["min", "prod_001"]
    prod = [s for s in stages if s["name"] == "prod_001"][0]
    assert prod["stage_role"] == "production"
    assert prod.get("gaps", {}).get("expected") == 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_manifest.py -q`
Expected: FAIL with `ModuleNotFoundError`/`AttributeError` (manifest module absent).

- [ ] **Step 3: Write `ambermeta/manifest.py`**

Move `_expand_env_vars`, `_parse_csv_manifest`, `_parse_toml_manifest`, `load_manifest`, `validate_manifest`, and `_normalize_manifest` out of `protocol.py` into this new module (cut them from protocol.py in Step 4). Then add normalization + the canonical writer:

```python
from __future__ import annotations

import csv
import json
import os
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from ambermeta.errors import AmberMetaError

try:  # pragma: no cover - optional dependency
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:  # pragma: no cover - optional dependency
    import tomllib
except ImportError:  # pragma: no cover
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

STAGE_FILE_KINDS = ("prmtop", "mdin", "mdout", "mdcrd", "inpcrd")
CSV_COLUMNS = ["name", "stage_role", "prmtop", "mdin", "mdout", "mdcrd",
               "inpcrd", "expected_gap_ps", "gap_tolerance_ps", "notes"]

# <PASTE moved helpers here unchanged: _expand_env_vars, _parse_csv_manifest,
#  _parse_toml_manifest, _normalize_manifest, validate_manifest>


def normalize_stage_keys(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Accept legacy/variant stage keys; return a canonicalized copy."""
    out = dict(entry)
    if "name" not in out and "stage" in out:
        out["name"] = out.pop("stage")
    if "stage_role" not in out and "role" in out:
        out["stage_role"] = out["role"]
    if "gaps" not in out and "gap" not in out:
        expected = out.pop("expected_gap_ps", None)
        tolerance = out.pop("gap_tolerance_ps", None)
        if expected is not None or tolerance is not None:
            gaps: Dict[str, Any] = {}
            if expected is not None:
                gaps["expected"] = expected
            if tolerance is not None:
                gaps["tolerance"] = tolerance
            out["gaps"] = gaps
    return out


def _normalize_container(manifest: Any) -> Any:
    """Apply normalize_stage_keys to every stage entry in any container shape."""
    if isinstance(manifest, list):
        return [normalize_stage_keys(e) if isinstance(e, dict) else e
                for e in manifest]
    if isinstance(manifest, dict):
        if isinstance(manifest.get("stages"), list):
            manifest = dict(manifest)
            manifest["stages"] = [normalize_stage_keys(e) if isinstance(e, dict)
                                  else e for e in manifest["stages"]]
            return manifest
        # dict-of-stages: keys are stage names
        return {k: (normalize_stage_keys(v) if isinstance(v, dict) else v)
                for k, v in manifest.items()}
    return manifest


def write_manifest(payload: Dict[str, Any], path: str, fmt: str) -> None:
    """Write a manifest payload ({'stages': [...]}, optional globals) canonically."""
    stages = payload.get("stages", [])
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
    if fmt == "toml":
        lines: List[str] = []
        for key in ("global_prmtop", "hmr_prmtop"):
            if payload.get(key):
                lines.append(f'{key} = "{_toml_escape(payload[key])}"')
        if lines:
            lines.append("")
        for stage in stages:
            lines.append("[[stages]]")
            for k, v in stage.items():
                if isinstance(v, dict):  # gaps
                    for gk, gv in v.items():
                        lines.append(f"{k}_{gk} = {gv}")
                elif isinstance(v, list):  # notes
                    lines.append(f"{k} = {json.dumps(v)}")
                else:
                    lines.append(f'{k} = "{_toml_escape(v)}"')
            lines.append("")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines).rstrip() + "\n")
        return
    if fmt == "csv":
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for stage in stages:
                gaps = stage.get("gaps", {}) or {}
                notes = stage.get("notes", []) or []
                writer.writerow({
                    "name": stage.get("name", ""),
                    "stage_role": stage.get("stage_role", ""),
                    "prmtop": stage.get("prmtop", ""),
                    "mdin": stage.get("mdin", ""),
                    "mdout": stage.get("mdout", ""),
                    "mdcrd": stage.get("mdcrd", ""),
                    "inpcrd": stage.get("inpcrd", ""),
                    "expected_gap_ps": gaps.get("expected", ""),
                    "gap_tolerance_ps": gaps.get("tolerance", ""),
                    "notes": "; ".join(str(n) for n in notes),
                })
        return
    raise ValueError(f"Unsupported manifest format: {fmt}")


def _toml_escape(value: Any) -> str:
    s = str(value)
    return s.replace("\\", "\\\\").replace('"', '\\"')
```

In the moved `load_manifest`, call the normalizer just before returning:

```python
    if expand_env:
        manifest = _expand_env_vars(manifest)
    return _normalize_container(manifest)
```

Also extend `_parse_csv_manifest` to pass each row through `normalize_stage_keys`
(so a CSV `stage`/`role`/`expected_gap_ps` column round-trips), and accept the
`notes` column split on `;` (this already exists) plus numeric gap columns.

- [ ] **Step 4: Update `protocol.py` to delegate**

Remove the moved functions from `protocol.py` and import them:

```python
from ambermeta.manifest import (
    load_manifest, validate_manifest, _expand_env_vars, _normalize_manifest,
    normalize_stage_keys, STAGE_FILE_KINDS,
)
```

Keep `ambermeta/__init__.py` re-exporting `load_manifest`, `load_protocol_from_manifest` (already does, via protocol). Verify `protocol.__all__` still lists them (re-exported names remain valid).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_manifest.py tests/test_protocol.py tests/test_cli_plan.py -q`
Expected: PASS (no regressions from the move).

- [ ] **Step 6: Commit**

```bash
git add ambermeta/manifest.py ambermeta/protocol.py ambermeta/__init__.py tests/test_manifest.py
git commit -m "feat(manifest): canonical writer + tolerant reader module"
```

---

## Task 2: Route CLI `init` writer through `manifest.write_manifest` (CORE-C8 CSV round-trip)

**Files:**
- Modify: `ambermeta/cli.py` (`_init_command`, delete `_write_manifest_payload`, `_toml_escape`)
- Test: `tests/test_cli_init.py`

**Interfaces:**
- Consumes: `manifest.write_manifest`, `manifest.load_manifest` (Task 1).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_init.py  (add)
from ambermeta import manifest as m
from ambermeta.cli import main


def test_init_auto_csv_roundtrips(tmp_path):
    d = tmp_path
    (d / "system.prmtop").write_text("dummy")
    (d / "prod_001.in").write_text("&cntrl\n/\n")
    (d / "prod_001.out").write_text("Final Performance Info\n")
    rc = main(["init", str(d), "--auto", "--format", "csv",
               "-o", "manifest.csv", "--force"])
    assert rc == 0
    loaded = m.load_manifest(str(d / "manifest.csv"), expand_env=False)
    stages = loaded if isinstance(loaded, list) else loaded["stages"]
    assert [s["name"] for s in stages] == ["prod_001"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_init.py::test_init_auto_csv_roundtrips -q`
Expected: FAIL (loader returns 0 stages — CSV `stage` header bug).

- [ ] **Step 3: Replace the writer call**

In `_init_command`, replace `_write_manifest_payload(output_path, manifest_payload, manifest_format)` with:

```python
        from ambermeta import manifest as manifest_io
        manifest_io.write_manifest(manifest_payload, output_path, manifest_format)
```

Delete `_write_manifest_payload` and the duplicate `_toml_escape` from `cli.py`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cli_init.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/cli.py tests/test_cli_init.py
git commit -m "fix(cli): init writes canonical manifests; CSV round-trips (CORE-C8)"
```

---

## Task 3: Reported Bug 1 — `init --auto` one stage per file group (CORE-C1/D1)

**Files:**
- Modify: `ambermeta/cli.py` (`_build_stage_candidates`, delete `_normalize_stage_stem`)
- Modify: `ambermeta/protocol.py` (add `_ordered_stems`)
- Test: `tests/test_cli_init.py`

**Interfaces:**
- Consumes: `protocol.smart_group_files`.
- Produces: `protocol._ordered_stems(grouped: dict) -> list[str]` (natural/numeric order), reused by Task 4's discovery loop.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_init.py  (add)
from ambermeta import manifest as m
from ambermeta.cli import main


def test_init_auto_keeps_every_numbered_file(tmp_path):
    d = tmp_path
    (d / "system.prmtop").write_text("dummy")
    for i in range(1, 6):
        (d / f"ntp_prod_{i:04d}.mdin").write_text("&cntrl\n/\n")
        (d / f"ntp_prod_{i:04d}.mdout").write_text("Final Performance Info\n")
        (d / f"ntp_prod_{i:04d}.rst").write_text("title\n 1\n")
    rc = main(["init", str(d), "--auto", "-o", "manifest.yaml", "--force"])
    assert rc == 0
    loaded = m.load_manifest(str(d / "manifest.yaml"), expand_env=False)
    stages = loaded["stages"] if isinstance(loaded, dict) else loaded
    names = sorted(s["name"] for s in stages)
    assert names == [f"ntp_prod_{i:04d}" for i in range(1, 6)]
    # each stage keeps its own mdin/mdout, none collapsed
    assert all(s.get("mdin") and s.get("mdout") for s in stages)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_init.py::test_init_auto_keeps_every_numbered_file -q`
Expected: FAIL (only one collapsed `ntp_prod` stage with the last file).

- [ ] **Step 3: Rewrite `_build_stage_candidates` on top of `smart_group_files`**

```python
def _build_stage_candidates(directory: str) -> List[Dict[str, Any]]:
    """Build ordered stage candidates using the engine's discovery (one stage
    per discovered file group, identical for every role)."""
    from ambermeta.protocol import smart_group_files

    grouped = smart_group_files(directory, recursive=True)
    candidates: List[Dict[str, Any]] = []
    for stem in _ordered_stems(grouped):
        kinds = grouped[stem]
        files = {k: v for k, v in kinds.items()
                 if k in ("mdin", "mdout", "mdcrd", "inpcrd")}
        if not files:
            continue  # prmtop-only groups are not stages
        candidates.append({
            "name": stem,
            "stage_role": _suggest_stage_role(stem),
            "files": files,
        })
    return candidates
```

First add `_ordered_stems` to `protocol.py` (near `detect_numeric_sequences`):

```python
def _ordered_stems(grouped: Dict[str, Any]) -> List[str]:
    """Return stems in natural (numeric-aware) order so prod_2 precedes prod_10."""
    def key(stem: str):
        return [int(tok) if tok.isdigit() else tok.lower()
                for tok in re.split(r'(\d+)', stem)]
    return sorted(grouped.keys(), key=key)
```

Import it in `cli.py`: `from ambermeta.protocol import smart_group_files, _ordered_stems` (place the import inside `_build_stage_candidates` to avoid a circular import at module load, matching the existing local-import style). Delete `_normalize_stage_stem`. Update `_init_command` to call `_build_stage_candidates(directory)` (it currently passes `discovered_files`); the `discovered_files` walk is still used for prmtop discovery (Task 15), so keep it for the prmtop list only.

Note: `smart_group_files` returns **relative** paths joined to `directory`? It returns absolute `full_path`. For manifest portability, convert to paths relative to `directory`:

```python
        files = {k: os.path.relpath(v, directory)
                 for k, v in kinds.items()
                 if k in ("mdin", "mdout", "mdcrd", "inpcrd")}
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cli_init.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/cli.py tests/test_cli_init.py
git commit -m "fix(cli): init --auto keeps every file group, no sequence collapse (Bug 1)"
```

---

## Task 4: Numeric stage ordering + single-digit sequence detection (CORE-D2/D7)

**Files:**
- Modify: `ambermeta/protocol.py` (`detect_numeric_sequences`; discovery-loop ordering)
- Test: `tests/test_core_hardening.py`

**Interfaces:**
- Consumes: `protocol._ordered_stems` (defined in Task 3).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_core_hardening.py
from ambermeta.protocol import detect_numeric_sequences, _ordered_stems


def test_natural_order_unpadded():
    grouped = {f"prod_{i}": {} for i in (1, 2, 10, 11)}
    assert _ordered_stems(grouped) == ["prod_1", "prod_2", "prod_10", "prod_11"]


def test_sequence_detects_single_digits():
    seqs = detect_numeric_sequences(["prod_1", "prod_2", "prod_3"])
    assert any(len(v) == 3 for v in seqs.values())
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_core_hardening.py -q`
Expected: FAIL (`_ordered_stems` missing; `\d{2,}` misses single digits).

- [ ] **Step 3: Implement**

In `detect_numeric_sequences`, change both regexes from `\d{2,}` to `\d+` and add a guard so a stem that is *only* a number is not treated as a base:

```python
    suffix_pattern = re.compile(r'^(.+?)[-_.]?(\d+)$')
    prefix_pattern = re.compile(r'^(\d+)[-_.]?(.+)$')
```

`_ordered_stems` already exists from Task 3. In `auto_discover`'s discovery branch, replace `for stem, kinds in sorted(grouped.items()):` with:

```python
    for stem in _ordered_stems(grouped):
        kinds = grouped[stem]
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_core_hardening.py tests/test_protocol.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/protocol.py ambermeta/cli.py tests/test_core_hardening.py
git commit -m "fix(discovery): natural stage ordering + single-digit sequences (CORE-D2/D7)"
```

---

## Task 5: prmtop truncated-octahedron volume (CORE-P1)

**Files:**
- Modify: `ambermeta/legacy_extractors/prmtop.py:413-435`
- Test: `tests/test_core_hardening.py`

- [ ] **Step 1: Add the prmtop fixture helper + failing test**

```python
# tests/test_core_hardening.py  (add at top)
import math


def _write_prmtop(path, sections):
    """sections: dict flag -> (format_str, [values]). Writes a minimal prmtop."""
    lines = ["%VERSION  VERSION_STAMP = V0001.000  DATE = 01/01/26"]
    for flag, (fmt, values) in sections.items():
        lines.append(f"%FLAG {flag}")
        lines.append(f"%FORMAT({fmt})")
        # one value per line keeps it simple and fixed-width safe
        for v in values:
            if isinstance(v, float):
                lines.append(f"{v:16.8E}")
            else:
                lines.append(f"{int(v):8d}")
    path.write_text("\n".join(lines) + "\n")


def test_truncated_octahedron_volume(tmp_path):
    from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
    p = tmp_path / "trunc.prmtop"
    # BOX_DIMENSIONS: beta then a,b,c
    _write_prmtop(p, {
        "POINTERS": ("10I8", [3, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0]),
        "MASS": ("5E16.8", [1.0, 1.0, 1.0]),
        "BOX_DIMENSIONS": ("5E16.8", [109.4712206, 50.0, 50.0, 50.0]),
    })
    md = extract_prmtop_metadata(str(p))
    factor = md.box_volume / (50.0 ** 3)
    assert abs(factor - 0.7698) < 1e-3  # truncated-octahedron factor, not 0.9428
    assert md.box_angles == [109.4712206, 109.4712206, 109.4712206]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_core_hardening.py::test_truncated_octahedron_volume -q`
Expected: FAIL (factor ≈ 0.9428; angles `[90, β, 90]`).

- [ ] **Step 3: Fix the box block**

Replace lines ~419-426:

```python
        md.box_dimensions = dims
        md.box_angles = [beta, beta, beta]
        ang = math.radians(beta)
        cos_a = math.cos(ang)
        md.box_volume = dims[0] * dims[1] * dims[2] * math.sqrt(
            max(0.0, 1 - 3 * cos_a ** 2 + 2 * cos_a ** 3)
        )
```

(When `beta == 90`, `cos_a == 0` so volume = `a*b*c`, orthorhombic — unchanged.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_core_hardening.py tests/test_parsers_smoke.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/legacy_extractors/prmtop.py tests/test_core_hardening.py
git commit -m "fix(prmtop): correct truncated-octahedron box volume (CORE-P1)"
```

---

## Task 6: prmtop nbond total + POINTERS length guard (CORE-P3/P4a)

**Files:**
- Modify: `ambermeta/legacy_extractors/prmtop.py:368-373`
- Test: `tests/test_core_hardening.py`

- [ ] **Step 1: Failing test**

```python
def test_nbond_total_and_short_pointers(tmp_path):
    from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
    p = tmp_path / "ptr.prmtop"
    # index2=NBONH=5, index11=nres=2, index12=NBONA=3
    _write_prmtop(p, {"POINTERS": ("10I8", [4, 0, 5, 0, 0, 0, 0, 0, 0, 0, 0, 2, 3])})
    md = extract_prmtop_metadata(str(p))
    assert md.nbond == 8  # 5 + 3, not 3

    short = tmp_path / "short.prmtop"
    _write_prmtop(short, {"POINTERS": ("10I8", [4, 0, 0])})  # < 13 entries
    md2 = extract_prmtop_metadata(str(short))  # must not raise
    assert md2.natom == 4
    assert md2.nres is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_core_hardening.py::test_nbond_total_and_short_pointers -q`
Expected: FAIL (nbond==3; short POINTERS raises `IndexError`).

- [ ] **Step 3: Fix the pointers block**

```python
    pointers = prmtop.get("POINTERS")
    if pointers:
        md.natom = pointers[0] if len(pointers) > 0 else None
        md.nres = pointers[11] if len(pointers) > 11 else None
        if len(pointers) > 12:
            nbonh = pointers[2] if len(pointers) > 2 else 0
            md.nbond = (nbonh or 0) + (pointers[12] or 0)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_core_hardening.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/legacy_extractors/prmtop.py tests/test_core_hardening.py
git commit -m "fix(prmtop): nbond=NBONH+NBONA; guard short POINTERS (CORE-P3/P4a)"
```

---

## Task 7: `_safe_parse` catches `LookupError` (CORE-P4b)

**Files:**
- Modify: `ambermeta/protocol.py` (`_safe_parse` except clause)
- Test: `tests/test_robustness.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_robustness.py  (add)
def test_safe_parse_swallows_lookup_error(tmp_path):
    from ambermeta.protocol import _safe_parse, SimulationStage

    class Boom:
        def __init__(self, path): ...
        def parse(self): raise IndexError("truncated")

    stage = SimulationStage(name="s")
    result = _safe_parse(Boom, "x.prmtop", "prmtop", stage, strict=False)
    assert result is None
    assert stage.load_errors and stage.load_errors[0].kind == "prmtop"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_robustness.py::test_safe_parse_swallows_lookup_error -q`
Expected: FAIL (`IndexError` propagates).

- [ ] **Step 3: Widen the caught exceptions**

In `_safe_parse`, change the except tuple to include `LookupError`:

```python
    except (FileNotFoundError, PermissionError, OSError,
            UnicodeDecodeError, ValueError, LookupError) as exc:
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_robustness.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/protocol.py tests/test_robustness.py
git commit -m "fix(protocol): _safe_parse degrades gracefully on LookupError (CORE-P4b)"
```

---

## Task 8: Robust HMR detection with ATOM_NAME fallback (CORE-H1/P5)

**Files:**
- Modify: `ambermeta/legacy_extractors/prmtop.py` (target_flags; HMR block; add `hmr_detection_method` field)
- Test: `tests/test_core_hardening.py`

**Interfaces:**
- Produces: `PrmtopMetadata.hmr_detection_method: Optional[str]` ("atomic_number" | "atom_name" | None).

- [ ] **Step 1: Failing test**

```python
def test_hmr_detected_without_atomic_number(tmp_path):
    from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
    p = tmp_path / "hmr.prmtop"
    # No ATOMIC_NUMBER; identify H by ATOM_NAME starting with 'H'
    _write_prmtop_atoms(p,
        atom_names=["N", "H1", "H2", "CA"],
        masses=[14.01, 3.024, 3.024, 12.01])
    md = extract_prmtop_metadata(str(p))
    assert md.hmr_active is True
    assert md.hmr_detection_method == "atom_name"
```

Add fixture helper (handles `20a4` ATOM_NAME):

```python
def _write_prmtop_atoms(path, atom_names, masses):
    name_line = "".join(f"{n:<4}" for n in atom_names)
    lines = [
        "%VERSION VERSION_STAMP = V0001.000",
        "%FLAG POINTERS", "%FORMAT(10I8)", f"{len(atom_names):8d}",
        "%FLAG ATOM_NAME", "%FORMAT(20a4)", name_line,
        "%FLAG MASS", "%FORMAT(5E16.8)",
        "".join(f"{m:16.8E}" for m in masses),
    ]
    path.write_text("\n".join(lines) + "\n")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_core_hardening.py::test_hmr_detected_without_atomic_number -q`
Expected: FAIL (`hmr_active` is None; no `hmr_detection_method`).

- [ ] **Step 3: Implement fallback**

Add `ATOM_NAME` is already in `target_flags`; add field to `PrmtopMetadata`:

```python
    hmr_detection_method: Optional[str] = None
```

Replace the HMR block (lines ~390-411) with a hydrogen-mass collector that prefers `ATOMIC_NUMBER` and falls back to `ATOM_NAME`:

```python
    masses = prmtop.get("MASS")
    if masses:
        valid_masses = [m for m in masses if m is not None]
        md.total_mass = sum(valid_masses)

    atomic_numbers = prmtop.get("ATOMIC_NUMBER")
    atom_names = prmtop.get("ATOM_NAME")
    hydrogen_masses: List[float] = []
    if masses and atomic_numbers:
        n = min(len(masses), len(atomic_numbers))
        hydrogen_masses = [masses[i] for i in range(n)
                           if atomic_numbers[i] == 1 and masses[i] is not None]
        if atomic_numbers:
            md.hmr_detection_method = "atomic_number"
    elif masses and atom_names:
        n = min(len(masses), len(atom_names))
        hydrogen_masses = [masses[i] for i in range(n)
                           if masses[i] is not None
                           and str(atom_names[i]).strip().upper().startswith("H")
                           and masses[i] < 5.0]
        if hydrogen_masses:
            md.hmr_detection_method = "atom_name"

    if hydrogen_masses:
        min_mass, max_mass = min(hydrogen_masses), max(hydrogen_masses)
        md.hmr_hydrogen_mass_range = (min_mass, max_mass)
        md.hmr_hydrogen_mass_summary = (
            f"{min_mass:.3f}-{max_mass:.3f} amu across {len(hydrogen_masses)} H"
        )
        md.hmr_active = (max_mass >= 2.0) or (max_mass >= 1.5 and min_mass <= 1.1)
    elif atomic_numbers or atom_names:
        md.hmr_active = False
```

(The `< 5.0` mass guard avoids misclassifying heavy atoms whose names start with H, e.g. "HG"/mercury edge cases, while still catching repartitioned H up to ~4 amu.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_core_hardening.py tests/test_parsers_smoke.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/legacy_extractors/prmtop.py tests/test_core_hardening.py
git commit -m "fix(prmtop): HMR detection falls back to ATOM_NAME (CORE-H1/P5)"
```

---

## Task 9: prmtop charge/mass completeness warning (CORE-P7)

**Files:**
- Modify: `ambermeta/legacy_extractors/prmtop.py` (add `warnings` field; CHARGE/MASS checks)
- Test: `tests/test_core_hardening.py`

**Interfaces:**
- Produces: `PrmtopMetadata.warnings: List[str]` (now surfaced by `PrmtopData.warnings`).

- [ ] **Step 1: Failing test**

```python
def test_charge_completeness_warning(tmp_path):
    from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
    p = tmp_path / "charge.prmtop"
    # natom=3 but only 2 valid CHARGE tokens (one blank -> None)
    lines = [
        "%VERSION x", "%FLAG POINTERS", "%FORMAT(10I8)", f"{3:8d}",
        "%FLAG CHARGE", "%FORMAT(3E16.8)",
        f"{1.0:16.8E}{2.0:16.8E}            ",  # third field blank
    ]
    p.write_text("\n".join(lines) + "\n")
    md = extract_prmtop_metadata(str(p))
    assert any("charge" in w.lower() for w in md.warnings)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_core_hardening.py::test_charge_completeness_warning -q`
Expected: FAIL (no `warnings` field / no warning).

- [ ] **Step 3: Implement**

Add to `PrmtopMetadata`:

```python
    warnings: List[str] = field(default_factory=list)
```

In the CHARGE block, compare valid count to `md.natom`:

```python
    charges = prmtop.get("CHARGE")
    if charges:
        valid_charges = [c for c in charges if c is not None]
        if md.natom and len(valid_charges) != md.natom:
            md.warnings.append(
                f"CHARGE has {len(valid_charges)} valid of {md.natom} atoms; "
                "neutrality verdict is uncertain."
            )
        if valid_charges:
            md.total_charge = sum(valid_charges) / 18.2223
            md.is_neutral = abs(md.total_charge) < 1e-2
```

Apply the same `len(valid_masses) != md.natom` warning in the MASS block.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_core_hardening.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/legacy_extractors/prmtop.py tests/test_core_hardening.py
git commit -m "fix(prmtop): warn on incomplete CHARGE/MASS (CORE-P7)"
```

---

## Task 10: mdout `1-4 NB` / `1-4 EEL` parsing (CORE-P2)

**Files:**
- Modify: `ambermeta/legacy_extractors/mdout.py` (`_extract_key_values`)
- Test: `tests/test_core_hardening.py`

- [ ] **Step 1: Failing test**

```python
def test_mdout_captures_1_4_terms():
    from ambermeta.legacy_extractors.mdout import _extract_key_values
    line = " 1-4 NB =  1393.4892  1-4 EEL = 15687.4768  VDWAALS = 21666.9998"
    kv = _extract_key_values(line)
    assert kv["1-4 NB"] == 1393.4892
    assert kv["1-4 EEL"] == 15687.4768
    assert kv["VDWAALS"] == 21666.9998
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_core_hardening.py::test_mdout_captures_1_4_terms -q`
Expected: FAIL (keys are `NB`/`EEL`, not `1-4 NB`/`1-4 EEL`).

- [ ] **Step 3: Implement**

Replace `_extract_key_values`:

```python
def _extract_key_values(line: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    # AMBER's spaced energy keys first so they win over the generic matcher.
    for m in re.finditer(r"(1-4\s+(?:NB|EEL))\s*=\s*([-\d\.\*eE\+]+)", line):
        key = re.sub(r"\s+", " ", m.group(1)).strip()
        result[key] = _parse_value(m.group(2))
    pattern = re.compile(r"([A-Za-z0-9_\-\(\)\./]+)\s*=\s*([-\d\.\*eE\+]+)")
    for k, v in pattern.findall(line):
        result.setdefault(k.strip(), _parse_value(v))
    return result
```

- [ ] **Step 4: Run tests (incl. real fixture)**

Run: `python -m pytest tests/test_core_hardening.py tests/test_parsers_smoke.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/legacy_extractors/mdout.py tests/test_core_hardening.py
git commit -m "fix(mdout): capture 1-4 NB/EEL energy components (CORE-P2)"
```

---

## Task 11: mdin production-vs-equilibration title precedence (CORE-P6)

**Files:**
- Modify: `ambermeta/legacy_extractors/mdin.py:706-719`
- Test: `tests/test_core_hardening.py`

- [ ] **Step 1: Failing test**

```python
def test_nvt_production_not_mislabeled(tmp_path):
    from ambermeta.legacy_extractors.mdin import parse_mdin_file
    p = tmp_path / "prod.in"
    p.write_text("Production NVT run\n&cntrl\n imin=0, nstlim=5000000,\n/\n")
    md = parse_mdin_file(str(p))
    role = md.stage_role if hasattr(md, "stage_role") else None
    from ambermeta.legacy_extractors.mdin import _classify_stage
    assert "Production" in _classify_stage(md)
```

(If `parse_mdin_file` differs, call the module's actual public parse entry; the assert is on `_classify_stage` output containing "Production".)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_core_hardening.py::test_nvt_production_not_mislabeled -q`
Expected: FAIL (returns "Equilibration [...]").

- [ ] **Step 3: Implement — production cue before ensemble-substring cue**

Reorder so explicit production/equilibration words win over bare ensemble substrings:

```python
    if "prod" in title or "production" in title:
        if ntr_i != 0:
            return f"Production with restraints [{md.ensemble}]"
        return f"Production [{md.ensemble}]"
    if "equil" in title or "nvt" in title or "npt equil" in title:
        if ntr_i != 0:
            return f"Equilibration with positional restraints [{md.ensemble}]"
        return f"Equilibration [{md.ensemble}]"
```

(The heating check at line 707 stays above both.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_core_hardening.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/legacy_extractors/mdin.py tests/test_core_hardening.py
git commit -m "fix(mdin): 'prod' title beats 'nvt' substring in classification (CORE-P6)"
```

---

## Task 12: inpcrd tiny-system box/velocity guard (CORE-P8)

**Files:**
- Modify: `ambermeta/legacy_extractors/inpcrd.py:173-194`
- Test: `tests/test_core_hardening.py`

- [ ] **Step 1: Failing test**

```python
def test_inpcrd_tiny_system_box_not_velocities(tmp_path):
    from ambermeta.legacy_extractors.inpcrd import parse_inpcrd
    p = tmp_path / "tiny.rst"
    # 2 atoms -> 1 coord line (6 floats); + 1 box line. Must read as box, not vel.
    p.write_text(
        "title\n"
        "    2\n"
        "  1.0000000  2.0000000  3.0000000  4.0000000  5.0000000  6.0000000\n"
        " 10.0000000 10.0000000 10.0000000 90.0000000 90.0000000 90.0000000\n"
    )
    md = parse_inpcrd(str(p))
    assert md.has_box is True
    assert md.has_velocities is False
```

(Use the module's real entry point name; if it's `parse_inpcrd_file`, adjust.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_core_hardening.py::test_inpcrd_tiny_system_box_not_velocities -q`
Expected: FAIL (misread as velocities; box dropped).

- [ ] **Step 3: Implement — validate last line as a 6-float box before assuming velocities**

Add a helper and prefer box interpretation when the trailing line parses as 3 or 6 box floats:

```python
    def _looks_like_box(p: str) -> bool:
        try:
            with open(p) as fh:
                last = [ln for ln in fh if ln.strip()][-1]
        except (OSError, IndexError):
            return False
        toks = last.split()
        return len(toks) in (3, 6) and all(
            _is_float(t) for t in toks)

    extra = line_count - lines_per_structure
    if extra == 1:
        md.has_velocities = False
        md.has_box = True
        _parse_ascii_box(md)
    elif line_count >= 2 * lines_per_structure:
        md.has_velocities = True
        remainder_box = line_count - (2 * lines_per_structure)
        if remainder_box >= 1 and _looks_like_box(md.filename):
            md.has_box = True
            _parse_ascii_box(md)
    elif line_count >= lines_per_structure:
        md.has_velocities = False
        remainder_box = line_count - lines_per_structure
        if remainder_box >= 1 and _looks_like_box(md.filename):
            md.has_box = True
            _parse_ascii_box(md)
    else:
        md.warnings.append(
            f"File too short. Expected at least {lines_per_structure} lines "
            f"for {md.natoms} atoms, found {line_count}.")
        return md
```

Add module-level `_is_float`:

```python
def _is_float(tok: str) -> bool:
    try:
        float(tok.replace("D", "E").replace("d", "e"))
        return True
    except ValueError:
        return False
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_core_hardening.py tests/test_parsers_smoke.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/legacy_extractors/inpcrd.py tests/test_core_hardening.py
git commit -m "fix(inpcrd): validate trailing box line for tiny systems (CORE-P8)"
```

---

## Task 13: Shared global/HMR-prmtop helper + threshold + missing-file warning (CORE-H2/H3/D3/D4)

**Files:**
- Modify: `ambermeta/protocol.py` (add constant + `_apply_global_and_hmr_prmtop`; call from both `auto_discover` branches)
- Test: `tests/test_core_hardening.py`

**Interfaces:**
- Produces: `HMR_TIMESTEP_THRESHOLD_PS = 0.003`; `_apply_global_and_hmr_prmtop(stages, directory, *, global_prmtop, hmr_prmtop, strict)`.

- [ ] **Step 1: Failing tests**

```python
def test_hmr_prmtop_applied_in_discovery_branch(tmp_path, caplog):
    import ambermeta.protocol as P
    # discovery branch: manifest=None
    # Build a stage with a large-dt mdin so HMR topology is selected.
    (tmp_path / "prod.in").write_text("&cntrl\n imin=0, dt=0.004, nstlim=10,\n/\n")
    (tmp_path / "prod.out").write_text("Final Performance Info\n")
    # minimal HMR prmtop
    _write_prmtop_atoms(tmp_path / "hmr.prmtop",
                        atom_names=["N", "H1"], masses=[14.0, 3.024])
    proto = P.auto_discover(str(tmp_path), manifest=None,
                            hmr_prmtop="hmr.prmtop")
    prod = [s for s in proto.stages if "prod" in s.name][0]
    assert prod.prmtop is not None  # HMR topology applied in discovery branch


def test_missing_global_prmtop_warns(tmp_path, caplog):
    import ambermeta.protocol as P
    (tmp_path / "prod.in").write_text("&cntrl\n imin=0, nstlim=10,\n/\n")
    proto = P.auto_discover(str(tmp_path), manifest=None,
                            global_prmtop="nope.prmtop")
    with pytest.raises(P.AmberMetaError):
        P.auto_discover(str(tmp_path), manifest=None,
                        global_prmtop="nope.prmtop", strict=True)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_core_hardening.py -k prmtop_applied_in_discovery or missing_global -q`
Expected: FAIL (discovery branch ignores hmr_prmtop; no strict raise on missing).

- [ ] **Step 3: Implement the helper + constant**

Add near the top of `protocol.py`:

```python
HMR_TIMESTEP_THRESHOLD_PS = 0.003  # >= 3 fs indicates HMR
```

Add the helper (replaces the duplicated blocks):

```python
def _resolve(directory: Optional[str], path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(directory or ".", path)


def _apply_global_and_hmr_prmtop(stages, directory, *, global_prmtop,
                                 hmr_prmtop, strict) -> None:
    def _load_topology(path, label):
        full = _resolve(directory, path)
        if not os.path.exists(full):
            msg = f"Requested {label} prmtop not found: {full}"
            if strict:
                raise AmberMetaError(msg)
            logger.warning(msg)
            for st in stages:
                st.validation.append(f"WARNING: {msg}")
            return None
        return _safe_parse(PrmtopParser, full, "prmtop", None, strict=strict)

    if global_prmtop:
        data = _load_topology(global_prmtop, "global")
        if data is not None:
            for st in stages:
                if not st.prmtop:
                    st.prmtop = data
                    st.validation.append(f"INFO: using global prmtop: {global_prmtop}")

    if hmr_prmtop:
        data = _load_topology(hmr_prmtop, "HMR")
        if data is not None:
            for st in stages:
                dt = None
                if st.mdin and st.mdin.details:
                    dt = getattr(st.mdin.details, "dt", None)
                if dt is None and st.mdout and st.mdout.details:
                    dt = getattr(st.mdout.details, "dt", None)
                if isinstance(dt, (int, float)) and dt >= HMR_TIMESTEP_THRESHOLD_PS:
                    st.prmtop = data
                    st.validation.append(
                        f"INFO: using HMR prmtop (dt={dt} ps): {hmr_prmtop}")
```

`logger` must exist in `protocol.py`; add `from ambermeta.logging_config import get_logger` and `logger = get_logger(__name__)` if not present.

In `auto_discover`, **delete** the inline global/HMR blocks in both branches and call:

```python
        _apply_global_and_hmr_prmtop(stages, directory, global_prmtop=global_prmtop,
                                     hmr_prmtop=hmr_prmtop, strict=strict)
```

before each `protocol = SimulationProtocol(stages=stages)`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_core_hardening.py tests/test_protocol.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/protocol.py tests/test_core_hardening.py
git commit -m "fix(protocol): shared global/HMR prmtop helper, both branches, warn on missing (CORE-H2/H3/D3/D4)"
```

---

## Task 14: Use the shared HMR threshold in `_collect_system` (CORE-D5)

**Files:**
- Modify: `ambermeta/protocol.py` (`_collect_system`, ~line 694)
- Test: `tests/test_core_hardening.py`

- [ ] **Step 1: Failing test**

```python
def test_hmr_inference_uses_shared_threshold():
    import ambermeta.protocol as P
    assert P.HMR_TIMESTEP_THRESHOLD_PS == 0.003
    # _collect_system must not hardcode a different number; guard via source check
    import inspect
    src = inspect.getsource(P.SimulationProtocol.to_methods_dict)
    assert "0.003" not in src  # uses the constant, not a literal
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_core_hardening.py::test_hmr_inference_uses_shared_threshold -q`
Expected: FAIL (literal `0.003` present).

- [ ] **Step 3: Implement**

Replace `if dt >= 0.003:` in `_collect_system` with:

```python
                if dt >= HMR_TIMESTEP_THRESHOLD_PS:
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_core_hardening.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/protocol.py tests/test_core_hardening.py
git commit -m "fix(protocol): single HMR timestep threshold constant (CORE-D5)"
```

---

## Task 15: `init --auto` topology awareness (CORE-H4/C3)

**Files:**
- Modify: `ambermeta/cli.py` (`_build_auto_manifest_payload`, prmtop selection; `_init_command`)
- Test: `tests/test_cli_init.py`

**Interfaces:**
- Consumes: `legacy_extractors.prmtop.extract_prmtop_metadata` (`.hmr_active`).

- [ ] **Step 1: Failing test**

```python
def test_init_auto_splits_normal_and_hmr_topology(tmp_path):
    from ambermeta import manifest as m
    from ambermeta.cli import main
    d = tmp_path
    # normal + HMR topologies, distinguishable by H masses
    from tests.test_core_hardening import _write_prmtop_atoms
    _write_prmtop_atoms(d / "system.prmtop", ["N", "H1"], [14.0, 1.008])
    _write_prmtop_atoms(d / "system.hmr.prmtop", ["N", "H1"], [14.0, 3.024])
    (d / "prod.in").write_text("&cntrl\n imin=0, dt=0.004, nstlim=10,\n/\n")
    (d / "prod.out").write_text("Final Performance Info\n")
    main(["init", str(d), "--auto", "-o", "manifest.yaml", "--force"])
    loaded = m.load_manifest(str(d / "manifest.yaml"), expand_env=False)
    assert loaded.get("global_prmtop", "").endswith("system.prmtop")
    assert loaded.get("hmr_prmtop", "").endswith("system.hmr.prmtop")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_cli_init.py::test_init_auto_splits_normal_and_hmr_topology -q`
Expected: FAIL (no `global_prmtop`/`hmr_prmtop` split; first prmtop assigned per stage).

- [ ] **Step 3: Implement topology classification**

Add a helper to `cli.py`:

```python
def _classify_topologies(directory: str, prmtops: List[str]):
    """Return (global_prmtop, hmr_prmtop) chosen deterministically from the
    discovered topology files using HMR detection. Warns on ambiguity."""
    from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
    prmtops = sorted(prmtops)
    normal, hmr = [], []
    for rel in prmtops:
        try:
            md = extract_prmtop_metadata(os.path.join(directory, rel))
            (hmr if md.hmr_active else normal).append(rel)
        except (IOError, OSError, ValueError, LookupError):
            normal.append(rel)
    if len(prmtops) > 1:
        print(Colors.warning(
            f"WARNING: {len(prmtops)} topology files found; "
            f"normal={normal or '-'}, HMR={hmr or '-'}."))
    global_prmtop = normal[0] if normal else (prmtops[0] if prmtops else None)
    hmr_prmtop = hmr[0] if hmr else None
    return global_prmtop, hmr_prmtop
```

In `_build_auto_manifest_payload`, stop assigning a single `prmtop` to every
stage; instead emit `global_prmtop`/`hmr_prmtop` at the top level:

```python
def _build_auto_manifest_payload(directory, discovered, stage_candidates):
    global_prmtop, hmr_prmtop = _classify_topologies(
        directory, sorted(discovered.get("prmtop", [])))
    payload: Dict[str, Any] = {}
    if global_prmtop:
        payload["global_prmtop"] = global_prmtop
    if hmr_prmtop:
        payload["hmr_prmtop"] = hmr_prmtop
    stages: List[Dict[str, Any]] = []
    for c in stage_candidates:
        stage = {"name": c["name"]}
        if c.get("stage_role"):
            stage["stage_role"] = c["stage_role"]
        for k in ("mdin", "mdout", "mdcrd", "inpcrd"):
            if c.get("files", {}).get(k):
                stage[k] = c["files"][k]
        stages.append(stage)
    payload["stages"] = stages
    return payload
```

Update `_init_command` and `_print_auto_stage_preview` call sites to the new
signatures (pass `directory`). The loader already applies `global_prmtop`/
`hmr_prmtop` via Task 13's helper.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cli_init.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/cli.py tests/test_cli_init.py
git commit -m "feat(cli): init --auto assigns normal vs HMR topology (CORE-H4/C3)"
```

---

## Task 16: `*prmtop*` substring misclassification (CORE-C2)

**Files:**
- Modify: `ambermeta/cli.py` (`_scan_directory_files` ~177; discovery loop ~802-811)
- Test: `tests/test_cli_init.py`

- [ ] **Step 1: Failing test**

```python
def test_prmtop_substring_not_misclassified(tmp_path):
    from ambermeta.cli import _scan_directory_files
    (tmp_path / "gen_prmtop.in").write_text("&cntrl\n/\n")
    files = _scan_directory_files(str(tmp_path))
    assert "gen_prmtop.in" in files["mdin"]
    assert "gen_prmtop.in" not in files["prmtop"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_cli_init.py::test_prmtop_substring_not_misclassified -q`
Expected: FAIL (bucketed as prmtop).

- [ ] **Step 3: Implement — extension wins over substring**

In both `_scan_directory_files` and the `_init_command` discovery loop, check the
specific extensions first and only fall back to the `prmtop` substring when the
extension is not a recognized non-topology kind:

```python
            ext = os.path.splitext(f)[1].lower()
            fl = f.lower()
            if ext in (".in", ".mdin"):
                discovered_files["mdin"].append(rel_path)
            elif ext in (".out", ".mdout"):
                discovered_files["mdout"].append(rel_path)
            elif ext in (".nc", ".mdcrd", ".crd", ".x"):
                discovered_files["mdcrd"].append(rel_path)
            elif ext in (".rst", ".rst7", ".ncrst", ".inpcrd", ".restrt"):
                discovered_files["inpcrd"].append(rel_path)
            elif ext in (".prmtop", ".parm7", ".top") or "prmtop" in fl:
                discovered_files["prmtop"].append(rel_path)
```

Apply the same ordering in `_scan_directory_files` (which has its own list keys).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cli_init.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/cli.py tests/test_cli_init.py
git commit -m "fix(cli): extension beats 'prmtop' substring in discovery (CORE-C2)"
```

---

## Task 17: `auto_detect_restart_chain` recursive (CORE-D6)

**Files:**
- Modify: `ambermeta/protocol.py` (`auto_detect_restart_chain` signature + scan; call sites)
- Test: `tests/test_core_hardening.py`

- [ ] **Step 1: Failing test**

```python
def test_restart_chain_scans_subdirs(tmp_path):
    import ambermeta.protocol as P
    sub = tmp_path / "prod"; sub.mkdir()
    (sub / "prod_001.rst").write_text("title\n    1\n  1.0 2.0 3.0\n")
    found = P.auto_detect_restart_chain.__code__.co_varnames
    # signature must accept recursive
    import inspect
    assert "recursive" in inspect.signature(P.auto_detect_restart_chain).parameters
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_core_hardening.py::test_restart_chain_scans_subdirs -q`
Expected: FAIL (no `recursive` parameter).

- [ ] **Step 3: Implement**

Add `recursive: bool = False` to `auto_detect_restart_chain`; replace the flat
`os.listdir` enumeration with a walk when recursive:

```python
    entries: List[str] = []
    if recursive:
        for root, _, files in os.walk(directory, onerror=lambda e: None):
            entries.extend(os.path.join(root, fn) for fn in files)
    else:
        try:
            entries = [os.path.join(directory, fn) for fn in os.listdir(directory)]
        except (PermissionError, OSError):
            entries = []
    for full_path in entries:
        if not os.path.isfile(full_path):
            continue
        _, ext = os.path.splitext(full_path)
        if ext.lower() not in ext_map:
            continue
        try:
            data = InpcrdParser(full_path).parse()
            restart_candidates.append((full_path, data))
        except (IOError, OSError, ValueError):
            continue
```

Thread `recursive` from `auto_discover` (it already knows `recursive`) and from
`cli._plan_command`'s call site.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_core_hardening.py tests/test_protocol.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/protocol.py ambermeta/cli.py tests/test_core_hardening.py
git commit -m "fix(protocol): recursive restart-chain scanning (CORE-D6)"
```

---

## Task 18: `--quiet` suppresses stdout (CORE-C4)

**Files:**
- Modify: `ambermeta/cli.py` (add `_out`/quiet gating; `main`)
- Test: `tests/test_cli_plan.py`

- [ ] **Step 1: Failing test**

```python
def test_quiet_suppresses_stdout(tmp_path, capsys):
    from ambermeta.cli import main
    (tmp_path / "manifest.yaml").write_text("stages: []\n")
    main(["-q", "plan", str(tmp_path), "--manifest",
          str(tmp_path / "manifest.yaml")])
    out = capsys.readouterr().out
    assert out.strip() == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_cli_plan.py::test_quiet_suppresses_stdout -q`
Expected: FAIL (prints "Loading manifest", report, etc.).

- [ ] **Step 3: Implement a quiet-aware print helper**

Add a module-level flag and helper, set in `main`:

```python
_QUIET = False

def _out(*args, **kwargs):
    if not _QUIET:
        print(*args, **kwargs)
```

In `main`, after parsing: `global _QUIET; _QUIET = bool(args.quiet)`.
Replace user-facing `print(...)` calls in `_plan_command`, `_print_protocol`,
`_init_command`, `_validate_command` (text branch), `_export_stats_csv`, and the
discovery/progress notices with `_out(...)`. Leave `file=sys.stderr` error prints
as `print(...)` (errors always show).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cli_plan.py tests/test_cli_init.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/cli.py tests/test_cli_plan.py
git commit -m "fix(cli): --quiet suppresses stdout output (CORE-C4)"
```

---

## Task 19: `--pattern` warns outside `--recursive` (CORE-C5)

**Files:**
- Modify: `ambermeta/cli.py` (`_plan_command`)
- Test: `tests/test_cli_plan.py`

- [ ] **Step 1: Failing test**

```python
def test_pattern_warns_in_manifest_mode(tmp_path, capsys):
    from ambermeta.cli import main
    (tmp_path / "manifest.yaml").write_text("stages: []\n")
    main(["plan", str(tmp_path), "--manifest",
          str(tmp_path / "manifest.yaml"), "--pattern", "prod_.*"])
    err = capsys.readouterr().err + capsys.readouterr().out
    # warning surfaced (stderr or stdout)
```

Use a robust assert:

```python
    out = capsys.readouterr()
    assert "pattern" in (out.out + out.err).lower()
```

(Place the single `readouterr()` call once.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_cli_plan.py::test_pattern_warns_in_manifest_mode -q`
Expected: FAIL (silent no-op).

- [ ] **Step 3: Implement**

In `_plan_command`, after computing `pattern_filter`, before the mode branches:

```python
    if pattern_filter and not args.recursive:
        print(Colors.warning(
            "WARNING: --pattern only applies to --recursive discovery; ignored."),
            file=sys.stderr)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cli_plan.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/cli.py tests/test_cli_plan.py
git commit -m "fix(cli): warn that --pattern needs --recursive (CORE-C5)"
```

---

## Task 20: Manifest `settings.strict_validation` honored via CLI (CORE-C6)

**Files:**
- Modify: `ambermeta/cli.py` (`--skip-cross-stage-validation` default; `_plan_command`)
- Test: `tests/test_cli_plan.py`

- [ ] **Step 1: Failing test**

```python
def test_skip_flag_defaults_to_none():
    from ambermeta.cli import build_parser
    args = build_parser().parse_args(["plan", "."])
    assert args.skip_cross_stage_validation is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_cli_plan.py::test_skip_flag_defaults_to_none -q`
Expected: FAIL (default is `False`).

- [ ] **Step 3: Implement**

Change the argument definition:

```python
    plan_parser.add_argument(
        "--skip-cross-stage-validation",
        action="store_const", const=True, default=None,
        help="Skip continuity checks between consecutive stages "
             "(overrides the manifest's settings.strict_validation)",
    )
```

In `_plan_command`'s recursive/interactive branches, `auto_discover` expects a
bool — pass `bool(args.skip_cross_stage_validation)` there; in the `--manifest`
branch pass `args.skip_cross_stage_validation` straight through (so `None` lets
the manifest setting win).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cli_plan.py tests/test_cli_validate.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/cli.py tests/test_cli_plan.py
git commit -m "fix(cli): manifest strict_validation honored when flag omitted (CORE-C6)"
```

---

## Task 21: Empty-manifest warning + non-zero exit (CORE-C7)

**Files:**
- Modify: `ambermeta/cli.py` (`_init_command`, `_plan_command`)
- Test: `tests/test_cli_init.py`, `tests/test_cli_plan.py`

- [ ] **Step 1: Failing tests**

```python
def test_init_auto_empty_warns_nonzero(tmp_path):
    from ambermeta.cli import main
    (tmp_path / "system.prmtop").write_text("dummy")  # only a topology
    rc = main(["init", str(tmp_path), "--auto", "-o", "m.yaml", "--force"])
    assert rc == 1


def test_plan_empty_manifest_nonzero(tmp_path):
    from ambermeta.cli import main
    (tmp_path / "m.yaml").write_text("stages: []\n")
    rc = main(["plan", str(tmp_path), "--manifest", str(tmp_path / "m.yaml")])
    assert rc == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_cli_init.py::test_init_auto_empty_warns_nonzero tests/test_cli_plan.py::test_plan_empty_manifest_nonzero -q`
Expected: FAIL (both currently exit 0).

- [ ] **Step 3: Implement guards**

In `_init_command` (auto path), after building `stage_candidates`:

```python
        if not stage_candidates:
            print(Colors.warning(
                "WARNING: no mdin/mdout/mdcrd/inpcrd files found; "
                "no stages generated."), file=sys.stderr)
            return 1
```

In `_plan_command`, after each `protocol` is built, before reporting:

```python
    if not protocol.stages:
        print(Colors.warning(
            "WARNING: manifest produced 0 stages; check format/column names."),
            file=sys.stderr)
        return 1
```

(The `--recursive` branch already returns 1 on empty; keep that.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cli_init.py tests/test_cli_plan.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/cli.py tests/test_cli_init.py tests/test_cli_plan.py
git commit -m "fix(cli): non-zero exit + warning on empty manifests (CORE-C7)"
```

---

## Task 22: zsh completion `tui` branch (CORE-C9)

**Files:**
- Modify: `ambermeta/cli.py` (`_completion_script` zsh case)
- Test: `tests/test_cli_completion.py`

- [ ] **Step 1: Failing test**

```python
def test_zsh_completion_has_tui_branch():
    from ambermeta.cli import _completion_script
    assert "tui)" in _completion_script("zsh")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_cli_completion.py::test_zsh_completion_has_tui_branch -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

In the zsh script's `case "$words[2]" in`, add before `completion)`:

```
        tui)
          _arguments '*:path:_files'
          ;;
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cli_completion.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/cli.py tests/test_cli_completion.py
git commit -m "fix(cli): zsh completion covers tui subcommand (CORE-C9)"
```

---

## Task 23: GUI path-traversal fix (CORE-G1)

**Files:**
- Modify: `ambermeta/gui/server.py` (`serve_spa`)
- Test: `tests/test_gui_security.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_gui_security.py
import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def test_spa_rejects_traversal(tmp_path):
    from ambermeta.gui import server
    static = tmp_path / "static"; (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>app</html>")
    secret = tmp_path / "secret.txt"; secret.write_text("TOPSECRET")
    # point the app at our static dir
    import ambermeta.gui.server as S
    app = S.create_app(str(tmp_path))
    # monkeypatch static_path resolution is internal; instead assert via route:
    client = TestClient(app)
    r = client.get("/..%2Fsecret.txt")
    assert "TOPSECRET" not in r.text
```

(If `create_app` requires a built frontend to register `serve_spa`, the test
builds the minimal `static/index.html`+`assets/` above so the route is mounted.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_gui_security.py -q`
Expected: FAIL (secret served).

- [ ] **Step 3: Implement containment check**

Replace `serve_spa`:

```python
        @app.get("/{path:path}")
        async def serve_spa(path: str):
            """Serve the SPA; never serve files outside the static dir."""
            index = static_path / "index.html"
            if ".." in path or path.startswith(("/", "\\")):
                return FileResponse(index)
            candidate = (static_path / path).resolve()
            root = static_path.resolve()
            if candidate == root or root in candidate.parents:
                if candidate.is_file():
                    return FileResponse(candidate)
            return FileResponse(index)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_gui_security.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/server.py tests/test_gui_security.py
git commit -m "fix(gui): block path traversal in SPA fallback route (CORE-G1)"
```

---

## Task 24: Docs & completion sync + full-suite gate

**Files:**
- Modify: `docs/cli.md`, `README.md` (flag/behavior notes for `--quiet`, `--pattern`, `--skip-cross-stage-validation`, init `global_prmtop`/`hmr_prmtop`, CSV header)
- Modify: completion scripts if any flags changed (zsh tui already in Task 22)
- Test: full suite

- [ ] **Step 1: Update docs**

Document: `--quiet` now suppresses stdout; `--pattern` only applies with
`--recursive`; manifest `settings.strict_validation` is honored when
`--skip-cross-stage-validation` is omitted; `init --auto` emits
`global_prmtop`/`hmr_prmtop` and one stage per file group; canonical CSV header
is `name,...`.

- [ ] **Step 2: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS (all tests green).

- [ ] **Step 3: Run the docs-sync check locally**

Run: `python scripts/export_cli_help.py` (or the command the CI workflow uses) and confirm no drift.
Expected: no diff / exit 0.

- [ ] **Step 4: Commit**

```bash
git add docs/ README.md ambermeta/cli.py
git commit -m "docs: sync CLI reference and completions for hardening changes"
```

---

## Self-review notes (author)

- **Spec coverage:** Every CORE-* item maps to a task — P1→T5, P2→T10, P3/P4a→T6,
  P4b→T7, P5/H1→T8, P6→T11, P7→T9, P8→T12, D1/C1→T3, D2/D7→T4, D3/D4/H2/H3→T13,
  D5→T14, D6→T17, H4/C3→T15, C2→T16, C4→T18, C5→T19, C6→T20, C7→T21, C8→T2,
  C9→T22, G1→T23; manifest module→T1; docs→T24. Reported Bug 1→T3, Bug 2→T8/T13/T15.
- **Deferred (not in this plan):** GUI `/files/metadata`, GUI export writers,
  all TUI-internal bugs → Sub-projects B/C.
- **Type consistency:** `write_manifest(payload, path, fmt)`, `load_manifest`,
  `normalize_stage_keys`, `STAGE_FILE_KINDS`, `HMR_TIMESTEP_THRESHOLD_PS`,
  `_apply_global_and_hmr_prmtop(...)`, `_ordered_stems(...)` are referenced
  consistently across tasks.
- **Verify entry-point names at implementation time:** `parse_inpcrd`/`parse_mdin_file`
  may differ in the legacy modules — confirm the actual public function name when
  writing Tasks 11/12 and adjust the import in the test accordingly.
