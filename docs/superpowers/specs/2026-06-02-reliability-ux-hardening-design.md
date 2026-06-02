# Reliability & UX Hardening — Design

**Date:** 2026-06-02
**Status:** Approved (brainstorm)
**Scope:** Spec 1 of 2. Spec 2 ("FAIR metadata layer", GROMACS-MetaDump-inspired) is deferred and built on this base.

## Problem

`ambermeta plan` — the primary command — aborts the entire run with a Python
traceback when it hits a single missing, malformed, or permission-denied input
file. The parse loops call `Parser(path).parse()` with no exception handling at
three sites:

- manifest parse loop (`protocol.py:943-957`)
- discovery parse loop (`protocol.py:1465-1474`)
- `auto_discover`

By contrast, `validate` and `info` already isolate per-file errors. Discovery
also crashes when `os.listdir` hits a permission-denied base directory, and
`os.walk` silently swallows inaccessible subdirectories (invisible failure).

A prior 40-bug audit landed in `e4b84a9`; a follow-up audit surfaced additional
leads, ~50% of which were false positives or overstated on inspection. Only
re-verified findings are in scope here.

## Goals

1. A single missing/faulty/unreadable input file must **not** crash `plan`.
2. Failures must be **visible** (recorded, summarized) — never silently swallowed.
3. No raw Python tracebacks reach stdout for expected error conditions.
4. Fix only **re-verified** bugs.
5. Keep all 43 existing tests green; add tests proving isolation.

## Non-goals (deferred to Spec 2)

FAIR metadata schema, JSON-Schema validation of output, annotation overlay,
provenance-per-field tagging, archive (`.zip`/`.tar.gz`) input.

## Design

### 1. Error model

A lightweight dataclass flowing parser → stage → protocol → output:

```python
@dataclass
class FileLoadError:
    kind: str         # "prmtop" | "mdin" | "mdout" | "mdcrd" | "inpcrd"
    path: str
    error_type: str   # "missing" | "permission" | "decode" | "malformed"
    message: str
```

- `SimulationStage` gains `load_errors: List[FileLoadError]` and a `degraded`
  property (`True` when `load_errors` is non-empty).
- `SimulationProtocol` aggregates `load_errors` across stages so summary,
  methods-summary, CSV, and the CLI report the same truth.

Distinction from existing `warnings`: *warnings* = "parsed but suspicious";
*load_errors* = "this file could not be parsed at all."

### 2. Per-file isolation (core fix)

One helper replaces every bare parse call:

```python
def _safe_parse(parser_cls, path, kind, stage, *, strict):
    try:
        return parser_cls(path).parse()
    except (FileNotFoundError, PermissionError, OSError,
            UnicodeDecodeError, ValueError) as e:
        if strict:
            raise AmberMetaError(f"Failed to parse {kind} '{path}': {e}") from e
        stage.load_errors.append(FileLoadError(kind, path, _classify(e), str(e)))
        return None
```

`_classify(e)` maps exception type → `error_type`. Applied at all three
unprotected sites. A failed file becomes `None`; the stage retains every file
that did parse; continuity checks run on available data.

### 3. Discovery robustness

- Wrap `os.listdir(base_dir)` in try/except `PermissionError` → record-and-skip.
- Pass `onerror` callback to `os.walk` → record inaccessible subdirectories as
  protocol-level warnings instead of silently skipping them.

### 4. `--strict` flag + exit codes

- New `--strict` flag on `plan`, honored by both manifest and discovery paths.
  Default off (graceful degrade).
- Exit codes:
  - `0` — clean, **including** degraded-with-warnings (graceful is the default contract).
  - `1` — strict-mode abort, or unrecoverable error.
- Optional future `--fail-on-skip` (treat skips as CI failures) — noted, not built.

### 5. Top-level guard

`main()` wraps command dispatch:

- `AmberMetaError` → clean one-line message to stderr, exit 1.
- Any unexpected `Exception` → `"Unexpected error (<type>). Re-run with
  --log-level DEBUG for details."` to stderr; full traceback to the log; exit 1.

`AmberMetaError` is a new base exception in the package.

### 6. Verified bug fixes (verify-then-fix)

Each lead is re-confirmed against current code before any change. Fix only those
that hold:

| Lead | Location | Claim |
|---|---|---|
| TOML escaping | `cli.py:946` | escapes only `"`, not `\` → Windows paths produce unparseable TOML |
| Exact-zero float gap | `protocol.py:426` | `gap != 0` should use a tolerance like the sibling check |
| inpcrd tail-seek | `inpcrd.py:206` | hardcoded 100-byte seek vs CRLF may truncate box line |
| Single-frame div-by-zero | `mdout.py:545` | `curr_int == 0` masks/​breaks gap detection |
| `_calc_stats` 0.0-as-missing | `utils.py` | callers using `if mean:` drop legitimate `0.0` |

Report which were real; leave false positives untouched (e.g. the `int(seq_idx)`
"crash" — unreachable default — and the "Windows role inference" claim —
already normalized at `protocol.py:1078`).

### 7. Testing

New fixtures and tests proving isolation:

- garbage binary file, zero-byte file, missing path, permission-denied
  (monkeypatched to raise `PermissionError`, not real `chmod` — deterministic on
  Windows).
- Assertions: `plan` completes; offending stage is `degraded`; error recorded;
  exit `0`. `--strict` aborts cleanly with exit `1` and no traceback.
- Top-level guard test: unexpected exception → no traceback on stdout, exit 1.
- All 43 existing tests remain green.

## Files touched (anticipated)

- `ambermeta/protocol.py` — error model, `_safe_parse`, discovery guards, gap fix
- `ambermeta/cli.py` — `--strict`, exit codes, top-level guard, TOML fix
- `ambermeta/__init__.py` — export `AmberMetaError`, `FileLoadError`
- `ambermeta/utils.py` — `_calc_stats` callers
- `ambermeta/legacy_extractors/inpcrd.py`, `mdout.py` — verified fixes
- `tests/` — new robustness tests + fixtures
