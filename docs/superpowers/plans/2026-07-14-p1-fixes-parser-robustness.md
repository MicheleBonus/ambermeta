# P1-fixes — Parser Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the ~15 localized, mostly-independent parser/file-kind robustness defects from the 2026-07-14 file-handling audit (the medium/low findings that were NOT part of P1's 5 redesign-critical clusters), each as a small TDD task.

**Architecture:** Targeted, in-place fixes to `ambermeta/legacy_extractors/{prmtop,inpcrd,mdout,mdcrd}.py` and the three file-kind extension maps (`gui/api/files.py`, `gui/api/core_bridge.py`, `protocol.py`). Each fix is self-contained with a regression test; fixes to the same file must run sequentially, but the groups are otherwise independent.

**Tech Stack:** Python 3.11+, pytest. NumPy/netCDF4 are optional (already handled behind `HAS_NETCDF`/`np is None` guards) — NetCDF tests are `skipif`-guarded. No new third-party dependencies.

## Global Constraints

- Branch: `phase-step-redesign`.
- **No new third-party dependencies.** NetCDF-dependent tests must `@pytest.mark.skipif(not …HAS_NETCDF …)`.
- **Do NOT alter the mass-based `ATOMIC_NUMBER` HMR detection** (`legacy_extractors/prmtop.py`, the `hmr_active = (max_mass >= 2.0) …` verdict on the `atomic_number` path) — that is the sound Bug-2 detection. Only harden the `atom_name` fallback (Task A5).
- **Parser metadata field names/shapes stay backward-compatible** unless a fix requires a documented change; the only additive fields introduced here are `PrmtopMetadata.box_is_topology_time` (A6) — additive, defaulted, no consumer breaks.
- Do NOT re-do anything already fixed in P1: the three role guessers, `.crd` content-sniffing (`ambermeta/coords.py`), continuity anchoring/tolerance/sequence-holes, `classify_topologies`→pool, `dt>0.002`. Do NOT "fix" the 3 audit-refuted findings (OPC3-pol water HMR false-positive, `tempi`/`ntx` heating, coverage fencepost) — they are not bugs.
- **Every task ends with the FULL `pytest -q` suite green** (not just the new test).

---

## File Structure

**Modify (source):**
- `ambermeta/legacy_extractors/prmtop.py` — env label, ligand classification, ions, neutrality, HMR name-fallback, box caveat (Tasks A1–A6).
- `ambermeta/legacy_extractors/inpcrd.py` — NetCDF magic; ASCII box-fabrication guard (B1–B2).
- `ambermeta/legacy_extractors/mdout.py` — barostat keyword; minimization run_type (C1–C2).
- `ambermeta/legacy_extractors/mdcrd.py` — AMBERRESTART crash + NetCDF magic; ASCII-flag + relative dt-variance/REMD (D1–D2).
- `ambermeta/gui/api/files.py`, `ambermeta/gui/api/core_bridge.py`, `ambermeta/protocol.py` — the three ext maps (E1–E3).

**New test file:** `tests/test_parser_fixes.py` (all tasks append here; the `_write_prmtop` helper is added in A1 and reused).

**Shared test helper (added in Task A1, top of `tests/test_parser_fixes.py`):**
```python
# tests/test_parser_fixes.py
import math
import pytest


def _write_prmtop(path, *, natom, nres, res_labels, charges=None, masses=None,
                  atomic_numbers=None, atom_names=None, radius_set=None, box=None):
    """Write a minimal but real prmtop containing only the flags a test needs.
    `box` is [beta, a, b, c] (the legacy BOX_DIMENSIONS layout)."""
    out = ["%VERSION VERSION_STAMP = V0001.000  DATE = 01/01/25"]

    def ints(vals, per=10, w=8):
        return ["".join(f"{v:{w}d}" for v in vals[i:i + per]) for i in range(0, len(vals), per)] or [""]

    def floats(vals, per=5, w=16):
        return ["".join(f"{v:{w}.8E}" for v in vals[i:i + per]) for i in range(0, len(vals), per)] or [""]

    def a4(vals, per=20):
        return ["".join(f"{str(v):<4}"[:4] for v in vals[i:i + per]) for i in range(0, len(vals), per)] or [""]

    def block(flag, fmt, cells):
        out.append(f"%FLAG {flag}")
        out.append(f"%FORMAT({fmt})")
        out.extend(cells)

    pointers = [0] * 32
    pointers[0] = natom
    pointers[11] = nres
    block("POINTERS", "10I8", ints(pointers))
    block("RESIDUE_LABEL", "20a4", a4(res_labels))
    if charges is not None:
        block("CHARGE", "5E16.8", floats(charges))
    if masses is not None:
        block("MASS", "5E16.8", floats(masses))
    if atomic_numbers is not None:
        block("ATOMIC_NUMBER", "10I8", ints(atomic_numbers))
    if atom_names is not None:
        block("ATOM_NAME", "20a4", a4(atom_names))
    if radius_set is not None:
        block("RADIUS_SET", "1a80", [radius_set])
    if box is not None:
        block("BOX_DIMENSIONS", "5E16.8", floats(box))
    path.write_text("\n".join(out) + "\n")
```

---

## Group A — prmtop (`legacy_extractors/prmtop.py`)

### Task A1: Non-periodic ≠ "Implicit Solvent" (severity: medium)

The `RADIUS_SET`-present branch labels every boxless system "Implicit Solvent" (LEaP writes RADIUS_SET into ~every prmtop), so the "Vacuum" branch is dead and vacuum systems are mislabeled. From the topology alone we can only distinguish periodic/explicit vs non-periodic.

**Files:** Modify `ambermeta/legacy_extractors/prmtop.py`; Test `tests/test_parser_fixes.py`.

- [ ] **Step 1: Add the helper + failing test**

Add the `_write_prmtop` helper (from File Structure above) to the top of `tests/test_parser_fixes.py`, then:
```python
from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata, _classify_simulation, PrmtopMetadata


def test_boxless_prmtop_is_non_periodic_not_implicit(tmp_path):
    p = tmp_path / "vac.prmtop"
    _write_prmtop(p, natom=1, nres=1, res_labels=["LIG"],
                  radius_set="modified Bondi radii (mbondi)")  # RADIUS_SET but NO box
    md = extract_prmtop_metadata(str(p))
    assert md.solvent_type == "Non-periodic"
    assert "Implicit Solvent" not in md.simulation_category
    assert "non-periodic" in md.simulation_category.lower()


def test_boxed_prmtop_is_explicit(sample_md_data_dir):
    md = extract_prmtop_metadata(str(sample_md_data_dir / "CH3L1_HUMAN_6NAG.top"))
    assert md.solvent_type == "Explicit Solvent"
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k non_periodic`
Expected: FAIL (`solvent_type == "Implicit Solvent"`).

- [ ] **Step 3: Apply the fix**

In `extract_prmtop_metadata`, replace the `elif prmtop.get("RADIUS_SET"):` branch (currently lines 454-459):
```python
    elif prmtop.get("RADIUS_SET"):
        md.solvent_type = "Implicit Solvent"
        rs = prmtop.get("RADIUS_SET")
        if rs:
            radius_str = "".join(str(x) for x in rs if x).strip()
            md.force_field_features.append(f"GB Radii: {radius_str}")
```
with:
```python
    else:
        # Vacuum vs implicit solvent is a runtime mdin choice (igb), NOT encoded in
        # the topology — LEaP writes RADIUS_SET/PBRadii into virtually every prmtop.
        # From the topology alone we can only say the system is non-periodic.
        md.solvent_type = "Non-periodic"
        rs = prmtop.get("RADIUS_SET")
        if rs:
            radius_str = "".join(str(x) for x in rs if x).strip()
            md.force_field_features.append(f"GB Radii: {radius_str}")
```
Then in `_classify_simulation`, replace the solvent-context head (currently lines 316-319):
```python
    if md.solvent_type == "Implicit Solvent":
        solvent_context = "in Implicit Solvent"
    elif md.solvent_type == "Vacuum":
        solvent_context = "in Vacuum"
```
with:
```python
    if md.solvent_type == "Non-periodic":
        solvent_context = "non-periodic (vacuum or implicit solvent — depends on mdin igb)"
    elif md.solvent_type == "Vacuum":
        solvent_context = "in Vacuum"
```

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k "non_periodic or boxed" && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ambermeta/legacy_extractors/prmtop.py tests/test_parser_fixes.py
git commit -m "fix(parser): report prmtop env as periodic/non-periodic, not implicit-from-RADIUS_SET"
```

### Task A2: Protein+ligand complexes actually get "Ligand" (severity: medium)

`_classify_simulation`'s `unknown_residues` comprehension has a loop-invariant `not (has_protein or …)` predicate, so once any biomolecule is present the ligand list is always empty (the `elif` is dead).

**Files:** Modify `ambermeta/legacy_extractors/prmtop.py`; Test `tests/test_parser_fixes.py`.

- [ ] **Step 1: Failing test**
```python
def _md(comp, solvent="Explicit Solvent"):
    return PrmtopMetadata(filename="x", residue_composition=comp, solvent_type=solvent)


def test_protein_ligand_complex_names_ligand():
    md = _md({"ALA": 20, "LIG": 1, "WAT": 500})
    _classify_simulation(md)
    assert "Protein" in md.simulation_category and "Ligand" in md.simulation_category
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k names_ligand`
Expected: FAIL ("Ligand" absent — dead `elif`).

- [ ] **Step 3: Apply the fix**

In `_classify_simulation`, replace (currently lines 305-310):
```python
    known_solvents = WATER_RESNAMES | ORGANIC_SOLVENT_RESNAMES | ION_RESNAMES
    unknown_residues = [r for r in md.residue_composition if r not in known_solvents and not (has_protein or has_dna or has_rna or has_lipid)]
    if unknown_residues and not solutes:
        solutes.append("Small Molecule / Ligand")
    elif unknown_residues:
        solutes.append("Ligand")
```
with (compute unknowns independent of the biomolecule flags — a residue is "unknown" iff it is not a known solvent/ion AND not itself a protein/nucleic/lipid residue):
```python
    known_solvents = WATER_RESNAMES | ORGANIC_SOLVENT_RESNAMES | ION_RESNAMES
    biomol = PROTEIN_RESNAMES | DNA_RESNAMES | RNA_RESNAMES | LIPID_RESNAMES
    unknown_residues = [
        r for r in md.residue_composition
        if r not in known_solvents and r not in biomol
        and not (len(r) == 4 and r[1:] in PROTEIN_RESNAMES)
    ]
    if unknown_residues and not solutes:
        solutes.append("Small Molecule / Ligand")
    elif unknown_residues:
        solutes.append("Ligand")
```

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k names_ligand && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ambermeta/legacy_extractors/prmtop.py tests/test_parser_fixes.py
git commit -m "fix(parser): classify a ligand in protein/nucleic/lipid complexes (dead elif)"
```

### Task A3: Recognize sign-less ion residue names (severity: low)

`ION_RESNAMES` has only signed names (`Na+`, `Cl-`); bare `NA`/`CL`/`K`/`MG`/`CA` (common in older/GROMACS-converted topologies) fall through and can be counted as ligands.

**Files:** Modify `ambermeta/legacy_extractors/prmtop.py`; Test `tests/test_parser_fixes.py`.

- [ ] **Step 1: Failing test**
```python
def test_signless_ions_not_ligands():
    md = _md({"ALA": 20, "NA": 8, "CL": 8, "WAT": 500})
    _classify_simulation(md)
    assert "Ligand" not in md.simulation_category  # NA/CL are ions, not a ligand
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k signless_ions`
Expected: FAIL ("Ligand" present — NA/CL unrecognized). (After A2, sign-less ions become "unknown" → "Ligand", which this test now catches.)

- [ ] **Step 3: Apply the fix**

Extend `ION_RESNAMES` (currently lines 69-76) — add the sign-less aliases before the closing brace:
```python
    "Fe3+", "Cr3+", "Al3+",            # Trivalent
    # Sign-less aliases (older / converted topologies)
    "NA", "CL", "K", "RB", "CS", "LI", "F", "BR", "I",
    "MG", "CA", "ZN", "MN", "FE", "CO", "NI", "CU", "CD", "BA", "SR", "IB",
```

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k signless_ions && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ambermeta/legacy_extractors/prmtop.py tests/test_parser_fixes.py
git commit -m "fix(parser): recognize sign-less ion residue names (NA/CL/K/MG/CA/...)"
```

### Task A4: Don't assert neutrality from incomplete CHARGE data (severity: low)

`extract_prmtop_metadata` warns when CHARGE is short of `natom`, but still computes `is_neutral` from the partial sum. Make `is_neutral` `None` (unknown) when the section is incomplete.

**Files:** Modify `ambermeta/legacy_extractors/prmtop.py` (+ `PrmtopMetadata.is_neutral` type); Test `tests/test_parser_fixes.py`.

**Interfaces:** `PrmtopMetadata.is_neutral` becomes `Optional[bool]` (was `bool`, default `False` → default `None`). `summarize_metadata` must render `None` as "Unknown".

- [ ] **Step 1: Failing test**
```python
def test_incomplete_charge_leaves_neutrality_unknown(tmp_path):
    p = tmp_path / "partial.prmtop"
    # natom=4 but only 2 charges present -> incomplete
    _write_prmtop(p, natom=4, nres=1, res_labels=["LIG"], charges=[0.5, -0.5])
    md = extract_prmtop_metadata(str(p))
    assert md.is_neutral is None
    assert any("neutrality verdict is uncertain" in w for w in md.warnings)
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k neutrality_unknown`
Expected: FAIL (`is_neutral` is `True`/`False`, not `None`).

- [ ] **Step 3: Apply the fix**

Change the dataclass field (line 239) `is_neutral: bool = False` → `is_neutral: Optional[bool] = None`. Then replace the CHARGE block (currently lines 382-394):
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
            raw_sum = sum(valid_charges)
            md.total_charge = raw_sum / 18.2223
            # Threshold set to 1e-2 as requested
            md.is_neutral = abs(md.total_charge) < 1e-2
```
with:
```python
    charges = prmtop.get("CHARGE")
    if charges:
        valid_charges = [c for c in charges if c is not None]
        complete = not (md.natom and len(valid_charges) != md.natom)
        if not complete:
            md.warnings.append(
                f"CHARGE has {len(valid_charges)} valid of {md.natom} atoms; "
                "neutrality verdict is uncertain."
            )
        if valid_charges:
            md.total_charge = sum(valid_charges) / 18.2223
            # Only assert neutrality when the CHARGE section was fully read.
            md.is_neutral = (abs(md.total_charge) < 1e-2) if complete else None
```
Then in `summarize_metadata` (currently line 508), replace:
```python
    lines.append(f"  Charge:   {md.total_charge:.4f} e ({'Neutral' if md.is_neutral else 'Charged'})")
```
with:
```python
    neutral_str = "Unknown" if md.is_neutral is None else ("Neutral" if md.is_neutral else "Charged")
    lines.append(f"  Charge:   {md.total_charge:.4f} e ({neutral_str})")
```

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k neutrality_unknown && pytest -q`
Expected: PASS. (If any existing test asserts `is_neutral is False` on a complete topology, it still holds — only the incomplete case changed.)

- [ ] **Step 5: Commit**
```bash
git add ambermeta/legacy_extractors/prmtop.py tests/test_parser_fixes.py
git commit -m "fix(parser): report is_neutral=None (unknown) when CHARGE data is incomplete"
```

### Task A5: Harden the atom-name HMR fallback (severity: low)

The name fallback (`name.startswith("H") and mass < 5.0`) can catch non-H elements whose names start with H, and deuterium (~2.014) trips the HMR verdict. Keep the sound `ATOMIC_NUMBER` path untouched; tighten only the name fallback.

**Files:** Modify `ambermeta/legacy_extractors/prmtop.py`; Test `tests/test_parser_fixes.py`.

- [ ] **Step 1: Failing test**
```python
def test_atom_name_hmr_fallback_excludes_non_hydrogen(tmp_path):
    # No ATOMIC_NUMBER -> name fallback. "Hg" (mercury) and "Ho" must NOT be read as H.
    p = tmp_path / "names.prmtop"
    _write_prmtop(p, natom=3, nres=1, res_labels=["LIG"],
                  masses=[200.59, 1.008, 1.008], atom_names=["Hg", "H1", "H2"])
    md = extract_prmtop_metadata(str(p))
    assert md.hmr_detection_method == "atom_name"
    # only the two real H (1.008) counted -> max 1.008 -> not HMR, and Hg (200) excluded
    assert md.hmr_active is False
    assert md.hmr_hydrogen_mass_range == (1.008, 1.008)
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k hmr_fallback`
Expected: FAIL (`Hg` mass 200.59 excluded by `<5.0`, but a `He`/`Ho`-style light element would slip through; and the current filter keys only on `startswith("H")`). Adjust: the current code already excludes mass≥5, so `Hg` is excluded — the real gap is elements like `He`/`Ho`. Make the test use a light non-H: replace `masses=[200.59,…]` with a Helium case below.

Use this test instead (Helium slips through the current filter):
```python
def test_atom_name_hmr_fallback_excludes_non_hydrogen(tmp_path):
    p = tmp_path / "names.prmtop"
    # "He" (helium, ~4.0) currently passes startswith("H") and mass<5 -> wrongly a "hydrogen".
    _write_prmtop(p, natom=3, nres=1, res_labels=["LIG"],
                  masses=[4.003, 1.008, 1.008], atom_names=["He", "H1", "H2"])
    md = extract_prmtop_metadata(str(p))
    assert md.hmr_detection_method == "atom_name"
    assert md.hmr_hydrogen_mass_range == (1.008, 1.008)   # He excluded
    assert md.hmr_active is False
```

- [ ] **Step 3: Apply the fix**

Replace the `atom_name` fallback (currently lines 414-421):
```python
    elif masses and atom_names:
        n = min(len(masses), len(atom_names))
        hydrogen_masses = [masses[i] for i in range(n)
                           if masses[i] is not None
                           and str(atom_names[i]).strip().upper().startswith("H")
                           and masses[i] < 5.0]
        if hydrogen_masses:
            md.hmr_detection_method = "atom_name"
```
with (a name is hydrogen iff it starts with "H" NOT followed by a lowercase letter — excludes He/Hg/Ho/Hf/Hs/Ho; keep the mass sanity bound):
```python
    elif masses and atom_names:
        n = min(len(masses), len(atom_names))
        def _is_h_name(nm: str) -> bool:
            nm = str(nm).strip()
            # "H", "H1", "HA", "HG1" are hydrogen; "He"/"Hg"/"Ho"/"Hf" (2nd char lowercase) are not.
            return bool(nm) and nm[0].upper() == "H" and not (len(nm) > 1 and nm[1].islower())
        hydrogen_masses = [masses[i] for i in range(n)
                           if masses[i] is not None
                           and _is_h_name(atom_names[i])
                           and masses[i] < 5.0]
        if hydrogen_masses:
            md.hmr_detection_method = "atom_name"
            if any(1.9 <= m <= 2.2 for m in hydrogen_masses):
                md.warnings.append(
                    "Hydrogen masses ~2.0 amu on the atom-name path may be deuterium, "
                    "not HMR; confirm via ATOMIC_NUMBER."
                )
```
(Leave the `hmr_active = (max_mass >= 2.0) …` verdict line unchanged — that is the shared verdict; the deuterium caveat is surfaced as a warning per the constraint.)

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k hmr_fallback && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ambermeta/legacy_extractors/prmtop.py tests/test_parser_fixes.py
git commit -m "fix(parser): tighten atom-name HMR fallback (exclude He/Hg/... ; warn on deuterium)"
```

### Task A6: Label box/density as topology-time, not current (severity: low)

`box_dimensions`/`box_volume`/`density` come from the LEaP-time `BOX_DIMENSIONS`, not the equilibrated box; report them with a caveat.

**Files:** Modify `ambermeta/legacy_extractors/prmtop.py` (+ additive field); Test `tests/test_parser_fixes.py`.

**Interfaces:** additive `PrmtopMetadata.box_is_topology_time: bool = False`.

- [ ] **Step 1: Failing test**
```python
def test_box_flagged_topology_time(sample_md_data_dir):
    md = extract_prmtop_metadata(str(sample_md_data_dir / "CH3L1_HUMAN_6NAG.top"))
    assert md.box_dimensions is not None
    assert md.box_is_topology_time is True
    assert any("topology-time box" in w.lower() for w in md.force_field_features + md.warnings)
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k topology_time`
Expected: FAIL (`box_is_topology_time` attribute missing).

- [ ] **Step 3: Apply the fix**

Add the field to `PrmtopMetadata` (after `density` at line 245):
```python
    box_is_topology_time: bool = True   # BOX_DIMENSIONS is the LEaP-time box, not the equilibrated one
```
Then in the box branch (`extract_prmtop_metadata`, after `md.solvent_type = "Explicit Solvent"` at line 453) append:
```python
        md.force_field_features.append("Box/density are the topology-time (LEaP) values")
```
(The `box_is_topology_time` default is `True`; it is only ever `True` when a box exists, so no further assignment is needed. If a consumer later derives the box from mdout/trajectory it can set it `False`.)

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k topology_time && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ambermeta/legacy_extractors/prmtop.py tests/test_parser_fixes.py
git commit -m "fix(parser): flag prmtop box/density as topology-time (LEaP) values"
```

---

## Group B — inpcrd (`legacy_extractors/inpcrd.py`)

### Task B1: Full NetCDF magic detection (severity: medium)

`_detect_format` returns "NetCDF" for a bare 3-byte `CDF` prefix — misrouting an HDF5-backed file to the ASCII parser AND an ASCII file whose title starts "CDF" to the NetCDF parser.

**Files:** Modify `ambermeta/legacy_extractors/inpcrd.py`; Test `tests/test_parser_fixes.py`.

- [ ] **Step 1: Failing test**
```python
from ambermeta.legacy_extractors.inpcrd import _detect_format as _inpcrd_detect


def test_inpcrd_detect_format_magic(tmp_path):
    classic = tmp_path / "a.ncrst"; classic.write_bytes(b"CDF\x01rest")
    hdf5 = tmp_path / "b.ncrst"; hdf5.write_bytes(b"\x89HDF\r\n")
    ascii_cdf = tmp_path / "c.rst"; ascii_cdf.write_text("CDF2 my restart title\n     3\n")
    assert _inpcrd_detect(str(classic)) == "NetCDF"
    assert _inpcrd_detect(str(hdf5)) == "NetCDF"     # HDF5-backed NetCDF, was misread as ASCII
    assert _inpcrd_detect(str(ascii_cdf)) == "ASCII" # title starting 'CDF', was misread as NetCDF
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k inpcrd_detect_format`
Expected: FAIL (HDF5 → "ASCII"; ascii_cdf → "NetCDF").

- [ ] **Step 3: Apply the fix**

Replace `_detect_format` (currently lines 103-112):
```python
def _detect_format(filepath: str) -> str:
    """
    Reads the first 4 bytes to determine if file is NetCDF or ASCII.
    NetCDF files start with 'CDF' (ASCII bytes 67 68 70).
    """
    with open(filepath, 'rb') as f:
        header = f.read(4)
        if header.startswith(b'CDF'):
            return "NetCDF"
    return "ASCII"
```
with:
```python
def _detect_format(filepath: str) -> str:
    """Determine NetCDF vs ASCII from the file's magic bytes.

    Classic NetCDF-3 begins with ``CDF\\x01``/``CDF\\x02`` (not a bare 3-byte
    ``CDF``, which an ASCII title could start with); NetCDF-4/HDF5 begins with
    ``\\x89HDF``.
    """
    with open(filepath, 'rb') as f:
        header = f.read(8)
    if header[:4] in (b'CDF\x01', b'CDF\x02') or header[:4] == b'\x89HDF':
        return "NetCDF"
    return "ASCII"
```

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k inpcrd_detect_format && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ambermeta/legacy_extractors/inpcrd.py tests/test_parser_fixes.py
git commit -m "fix(parser): inpcrd NetCDF detection uses full classic magic + HDF5 signature"
```

### Task B2: Don't fabricate a box from a trailing blank line (severity: medium — silent data corruption)

A stray trailing blank line makes `line_count` off by one; the `extra == 1` branch then unconditionally declares `has_box=True` and parses the last coordinate line as a box.

**Files:** Modify `ambermeta/legacy_extractors/inpcrd.py`; Test `tests/test_parser_fixes.py`.

- [ ] **Step 1: Failing test**
```python
from ambermeta.legacy_extractors.inpcrd import parse_inpcrd


def _coords_only_inpcrd(path, natoms, trailing_blank):
    # title, "NATOM", then ceil(natoms*3/6) coord lines of 6 floats
    import math as _m
    body = "\n".join("  1.0  2.0  3.0  4.0  5.0  6.0" for _ in range(_m.ceil(natoms * 3 / 6)))
    text = f"default_name\n{natoms:6d}\n{body}\n"
    if trailing_blank:
        text += "\n"
    path.write_text(text)


def test_trailing_blank_line_does_not_fabricate_box(tmp_path):
    clean = tmp_path / "clean.inpcrd"; _coords_only_inpcrd(clean, 4, trailing_blank=False)
    blanked = tmp_path / "blank.inpcrd"; _coords_only_inpcrd(blanked, 4, trailing_blank=True)
    assert parse_inpcrd(str(clean)).has_box is False
    assert parse_inpcrd(str(blanked)).has_box is False   # was True: coord line read as box
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k fabricate_box`
Expected: FAIL (blanked → `has_box is True`).

- [ ] **Step 3: Apply the fix**

(a) Count only non-blank body lines. Replace the body-count block (currently lines 165-167):
```python
    with open(filepath, 'r') as f:
        # Subtract 2 for Title + Natom line
        line_count = sum(1 for _ in f) - 2
```
with:
```python
    with open(filepath, 'r') as f:
        # Count only non-blank lines, then drop Title + NATOM header (2 lines).
        non_blank = sum(1 for ln in f if ln.strip())
        line_count = non_blank - 2
```
(b) Guard the `extra == 1` branch with `_looks_like_box` (so a coordinate line is never taken as a box). Replace (currently lines 191-195):
```python
    extra = line_count - lines_per_structure
    if extra == 1:
        md.has_velocities = False
        md.has_box = True
        _parse_ascii_box(md)
```
with:
```python
    extra = line_count - lines_per_structure
    if extra == 1 and _looks_like_box(md.filename):
        md.has_velocities = False
        md.has_box = True
        _parse_ascii_box(md)
```
Also tighten `_looks_like_box` so a full 6-float coordinate line is not accepted as a box: a real box tail is exactly 6 tokens (a,b,c,α,β,γ) or 3 (old orthogonal). A coordinate line is also 6 floats, so `_looks_like_box` alone cannot disambiguate a 6-float line — the non-blank count fix (a) is what prevents the miscount; keep `_looks_like_box` as the shape guard. (No change to `_looks_like_box` body required beyond (a)+(b); the two together fix the reported case.)

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k fabricate_box && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ambermeta/legacy_extractors/inpcrd.py tests/test_parser_fixes.py
git commit -m "fix(parser): inpcrd counts non-blank lines + guards extra==1 box (no fabricated box)"
```

---

## Group C — mdout (`legacy_extractors/mdout.py`)

### Task C1: Name the barostat from the `barostat` keyword, not `ntp` (severity: medium)

`ntp` is the pressure-scaling geometry (1=iso, 2=aniso, 3=semi), NOT the barostat algorithm. The algorithm is the separate `barostat` keyword (1=Berendsen, 2=Monte-Carlo).

**Files:** Modify `ambermeta/legacy_extractors/mdout.py`; Test `tests/test_parser_fixes.py`.

- [ ] **Step 1: Failing test**
```python
from ambermeta.legacy_extractors.mdout import parse_mdout


def _mdout(path, control):
    path.write_text(
        "          Amber 22 PMEMD\n\n"
        "   1.  RESOURCE   USE:\n\n"
        "     NATOM  =    1000 NRES   =     300\n\n"
        "   2.  CONTROL  DATA:\n\n"
        f"{control}\n"
    )


def test_barostat_from_keyword_not_ntp(tmp_path):
    p = tmp_path / "npt.mdout"
    _mdout(p, "     ntp     =       1, barostat=       2, temp0   = 300.0,")
    md = parse_mdout(str(p))
    assert md.barostat == "Monte Carlo"   # from barostat=2, NOT Berendsen-from-ntp=1
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k barostat_from_keyword`
Expected: FAIL (`barostat == "Berendsen"` from `ntp=1`).

- [ ] **Step 3: Apply the fix**

Replace the `ntp` handler (currently lines 380-383):
```python
        if "ntp" in line and "=" in line:
            kvs = _extract_key_values(line)
            if 'ntp' in kvs:
                md.barostat = BAROSTATS.get(kvs['ntp'], str(kvs['ntp']))
```
with (ntp only tells us pressure coupling is ON; the algorithm name comes from `barostat`):
```python
        if "ntp" in line and "=" in line:
            kvs = _extract_key_values(line)
            ntp = kvs.get('ntp')
            if isinstance(ntp, (int, float)) and ntp > 0 and md.barostat == "None":
                md.barostat = "Berendsen"   # Amber default when ntp>0 and barostat unset

        if "barostat" in line and "=" in line:
            kvs = _extract_key_values(line)
            if 'barostat' in kvs:
                md.barostat = BAROSTATS.get(kvs['barostat'], str(kvs['barostat']))
```

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k barostat && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ambermeta/legacy_extractors/mdout.py tests/test_parser_fixes.py
git commit -m "fix(parser): mdout barostat name from the barostat keyword, not ntp geometry"
```

### Task C2: Detect minimization mdout (`imin=1`) (severity: low — legacy summarizer only)

`run_type` is hard-coded "MD"; a minimization mdout is never detected.

**Files:** Modify `ambermeta/legacy_extractors/mdout.py`; Test `tests/test_parser_fixes.py`.

- [ ] **Step 1: Failing test**
```python
def test_minimization_run_type(tmp_path):
    p = tmp_path / "min.mdout"
    _mdout(p, "     imin    =       1, maxcyc  =    5000, ntb     =       1,")
    md = parse_mdout(str(p))
    assert md.run_type == "Minimization"
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k minimization_run_type`
Expected: FAIL (`run_type == "MD"`).

- [ ] **Step 3: Apply the fix**

Add an `imin` handler in the CONTROL-DATA scan of `parse_mdout` — insert after the `ntc` handler (after line 388):
```python
        if "imin" in line and "=" in line:
            kvs = _extract_key_values(line)
            imin = kvs.get('imin')
            if imin == 1:
                md.run_type = "Minimization"
```

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k minimization_run_type && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ambermeta/legacy_extractors/mdout.py tests/test_parser_fixes.py
git commit -m "fix(parser): mdout run_type=Minimization when imin=1"
```

---

## Group D — mdcrd (`legacy_extractors/mdcrd.py`)

### Task D1: NetCDF magic + AMBERRESTART misroute crash (severity: medium — real crash)

`_detect_format` is CDF-only (same bug as B1); and a NetCDF `AMBERRESTART` (scalar `time`) misrouted to the trajectory parser throws an uncaught `TypeError` (`len()` of a 0-d array).

**Files:** Modify `ambermeta/legacy_extractors/mdcrd.py`; Test `tests/test_parser_fixes.py`.

- [ ] **Step 1: Failing tests**
```python
from ambermeta.legacy_extractors.mdcrd import _detect_format as _mdcrd_detect
from ambermeta.legacy_extractors import mdcrd as _mdcrd


def test_mdcrd_detect_format_magic(tmp_path):
    hdf5 = tmp_path / "t.nc"; hdf5.write_bytes(b"\x89HDF\r\n")
    ascii_cdf = tmp_path / "t.mdcrd"; ascii_cdf.write_text("CDF trajectory title\n")
    assert _mdcrd_detect(str(hdf5)) == "NetCDF"
    assert _mdcrd_detect(str(ascii_cdf)) == "ASCII"


@pytest.mark.skipif(not _mdcrd.HAS_NETCDF or _mdcrd.np is None,
                    reason="needs a NetCDF backend + numpy to build an AMBERRESTART file")
def test_amberrestart_does_not_crash_trajectory_parser(tmp_path):
    import numpy as np
    path = str(tmp_path / "prod.ncrst")
    if _mdcrd.NETCDF_BACKEND == "netCDF4":
        ds = _mdcrd.nc.Dataset(path, "w", format="NETCDF3_64BIT_OFFSET")
        ds.Conventions = "AMBERRESTART"
        ds.createDimension("atom", 3); ds.createDimension("spatial", 3)
        t = ds.createVariable("time", "f8", ())      # 0-d scalar time
        t[...] = 10.0
        ds.createVariable("coordinates", "f8", ("atom", "spatial"))
        ds.close()
        # It is a .ncrst, but force the trajectory path to prove it degrades, not crashes:
        md = _mdcrd.parse_mdcrd(path)
        assert md is not None  # no uncaught TypeError
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k "mdcrd_detect_format or amberrestart"`
Expected: FAIL on `mdcrd_detect_format` (HDF5→ASCII, ascii_cdf→NetCDF). (The AMBERRESTART test is skipped where no NetCDF backend exists.)

- [ ] **Step 3: Apply the fix**

(a) Replace `_detect_format` (currently lines 125-133) with the same magic check as B1:
```python
def _detect_format(filepath: str) -> str:
    try:
        with open(filepath, 'rb') as f:
            header = f.read(8)
    except (IOError, OSError):
        return "ASCII"
    if header[:4] in (b'CDF\x01', b'CDF\x02') or header[:4] == b'\x89HDF':
        return "NetCDF"
    return "ASCII"
```
(b) In `_parse_netcdf_trajectory`, route an AMBERRESTART away and guard a scalar `time`. Replace the time block (currently lines 172-194):
```python
            if 'time' in vars_keys:
                md.has_time = True
                t_var = ds.variables['time']
                # Read all times (1D array, usually small memory footprint)
                times = t_var[:]
                md.n_frames = len(times)

                if md.n_frames > 0:
                    md.time_start = float(times[0])
                    md.time_end = float(times[-1])
                    md.total_duration = md.time_end - md.time_start

                    if md.n_frames > 1:
                        # Calculate dt steps
                        deltas = np.diff(times)
                        md.avg_dt = float(np.mean(deltas))

                        # Check for internal consistency
                        if np.std(deltas) > 0.01:
                            md.warnings.append("Variable timestep detected within file.")
            elif 'coordinates' in vars_keys:
```
with:
```python
            if "AMBERRESTART" in md.conventions:
                md.warnings.append("NetCDF AMBERRESTART (single-frame restart), not a trajectory.")
                md.n_frames = 1
                if 'time' in vars_keys:
                    md.has_time = True
                    tv = ds.variables['time']
                    scalar = float(tv[...]) if tv.shape == () else float(tv[:][-1])
                    md.time_start = md.time_end = scalar
            elif 'time' in vars_keys:
                md.has_time = True
                t_var = ds.variables['time']
                times = np.atleast_1d(t_var[:])   # guard 0-d scalar
                md.n_frames = len(times)

                if md.n_frames > 0:
                    md.time_start = float(times[0])
                    md.time_end = float(times[-1])
                    md.total_duration = md.time_end - md.time_start

                    if md.n_frames > 1:
                        deltas = np.diff(times)
                        md.avg_dt = float(np.mean(deltas))
                        if _is_variable_dt(deltas, md.avg_dt):
                            md.warnings.append("Variable timestep detected within file.")
            elif 'coordinates' in vars_keys:
```
(c) Add `TypeError` to the NetCDF catch tuple (currently line 240) as a safety net, and add the `_is_variable_dt` helper used above — insert near the top helpers (after `_get_nc_attr`):
```python
def _is_variable_dt(deltas, avg_dt) -> bool:
    """Relative variance check: flag only if the frame-interval spread is a
    meaningful fraction of the interval itself (avoids false-firing on float32
    NetCDF times over long runs, where an absolute 0.01 ps floor is noise)."""
    if np is None or len(deltas) < 2 or not avg_dt:
        return False
    return float(np.std(deltas)) > max(1e-4, abs(avg_dt) * 0.05)
```
Change the catch tuple at line 240:
```python
    except (IOError, OSError, ValueError, KeyError, IndexError, RuntimeError) as e:
```
→
```python
    except (IOError, OSError, ValueError, TypeError, KeyError, IndexError, RuntimeError) as e:
```

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k "mdcrd_detect_format or amberrestart" && pytest -q`
Expected: PASS (AMBERRESTART test passes where a backend exists, else skipped).

- [ ] **Step 5: Commit**
```bash
git add ambermeta/legacy_extractors/mdcrd.py tests/test_parser_fixes.py
git commit -m "fix(parser): mdcrd full NetCDF magic + AMBERRESTART/scalar-time guard (no crash)"
```

### Task D2: ASCII trajectory flagged; relative dt-variance threshold (severity: low)

ASCII trajectories report `n_frames=0` and are silently dropped from sequence analysis; make the exclusion explicit. (The absolute 0.01 ps dt-variance threshold was already replaced by `_is_variable_dt` in D1 — this task adds its unit test + the ASCII flag.)

**Files:** Modify `ambermeta/legacy_extractors/mdcrd.py`; Test `tests/test_parser_fixes.py`.

- [ ] **Step 1: Failing tests**
```python
from ambermeta.legacy_extractors.mdcrd import parse_mdcrd, _is_variable_dt
import numpy as _np


def test_ascii_trajectory_flagged_not_silent(tmp_path):
    p = tmp_path / "old.mdcrd"
    p.write_text("TITLE\n" + "  1.000  2.000  3.000  4.000  5.000  6.000\n" * 4)
    md = parse_mdcrd(str(p))
    assert md.file_format == "ASCII"
    assert any("sequence analysis" in w.lower() for w in md.warnings)


def test_relative_dt_variance_threshold():
    # ~2 ps interval, float32-scale jitter -> NOT variable (relative check)
    steady = _np.array([2.0, 2.0001, 1.9999, 2.0002])
    assert _is_variable_dt(steady, 2.0) is False
    # a real doubling -> variable
    jumpy = _np.array([2.0, 4.0, 2.0, 4.0])
    assert _is_variable_dt(jumpy, 3.0) is True
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k "ascii_trajectory or relative_dt"`
Expected: FAIL on `ascii_trajectory` (no "sequence analysis" warning). (`relative_dt` passes once D1's helper exists.)

- [ ] **Step 3: Apply the fix**

Replace `_parse_ascii_trajectory` (currently lines 245-253):
```python
def _parse_ascii_trajectory(filepath: str) -> TrajectoryMetadata:
    md = TrajectoryMetadata(filename=filepath, file_format="ASCII")
    try:
        with open(filepath, 'r') as f:
            md.title = f.readline().strip()
        md.warnings.append("ASCII format: No detailed metadata (time, box, count) extractable without prmtop.")
    except (IOError, OSError, UnicodeDecodeError):
        md.warnings.append("File empty or unreadable.")
    return md
```
with:
```python
def _parse_ascii_trajectory(filepath: str) -> TrajectoryMetadata:
    md = TrajectoryMetadata(filename=filepath, file_format="ASCII")
    try:
        with open(filepath, 'r') as f:
            md.title = f.readline().strip()
        md.warnings.append(
            "ASCII trajectory: no per-frame time/box/atom-count metadata without the prmtop; "
            "excluded from time-based sequence analysis."
        )
    except (IOError, OSError, UnicodeDecodeError):
        md.warnings.append("File empty or unreadable.")
    return md
```

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k "ascii_trajectory or relative_dt" && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ambermeta/legacy_extractors/mdcrd.py tests/test_parser_fixes.py
git commit -m "fix(parser): flag ASCII trajectory exclusion; unit-test relative dt-variance"
```

---

## Group E — file-kind maps

### Task E1: Classify extensionless canonical Amber defaults (severity: medium)

`prmtop`/`inpcrd`/`mdin`/`mdout`/`mdcrd`/`restrt` (no extension) classify as OTHER in all three maps → a whole default-named job is invisible. Also note the `.in`/`.out` greedy-match trade-off (finding #18) with a code comment (no behavior change).

**Files:** Modify `ambermeta/gui/api/files.py`, `ambermeta/gui/api/core_bridge.py`, `ambermeta/protocol.py`; Test `tests/test_parser_fixes.py`.

- [ ] **Step 1: Failing test**
```python
from ambermeta.gui.api.files import detect_file_type, FileType
from ambermeta.gui.api import core_bridge
from ambermeta.protocol import smart_group_files


def test_extensionless_defaults_classified(tmp_path):
    for name in ("prmtop", "inpcrd", "mdin", "mdout", "mdcrd", "restrt"):
        (tmp_path / name).write_text("x")
    assert detect_file_type(str(tmp_path / "prmtop")) == FileType.PRMTOP
    assert detect_file_type(str(tmp_path / "mdout")) == FileType.MDOUT
    assert detect_file_type(str(tmp_path / "restrt")) == FileType.INPCRD
    assert core_bridge._EXT_KIND.get("") is None  # unchanged; kind resolved by basename
    grouped = smart_group_files(str(tmp_path), recursive=False)
    # the default job groups under stems (prmtop/inpcrd/... each their own stem)
    kinds = {k for g in grouped.values() for k in g if not k.startswith("_")}
    assert {"prmtop", "inpcrd", "mdin", "mdout", "mdcrd"} <= kinds
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k extensionless`
Expected: FAIL (all OTHER / not grouped).

- [ ] **Step 3: Apply the fix (three maps, one canonical basename set)**

(a) `ambermeta/gui/api/files.py` `detect_file_type` — add a basename fallback before the final `return FileType.OTHER` (after line 33):
```python
    # Extensionless canonical Amber default filenames (sander/pmemd defaults).
    if not ext:
        base = Path(path).name.lower()
        if base in ("prmtop", "parm7"):
            return FileType.PRMTOP
        if base == "mdin":
            return FileType.MDIN
        if base == "mdout":
            return FileType.MDOUT
        if base == "mdcrd":
            return FileType.MDCRD
        if base in ("inpcrd", "restrt"):
            return FileType.INPCRD
    return FileType.OTHER
```
(b) `ambermeta/gui/api/core_bridge.py` `file_metadata` — resolve extensionless defaults by basename. Replace (currently lines 283-284):
```python
    ext = os.path.splitext(path)[1].lower()
    kind = _EXT_KIND.get(ext, "other")
```
with:
```python
    ext = os.path.splitext(path)[1].lower()
    kind = _EXT_KIND.get(ext, "other")
    if kind == "other" and not ext:
        kind = _DEFAULT_BASENAME_KIND.get(os.path.basename(path).lower(), "other")
```
and add the module constant next to `_EXT_KIND` (after line 275):
```python
_DEFAULT_BASENAME_KIND = {
    "prmtop": "prmtop", "parm7": "prmtop",
    "mdin": "mdin", "mdout": "mdout", "mdcrd": "mdcrd",
    "inpcrd": "inpcrd", "restrt": "inpcrd",
}
```
(c) `ambermeta/protocol.py` `smart_group_files` — resolve extensionless defaults by basename. Replace the kind lookup (currently lines 1363-1366):
```python
        _, ext = os.path.splitext(rel_path)
        kind = ext_map.get(ext.lower())
        if not kind:
            continue
```
with:
```python
        _, ext = os.path.splitext(rel_path)
        kind = ext_map.get(ext.lower())
        if not kind and not ext:
            # Extensionless canonical Amber default filenames.
            kind = _DEFAULT_BASENAME_KIND.get(os.path.basename(rel_path).lower())
        if not kind:
            continue
```
and add the same constant near `ext_map` (after line 1356, before `# Group by stem`):
```python
    _DEFAULT_BASENAME_KIND = {
        "prmtop": "prmtop", "parm7": "prmtop",
        "mdin": "mdin", "mdout": "mdout", "mdcrd": "mdcrd",
        "inpcrd": "inpcrd", "restrt": "inpcrd",
    }
```
(d) Finding #18 (documented, no behavior change): add a comment above the `.in`/`.out` entries in each map, e.g. in `files.detect_file_type` above the `mdin`/`mdout` checks:
```python
    # NOTE: .in/.out are claimed for Amber mdin/mdout by convention; a non-Amber
    # .in/.out would be mis-typed. Accepted trade-off (content sniff is a follow-up).
```

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k extensionless && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ambermeta/gui/api/files.py ambermeta/gui/api/core_bridge.py ambermeta/protocol.py tests/test_parser_fixes.py
git commit -m "fix(kinds): classify extensionless canonical Amber default filenames in all 3 maps"
```

### Task E2: Classify `.trj` (ASCII trajectory) (severity: low)

`.trj` is an Amber ASCII trajectory extension, unclassified in all three maps.

**Files:** Modify `ambermeta/gui/api/files.py`, `ambermeta/gui/api/core_bridge.py`, `ambermeta/protocol.py`; Test `tests/test_parser_fixes.py`.

- [ ] **Step 1: Failing test**
```python
def test_trj_classified_as_trajectory(tmp_path):
    (tmp_path / "run.trj").write_text("x")
    assert detect_file_type(str(tmp_path / "run.trj")) == FileType.MDCRD
    assert core_bridge._EXT_KIND.get(".trj") == "mdcrd"
    grouped = smart_group_files(str(tmp_path), recursive=False)
    assert any("mdcrd" in g for g in grouped.values())
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k trj_classified`
Expected: FAIL (`.trj` → OTHER / unmapped).

- [ ] **Step 3: Apply the fix**

(a) `files.detect_file_type` — add `"trj"` to the mdcrd extension tuple (line 31): `if ext in ("mdcrd", "nc", "crd", "x", "trj") or name.endswith(".mdcrd"):`.
(b) `core_bridge._EXT_KIND` — add `".trj": "mdcrd",` to the mdcrd line (line 272).
(c) `protocol.smart_group_files` `ext_map` — add `".trj": "mdcrd",` after `".x": "mdcrd",` (line 1355).

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k trj_classified && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ambermeta/gui/api/files.py ambermeta/gui/api/core_bridge.py ambermeta/protocol.py tests/test_parser_fixes.py
git commit -m "fix(kinds): map .trj -> mdcrd (ASCII trajectory) in all 3 maps"
```

### Task E3: `smart_group_files` — don't silently overwrite same-kind collisions (severity: low)

Two files in the same stem resolving to the same kind (e.g. `prod.nc` and `prod.mdcrd`) overwrite silently, order-dependent. Keep the first deterministically and record a collision note.

**Files:** Modify `ambermeta/protocol.py`; Test `tests/test_parser_fixes.py`.

- [ ] **Step 1: Failing test**
```python
def test_smart_group_same_kind_collision_deterministic(tmp_path):
    (tmp_path / "prod.nc").write_text("x")
    (tmp_path / "prod.mdcrd").write_text("x")  # both -> kind "mdcrd", same stem "prod"
    grouped = smart_group_files(str(tmp_path), recursive=False)
    g = grouped["prod"]
    # deterministic winner (sorted-first path) + a recorded collision marker
    assert g["mdcrd"].endswith("prod.mdcrd")           # ".mdcrd" sorts before ".nc"
    assert any(k.startswith("_collision") for k in g)
```

- [ ] **Step 2: Run → RED**

Run: `pytest tests/test_parser_fixes.py -q -k collision`
Expected: FAIL (order-dependent winner; no collision marker).

- [ ] **Step 3: Apply the fix**

Make the discovered list order deterministic and detect collisions. Replace the grouping loop (currently lines 1361-1367):
```python
    for rel_path, full_path in discovered:
        stem = Path(rel_path).with_suffix("").as_posix()
        _, ext = os.path.splitext(rel_path)
        kind = ext_map.get(ext.lower())
        if not kind:
            continue
        grouped.setdefault(stem, {})[kind] = full_path
```
with:
```python
    for rel_path, full_path in sorted(discovered):   # deterministic order
        stem = Path(rel_path).with_suffix("").as_posix()
        _, ext = os.path.splitext(rel_path)
        kind = ext_map.get(ext.lower())
        if not kind and not ext:
            kind = _DEFAULT_BASENAME_KIND.get(os.path.basename(rel_path).lower())
        if not kind:
            continue
        group = grouped.setdefault(stem, {})
        if kind in group:
            # Same stem + same kind (e.g. prod.nc and prod.mdcrd): keep the first
            # (sorted) deterministically and record the collision.
            group.setdefault(f"_collision_{kind}", os.path.basename(full_path))
            continue
        group[kind] = full_path
```
(Note: the `_DEFAULT_BASENAME_KIND` line inside the loop is the one added in E1 — E1 runs before E3, so it exists; if executing E3 first, add it per E1(c).)

- [ ] **Step 4: Run → GREEN**

Run: `pytest tests/test_parser_fixes.py -q -k collision && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add ambermeta/protocol.py tests/test_parser_fixes.py
git commit -m "fix(kinds): smart_group_files is deterministic + records same-kind collisions"
```

---

## Self-Review — audit fix-list coverage

| Audit item | Task | Severity |
|---|---|---|
| #1 vacuum → "Implicit Solvent" | A1 | medium |
| #2 protein+ligand never "Ligand" (dead elif) | A2 | medium |
| #3 sign-less ions unrecognized | A3 | low |
| #4 neutrality from incomplete CHARGE | A4 | low |
| #5 deuterium / atom-name HMR fallback | A5 | low |
| #6 box/density are LEaP-time, no caveat | A6 | low |
| #7 inpcrd NetCDF magic (CDF-prefix) | B1 | medium |
| #8 inpcrd blank-line box fabrication | B2 | medium (corruption) |
| #9 barostat from ntp not `barostat` | C1 | medium |
| #10 run_type hard-coded MD (minimization) | C2 | low |
| #11 mdcrd AMBERRESTART crash (TypeError) | D1 | medium (crash) |
| #12 mdcrd NetCDF magic | D1 | medium |
| #13 ASCII trajectory silently dropped | D2 | low |
| #14 absolute dt-variance threshold / REMD | D2 (+D1 helper) | low |
| #15 extensionless canonical defaults OTHER | E1 | medium |
| #16 `.trj` unclassified | E2 | low |
| #17 same-kind stem collision overwrite | E3 | low |
| #18 `.in`/`.out` greedy match | E1(d) — documented comment, no behavior change | low |

**Field-shape changes (all additive / widened, backward-compatible):** `PrmtopMetadata.is_neutral: bool→Optional[bool]` (A4); `PrmtopMetadata.box_is_topology_time: bool = True` new (A6). No consumer reads these as required non-None today; the GUI `file_metadata` serializes the dataclass generically. **Not touched:** the mass-based `ATOMIC_NUMBER` HMR verdict; the P1 role classifier, `.crd` sniffing, continuity, topology pool, HMR-dt threshold. **REMD extension (#14):** the plan makes the dt-variance check relative and leaves REMD detection as-is (T-REMD + multi-D already covered); broader single-dimension H/pH-REMD detection is noted as a follow-up rather than implemented, to avoid guessing at NetCDF variable names not present in the repo's fixtures.

**Ordering:** groups are independent; within a file, tasks are sequential (A1→A6, B1→B2, C1→C2, D1→D2, E1→E3). E3 assumes E1's `_DEFAULT_BASENAME_KIND` in `protocol.py` exists (E1 precedes E3).
