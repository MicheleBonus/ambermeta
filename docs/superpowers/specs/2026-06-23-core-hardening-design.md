# Core Correctness & Hardening — Design Spec

**Date**: 2026-06-23
**Status**: Approved (design); pending implementation plan
**Sub-project**: A of 3 (A: core hardening → B: GUI redesign → C: TUI redesign)
**Owner**: AmberMeta v1 release hardening

## Context

AmberMeta is heading toward its first "ready" release. A read-only,
adversarially-verified audit of the whole codebase found **39 real bugs**. The
user also reported two of these directly:

- **Reported Bug 1**: `ambermeta init --auto` over a folder with many numbered
  `mdin/mdout/rst` files writes only the *last* file of each kind to the
  manifest (numbered sequences collapse into one stage).
- **Reported Bug 2**: HMR (Hydrogen Mass Repartitioning) prmtop files cannot be
  distinguished from normal prmtop files reliably.

The TUI and GUI are both slated for a full redesign (Sub-projects B and C). To
avoid throwing away work, **this sub-project fixes only the core engine, the
CLI, the shared manifest contract, and the one live GUI security hole.** All
UI-*internal* defects are deferred to the redesigns, where that code is replaced.

## Goals

1. Fix both reported bugs, consistently (production behaves like equilibration).
2. Fix the parser correctness bugs that corrupt reported provenance numbers.
3. Make the manifest interchange format a single, well-defined contract that
   round-trips across all formats and tolerates legacy/variant inputs.
4. Replace *silent* wrong/empty output with warnings or non-zero exits.
5. Patch the GUI path-traversal vulnerability.
6. Ship regression tests for every fixed bug.

## Non-goals (deferred)

Deferred to **B (GUI redesign)**: `/files/metadata` endpoint using the wrong
parser API; GUI export code emitting non-canonical CSV `role` header, flat gap
keys, and unescaped CSV — the **reader** is made tolerant now (A), and the GUI
**writer** adopts the canonical writer during the redesign.

Deferred to **C (TUI redesign)**: undo/redo dropping `hmr_prmtop`; Windows
subdirectory selection (posix/native stem mismatch); export preview not
refreshing on path-mode toggle; stale state after `load_session`; blocking I/O
on the event loop; arrow-key navigation not syncing the editor; `#stem-list`
CSS targeting `RadioButton` instead of `Checkbox`; 30-char stage-name truncation.

No new features. No behavior change beyond bug fixes and the new warnings.

## Methodology

TDD. For each fix: write a failing regression test first (red), implement the
fix (green), keep the suite green. Reuse existing fixtures
(`tests/data/amber/md_test_files/`) where possible; add new minimal synthetic
fixtures where the existing data can't exercise the bug (see Testing).

---

## Architecture changes

### Change 1 — New module `ambermeta/manifest.py` (canonical writer + tolerant reader)

The manifest format is currently read in `protocol.py` and written in `cli.py`
(and again in `tui.py`/GUI), with subtle divergences that cause silent
round-trip data loss. Extract a single cohesive module.

`protocol.py` is 2,160 lines and `cli.py` is 1,869; moving manifest I/O out is a
targeted, well-bounded reduction.

**Canonical schema** (one documented shape, all formats):

```yaml
global_prmtop: <path>        # optional
hmr_prmtop: <path>           # optional
settings:                    # optional
  strict_validation: false
  allow_gaps: false
stage_role_rules:            # optional
  - {pattern: "prod.*", role: production}
stages:
  - name: <str>              # required
    stage_role: <str>        # optional
    prmtop|mdin|mdout|mdcrd|inpcrd: <path>   # optional
    gaps: {expected: <float>, tolerance: <float>}   # optional, NESTED
    notes: [<str>, ...]      # optional
```

CSV canonical header: `name,stage_role,prmtop,mdin,mdout,mdcrd,inpcrd,expected_gap_ps,gap_tolerance_ps,notes`
(notes `;`-joined). Uses the stdlib `csv` module for RFC-4180 quoting.

**Canonical writer** — `write_manifest(payload, path, fmt)`; one branch per
format, all emitting the schema above. Replaces `cli._write_manifest_payload`.

**Tolerant reader** — `load_manifest(path)` normalizes on read so *any* prior
export loads correctly:
- `stage` → `name` (CSV alias)
- `role` → `stage_role`
- flat `expected_gap_ps`/`gap_tolerance_ps` → nested `gaps`
- existing nested `gaps`/`gap` continue to work

This single normalization retroactively fixes the CSV and GUI gap/role
round-trip bugs at the read side without touching the (to-be-replaced) GUI/TUI
writers.

**Compat**: `ambermeta.load_manifest` and `ambermeta.load_protocol_from_manifest`
remain importable (re-exported). Moved helpers: `load_manifest`,
`_parse_csv_manifest`, `_parse_toml_manifest`, `validate_manifest`,
`_expand_env_vars`.

### Change 2 — One discovery path

`init --auto` currently has its own grouping (`_normalize_stage_stem`,
`_build_stage_candidates`) that diverges from the engine's `smart_group_files`.
`init --auto` will build stage candidates from `smart_group_files` so discovery
behaves identically across `init`, `plan --recursive`, and the (future) UIs.

### Change 3 — One global/HMR-prmtop application helper

The logic that applies `global_prmtop` and `hmr_prmtop` to stages exists only in
the manifest branch of `auto_discover`. Factor it into one helper called from
both the manifest and discovery branches, with a single shared HMR timestep
threshold constant.

---

## Fix catalog (A-scope)

Severity is post-verification. IDs are for the implementation plan.

### Parsers — `ambermeta/legacy_extractors/`

- **CORE-P1 [HIGH] Truncated-octahedron box volume** (`prmtop.py` ~419-429).
  `box_angles` built as `[90, β, 90]`; volume uses α=γ=90 → ~+22% volume,
  ~−18% density for the most common AMBER box. Fix: set all three angles to the
  stored angle (`[β, β, β]`); compute volume with the triclinic formula
  (orthorhombic shortcut when β==90). Test: synthetic trunc-oct prmtop; assert
  geometric factor 0.7698 at β=109.4712°.
- **CORE-P2 [HIGH] `1-4 NB` / `1-4 EEL` dropped** (`mdout.py` ~213-214, root
  cause regex ~295 excludes spaces in keys). VDW/Elec averages systematically
  wrong. Fix: extract these two spaced keys with dedicated regexes and store
  under stable aliases used by `add_frame`. Test: `ntp_prod_0001.mdout`
  (existing) — assert VDW≈22877, Elec≈−224250.
- **CORE-P3 [MED] `nbond` undercounts** (`prmtop.py` ~373): uses `pointers[12]`
  (NBONA) only. Fix: `nbond = pointers[2] + pointers[12]` (NBONH+NBONA),
  length-guarded. Test: `CH3L1_HUMAN_6NAG.top` → 64539.
- **CORE-P4 [MED] `POINTERS` IndexError on truncated prmtop** (`prmtop.py`
  ~370-373). Guard `len(pointers)` before indexing 11/12. Also widen
  `_safe_parse`'s caught exceptions to include `LookupError` so a malformed file
  degrades gracefully instead of crashing the whole build. Test: truncated
  POINTERS fixture loads degraded, not crashing.
- **CORE-P5 [LOW] HMR detection needs `ATOMIC_NUMBER`** (`prmtop.py` ~390-411).
  See CORE-H1 (part of Bug 2).
- **CORE-P6 [LOW] `nvt` in title mislabels production** (`mdin.py` ~709-719):
  equilibration/ensemble check runs before production check. Fix: check
  explicit `prod`/`production` cue first, or require `nvt`/`npt` to co-occur
  with `equil`. Test: title "Production NVT run" → production.
- **CORE-P7 [LOW] Charge/mass tokens silently dropped** (`prmtop.py` ~376-388):
  partial CHARGE/MASS sums reported with full confidence. Fix: when the valid
  token count != natom, emit a warning and flag the neutrality verdict as
  uncertain. Test: truncated CHARGE fixture emits warning.
- **CORE-P8 [LOW] Tiny-system inpcrd misclassification** (`inpcrd.py`
  ~153-194): natoms≤2 coords+box misread as velocities. Fix: validate the last
  line's fixed-width box columns before assuming velocities/box. Low priority;
  guard only. Test: natoms=2 coords+box fixture.

### Protocol / discovery — `ambermeta/protocol.py`

- **CORE-D1 [MED] Reported Bug 1 — sequence collapse.** Root cause lives in
  `cli.py` (`_normalize_stage_stem`); see CORE-C1. The engine's
  `smart_group_files` already keeps sequences as separate stems — this fix
  routes `init` through it.
- **CORE-D2 [MED] Lexicographic stage ordering** (~1494, `sorted(grouped.items())`).
  `prod_2` sorts after `prod_10`, so `_check_continuity` pairs wrong neighbors.
  Fix: order stems with a natural/numeric sort (reuse `detect_numeric_sequences`
  ordering). Test: stems `prod_1..prod_10` (unpadded) enter chronologically.
- **CORE-D3 [MED] `hmr_prmtop` ignored in discovery branch** (~1580-1595): only
  the manifest branch applies it. Fix via Change 3 (shared helper). Test:
  `auto_discover(dir, hmr_prmtop=...)` with `manifest=None` applies HMR topology.
- **CORE-D4 [MED] Missing global/HMR prmtop skipped silently** (guards at
  ~1451/1583, and `_safe_parse(..., stage=None)`): even under `--strict`. Fix:
  warn (graceful) / raise (strict) when a requested topology path is
  missing/unparseable. Test: nonexistent `--prmtop` warns; under `--strict`
  exits non-zero.
- **CORE-D5 [LOW] HMR threshold inconsistency** (~694 uses dt≥0.003, ~1471 uses
  dt≥0.004). Fix: single shared constant (Change 3). Test: a 3.5 fs stage is
  treated consistently by inference and topology selection.
- **CORE-D6 [LOW] `auto_detect_restart_chain` not recursive** (~1228-1243): flat
  `os.listdir` even when discovery is recursive. Fix: thread `recursive` through;
  use `os.walk` when set. Test: restart in subdir is found under recursive.
- **CORE-D7 [LOW] `detect_numeric_sequences` requires 2+ digits** (~1067/1070,
  `\d{2,}`): unpadded single-digit runs (`prod_1`,`prod_2`) undetected. Fix:
  allow `\d+` with a guard against version-like over-matching. Test: `prod_1..3`
  detected as a sequence.

### Bug 2 (HMR) — spans parser + protocol + CLI

- **CORE-H1 — Robust HMR detection** (`prmtop.py`): when `ATOMIC_NUMBER` is
  absent, identify hydrogens via `ATOM_NAME`/`AMBER_ATOM_TYPE` (name/type
  starting with H) before giving up; record the detection method on the
  metadata. Test: HMR prmtop without `ATOMIC_NUMBER` → `hmr_active=True`.
- **CORE-H2 — Shared timestep threshold constant** (resolves CORE-D5).
- **CORE-H3 — Apply HMR in both branches** (resolves CORE-D3 via Change 3).
- **CORE-H4 — `init --auto` topology awareness** (`cli.py`): when ≥2 topologies
  are discovered, parse each and use `hmr_active` to assign the non-HMR one as
  `global_prmtop` and the HMR one as `hmr_prmtop`; deterministic (sorted);
  warn when the split is ambiguous (0 or ≥2 candidates of a kind). Test: a
  folder with `system.prmtop` + `system.hmr.prmtop` produces both keys correctly.

### CLI — `ambermeta/cli.py`

- **CORE-C1 [MED] Reported Bug 1 fix.** Remove `_normalize_stage_stem` /
  `_build_stage_candidates`; build candidates from `smart_group_files`
  (one stage per file group, all roles identical). Preserve relative paths and
  apply CORE-D2 ordering. Test: 5 `ntp_prod_000X` groups → 5 stages, each with
  its own mdin/mdout/rst (this is the user-reported scenario).
- **CORE-C2 [MED] `*prmtop*`-substring misclassification** (~177, ~802-811): a
  file merely named `*prmtop*` with a non-topology extension is bucketed as
  prmtop (and dropped from mdin/mdout). Fix: check specific extensions before
  the substring fallback; gate the substring on the extension not matching a
  more specific kind. Test: `gen_prmtop.in` classified as mdin.
- **CORE-C3 [MED] Nondeterministic prmtop pick** (~886/918/1022, also
  1083/1155): `discovered['prmtop'][0]` over unsorted `os.walk` order. Fix:
  sort; warn when multiple topologies exist (ties into CORE-H4). Test:
  deterministic selection across runs.
- **CORE-C4 [MED] `--quiet` doesn't suppress stdout** (only raises log level,
  ~1823). Fix: route user-facing `print()` through a helper gated on
  `args.quiet` (errors still print). Test: `-q plan …` prints nothing on success.
- **CORE-C5 [MED] `--pattern` no-op outside `--recursive`** (~1250, manifest
  branch). Decision: a manifest/interactive run lists files explicitly, so
  pattern-filtering there is out of scope; instead emit a clear warning that
  `--pattern` applies only to `--recursive` discovery (no silent ignore). Test:
  `--pattern` with `--manifest` emits the warning.
- **CORE-C6 [MED] `settings.strict_validation` dead via CLI** (~1281;
  `protocol.py` ~1849-1853): `store_true` is never `None`, always overriding the
  manifest. Fix: default the flag to `None` (`store_const`/`default=None`) so the
  manifest setting applies when the flag is absent. Test: manifest setting
  honored when flag omitted.
- **CORE-C7 [LOW] Empty manifest false success** (`init` ~863-899; `plan`
  ~1276-1287): `init` reports "Created" with zero stages; `plan` exits 0 on an
  empty/all-dropped manifest. Fix: warn + non-zero exit when zero stages result.
  Test: prmtop-only folder; empty manifest.
- **CORE-C8 [LOW] CSV round-trip** — resolved by Change 1 (canonical writer
  emits `name` header; tolerant reader accepts `stage`). Test: `init --format
  csv` → `load_manifest` round-trips all stages and fields.
- **CORE-C9 [LOW] zsh completion missing `tui` branch** (~683-702). Fix: add
  `tui)` → `*:path:_files`. (Completion only; harmless even though TUI is being
  redesigned, keeps the script self-consistent.)

### GUI security — `ambermeta/gui/server.py`

- **CORE-G1 [HIGH] Path traversal in SPA fallback** (~98-105): `static_path /
  path` served via `FileResponse` with no containment check; `%2e%2e`/`%2f`
  escapes the static dir. Fix: resolve and verify the candidate is within
  `static_path.resolve()`; reject `..`/absolute components; otherwise serve
  `index.html`. Test: encoded-traversal request does not read outside static dir.

---

## Testing & fixtures

Existing data reused: `ntp_prod_000X.*` (sequence + CORE-P2), `CH3L1_HUMAN_6NAG.top`
(CORE-P3).

New minimal synthetic fixtures (generated, documented):
- Truncated-octahedron prmtop with `BOX_DIMENSIONS` β≈109.4712° (CORE-P1).
- HMR prmtop with elevated H masses, **without** `ATOMIC_NUMBER` (CORE-H1) and a
  matching normal prmtop (CORE-H4).
- Truncated `POINTERS` prmtop (CORE-P4) and truncated `CHARGE` prmtop (CORE-P7).
- A two-topology discovery folder (normal + `.hmr.`) for CORE-H4/CORE-C3.

Cross-cutting tests:
- Manifest round-trip for **every** format (yaml/json/toml/csv): write canonical
  → read tolerant → identical stages/fields.
- Tolerant reader accepts legacy `stage`/`role`/flat-gap inputs.
- `init --auto` on the reported numbered-sequence folder → N stages, no files lost.

CI: keep `cli-docs-sync` and `gui-static-check` green; sync docs/completions for
any flag-default changes (CORE-C6).

## Backward compatibility

- Public API (`auto_discover`, `load_manifest`, `load_protocol_from_manifest`,
  `ProtocolBuilder`, parser classes) unchanged in signature; `manifest.py`
  symbols re-exported.
- Manifests previously written by **any** interface still load (tolerant reader).
- Newly written manifests use the canonical schema; the canonical CSV header
  changes from `stage` to `name` (the old header was unreadable anyway).

## Risks

- HMR fallback heuristics (name/type/mass) can have false positives on exotic
  topologies → always record the detection method and keep `ATOMIC_NUMBER` as
  the authoritative source when present.
- Numeric/natural sort must not reorder genuinely non-sequence stages → only
  reorder within detected sequences; otherwise preserve stable order.

## Acceptance criteria

1. Both reported bugs fixed with regression tests (numbered sequences preserved;
   HMR vs normal distinguished, incl. missing `ATOMIC_NUMBER`).
2. All A-scope catalog items fixed, each with a test.
3. Every manifest format round-trips; tolerant reader covered.
4. GUI path traversal closed with a test.
5. No silent wrong/empty output on the covered paths (warning or non-zero exit).
6. Full suite green; docs/completions synced.
