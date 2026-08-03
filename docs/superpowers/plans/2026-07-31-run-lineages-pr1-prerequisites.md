# Run Lineages PR 1 (Prerequisites) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the lineage feature a working output path and a readable CI signal, by making CI run the test suites, fixing `plan --manifest` writing zero files, and removing the v1 manifest file format.

**Architecture:** Three independent strands, ordered so each lands against a signal the previous one created. CI first (so every later commit is checked). Then the `plan` fix, which extracts one artifact writer shared by the CLI and the GUI instead of the two that exist today. Then the v1-format removal, which deletes the dispatch that caused the `plan` bug in the first place.

**Tech Stack:** Python 3.9+ (argparse CLI, dataclasses, pydantic v2 + FastAPI for the GUI API), pytest, GitHub Actions, Vitest/React for the frontend.

## Global Constraints

- **The flat engine in `ambermeta/protocol.py` is the analysis layer, not back-compat.** `SimulationProtocol`, `SimulationStage`, `auto_discover`, `_check_continuity`, `to_dict`, `to_methods_dict`, `write_stats_csv` all stay. Only the *file-reading* v1 entry points go.
- **CSV and TOML survive as export-only views.** `write_manifest`, `CSV_COLUMNS`, `_toml_escape` stay. Only the *parsers* go.
  > **SUPERSEDED during execution (user ruling).** CSV/TOML export was dropped entirely: `write_manifest`, `CSV_COLUMNS` and `_toml_escape` are all gone, and `_read_raw_manifest` refuses a `.toml`/`.csv` path outright. JSON and YAML are the only manifest formats, in both directions. Do not plan PR 2 around a TOML/CSV export view — there is none.
- **The in-memory v1-shaped dict stays.** `core_bridge.document_to_payload` builds it as an argument to `auto_discover`; it is never serialised.
- **`docs/cli.md` must be regenerated with Python 3.11 exactly** (`scripts/export_cli_help.py:25` hard-refuses other versions) whenever `build_parser` changes, or the `cli-docs-sync` CI job fails.
- **Any change under `ambermeta/gui/frontend/src/**` requires `npm ci && npm run build` and a commit of `ambermeta/gui/static/`**, or `gui-static-check` fails. No task in this PR touches the frontend.
- **The three shell-completion scripts are hand-written** (`cli.py:855-880` bash, `:916-941` zsh, `:964-1008` fish). Any flag removed must be removed from all three.
- Run tests with the repo root as CWD. The `ambermeta` conda env lacks `httpx`, so `tests/test_gui_api_sim.py` cannot collect there; use an env with `pip install -e ".[all,tests]"`.

---

## File Structure

| File | Responsibility after this PR |
|---|---|
| `.github/workflows/tests.yml` | **NEW.** Runs pytest (matrix) and vitest. Unfiltered. |
| `ambermeta/gui/api/__init__.py` | **Emptied.** Importing it must not require FastAPI. |
| `ambermeta/protocol.py` | Gains `write_protocol_outputs` + `PLAN_ARTIFACTS`. Loses `load_protocol_from_manifest`, `ProtocolBuilder.from_manifest`. |
| `ambermeta/gui/api/core_bridge.py` | `write_plan_outputs` becomes a thin wrapper. `build_protocol` honours `strict`/`auto_detect_restarts`. |
| `ambermeta/cli.py` | One artifact-writing path. No v1/v2 dispatch. No `--to legacy`, no `init --auto`, no v1 templates. |
| `ambermeta/simulation.py` | `load_simulation` reads v2 only, with an explicit shape error. |
| `ambermeta/manifest.py` | Write side + in-memory normalisation only. No CSV/TOML parsing, no `load_manifest`. |

---

### Task 1: CI runs the test suites

Nothing in this repo has ever run a test in CI. Land this alone so the first green/red is readable.

**Files:**
- Create: `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: a `Tests` check on every PR and every push to `main`.

- [ ] **Step 1: Confirm the suites are green locally before automating them**

```bash
python -m pip install -e ".[all,tests]"
python -m pytest -q
cd ambermeta/gui/frontend && npm ci && npm test
```

Expected: pytest 267 passed; vitest 28 files / 267 tests passed. If pytest reports `Interrupted: 1 error during collection` mentioning `httpx`, the install did not take — `starlette.testclient` refuses to import without it and **zero tests run**.

- [ ] **Step 2: Write the workflow**

```yaml
name: Tests

on:
  pull_request:
  push:
    branches:
      - main

jobs:
  python-tests:
    name: pytest (Python ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ['3.9', '3.12']

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install package and test dependencies
        # Both extras are required and neither is sufficient alone.
        # [tests] gives pytest + httpx: without httpx, starlette.testclient
        # raises on import and the ENTIRE collection aborts, running no tests.
        # [all] gives fastapi, numpy and pyyaml, each imported unguarded at
        # module level by a test file (test_gui_api_sim.py, test_parser_fixes.py,
        # test_protocol.py) - so each missing one is a collection error, not a skip.
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e ".[all,tests]"

      - name: Run pytest
        run: python -m pytest

  frontend-tests:
    name: vitest
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: npm
          cache-dependency-path: ambermeta/gui/frontend/package-lock.json

      - name: Install frontend dependencies
        working-directory: ambermeta/gui/frontend
        run: npm ci

      - name: Run vitest
        working-directory: ambermeta/gui/frontend
        run: npm test
```

Deliberately **no `paths:` filter**, unlike the two existing workflows. Theirs are safe because each guards a generated artifact whose inputs are exactly the filtered paths. A correct filter for tests would have to list `ambermeta/**`, `tests/**`, `pyproject.toml` and the frontend tree — i.e. everything. And a path-filtered workflow that does not trigger leaves a *missing* check, which blocks a merge forever if it is ever marked required.

- [ ] **Step 3: Commit and push, then read the result**

```bash
git add .github/workflows/tests.yml
git commit -m "ci: run the Python and frontend test suites"
git push -u origin run-lineages
```

Expected: `Tests / pytest (Python 3.12)` and `Tests / vitest` pass.

- [ ] **Step 4: Handle the two predicted CI-only failures**

Neither can be reproduced locally; both are why this task lands first.

**(a) `tests/test_parser_fixes.py:177 test_amberrestart_does_not_crash_trajectory_parser`.** Locally `NETCDF_BACKEND` resolves to `"scipy"`, so the test passes with its body never executing. `[all]` installs real netCDF4 on the runner, flipping the backend and running that `createVariable` block for the first time. If it fails, fix the test body — do not remove the extra.

**(b) The Python 3.9 leg may fail installing `netCDF4>=1.6`/`scipy>=1.8`** if no manylinux wheel exists. If it does, change that job's install to reproduce the local environment instead:

```yaml
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e ".[gui,yaml,toml,tests]" numpy scipy
```

Commit either fix separately so the reason stays in the history.

---

### Task 2: Importing the GUI API package must not require FastAPI

`ambermeta plan --manifest`, `ambermeta discover` and `ambermeta validate --manifest` all import `core_bridge` and therefore **fail today on a base install**. After Task 6 removes the v1 branch this would break *every* `plan --manifest`, so it is a prerequisite of the fix, not a nicety.

**Files:**
- Modify: `ambermeta/gui/api/__init__.py` (whole file)
- Test: `tests/test_cli_plan_v2.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ambermeta.gui.api.core_bridge` importable without FastAPI installed.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_plan_v2.py`. It must run out-of-process: other tests import `ambermeta.gui.api`, so blocking `fastapi` in-process would be defeated by `sys.modules`.

```python
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_core_bridge_imports_without_the_gui_extra():
    """`plan`, `discover` and `validate --manifest` all import core_bridge.

    Eagerly importing .routes in the package __init__ made every one of those
    commands require the `gui` extra, which the base install does not have.
    """
    script = textwrap.dedent("""
        import sys, importlib.abc
        class _NoFastAPI(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name == "fastapi" or name.startswith("fastapi."):
                    raise ImportError("No module named 'fastapi'")
                return None
        sys.meta_path.insert(0, _NoFastAPI())
        from ambermeta.gui.api import core_bridge
        assert hasattr(core_bridge, "build_protocol")
        print("ok")
    """)
    proc = subprocess.run([sys.executable, "-c", script],
                          cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python -m pytest tests/test_cli_plan_v2.py::test_core_bridge_imports_without_the_gui_extra -v`
Expected: FAIL. `proc.stderr` contains `from fastapi import APIRouter, HTTPException, Query` raised from `ambermeta/gui/api/routes.py:6`, reached via `ambermeta/gui/api/__init__.py:5`.

- [ ] **Step 3: Empty the package `__init__`**

Replace the entire contents of `ambermeta/gui/api/__init__.py` with:

```python
"""AmberMeta GUI API package.

Deliberately imports nothing. ``core_bridge`` is the CLI's engine facade on the
plan/discover/validate paths, and eagerly importing ``.routes`` here made every
one of those commands require the ``gui`` extra. Import submodules directly:

    from ambermeta.gui.api import core_bridge
    from ambermeta.gui.api.routes import router
"""
```

This is safe because nothing consumes the old re-exports: `server.py:47` imports `from .api.routes import ...` (submodule form), and every test uses submodule form too.

- [ ] **Step 4: Verify the test passes and nothing else broke**

Run: `python -m pytest tests/ -q`
Expected: all pass, one more than before.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/gui/api/__init__.py tests/test_cli_plan_v2.py
git commit -m "fix: stop the GUI API package dragging FastAPI into the CLI"
```

---

### Task 3: Extract one artifact writer

The CLI and the GUI have two artifact writers. They have already drifted: the GUI's creates parent directories and captures per-artifact `OSError` into a `failed` list; the CLI's does neither.

**Files:**
- Modify: `ambermeta/protocol.py` (add near `write_stats_csv`, ~line 1990)
- Modify: `ambermeta/gui/api/core_bridge.py:374-437`
- Test: `tests/test_protocol.py`

**Interfaces:**
- Consumes: `SimulationProtocol` (`protocol.py:343`), `to_plain` (`protocol.py:1970`), `write_stats_csv` (`protocol.py:1998`).
- Produces:
  - `protocol.PLAN_ARTIFACTS: tuple[str, ...]` = `("summary", "methods_summary", "stats_csv")`
  - `protocol.write_protocol_outputs(protocol, targets: dict[str, str], summary_format: str = "json") -> dict` returning `{"written": [{"artifact","path"}], "failed": [{"artifact","path","error"}], "warnings": [str]}`
  - `core_bridge.write_plan_outputs` keeps its existing signature and return shape exactly.

- [ ] **Step 1: Write the failing test**

```python
def test_write_protocol_outputs_creates_parent_directories(tmp_path):
    """The CLI's old writer raised FileNotFoundError on a missing parent."""
    from ambermeta.protocol import write_protocol_outputs
    protocol = SimulationProtocol()
    target = tmp_path / "reports" / "deep" / "summary.json"

    result = write_protocol_outputs(protocol, {"summary": str(target)})

    assert target.is_file()
    assert result["written"] == [{"artifact": "summary", "path": str(target)}]
    assert result["failed"] == []


def test_write_protocol_outputs_rejects_an_unknown_artifact(tmp_path):
    from ambermeta.protocol import write_protocol_outputs
    with pytest.raises(ValueError, match="unknown plan artifact"):
        write_protocol_outputs(SimulationProtocol(), {"nope": str(tmp_path / "x")})


def test_write_protocol_outputs_rejects_an_unsupported_summary_format(tmp_path):
    from ambermeta.protocol import write_protocol_outputs
    with pytest.raises(ValueError, match="json or yaml"):
        write_protocol_outputs(SimulationProtocol(),
                               {"summary": str(tmp_path / "s.toml")},
                               summary_format="toml")
```

`SimulationProtocol` and `pytest` are already imported in this file.

- [ ] **Step 2: Run and confirm it fails**

Run: `python -m pytest tests/test_protocol.py -k write_protocol_outputs -v`
Expected: FAIL, `ImportError: cannot import name 'write_protocol_outputs'`.

- [ ] **Step 3: Add the function to `ambermeta/protocol.py`**

Place it immediately after `write_stats_csv`. Move the body verbatim from `core_bridge.py:394-437`, dropping only the `build_protocol(...)` line — nothing in that range touches `sim`, `settings` or `base_directory`.

```python
PLAN_ARTIFACTS = ("summary", "methods_summary", "stats_csv")


def write_protocol_outputs(protocol, targets, summary_format="json"):
    """Write the requested plan artifacts from one already-built protocol.

    Shared by `ambermeta plan` and the GUI's Plan action so the two cannot drift.
    Each artifact is attempted independently: a permission error on one is
    reported in `failed` rather than aborting the others, because a partially
    successful run must say exactly which files landed.
    """
    unknown = sorted(set(targets) - set(PLAN_ARTIFACTS))
    if unknown:
        raise ValueError(f"unknown plan artifact(s): {', '.join(unknown)}")
    if summary_format not in ("json", "yaml"):
        raise ValueError(f"summary format must be json or yaml, got: {summary_format}")

    written, failed, warnings = [], [], []
    if not protocol.stages:
        warnings.append("The document has no steps, so the outputs describe nothing.")

    def _attempt(artifact, path, write):
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            write(path)
        except OSError as exc:
            failed.append({"artifact": artifact, "path": path, "error": str(exc)})
        else:
            written.append({"artifact": artifact, "path": path})

    if "summary" in targets:
        payload = to_plain(protocol.to_dict())

        def _write_summary(path):
            with open(path, "w", encoding="utf-8") as fh:
                if summary_format == "yaml":
                    import yaml as _yaml
                    _yaml.safe_dump(payload, fh, sort_keys=False)
                else:
                    json.dump(payload, fh, indent=2)

        _attempt("summary", targets["summary"], _write_summary)

    if "methods_summary" in targets:
        methods = to_plain(protocol.to_methods_dict())

        def _write_methods(path):
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(methods, fh, indent=2)

        _attempt("methods_summary", targets["methods_summary"], _write_methods)

    if "stats_csv" in targets:
        if not any(s.mdout for s in protocol.stages):
            warnings.append("No step has an mdout, so the statistics CSV has headers only.")
        _attempt("stats_csv", targets["stats_csv"],
                 lambda path: write_stats_csv(protocol, path))

    return {"written": written, "failed": failed, "warnings": warnings}
```

Add `"PLAN_ARTIFACTS"` and `"write_protocol_outputs"` to `protocol.py`'s `__all__`. Confirm `import json` and `import os` are already at module scope (they are).

- [ ] **Step 4: Make `core_bridge.write_plan_outputs` a wrapper**

Replace `core_bridge.py:374-437` with:

```python
def write_plan_outputs(sim, settings, base_directory, targets, summary_format="json"):
    """Build the protocol for `sim`, then write the requested artifacts.

    The writing half lives in ambermeta.protocol so the CLI shares it; keeping a
    second copy here is how the CLI ended up without mkdir and without per-artifact
    failure capture.
    """
    from ambermeta.protocol import write_protocol_outputs

    protocol = build_protocol(_flatten_simulation(sim), dict(settings), base_directory)
    result = write_protocol_outputs(protocol, targets, summary_format=summary_format)
    result["totals"] = protocol.totals()
    result["stage_count"] = len(protocol.stages)
    return result
```

Keep `PLAN_ARTIFACTS` importable from `core_bridge` for `routes.py`: add `from ambermeta.protocol import PLAN_ARTIFACTS  # noqa: F401` near the other protocol imports.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all pass. `tests/test_gui_api_sim.py::test_the_summaries_match_what_the_cli_would_write` is the load-bearing one — it asserts the GUI's output equals `to_plain(protocol.to_dict())` and must be unaffected.

- [ ] **Step 6: Commit**

```bash
git add ambermeta/protocol.py ambermeta/gui/api/core_bridge.py tests/test_protocol.py
git commit -m "refactor: one plan-artifact writer shared by the CLI and the GUI"
```

---

### Task 4: `plan --manifest` writes its artifacts

Verified bug: `ambermeta plan <dir> -m sim.yaml --summary-path s.json --methods-summary-path m.json --stats-csv stats.csv` exits **0** and writes **nothing**. `_plan_v2` returns before the artifact block. No test has ever exercised these three flags on any path — a repo-wide grep for `--summary-path` across `tests/` returns zero hits.

**Files:**
- Modify: `ambermeta/cli.py:1525-1538` (`_plan_v2`), `ambermeta/cli.py:236-256` (`_print_simulation`)
- Modify: `ambermeta/gui/api/core_bridge.py:136-153` (`build_protocol`), `:156` and `:358` (thread a prebuilt protocol)
- Modify: `ambermeta/simulation.py:182-187` (`load_simulation` gains `expand_env`)
- Test: `tests/test_cli_plan_v2.py`

**Interfaces:**
- Consumes: `protocol.write_protocol_outputs` (Task 3), `core_bridge.build_protocol`, `core_bridge._flatten_simulation`, `core_bridge.validate_simulation`, `cli._resolve_sim_format` (`cli.py:275-280`).
- Produces: `_plan_v2(args, directory) -> int` writing every requested artifact; `build_protocol` honouring `settings["strict"]`, `settings["auto_detect_restarts"]`, `settings["global_prmtop"]`; `validate_simulation(..., protocol=None)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli_plan_v2.py`. Uses the existing `sample_md_data_dir` fixture (`tests/conftest.py:14`).

```python
import csv
import json
import shutil

V2_MD_TEST_FILES = """\
version: 2
simulation:
  topologies:
    - id: top_wt
      path: CH3L1_HUMAN_6NAG.top
      kind: normal
  starting_structure: CH3L1_HUMAN_6NAG.crd
phases:
  - { id: ph_prod, name: Production, role: production, order: 0 }
steps:
  - id: st_0001
    name: ntp_prod_0001
    phase: ph_prod
    order: 0
    topology: top_wt
    input_coords: { source: starting_structure }
    mdin: ntp_prod_0001.mdin
    mdout: ntp_prod_0001.mdout
    rst: ntp_prod_0001.rst
  - id: st_0002
    name: ntp_prod_0002
    phase: ph_prod
    order: 1
    topology: top_wt
    input_coords: { source: step, ref: st_0001 }
    mdin: ntp_prod_0002.mdin
    mdout: ntp_prod_0002.mdout
    rst: ntp_prod_0002.rst
"""


@pytest.fixture
def v2_run(tmp_path, sample_md_data_dir):
    """The real sample run, plus a v2 manifest describing two of its steps."""
    for f in sample_md_data_dir.iterdir():
        shutil.copy(f, tmp_path)
    (tmp_path / "sim.yaml").write_text(V2_MD_TEST_FILES, encoding="utf-8")
    return tmp_path


def test_plan_writes_every_requested_artifact(v2_run, capsys):
    rc = main(["plan", str(v2_run), "--manifest", str(v2_run / "sim.yaml"),
               "--summary-path", str(v2_run / "reports" / "summary.json"),
               "--methods-summary-path", str(v2_run / "methods.json"),
               "--stats-csv", str(v2_run / "stats.csv")])
    assert rc == 0
    # All three landed, and the missing parent directory was created, not an error.
    assert (v2_run / "reports" / "summary.json").is_file()
    assert (v2_run / "methods.json").is_file()
    assert (v2_run / "stats.csv").is_file()
    out = capsys.readouterr().out
    assert "summary.json" in out and "methods.json" in out and "stats.csv" in out


def test_plan_summary_matches_the_protocol_the_gui_would_build(v2_run):
    """One engine, one parse: the CLI must not write a different summary than the GUI."""
    from ambermeta.gui.api import core_bridge
    from ambermeta.protocol import to_plain
    from ambermeta.simulation import load_simulation

    main(["plan", str(v2_run), "--manifest", str(v2_run / "sim.yaml"),
          "--summary-path", str(v2_run / "s.json"),
          "--methods-summary-path", str(v2_run / "m.json")])
    sim = load_simulation(str(v2_run / "sim.yaml"))
    protocol = core_bridge.build_protocol(
        core_bridge._flatten_simulation(sim),
        {"strict_validation": True, "allow_gaps": False, "use_relative_paths": True},
        str(v2_run))
    assert json.loads((v2_run / "s.json").read_text(encoding="utf-8")) \
        == to_plain(protocol.to_dict())
    assert json.loads((v2_run / "m.json").read_text(encoding="utf-8")) \
        == to_plain(protocol.to_methods_dict())


def test_plan_stats_csv_has_a_row_per_step(v2_run):
    from ambermeta.protocol import STATS_CSV_COLUMNS

    rc = main(["plan", str(v2_run), "--manifest", str(v2_run / "sim.yaml"),
               "--stats-csv", str(v2_run / "stats.csv")])
    assert rc == 0
    rows = list(csv.DictReader((v2_run / "stats.csv").open(encoding="utf-8")))
    assert [r["stage_name"] for r in rows] == ["ntp_prod_0001", "ntp_prod_0002"]
    assert list(rows[0]) == STATS_CSV_COLUMNS
    assert float(rows[1]["time_end_ps"]) > float(rows[0]["time_end_ps"])


def test_plan_summary_format_follows_the_extension(v2_run):
    main(["plan", str(v2_run), "--manifest", str(v2_run / "sim.yaml"),
          "--summary-path", str(v2_run / "s.yaml")])
    text = (v2_run / "s.yaml").read_text(encoding="utf-8")
    assert not text.lstrip().startswith("{")      # YAML, not JSON in a .yaml
    assert "stages:" in text


def test_plan_strict_fails_cleanly_on_a_missing_file(v2_run, capsys):
    (v2_run / "ntp_prod_0002.mdout").unlink()
    rc = main(["plan", str(v2_run), "--manifest", str(v2_run / "sim.yaml"), "--strict"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "ntp_prod_0002.mdout" in err
    assert "Traceback" not in err


def test_plan_honours_the_global_prmtop_flag(v2_run):
    manifest = v2_run / "no_topo.yaml"
    manifest.write_text(
        V2_MD_TEST_FILES.replace("    topology: top_wt\n", ""), encoding="utf-8")
    main(["plan", str(v2_run), "--manifest", str(manifest),
          "--prmtop", "CH3L1_HUMAN_6NAG.top",
          "--summary-path", str(v2_run / "s.json")])
    summary = json.loads((v2_run / "s.json").read_text(encoding="utf-8"))
    assert summary["stages"][0]["files"]["prmtop"] is not None


def test_plan_refuses_two_outputs_aimed_at_one_file(v2_run, capsys):
    rc = main(["plan", str(v2_run), "--manifest", str(v2_run / "sim.yaml"),
               "--summary-path", str(v2_run / "same.json"),
               "--methods-summary-path", str(v2_run / "same.json")])
    assert rc == 2
    assert "own file" in capsys.readouterr().err
    assert not (v2_run / "same.json").exists()
```

`main` is already imported at `tests/test_cli_plan_v2.py:1`; add `import pytest` if absent.

- [ ] **Step 2: Run and confirm they fail**

Run: `python -m pytest tests/test_cli_plan_v2.py -v`
Expected: all seven FAIL. The first fails on `assert (v2_run / "reports" / "summary.json").is_file()` with `rc == 0` — the exact bug.

- [ ] **Step 3: Let `build_protocol` honour the flags**

In `core_bridge.py:145-153`, replace the `auto_discover(...)` call's tail:

```python
    return auto_discover(
        base_directory,
        manifest=payload["stages"],
        global_prmtop=payload.get("global_prmtop"),
        hmr_prmtop=payload.get("hmr_prmtop"),
        skip_cross_stage_validation=not settings.get("strict_validation", True),
        allow_unexpected_gaps=settings.get("allow_gaps", False),
        auto_detect_restarts=bool(settings.get("auto_detect_restarts", False)),
        strict=bool(settings.get("strict", False)),
    )
```

Both new keys are absent from `RuntimeSettings` (`schemas.py:95-100`), so GUI behaviour is unchanged.

- [ ] **Step 4: Let a prebuilt protocol be threaded through, to avoid parsing twice**

Add `protocol=None` to `build_validation_report` (`core_bridge.py:156`) and `validate_simulation` (`core_bridge.py:358`); inside `build_validation_report`, replace the unconditional build with:

```python
    if protocol is None:
        protocol = build_protocol(stages, settings, base_directory)
```

and have `validate_simulation` pass its `protocol` argument down. Defaults preserve every existing caller.

- [ ] **Step 5: Give `load_simulation` an `expand_env` parameter**

`--no-expand-env` is currently ignored on this path. In `simulation.py:182`:

```python
def load_simulation(path: str, expand_env: bool = True) -> Simulation:
    """Load a Simulation from a v2 manifest file."""
    return payload_to_simulation(_read_raw_manifest(path, expand_env=expand_env))
```

(The migration branch is removed in Task 6; until then keep the existing body and only add the parameter, forwarding it to `_read_raw_manifest`.)

- [ ] **Step 6: Rewrite `_plan_v2`**

Replace `cli.py:1525-1538` entirely:

```python
def _plan_v2(args: argparse.Namespace, directory: str) -> int:
    """Summarize a v2 manifest and write any requested plan artifacts."""
    from ambermeta.simulation import load_simulation
    from ambermeta.gui.api.core_bridge import (
        _flatten_simulation, build_protocol, validate_simulation,
    )
    from ambermeta.protocol import write_protocol_outputs

    expand_env = not getattr(args, "no_expand_env", False)
    sim = load_simulation(args.manifest, expand_env=expand_env)
    settings = {
        "strict_validation": not bool(getattr(args, "skip_cross_stage_validation", None)),
        "allow_gaps": False,
        "use_relative_paths": True,
        "global_prmtop": getattr(args, "prmtop", None),
        "auto_detect_restarts": bool(getattr(args, "auto_detect_restarts", False)),
        "strict": bool(getattr(args, "strict", False)),
    }
    protocol = build_protocol(_flatten_simulation(sim), settings, directory)

    # An empty manifest was an error on the old flat path; keep that contract.
    if not protocol.stages:
        print("ERROR: manifest produced 0 stages.", file=sys.stderr)
        return 1

    report = validate_simulation(sim, settings, directory, protocol=protocol)
    _print_simulation(sim, report, verbose=bool(getattr(args, "verbose", False)))

    targets = {}
    for artifact, raw in (("summary", args.summary_path),
                          ("methods_summary", args.methods_summary_path),
                          ("stats_csv", getattr(args, "stats_csv", None))):
        if raw:
            targets[artifact] = os.path.abspath(raw)
    if not targets:
        return 0

    paths = list(targets.values())
    dupes = sorted({p for p in paths if paths.count(p) > 1})
    if dupes:
        print(Colors.error("ERROR: each output needs its own file; more than one is "
                           "aimed at " + ", ".join(dupes)), file=sys.stderr)
        return 2

    fmt = _resolve_sim_format(args.summary_path or "", args.summary_format)
    result = write_protocol_outputs(protocol, targets, summary_format=fmt)
    for item in result["written"]:
        _out(f"Wrote {item['artifact']}: {item['path']}")
    for warning in result["warnings"]:
        print(Colors.warning(f"WARNING: {warning}"), file=sys.stderr)
    for item in result["failed"]:
        print(Colors.error(f"ERROR: could not write {item['artifact']} to "
                           f"{item['path']}: {item['error']}"), file=sys.stderr)
    return 1 if result["failed"] else 0
```

- [ ] **Step 7: Give `_print_simulation` a verbose mode**

`--verbose` is ignored on this path. Change the signature at `cli.py:236` to
`def _print_simulation(sim, report, *, verbose: bool = False) -> None:` and append, before the suggestions block:

```python
    if verbose:
        for issue in report.get("stage_issues", []):
            lines = ((issue.get("errors") or []) + (issue.get("warnings") or [])
                     + (issue.get("info") or []))
            for line in lines:
                _out(f"    {issue['name']}: {line}")
```

The other caller, `_discover_command` (`cli.py:298`), is unaffected by the keyword-only default.

- [ ] **Step 8: Run the tests**

Run: `python -m pytest tests/test_cli_plan_v2.py -v && python -m pytest tests/ -q`
Expected: all seven new tests PASS; full suite green.

- [ ] **Step 9: Commit**

```bash
git add ambermeta/cli.py ambermeta/gui/api/core_bridge.py ambermeta/simulation.py tests/test_cli_plan_v2.py
git commit -m "fix: plan --manifest writes the summaries it was asked for"
```

---

### Task 5: One artifact-writing site in the CLI

`plan --recursive` and `plan --interactive` still write artifacts through the old inline block. Collapse them onto the same helper so the two cannot drift again.

**Files:**
- Modify: `ambermeta/cli.py:1669-1701`, delete `_export_stats_csv` at `cli.py:1733-1738`

**Interfaces:**
- Consumes: `protocol.write_protocol_outputs`.
- Produces: no new symbols. `_export_stats_csv` is gone.

- [ ] **Step 1: Write the failing test**

```python
def test_plan_recursive_creates_missing_parent_directories(tmp_path, sample_md_data_dir):
    """The recursive path used to raise FileNotFoundError on a missing parent."""
    for f in sample_md_data_dir.iterdir():
        shutil.copy(f, tmp_path)
    rc = main(["plan", str(tmp_path), "--recursive",
               "--summary-path", str(tmp_path / "out" / "summary.json")])
    assert rc == 0
    assert (tmp_path / "out" / "summary.json").is_file()
```

Add to `tests/test_cli_plan.py` (needs `import shutil` and the `sample_md_data_dir` fixture).

- [ ] **Step 2: Run and confirm it fails**

Run: `python -m pytest tests/test_cli_plan.py -k missing_parent -v`
Expected: FAIL with `Unexpected error (FileNotFoundError: ...)` and rc 1.

- [ ] **Step 3: Replace the inline block**

Replace `cli.py:1669-1701` with:

```python
    targets = {}
    for artifact, raw in (("summary", args.summary_path),
                          ("methods_summary", args.methods_summary_path),
                          ("stats_csv", getattr(args, "stats_csv", None))):
        if raw:
            targets[artifact] = os.path.abspath(raw)
    if targets:
        from ambermeta.protocol import write_protocol_outputs

        fmt = _resolve_sim_format(args.summary_path or "", args.summary_format)
        result = write_protocol_outputs(protocol, targets, summary_format=fmt)
        for item in result["written"]:
            _out(f"Wrote {item['artifact']}: {item['path']}")
        for warning in result["warnings"]:
            print(Colors.warning(f"WARNING: {warning}"), file=sys.stderr)
        for item in result["failed"]:
            print(Colors.error(f"ERROR: could not write {item['artifact']} to "
                               f"{item['path']}: {item['error']}"), file=sys.stderr)
        if result["failed"]:
            return 1
```

Then delete `_export_stats_csv` (`cli.py:1733-1738`). Repo-wide grep confirms nothing references its `Statistics exported to:` string.

**Behaviour deltas to note in the commit message:** parent directories are now created; an unwritable path gives a clean `ERROR:` line and rc 1 instead of `Unexpected error (FileNotFoundError: ...)`; `--stats-csv`'s confirmation wording becomes `Wrote stats_csv: <path>`.

- [ ] **Step 4: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ambermeta/cli.py tests/test_cli_plan.py
git commit -m "refactor: collapse the CLI onto one artifact writer"
```

---

### Task 6: Remove the v1 manifest reader

**Decision recorded here, resolving an ambiguity the spec left open:** `protocol.load_protocol_from_manifest` and `ProtocolBuilder.from_manifest` **are removed**. Both read a v1 manifest file from disk via `manifest.load_manifest`, and once `plan --manifest` is unconditionally v2 they are unreachable from the CLI. Keeping a public function that reads a format the tool no longer supports is worse than deleting it. `auto_discover(manifest=<list>)` — the in-memory door — is untouched and is what every surviving test uses.

**Files:**
- Modify: `ambermeta/simulation.py` (delete 137-158, 161-162, 190-191, 194-267; simplify `load_simulation`)
- Modify: `ambermeta/manifest.py` (delete 77-113, 116-137, 210-254, 257-271, `load_manifest`; trim `_read_raw_manifest`)
- Modify: `ambermeta/protocol.py` (delete `load_protocol_from_manifest` at 1568, `ProtocolBuilder.from_manifest` at 1742)
- Modify: `ambermeta/cli.py:1578-1597` (the dispatch), `ambermeta/__init__.py`
- Delete: `tests/test_migration.py`
- Modify: `tests/test_manifest.py`, `tests/test_protocol.py`, `tests/test_cli_plan.py`, `tests/test_cli_plan_v2.py`

**Interfaces:**
- Consumes: `_read_raw_manifest` (kept), `payload_to_simulation` (kept).
- Produces: `load_simulation(path, expand_env=True)` raising `AmberMetaError` on a non-v2 document.

- [ ] **Step 1: Write the failing test for the new error**

Add to `tests/test_simulation.py`:

```python
def test_loading_a_flat_manifest_says_so_instead_of_returning_nothing(tmp_path):
    """A v1 file used to migrate silently; now it must be a clear error.

    Without this guard payload_to_simulation reads no "phases"/"steps" key and
    returns an EMPTY Simulation, so every caller reports "0 steps" for a file
    that is simply the wrong format.
    """
    from ambermeta.errors import AmberMetaError
    from ambermeta.simulation import load_simulation

    flat = tmp_path / "old.yaml"
    flat.write_text("stages:\n  - name: prod\n    mdin: prod.in\n", encoding="utf-8")

    with pytest.raises(AmberMetaError, match="not a v2 manifest"):
        load_simulation(str(flat))
```

- [ ] **Step 2: Run and confirm it fails**

Run: `python -m pytest tests/test_simulation.py -k flat_manifest -v`
Expected: FAIL — no exception raised, because the v1 migration path still handles it.

- [ ] **Step 3: Simplify `load_simulation`**

Replace `simulation.py:182-187`:

```python
def load_simulation(path: str, expand_env: bool = True) -> Simulation:
    """Load a Simulation from a v2 manifest file."""
    raw = _read_raw_manifest(path, expand_env=expand_env)
    if not isinstance(raw, dict) or "steps" not in raw:
        raise AmberMetaError(
            f"{path} is not a v2 manifest (no 'steps' key). "
            "Rebuild it with `ambermeta discover <dir> --write <path>`."
        )
    return payload_to_simulation(raw)
```

Add `from ambermeta.errors import AmberMetaError` to the imports.

- [ ] **Step 4: Delete the v1 code**

In `ambermeta/simulation.py`, delete in this order (bottom-up, so line numbers stay valid):
`migrate_v1_manifest` (194-267), `_v1_globals` (190-191), `_is_v2` (161-162), `_adopt_legacy_restart_paths` (137-158) **and its call at line 133**. Then trim the now-dead imports: line 8 becomes `from ambermeta.manifest import _read_raw_manifest`; delete line 9 (`classify_role`); drop `Any` from the typing import at line 6.

> **PARTLY SUPERSEDED during execution (controller ruling).** `_adopt_legacy_restart_paths` and its call **were kept** and are still in the file. Despite the name it is v2 schema-evolution compat, not v1 code: it normalises v2 documents written before `Step.rst` existed, which stored a chained step's restart on the consuming step as `input_coords.path`. It has a passing test (`tests/test_gui_document.py::test_loading_a_legacy_manifest_moves_the_restart_onto_the_step_that_wrote_it`). Do not schedule it for removal in PR 2.

In `ambermeta/manifest.py`, delete `_parse_csv_manifest` (77-113), `_parse_toml_manifest` (116-137), `normalize_stage_keys` (210-254), `_normalize_container` (257-271), and `load_manifest`. In `_read_raw_manifest`, delete the `.toml` branch (361-362) and the `.csv` branch (363-364) and add an explicit guard so an unsupported suffix is not swallowed by the JSON fallback:

```python
    if ext in (".toml", ".csv"):
        raise AmberMetaError(
            f"{path}: TOML and CSV are export-only formats and cannot be read back. "
            "Manifests are YAML or JSON."
        )
```

> **Wording superseded** by the same user ruling: with no export side left, "export-only formats" advertised a feature that does not exist. The shipped message is `f"{path}: AmberMeta reads and writes manifests as YAML or JSON only; TOML and CSV are not manifest formats."` (`ambermeta/manifest.py`).

Delete the now-dead `from io import StringIO` (line 7) and the `tomllib`/`tomli` try-block (18-24). Remove `"normalize_stage_keys"`, `"_normalize_container"` and `"load_manifest"` from `__all__`.

In `ambermeta/protocol.py`, delete `load_protocol_from_manifest` and `ProtocolBuilder.from_manifest`, and drop the now-unused `_expand_env_vars` and `STAGE_FILE_KINDS` names from the import at lines 24/27 (verified unused elsewhere in that file). In `ambermeta/__init__.py`, remove `load_protocol_from_manifest` from the imports and `__all__`.

In `ambermeta/cli.py`, replace the dispatch at 1578-1597 so `--manifest` always routes to `_plan_v2`:

```python
    if args.manifest:
        return _plan_v2(args, directory)
```

- [ ] **Step 5: Update the tests**

Delete `tests/test_migration.py` entirely (4 tests, all call `migrate_v1_manifest`).

Delete these individually:
- `tests/test_manifest.py:7 test_normalize_stage_keys_aliases`
- `tests/test_cli_plan_v2.py:50 test_plan_v1_manifest_still_uses_flat_path`
- `tests/test_protocol.py:302 test_load_protocol_from_manifest_uses_parent_directory`

Rewrite these to go through the surviving door:
- `tests/test_manifest.py:19 test_write_then_load_roundtrip` — drop the `m.load_manifest` read-back; assert the written text's shape per format instead. Keep all four format params.
- `tests/test_protocol.py:265, :320, :345` — replace `load_protocol_from_manifest(<file>)` with `auto_discover(dir, manifest=<list>, global_prmtop=...)` / `grouping_rules=` / `skip_cross_stage_validation=`, which is where each behaviour actually lives.
- `tests/test_cli_plan.py:51 test_quiet_suppresses_stdout`, `:99 test_pattern_warns_in_manifest_mode`, `:114 test_plan_empty_manifest_nonzero` — their `stages: []` fixture becomes a v2 document. For the last one, an empty v2 manifest must still give rc 1 (the guard added in Task 4 Step 6).

- [ ] **Step 6: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: green, with roughly 8 fewer tests than before.

- [ ] **Step 7: Commit**

```bash
git add -A ambermeta tests
git commit -m "refactor!: remove the v1 manifest file format"
```

---

### Task 7: Remove `export --to legacy`

**Files:**
- Modify: `ambermeta/cli.py` — delete `_sim_to_legacy_payload` (315-350), the `--to legacy` branch (367-376), and the `--to` argument (1962-1975 block)
- Modify: `ambermeta/cli.py:855-880`, `:916-941`, `:964-1008` (three completion scripts)
- Modify: `tests/test_cli_export.py`
- Modify: `docs/cli.md` (regenerate)

- [ ] **Step 1: Delete the legacy branch and its flag**

Remove `_sim_to_legacy_payload`, the `if args.to == "legacy":` block in `_export_command`, and the `--to` argument from `build_parser`. Update `_export_command`'s docstring at `cli.py:354`, which still says "or a legacy flat manifest". Remove `--to` from all three completion scripts.

- [ ] **Step 2: Update the tests**

Delete `tests/test_cli_export.py:51 test_export_to_legacy_flat`. In `test_export_v1_to_v2_stdout_is_v2_payload` (`:29`) and `test_export_v1_to_v2_file_roundtrips` (`:40`), replace the module-level `V1_MANIFEST` fixture (lines 8-20) with a v2 document and drop the `to="v2"` kwarg from `_args` (line 24). Rename both tests — they no longer test v1.

- [ ] **Step 3: Regenerate the CLI docs on Python 3.11**

```bash
py -3.11 scripts/export_cli_help.py
py -3.11 scripts/export_cli_help.py --check
```

Expected: `--check` exits 0. If Python 3.11 is unavailable, this must be done before the PR opens or `cli-docs-sync` fails.

- [ ] **Step 4: Run the suite and commit**

```bash
python -m pytest tests/ -q
git add -A ambermeta tests docs
git commit -m "refactor!: drop export --to legacy"
```

---

### Task 8: `init` writes a v2 template only

**Decision recorded here:** `init --auto` is **removed**, not retargeted. It is a second directory-scanning heuristic duplicating `discover`, which does the same job better (content-based, produces a full v2 `Simulation`). Keeping both would violate the project rule against reimplementing one heuristic in two places. `init` becomes "write a starting template"; `discover --write` is "scan a directory".

**Files:**
- Modify: `ambermeta/cli.py` — `_init_command` (1019-1125), delete `_generate_minimal_manifest` (1321-1342), `_generate_standard_manifest` (1345-1403), `_generate_comprehensive_manifest` (1406-1522), `_render_candidate_stages` (1257-1279), and the `--v2`/`--auto`/`--template`/`--format` arguments
- Modify: the three completion scripts
- Modify: `tests/test_cli_init.py`, `tests/test_cli_init_v2.py`
- Modify: `docs/cli.md` (regenerate)

- [ ] **Step 1: Reduce `_init_command` to the v2 path**

Keep the overwrite check (1025-1036) and `_generate_v2_template` (1282-1318). The body becomes: resolve the output path, refuse to overwrite without `--force`, write the v2 template, report. Delete `--auto`, `--template`, `--format` and `--v2` from `build_parser` and from all three completion scripts. (`--v2` was already missing from all three — that drift is what this removes.)

- [ ] **Step 2: Update the tests**

Delete from `tests/test_cli_init.py`: `:10`, `:33`, `:146`, `:193`, plus `:44`, `:77`, `:111`, `:168` (all `--auto`-only) and `:127`, `:185` (dry-run and empty-warn, both `--auto`-only). Keep `:160 test_prmtop_substring_not_misclassified` — it exercises `cli._scan_directory_files`, which survives. Note `tests/test_cli_init.py:116` imports `_write_prmtop_atoms` from `test_core_hardening`; preserve that helper.

Delete `tests/test_cli_init_v2.py:30 test_init_without_v2_is_unchanged`. Keep `:14 test_init_v2_writes_loadable_v2_manifest` and drop the now-meaningless `v2=True` from its `_args` at line 9.

- [ ] **Step 3: Regenerate docs, run, commit**

```bash
py -3.11 scripts/export_cli_help.py
python -m pytest tests/ -q
cd ambermeta/gui/frontend && npm test && cd ../../..
git add -A ambermeta tests docs
git commit -m "refactor!: init writes a v2 template; discover does the scanning"
```

- [ ] **Step 4: Final check before opening the PR**

```bash
python -m pytest tests/ -q
cd ambermeta/gui/frontend && npm ci && npm run build && cd ../../..
git diff --quiet -- ambermeta/gui/static && echo "bundle clean"
py -3.11 scripts/export_cli_help.py --check && echo "docs in sync"
git grep -n "load_manifest\|migrate_v1\|normalize_stage_keys\|--to legacy\|_export_stats_csv" -- ambermeta tests
```

Expected: suite green, bundle clean, docs in sync, and the final grep returns **nothing**.

---

## Self-Review

**Spec coverage.** Spec §12 PR 1 lists three items: remove the v1 file format (Tasks 6, 7, 8), fix `plan -m` writing zero files (Task 4, extended by Tasks 3 and 5), CI runs the suites (Task 1). Task 2 is an addition — the spec did not name it, but §8.2's "no new CLI flags, no `docs/cli.md` regeneration" claim is void if `plan --manifest` cannot run on a base install, and the removal in Task 6 makes every `plan --manifest` take that import path. It is a prerequisite, not scope creep.

**Two ambiguities the spec left open, resolved above with reasons:** `load_protocol_from_manifest` is removed (Task 6); `init --auto` is removed rather than retargeted (Task 8). Both are called out in the task text rather than buried.

**Type consistency.** `write_protocol_outputs(protocol, targets, summary_format)` returning `{"written","failed","warnings"}` is defined in Task 3 and consumed unchanged in Tasks 4 and 5. `core_bridge.write_plan_outputs` keeps its `{"written","failed","warnings","totals","stage_count"}` shape, so `routes.py` and `PlanResult` are untouched. `load_simulation(path, expand_env=True)` is introduced in Task 4 Step 5 and its body finalised in Task 6 Step 3.

**Not in this PR:** everything lineage-related. `Step.lineage`, the chain invariant, per-lineage totals, the header-only mdout read, discover tagging, canvas bands. PR 2's plan is written after this one merges, because Task 6 changes the surface it builds on.
