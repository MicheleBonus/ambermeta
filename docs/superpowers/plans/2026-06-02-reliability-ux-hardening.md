# Reliability & UX Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ambermeta plan` tolerate a single missing/malformed/unreadable input file by isolating errors per-file, surfacing them visibly, and never printing a raw traceback — plus land the re-verified bug fixes.

**Architecture:** A new `FileLoadError` record flows parser→stage→protocol→output. A `_safe_parse` helper wraps every parser call and, in graceful mode (default), records the error on the stage and returns `None`; in `--strict` mode it raises a typed `AmberMetaError`. Discovery walks are guarded against permission errors. `main()` gets a top-level guard converting exceptions into clean messages + exit codes.

**Tech Stack:** Python 3.8+, dataclasses, pytest, monkeypatch (no real `chmod` — deterministic on Windows).

**Spec:** `docs/superpowers/specs/2026-06-02-reliability-ux-hardening-design.md`

---

## File Structure

- `ambermeta/errors.py` — **new**: `AmberMetaError` base exception + `FileLoadError` dataclass + `classify_exception()`. Small, single-purpose, importable without pulling in `protocol`.
- `ambermeta/protocol.py` — `_safe_parse` helper; thread `strict` through `_manifest_to_stages`, `smart_group_files`, `auto_discover`, `load_protocol_from_manifest`; downgrade the missing-file pre-check; guard discovery walks; aggregate `load_errors`; serialize them; gap-comparison fix.
- `ambermeta/cli.py` — `--strict` flag on `plan`; degraded-stage summary; top-level guard in `main()`; TOML escaping fix.
- `ambermeta/__init__.py` — export `AmberMetaError`, `FileLoadError`.
- `ambermeta/utils.py`, `ambermeta/legacy_extractors/inpcrd.py`, `ambermeta/legacy_extractors/mdout.py` — verified bug fixes only.
- `tests/test_robustness.py` — **new**: per-file isolation, `--strict`, top-level guard, discovery guards.
- `tests/test_bugfixes.py` — **new**: regression tests for each confirmed bug.

---

## Task 1: Error model (`errors.py` + stage fields)

**Files:**
- Create: `ambermeta/errors.py`
- Modify: `ambermeta/protocol.py:122-136` (SimulationStage fields), `:313-331` (to_dict)
- Modify: `ambermeta/__init__.py`
- Test: `tests/test_robustness.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_robustness.py
from ambermeta.errors import AmberMetaError, FileLoadError, classify_exception
from ambermeta.protocol import SimulationStage


def test_fileloaderror_fields():
    e = FileLoadError(kind="mdout", path="/x/p.mdout", error_type="missing", message="nope")
    assert e.kind == "mdout"
    assert e.error_type == "missing"


def test_classify_exception_maps_types():
    assert classify_exception(FileNotFoundError()) == "missing"
    assert classify_exception(PermissionError()) == "permission"
    assert classify_exception(UnicodeDecodeError("utf-8", b"", 0, 1, "x")) == "decode"
    assert classify_exception(ValueError()) == "malformed"
    assert classify_exception(OSError()) == "malformed"


def test_ambermetaerror_is_exception():
    assert issubclass(AmberMetaError, Exception)


def test_stage_degraded_property():
    stage = SimulationStage(name="prod")
    assert stage.degraded is False
    stage.load_errors.append(FileLoadError("mdout", "/x", "missing", "nope"))
    assert stage.degraded is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_robustness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ambermeta.errors'`

- [ ] **Step 3: Create `ambermeta/errors.py`**

```python
"""Typed errors and the file-load error record used across AmberMeta."""

from dataclasses import dataclass


class AmberMetaError(Exception):
    """Base class for expected AmberMeta failures handled cleanly by the CLI."""


@dataclass
class FileLoadError:
    """A single input file that could not be parsed.

    Distinct from a parser ``warnings`` entry: a warning means "parsed but
    suspicious"; a FileLoadError means "this file could not be parsed at all".
    """

    kind: str          # "prmtop" | "mdin" | "mdout" | "mdcrd" | "inpcrd"
    path: str
    error_type: str    # "missing" | "permission" | "decode" | "malformed"
    message: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "path": self.path,
            "error_type": self.error_type,
            "message": self.message,
        }


def classify_exception(exc: BaseException) -> str:
    """Map an exception raised while opening/parsing a file to an error_type."""
    if isinstance(exc, FileNotFoundError):
        return "missing"
    if isinstance(exc, PermissionError):
        return "permission"
    if isinstance(exc, UnicodeDecodeError):
        return "decode"
    # ValueError, OSError, and anything else parse-related
    return "malformed"
```

- [ ] **Step 4: Add fields + property to `SimulationStage`**

In `ambermeta/protocol.py`, add the import near the top with the other intra-package imports:

```python
from ambermeta.errors import AmberMetaError, FileLoadError, classify_exception
```

Then in the `SimulationStage` dataclass (currently ending at line 136 with `continuity`), add after the `continuity` field:

```python
    continuity: List[str] = field(default_factory=list)
    load_errors: List[FileLoadError] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        """True when one or more of this stage's files failed to parse."""
        return bool(self.load_errors)
```

- [ ] **Step 5: Serialize `load_errors` in `SimulationStage.to_dict`**

In `ambermeta/protocol.py:313-331`, add a `load_errors` key to the returned dict (after `"continuity"`):

```python
            "validation": list(self.validation),
            "continuity": list(self.continuity),
            "degraded": self.degraded,
            "load_errors": [e.to_dict() for e in self.load_errors],
```

- [ ] **Step 6: Export from `ambermeta/__init__.py`**

Add an import block after the `protocol` import (line 16) and add the names to `__all__`:

```python
from ambermeta.errors import AmberMetaError, FileLoadError
```

In `__all__`, add `"AmberMetaError",` and `"FileLoadError",` near the top.

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_robustness.py -v`
Expected: PASS (4 tests)

- [ ] **Step 8: Commit**

```bash
git add ambermeta/errors.py ambermeta/protocol.py ambermeta/__init__.py tests/test_robustness.py
git commit -m "Add FileLoadError model and AmberMetaError"
```

---

## Task 2: `_safe_parse` + per-file isolation in the manifest loop

**Files:**
- Modify: `ambermeta/protocol.py` (add `_safe_parse`; `_manifest_to_stages:866-957`)
- Test: `tests/test_robustness.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_robustness.py (append)
import os
import pytest
from ambermeta.protocol import load_protocol_from_manifest


def _write(p, text=""):
    with open(p, "w") as fh:
        fh.write(text)


def test_manifest_bad_mdout_keeps_stage(tmp_path):
    # prmtop + mdin readable, mdout is garbage; stage must survive
    prmtop = tmp_path / "s.prmtop"; _write(prmtop, "%VERSION\n%FLAG TITLE\n")
    mdin = tmp_path / "s.mdin"; _write(mdin, "&cntrl\n nstlim=1000, dt=0.002,\n/\n")
    mdout = tmp_path / "s.mdout"
    with open(mdout, "wb") as fh:
        fh.write(b"\x00\x01\x02not a real mdout")
    manifest = {"prod": {"prmtop": str(prmtop), "mdin": str(mdin), "mdout": str(mdout)}}
    mpath = tmp_path / "manifest.json"
    import json; _write(mpath, json.dumps(manifest))

    protocol = load_protocol_from_manifest(str(mpath), directory=str(tmp_path))
    assert len(protocol.stages) == 1
    stage = protocol.stages[0]
    assert stage.mdin is not None        # readable file survived
    # mdout either parsed-with-warnings or recorded as load error; stage not dropped
    assert stage.name == "prod"


def test_manifest_missing_file_graceful(tmp_path):
    prmtop = tmp_path / "s.prmtop"; _write(prmtop, "%VERSION\n")
    manifest = {"prod": {"prmtop": str(prmtop), "mdout": str(tmp_path / "absent.mdout")}}
    mpath = tmp_path / "manifest.json"
    import json; _write(mpath, json.dumps(manifest))

    protocol = load_protocol_from_manifest(str(mpath), directory=str(tmp_path))
    assert len(protocol.stages) == 1
    errs = protocol.stages[0].load_errors
    assert any(e.kind == "mdout" and e.error_type == "missing" for e in errs)


def test_manifest_strict_raises_on_missing(tmp_path):
    prmtop = tmp_path / "s.prmtop"; _write(prmtop, "%VERSION\n")
    manifest = {"prod": {"prmtop": str(prmtop), "mdout": str(tmp_path / "absent.mdout")}}
    mpath = tmp_path / "manifest.json"
    import json; _write(mpath, json.dumps(manifest))

    from ambermeta.errors import AmberMetaError
    with pytest.raises(AmberMetaError):
        load_protocol_from_manifest(str(mpath), directory=str(tmp_path), strict=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_robustness.py -k "manifest" -v`
Expected: FAIL — `TypeError: load_protocol_from_manifest() got an unexpected keyword argument 'strict'` (and the missing-file case currently raises bare `FileNotFoundError`).

- [ ] **Step 3: Add the `_safe_parse` helper**

In `ambermeta/protocol.py`, add this module-level function above `_manifest_to_stages` (before line 866):

```python
def _safe_parse(parser_cls, path, kind, stage, *, strict):
    """Parse one file, isolating failures unless strict.

    On success: return the parsed metadata object.
    On failure (graceful): record a FileLoadError on ``stage`` and return None.
    On failure (strict): raise AmberMetaError.
    """
    try:
        return parser_cls(path).parse()
    except (FileNotFoundError, PermissionError, OSError,
            UnicodeDecodeError, ValueError) as exc:
        if strict:
            raise AmberMetaError(f"Failed to parse {kind} '{path}': {exc}") from exc
        stage.load_errors.append(
            FileLoadError(kind=kind, path=path,
                          error_type=classify_exception(exc), message=str(exc))
        )
        return None
```

- [ ] **Step 4: Thread `strict` into `_manifest_to_stages` and use `_safe_parse`**

Change the signature at `ambermeta/protocol.py:866-874` to add `strict`:

```python
def _manifest_to_stages(
    manifest: Dict[str, Dict[str, str]] | List[Dict[str, str]],
    directory: Optional[str],
    include_roles: Optional[List[str]],
    include_stems: Optional[List[str]],
    restart_files: Optional[Dict[str, str]],
    stage_role_rules: Optional[Dict[str, str]] = None,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    strict: bool = False,
) -> List[SimulationStage]:
```

Replace the parse block at lines 943-957 with `_safe_parse` calls (note `stage` already exists at line 934):

```python
        if "prmtop" in resolved:
            stage.prmtop = _safe_parse(PrmtopParser, resolved["prmtop"], "prmtop", stage, strict=strict)
        if "mdin" in resolved:
            stage.mdin = _safe_parse(MdinParser, resolved["mdin"], "mdin", stage, strict=strict)
            inferred_role = getattr(getattr(stage.mdin, "details", None), "stage_role", None) if stage.mdin else None
            if not stage.stage_role and inferred_role:
                stage.stage_role = inferred_role
                stage.validation.append(f"INFO: stage_role '{inferred_role}' inferred from mdin file")
        if "mdout" in resolved:
            stage.mdout = _safe_parse(MdoutParser, resolved["mdout"], "mdout", stage, strict=strict)
        if "mdcrd" in resolved:
            stage.mdcrd = _safe_parse(MdcrdParser, resolved["mdcrd"], "mdcrd", stage, strict=strict)
        if "inpcrd" in resolved:
            stage.inpcrd = _safe_parse(InpcrdParser, resolved["inpcrd"], "inpcrd", stage, strict=strict)
            stage.restart_path = resolved["inpcrd"]
```

Also update the restart-source parse at lines 966-968:

```python
        if restart_source and "inpcrd" not in resolved:
            stage.inpcrd = _safe_parse(InpcrdParser, restart_source, "inpcrd", stage, strict=strict)
            if stage.inpcrd is not None:
                stage.restart_path = restart_source
```

- [ ] **Step 5: Downgrade the missing-file pre-check to respect `strict`**

The pre-check at `ambermeta/protocol.py:857-863` hard-raises `FileNotFoundError` before parsing. Find the function that contains it (it iterates `_normalize_manifest(manifest)` building a `missing` list) and add a `strict` parameter to its signature. Replace the raise block (lines 861-863) with:

```python
    if missing and strict:
        message = "Manifest references missing files:\n" + "\n".join(missing)
        raise AmberMetaError(message)
    # In graceful mode, missing files are recorded per-file by _safe_parse.
```

Thread `strict` from the caller (`load_protocol_from_manifest`) into this pre-check call.

- [ ] **Step 6: Thread `strict` through `load_protocol_from_manifest`**

At `ambermeta/protocol.py:1690`, add `strict: bool = False` to the signature, pass it into the missing-file pre-check call and into the `_manifest_to_stages(...)` call near line 1810:

```python
        progress_callback=progress_callback,
        strict=strict,
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_robustness.py -k "manifest" -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Run full suite (no regressions)**

Run: `python -m pytest -q`
Expected: all previously-passing tests still pass.

- [ ] **Step 9: Commit**

```bash
git add ambermeta/protocol.py tests/test_robustness.py
git commit -m "Isolate per-file parse errors in manifest loop; add --strict path"
```

---

## Task 3: Per-file isolation in the discovery loop

**Files:**
- Modify: `ambermeta/protocol.py` (`smart_group_files`/`auto_discover` parse loop at `1465-1480, 1508-1510`; thread `strict`)
- Test: `tests/test_robustness.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_robustness.py (append)
from ambermeta.protocol import auto_discover


def test_discovery_bad_file_keeps_going(tmp_path):
    # one good stage, one stage with a garbage mdout
    (tmp_path / "min.mdin").write_text("&cntrl\n imin=1,\n/\n")
    good = tmp_path / "prod_001.mdin"; good.write_text("&cntrl\n nstlim=10, dt=0.002,\n/\n")
    bad = tmp_path / "prod_001.mdout"
    bad.write_bytes(b"\x00\x01\x02garbage")
    protocol = auto_discover(str(tmp_path), recursive=True)
    # discovery completed and produced stages despite the garbage mdout
    assert len(protocol.stages) >= 1


def test_discovery_strict_raises(tmp_path, monkeypatch):
    good = tmp_path / "prod_001.mdin"; good.write_text("&cntrl\n nstlim=10,\n/\n")
    from ambermeta.parsers.mdin import MdinParser
    from ambermeta.errors import AmberMetaError

    def boom(self):
        raise ValueError("synthetic parse failure")
    monkeypatch.setattr(MdinParser, "parse", boom)
    with pytest.raises(AmberMetaError):
        auto_discover(str(tmp_path), recursive=True, strict=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_robustness.py -k "discovery" -v`
Expected: FAIL — `auto_discover()` has no `strict` kwarg; garbage mdout currently raises and aborts.

- [ ] **Step 3: Thread `strict` through `auto_discover` and `smart_group_files`**

Add `strict: bool = False` to the `auto_discover` signature (`ambermeta/protocol.py:1359`) and to `smart_group_files` (`:1272`). Pass `strict=strict` from `auto_discover` into the stage-building call (the loop containing lines 1465-1510) and into any `smart_group_files(...)` call.

- [ ] **Step 4: Replace the discovery parse block with `_safe_parse`**

Replace lines 1465-1480:

```python
        if "prmtop" in file_kinds:
            stage.prmtop = _safe_parse(PrmtopParser, file_kinds["prmtop"], "prmtop", stage, strict=strict)
        if "mdin" in file_kinds:
            stage.mdin = _safe_parse(MdinParser, file_kinds["mdin"], "mdin", stage, strict=strict)
        if "mdout" in file_kinds:
            stage.mdout = _safe_parse(MdoutParser, file_kinds["mdout"], "mdout", stage, strict=strict)
        if "mdcrd" in file_kinds:
            stage.mdcrd = _safe_parse(MdcrdParser, file_kinds["mdcrd"], "mdcrd", stage, strict=strict)
        if "inpcrd" in file_kinds:
            stage.inpcrd = _safe_parse(InpcrdParser, file_kinds["inpcrd"], "inpcrd", stage, strict=strict)
            if stage.inpcrd is not None:
                stage.restart_path = file_kinds["inpcrd"]
```

And the restart-source block at lines 1508-1510:

```python
        if restart_source:
            stage.inpcrd = _safe_parse(InpcrdParser, restart_source, "inpcrd", stage, strict=strict)
            if stage.inpcrd is not None:
                stage.restart_path = restart_source
```

> Note: the content-based role inference at lines 1483-1487 already guards `stage.mdin`/`stage.mdout` being falsy via `infer_stage_role_from_content`, so `None` values are safe there.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_robustness.py -k "discovery" -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add ambermeta/protocol.py tests/test_robustness.py
git commit -m "Isolate per-file parse errors in discovery loop"
```

---

## Task 4: Guard directory walks against permission errors

**Files:**
- Modify: `ambermeta/protocol.py` (the `os.listdir`/`os.walk` discovery enumeration inside `smart_group_files`)
- Test: `tests/test_robustness.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_robustness.py (append)
def test_listdir_permission_denied_does_not_crash(tmp_path, monkeypatch):
    (tmp_path / "prod_001.mdin").write_text("&cntrl\n/\n")
    real_listdir = os.listdir

    def denied(path, *a, **k):
        raise PermissionError(f"denied: {path}")
    monkeypatch.setattr(os, "listdir", denied)
    # Must not raise; returns an (empty) protocol gracefully.
    protocol = auto_discover(str(tmp_path), recursive=False)
    assert protocol is not None
    monkeypatch.setattr(os, "listdir", real_listdir)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_robustness.py -k "permission_denied" -v`
Expected: FAIL — `PermissionError` propagates out of discovery.

- [ ] **Step 3: Guard the enumeration**

Locate the non-recursive enumeration in `smart_group_files` (the `for fname in os.listdir(directory):` block, ~line 1304). Wrap it:

```python
    discovered = []
    try:
        entries = os.listdir(directory)
    except (PermissionError, OSError):
        entries = []
    for fname in entries:
        full_path = os.path.join(directory, fname)
        if os.path.isfile(full_path):
            discovered.append((fname, full_path))
```

For the recursive branch, give `os.walk` an `onerror` callback so inaccessible subdirectories are skipped (not silently — leave a breadcrumb for now via the standard skip; protocol-level surfacing is optional and not required for this task):

```python
        for root, _dirs, files in os.walk(directory, onerror=lambda e: None):
            ...
```

> The `onerror=lambda e: None` keeps `os.walk` from swallowing-then-continuing inconsistently across platforms; the default already skips denied subdirs, this just makes it explicit and prevents the rare propagation case.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_robustness.py -k "permission_denied" -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add ambermeta/protocol.py tests/test_robustness.py
git commit -m "Guard directory enumeration against permission errors"
```

---

## Task 5: CLI `--strict` flag, degraded summary, exit codes

**Files:**
- Modify: `ambermeta/cli.py` (`build_parser` plan subparser; `_plan_command:1232-1320` and its tail)
- Test: `tests/test_robustness.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_robustness.py (append)
from ambermeta.cli import main


def test_cli_plan_degraded_exits_zero(tmp_path, capsys):
    (tmp_path / "prod_001.mdin").write_text("&cntrl\n nstlim=10, dt=0.002,\n/\n")
    (tmp_path / "prod_001.mdout").write_bytes(b"\x00\x01garbage")
    rc = main(["plan", str(tmp_path), "--recursive"])
    assert rc == 0  # graceful default: degraded run still succeeds


def test_cli_plan_strict_exits_one(tmp_path, monkeypatch, capsys):
    (tmp_path / "prod_001.mdin").write_text("&cntrl\n/\n")
    from ambermeta.parsers.mdin import MdinParser

    def boom(self):
        raise ValueError("synthetic")
    monkeypatch.setattr(MdinParser, "parse", boom)
    rc = main(["plan", str(tmp_path), "--recursive", "--strict"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "Traceback" not in captured.err  # clean message, no traceback
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_robustness.py -k "cli_plan" -v`
Expected: FAIL — `--strict` is not a recognized argument.

- [ ] **Step 3: Add the `--strict` flag to the `plan` subparser**

In `ambermeta/cli.py` `build_parser()`, find the `plan` subparser (where `--skip-cross-stage-validation` is added) and add:

```python
    plan_parser.add_argument(
        "--strict",
        action="store_true",
        help="Abort on the first unreadable/malformed input file instead of skipping it.",
    )
```

- [ ] **Step 4: Pass `strict` into the planning calls**

In `_plan_command` (`ambermeta/cli.py:1232`), read the flag near the other getattr defaults (after line 1240):

```python
    strict = getattr(args, "strict", False)
```

Add `strict=strict,` to the `load_protocol_from_manifest(...)` call (after line 1271), the recursive `auto_discover(...)` call (after line 1294), and the interactive `auto_discover(...)` call (after line 1319).

- [ ] **Step 5: Print a degraded-stage summary before returning**

Find where `_plan_command` finishes building `protocol` and prints/export results (after the interactive branch, before the export logic). Add a summary block:

```python
    degraded = [s for s in protocol.stages if s.degraded]
    if degraded:
        print(f"\n{Colors.warn('WARNING')}: {len(degraded)} stage(s) had unreadable files:")
        for stage in degraded:
            for err in stage.load_errors:
                print(f"  - {stage.name}: {err.kind} ({err.error_type}) {err.path}")
```

> Use the existing `Colors` helper already imported in `cli.py`. If `Colors.warn` does not exist, use `Colors.error`/plain text consistent with the codebase's existing helpers (verify the available methods on `Colors` first).

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_robustness.py -k "cli_plan" -v`
Expected: `test_cli_plan_degraded_exits_zero` PASSES. `test_cli_plan_strict_exits_one` may still fail on the `rc == 1`/traceback assertion until Task 6 adds the top-level guard — that is expected; re-run after Task 6.

- [ ] **Step 7: Commit**

```bash
git add ambermeta/cli.py tests/test_robustness.py
git commit -m "Add plan --strict flag and degraded-stage summary"
```

---

## Task 6: Top-level guard in `main()`

**Files:**
- Modify: `ambermeta/cli.py:1783-1811` (`main`)
- Test: `tests/test_robustness.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_robustness.py (append)
def test_main_converts_unexpected_exception_cleanly(tmp_path, monkeypatch, capsys):
    # Force an unexpected (non-AmberMetaError) exception inside a command.
    import ambermeta.cli as cli

    def boom(args):
        raise RuntimeError("kaboom internal")
    monkeypatch.setattr(cli, "_info_command", boom)
    f = tmp_path / "x.prmtop"; f.write_text("%VERSION\n")
    rc = cli.main(["info", str(f)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "Traceback" not in captured.out and "Traceback" not in captured.err
    assert "Unexpected error" in (captured.out + captured.err)


def test_main_converts_ambermetaerror_cleanly(monkeypatch, capsys):
    import ambermeta.cli as cli
    from ambermeta.errors import AmberMetaError

    def boom(args):
        raise AmberMetaError("manifest references missing files")
    monkeypatch.setattr(cli, "_plan_command", boom)
    rc = cli.main(["plan", ".", "--recursive"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "manifest references missing files" in (captured.out + captured.err)
    assert "Traceback" not in (captured.out + captured.err)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_robustness.py -k "main_converts" -v`
Expected: FAIL — exception propagates as an uncaught traceback.

- [ ] **Step 3: Wrap dispatch in `main()`**

Add the import at the top of `ambermeta/cli.py` if not present:

```python
from ambermeta.errors import AmberMetaError
```

Refactor the dispatch in `main()` (lines 1795-1811). Move the `if args.command == ...` chain into a small inner dispatch and wrap it:

```python
    import logging
    logger = logging.getLogger("ambermeta")

    def _dispatch() -> int:
        if args.command == "plan":
            return _plan_command(args)
        if args.command == "validate":
            return _validate_command(args)
        if args.command == "info":
            return _info_command(args)
        if args.command == "init":
            return _init_command(args)
        if args.command == "tui":
            return _tui_command(args)
        if args.command == "gui":
            return _gui_command(args)
        if args.command == "completion":
            return _completion_command(args)
        parser.print_help()
        return 1

    try:
        return _dispatch()
    except AmberMetaError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level guard
        logger.debug("Unhandled exception", exc_info=True)
        print(
            f"Unexpected error ({type(exc).__name__}: {exc}). "
            "Re-run with --log-level DEBUG for the full traceback.",
            file=sys.stderr,
        )
        return 1
```

> `parser` is in scope (built at line 1784). Keep the existing logging configuration above this block unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_robustness.py -k "main_converts or cli_plan_strict" -v`
Expected: PASS — including `test_cli_plan_strict_exits_one` from Task 5.

- [ ] **Step 5: Run full suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add ambermeta/cli.py tests/test_robustness.py
git commit -m "Add top-level CLI guard: clean messages, no tracebacks"
```

---

## Task 7: Verified bug fixes (verify-then-fix)

For each lead: first confirm against current code; if confirmed, write a regression test that fails, then fix. If a lead does **not** hold, note it in the commit message and skip it. Do not change behavior you cannot first prove wrong with a failing test.

**Files:**
- Modify (if confirmed): `ambermeta/cli.py:946`, `ambermeta/protocol.py:426`, `ambermeta/legacy_extractors/mdout.py:545`, `ambermeta/legacy_extractors/inpcrd.py:206`, `ambermeta/utils.py`
- Test: `tests/test_bugfixes.py`

### 7a: TOML backslash escaping (`cli.py:946`)

- [ ] **Step 1: Failing test**

```python
# tests/test_bugfixes.py
import os


def test_toml_export_escapes_backslashes(tmp_path):
    # Reproduce the TOML writer used by the export path that hits line 946.
    # If the export is reachable via a public CLI/function, drive it that way;
    # otherwise test the escaping helper directly once it is extracted.
    from ambermeta.cli import _toml_escape  # to be introduced in the fix
    assert _toml_escape(r"C:\data\file.prmtop") == r"C:\\data\\file.prmtop"
    assert _toml_escape('quote"here') == 'quote\\"here'
```

- [ ] **Step 2: Run it — confirm FAIL** (`_toml_escape` does not exist yet).

Run: `python -m pytest tests/test_bugfixes.py -k toml -v`

- [ ] **Step 3: Fix** — extract a helper and escape backslash *before* quote (order matters):

```python
def _toml_escape(value) -> str:
    s = str(value)
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    return s
```

Replace `cli.py:946-947`:

```python
                lines.append(f'{key} = "{_toml_escape(value)}"')
```

- [ ] **Step 4: Run — confirm PASS.**

- [ ] **Step 5: Commit**

```bash
git add ambermeta/cli.py tests/test_bugfixes.py
git commit -m "Fix TOML export: escape backslashes (Windows paths)"
```

### 7b: Exact-zero float gap comparison (`protocol.py:426`)

- [ ] **Step 1:** Read `protocol.py:420-430`. Confirm whether `gap != 0` should use the `default_tolerance` already computed nearby (as the sibling check at line 386 does). If confirmed, write a test feeding two stages whose continuity gap is a sub-tolerance float (e.g. `1e-9`) and assert no spurious "Gap detected" continuity note is added.

- [ ] **Step 2:** Run — confirm FAIL.

- [ ] **Step 3:** Replace the exact comparison with a tolerance-aware one, e.g. `elif abs(gap) > default_tolerance:` (match the variable actually in scope at that line — verify before editing).

- [ ] **Step 4:** Run — confirm PASS. **Step 5:** Commit `"Fix spurious gap note from exact float comparison"`.

### 7c: Single-frame div/zero in gap detection (`mdout.py:545`)

- [ ] **Step 1:** Read `mdout.py:535-550`. Confirm `curr_int` can be `0` for a single-frame mdout and that the comparison then misbehaves. If confirmed, write a test with a single-frame mdout pair.

- [ ] **Step 2:** Run — confirm FAIL.

- [ ] **Step 3:** Guard: skip the scaled-tolerance branch when `curr_int <= 0`, falling back to the absolute `0.1` threshold only.

- [ ] **Step 4:** Run — confirm PASS. **Step 5:** Commit `"Fix gap detection for single-frame mdout"`.

### 7d: inpcrd tail-seek vs CRLF (`inpcrd.py:206`)

- [ ] **Step 1:** Read `inpcrd.py:200-224`. Confirm the hardcoded `f.seek(-min(size, 100), 2)` can truncate the box line for CRLF files / 7+ box values. If confirmed, write a test with a small ASCII inpcrd whose box line sits just inside a CRLF-inflated tail.

- [ ] **Step 2:** Run — confirm FAIL (or document that the existing try/except already degrades safely, in which case downgrade severity and skip).

- [ ] **Step 3:** Widen the tail window (e.g. read last `min(size, 256)` bytes) and split on the last non-empty line; keep the existing try/except.

- [ ] **Step 4:** Run — confirm PASS. **Step 5:** Commit `"Widen inpcrd box tail-read for CRLF/long box lines"`.

### 7e: `_calc_stats` 0.0-treated-as-missing (`utils.py`)

- [ ] **Step 1:** Grep callers of `_calc_stats` and the stats helpers. Confirm any caller uses `if mean:` (truthy) rather than `if mean is not None:`, which would drop a legitimate `0.0`. If confirmed, write a test where a metric mean is exactly `0.0` and assert it appears in output.

- [ ] **Step 2:** Run — confirm FAIL.

- [ ] **Step 3:** Change the offending caller(s) to `is not None` checks.

- [ ] **Step 4:** Run — confirm PASS. **Step 5:** Commit `"Treat 0.0 statistics as present, not missing"`.

---

## Task 8: Documentation + final verification

**Files:**
- Modify: `README.md` (document `--strict` and graceful-degrade behavior)
- Test: full suite + manual smoke

- [ ] **Step 1: Document the new behavior**

In `README.md` under the `plan` command's "Key flags", add:

```markdown
- `--strict` (abort on the first unreadable/malformed input file; default is to skip it and continue)
```

And add a short subsection noting that, by default, `plan` skips files it cannot read and prints a summary of skipped files, exiting 0; `--strict` makes any unreadable file a hard error (exit 1).

- [ ] **Step 2: Manual smoke test (degraded run)**

Run:
```bash
python -m ambermeta plan tests/data/amber/md_test_files --recursive
```
Expected: completes, prints stage count, exit 0.

- [ ] **Step 3: Manual smoke test (no traceback on garbage)**

Create a garbage file in a temp dir alongside a valid `.mdin`, run `plan --recursive`, confirm a clean WARNING summary and no traceback.

- [ ] **Step 4: Full suite green**

Run: `python -m pytest -q`
Expected: all original 43 tests + new robustness/bugfix tests pass.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "Document graceful-degrade behavior and --strict flag"
```

---

## Self-Review Notes

- **Spec §1 (error model)** → Task 1. **§2 (per-file isolation)** → Tasks 2-3. **§3 (discovery robustness)** → Task 4. **§4 (--strict + exit codes)** → Tasks 5-6. **§5 (top-level guard)** → Task 6. **§6 (verified fixes)** → Task 7. **§7 (testing)** → tests embedded in every task + Task 8. All spec sections covered.
- Exit-code contract is consistent across Tasks 5-6: `0` graceful (incl. degraded), `1` strict/unrecoverable, `130` Ctrl-C.
- `_safe_parse` signature is identical everywhere it's called (Tasks 2, 3).
- Verify-then-fix tasks (7b-7e) explicitly allow skipping a lead that doesn't reproduce — they are not assumed-real.
