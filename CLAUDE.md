# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AmberMeta reconstructs the provenance of AMBER MD runs from the files they left behind (prmtop, mdin, mdout, mdcrd, inpcrd/restart). It builds a Simulation → Phase → Step document, checks that the steps actually connect, and exports manifests and methods summaries. One Python core sits under two front ends: an argparse CLI (`ambermeta/cli.py`) and an optional, localhost-only FastAPI + React GUI (`ambermeta/gui/`).

Removed on purpose, so don't bring them back: the Textual TUI, and the v1 flat manifest format (a `stages:` list). Every entry point refuses a v1 manifest and points the user at `ambermeta discover`. There is no migration path, by design.

## Commands

Setup (you need both extras: without `httpx` from `tests` the whole pytest collection aborts, and several test files import fastapi, numpy or yaml unguarded):

```bash
python -m pip install -e ".[all,tests]"
```

Run the CLI through the `ambermeta` console script this installs. `python -m ambermeta` does not work, because there is no `__main__.py`.

Python tests (about 800 tests, around 70 s):

```bash
python -m pytest                                                     # full suite
python -m pytest tests/test_roles.py                                 # one file
python -m pytest tests/test_roles.py::test_canonical_tokens_only     # one test
python -m pytest -k lineage                                          # by keyword
```

Frontend (run in `ambermeta/gui/frontend`):

```bash
npm ci
npm test                                  # vitest run (about 300 tests)
npx vitest run src/lib/chain.test.ts      # one file
npm run build                             # tsc && vite build, writes ../static/
npm run dev                               # Vite dev server, proxies /api to localhost:8765
```

For frontend development, run the backend in another shell: `ambermeta gui tests/data/amber/md_test_files --no-browser` (port 8765).

CLI reference docs (the generator only runs on Python 3.11; see CI gates):

```bash
uv run --python 3.11 --no-project python scripts/export_cli_help.py          # regenerate docs/cli.md
uv run --python 3.11 --no-project python scripts/export_cli_help.py --check  # what CI runs
```

## CI gates

- **tests.yml**: pytest on Python 3.9 and 3.12, plus vitest. 3.9 is the supported floor, so keep code 3.9-compatible (no `match`, no runtime `X | Y` unions, no 3.10+ stdlib APIs).
- **cli-docs-sync**: `docs/cli.md` embeds `build_parser()` help output verbatim between `<!-- BEGIN_CLI_HELP:<cmd> -->` / `<!-- END_CLI_HELP:<cmd> -->` markers. Any change to a CLI argument or help string means regenerating it. The script exits 2 on anything but Python 3.11, because argparse formats help differently across versions. The local default Python is 3.12, hence `uv`.
- **gui-static-check**: rebuilds the frontend and fails if `ambermeta/gui/static/` differs from what is committed. Any change under `frontend/src` needs `npm run build` and a commit of the regenerated `static/`. By convention that is a separate `build(gui): rebuild static bundle ...` commit. `.gitattributes` forces LF on the bundle so a Windows build matches the Linux one. Never hand-edit `static/`.

## Lint and formatting

`ruff` and `black` are configured in `pyproject.toml`, but the codebase is not clean against either (hundreds of ruff findings, black would reformat most files) and CI does not lint. Do not run `black` or `ruff --fix` over the package, since that buries the real change in noise. Match the surrounding style, line length 100. mypy is configured but not used.

## Architecture

`docs/architecture.md` is current and lists the invariants. Read it before changing core behaviour. The points below are the ones that span several files.

**Two engine layers, deliberately.**
- `simulation.py` holds the v2 dataclasses (`Simulation`, `Phase`, `Step`, `Topology`, `InputCoords`) and the only manifest reader and writer: `load_simulation` / `write_simulation`, JSON or YAML, gated on the presence of a `steps` key. `simulation_to_payload` / `payload_to_simulation` convert to the dict shape the GUI API uses.
- `protocol.py` (about 3k lines) is the flat `SimulationProtocol` / `SimulationStage` engine. It still does file grouping, parse orchestration, continuity math and sequence-hole detection. v2 validation does not reimplement any of that: `core_bridge._flatten_simulation()` turns a `Simulation` into flat stage dicts and runs `protocol.auto_discover(dir, manifest=flat)`. A change to continuity or validation therefore belongs in `protocol.py`, and it affects both `plan --recursive` and v2 validation.

**`gui/api/core_bridge.py` is the one bridge.** It is the only GUI module that imports the core, and the CLI calls it too: `discover_draft()` backs both `ambermeta discover` and the GUI's Discover, and `validate_simulation()` backs `validate --manifest`, `plan -m` and the GUI's Validate. Shared logic goes there or in the core, never in `routes.py` or the frontend.

**The CLI must work without the `gui` extra.** `discover`, `validate --manifest` and `plan -m` import `core_bridge`, which pulls in `ambermeta/gui/__init__.py` and `gui/server.py`. That works in a base install only because `server.py` guards its FastAPI import. Keep FastAPI and Pydantic out of `core_bridge.py` and out of everything it imports. Rules both front ends share (`lineages.py`, `run_order.py`) live in `ambermeta/`, not in `gui/api/`, for this reason.

**Single sources of truth.** Don't add a second one:
- Role inference: `roles.classify_role()` (mdin/mdout `imin` first, then word-boundary path tokens, then content heuristics). Its two callers pass different evidence: `discover` classifies by name first, while the `plan --recursive` scan reads mdin content first. That makes roles differ between the two paths on some trees, which `docs/architecture.md` §2 documents.
- HMR detection: `topology_pool.py` (atom masses; `dt > 0.002` implies HMR).
- Restart vs trajectory, by content rather than extension: `coords.sniff_coordinate_kind()`.
- Run lineages (replicas, branches, poses): `lineages.py` (`infer_lineages_from_layout`, `UNTAGGED`). Continuity and sequence-hole checks are partitioned per lineage.
- Which run continued which, and execution order: `run_order.py`. It reads the INPCRD row of each mdout's File Assignments block (what AMBER actually opened), and both `discover_draft` and the `auto_discover` scan use it. The starting structure is also taken from those records where they resolve, with `sniff_coordinate_kind` as the fallback.
- Declared input vs recorded input: `recorded_inputs.compare_recorded_input()`, the source of the `input_mismatch` finding. A path that resolves locally is compared as a file; a path from another machine is compared by name only.

**Findings per run.** Besides continuity gaps and sequence holes, every run gets its own findings: `step_check`, `unfinished_run` and `input_mismatch` (from `SimulationStage.validate()`). The GUI shows them as cards via `protocol.stage_finding_cards()`; `plan --recursive` prints them via `SimulationProtocol.stage_findings()`. `--strict` turns any finding into exit 1.

**Methods summary** (`methods_summary.py`). `build_methods_summary(summary)` is a pure function of the `summary.json` dict: it reads no file, so it can be rebuilt from any summary on disk (`python -m ambermeta.methods_summary summary.json`). Every interpreted value carries a `source` (`mdin`, `mdout`, `default` or `derived`). Older summaries that lack fields must still digest, with the fallback stated in `basis` fields.

**Untagged documents must not change.** A document with no lineage tags has to produce exactly the output it did before lineages existed. Golden files in `tests/data/lineage_backcompat/` (checked by `tests/test_lineage_backcompat.py`) guard this. Regenerate them with `python tests/data/lineage_backcompat/regenerate.py` only when an output change is intended, and say why in the commit message.

**Parsers.** `parsers/*.py` are thin wrappers, and `legacy_extractors/*.py` do the byte-level work. Metadata lives on `.parse().details`, not on the object `parse()` returns. `mdout_header.py` reads mdout headers, including the File Assignments block and AMBER's `**********` overflow of the begin-time field. NetCDF support is optional (`netcdf_backend.py`), and every NetCDF open goes through one lock because netCDF4/HDF5 is not thread-safe.

**Parse cache** (`parse_cache.py`). Parses are memoised by `(kind, path, st_dev, st_ino, st_mtime_ns, st_size)` and shared by reference. Never mutate a parsed metadata object, because the cache is only correct while nothing does. Set `AMBERMETA_PARSE_CACHE=0` to disable it while debugging.

**Failures are data, inference is announced.** An expected file problem becomes a `FileLoadError` (`errors.py`, `classify_exception`) attached to its stage, never a traceback. `plan` and `discover` are fault-tolerant by default, and `--strict` makes errors fatal. Anything inferred (role, topology kind, starting structure, lineage) must surface as an INFO note or a suggestion. A check that could not run says so instead of staying silent, because silence reads as "checked and fine".

**GUI backend** (`gui/api/`). The server is authoritative. A singleton `DocumentStore` (`document.py`) holds one document, with deep-copy undo/redo under an `RLock` and a `revision` counter that moves on every content mutation. `snapshot_at()` returns the state and its revision under one lock, so a slow result (Validate, Save) can tell when it went stale and does not overwrite a later edit. Every route that accepts a path must resolve it through `files.resolve_within_base()` (403 outside the launch directory; tests in `tests/test_gui_files.py`). `tests/test_gui_security.py` copies the SPA-fallback containment logic from `server.py` verbatim, so a change there has to be mirrored in that test.

**GUI frontend** (`gui/frontend/src/`). React 18 + TS + Vite + Tailwind. Server state lives in a single react-query entry, `DOCUMENT_KEY = ["document"]` (`api/queryClient.ts`). Every mutation returns the new document, which is written there. There is no client-side copy of the document and no client undo stack. One app-level dnd-kit `DndContext` routes drops through `resolveDrop` in `App.tsx`. The app re-validates on every document change, so validation cost is user-visible on large campaigns.

**Test fixtures.** `tests/data/amber/md_test_files/` is a real 64,528-atom system with production runs `ntp_prod_0001..0005` (session fixture `sample_md_data_dir`). `tests/conftest.py` has a `RunSpec` builder that writes synthetic mdin/mdout trees (replicas, queued runs, killed runs, begin-time overflow). Prefer it over adding large fixture files.

## Docs

- User docs are `README.md` and `docs/*.md`. `docs/ambermeta.html` is a single-page offline copy of the same content. Nothing regenerates it, so it drifts unless it is edited together with the Markdown docs.
- The help blocks in `docs/cli.md` are generated (see Commands).
- `docs/superpowers/{specs,plans}/` are dated design and plan records of past work. Treat them as history, not as a spec of current behaviour.
- `docs/sop/` is LaTeX. Build it as described in `docs/sop/README.md`, and clean with `latexmk -c`, never `-C` (which deletes the tracked PDFs).

## Packaging

- `pyproject.toml` is the only packaging file: metadata, version, extras and tool config all live there. There is no `setup.py`. Editable installs go through PEP 660, hence `setuptools>=64` in `[build-system]`.
- `[tool.setuptools] packages` is an explicit list. A new subpackage has to be added there, or it won't ship in a non-editable install. A new module inside an existing package needs nothing.

## Conventions

Commit subjects mostly follow conventional commits with scopes, e.g. `fix(core):`, `fix(gui):`, `perf(core,gui):`, `feat(cli):`, `test(gui):`, `docs(sop):`, and `build(gui):` for bundle rebuilds. Subjects state the behaviour in plain words ("stop four parsing faults from inventing continuity gaps"). Work lands on `main` through PRs. Comments and docstrings explain *why*, often at length (see `parse_cache.py`, `tests/conftest.py`). Keep that up when touching such code.
