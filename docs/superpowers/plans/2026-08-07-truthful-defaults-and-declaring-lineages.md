# Truthful Defaults and Declaring Lineages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AmberMeta claim only what the files support — stop counting runs that never ran, stop asserting continuations that never happened — and give the GUI a way to declare and confirm run lineages.

**Architecture:** Three layers, changed bottom-up. The engine (`protocol.py`, `lineages.py`, `simulation.py`) learns to source totals from mdout elapsed time, to mark queued runs, and to reconcile lineage cohorts. The GUI backend (`core_bridge.py`, `routes.py`, `schemas.py`, `document.py`) stops writing cross-directory edges and grows a *proposal* object that Discover returns and the user accepts. The frontend grows one new component, `ProposalStrip.tsx`, used in two modes — proposed and manual — and loses the old no-preview "Infer lineages" button.

**Tech Stack:** Python 3.9/3.12 (dual CI), FastAPI + pydantic v2, pytest. React 18 + TypeScript (strict) + Vite + Tailwind, vitest + @testing-library + msw.

**Spec:** `docs/superpowers/specs/2026-08-07-truthful-defaults-and-declaring-lineages-design.md`
**Base commit:** `d1bac14` on branch `truthful-defaults-and-lineage-declaration`.

## Global Constraints

- **Python 3.9 compatible.** CI runs 3.9 *and* 3.12. No `X | Y` runtime annotations, no `match`, no 3.10+ syntax in `ambermeta/`. Use `from __future__ import annotations` and `typing.Dict/List/Optional/FrozenSet`.
- **Accumulate floats with `+=`, never `sum()` or `math.fsum`.** CPython 3.12's `sum` is compensated (Neumaier); the goldens compare floats across both interpreters. This is documented in `_sum_stages`' own docstring.
- **Emit-when-set for every new field.** A key appears in a payload only when it has a non-default value, so untagged/ordinary documents keep byte-identical artifacts. `assert_matches_golden` fails on any *added* key path.
- **Every key the server emits must be declared on its pydantic model.** `extra='ignore'` drops undeclared keys silently. Same for `types/index.ts` on the client.
- **Comments and docstrings carry the WHY at length**, naming the concrete failure prevented. This is the single most distinctive convention in the repo; terse code will read as out of place.
- **Test names are full sentences.** `test_a_queued_run_contributes_no_time`. Module docstrings state the contract pinned and what is deliberately *not* asserted. `# --- section ---` banners.
- **Frontend:** `strict`, `noUnusedLocals`, `noUnusedParameters` all on. An unused import is a hard build failure — no stub code. Tailwind utilities inline only; tokens from `tailwind.config.js` only. No `describe` in newer test files; `it("sentence", …)`.
- **`npm test` passing does NOT mean the bundle builds.** Vitest strips types. Run `npm run build` before claiming frontend work is done.
- **Commit style:** `feat(core):`, `fix(gui):`, `docs(spec):`, `build(gui):`. Bodies are long and argumentative, use `--` not em dashes, and end with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Do NOT regenerate any golden** unless a task explicitly says to. If a golden moves unexpectedly, the change is wrong — stop and diagnose.

## Environment

Nothing is installed on this machine. Task 0 handles it.

| Need | Command | Note |
| --- | --- | --- |
| Python deps | `python -m pip install -e ".[all,tests]"` | Exactly CI's line. `[all]` or `[tests]` alone = collection errors. |
| Full python suite | `python -m pytest` | From repo root. `testpaths`/`addopts` come from pyproject; add no flags. |
| One python test | `python -m pytest tests/test_lineages.py::test_name` | No test classes exist anywhere. |
| Node | `/home/bonus/Software/miniforge3/envs/ambermeta/bin` | node v25.6.0, npm 11.8.0. `node_modules/` absent. |
| Frontend suite | `cd ambermeta/gui/frontend && npm ci && npm test` | `npm test` is `vitest run`. |
| One frontend test | `npx vitest run src/path/X.test.tsx -t "sentence"` | From `ambermeta/gui/frontend`. |
| Type check | `npx tsc --noEmit` | The only automated type gate. CI runs no Python linter/typechecker. |
| Bundle | `npm ci && npm run build`, then `git add -A ambermeta/gui/static` | `emptyOutDir: true`; asset names are content-hashed, so `-A` is required to stage deletions. |

**CI jobs:** pytest 3.9, pytest 3.12, vitest (node 20), GUI Static Build Check (`paths:` filter on `frontend/src/**`, `vite.config.ts`, `package*.json`), CLI Docs Sync Check (`docs/cli.md` only).

**No Python 3.11 exists on this box**, so `python scripts/export_cli_help.py` cannot run. No task here changes `ambermeta/cli.py`'s *help text*, so `docs/cli.md` should not need regenerating — Task 14 verifies that.

---

### Task 0: Environment and baseline

**Files:** none (no commit).

- [ ] **Step 1: Install**

```bash
cd /home/bonus/git/ambermeta
python -m pip install -e ".[all,tests]"
```

- [ ] **Step 2: Capture the Python baseline**

```bash
python -m pytest -q 2>&1 | tail -3
```

Record the passing count. PR #77's body says `476 pytest on Python 3.9 and 3.12, 286 vitest.` — expect a number near 476. Write it down; the final commit states the delta.

- [ ] **Step 3: Capture the frontend baseline**

```bash
cd /home/bonus/git/ambermeta/ambermeta/gui/frontend
npm ci
npm test 2>&1 | tail -5
```

Expect ~286 passing.

- [ ] **Step 4: Confirm the committed bundle is byte-identical to a fresh build**

```bash
npm run build
cd /home/bonus/git/ambermeta && git status --porcelain ambermeta/gui/static
```

Expected: **empty output**. If not, stop — the branch has a pre-existing bundle drift that must be resolved before any frontend task, or Task 14's diff will be unattributable.

**Verify:** both baselines recorded, `git status --porcelain ambermeta/gui/static` empty.

---

### Task 1: Teach the fixture helper to write mdouts

Everything in P1 needs a fixture that can express *ran* / *truncated* / *unusable* / *queued*, and `write_run_tree` writes mdin only. It also crashes on stems whose name contains none of `min`/`heat`/`equil`/`prod` — which is every real `sys021` stem.

**Files:**
- Modify: `tests/conftest.py:33-45` (`write_run_tree`), plus a new `sys021_tree` fixture at end of file.

**Interfaces:**
- Produces: `write_run_tree(root, runs, *, mdin=None, mdout=None)` where `runs` may be a list of stems (as today) **or** a list of `(stem, spec)` pairs; `spec` is a `RunSpec`.
- Produces: `RunSpec(mdin: str, elapsed_ps: float | None, begin_ps: float | None, dt: float, inpcrd: str | None)` — a NamedTuple describing what to write for one run. `elapsed_ps=None` means **write no mdout** (queued).
- Produces: fixture `sys021_tree(tmp_path) -> Path`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_lineages.py` (new section banner `# --- the sys021 shape ---`):

```python
def test_the_sys021_fixture_has_five_equil_and_five_prod_directories(sys021_tree):
    """The fixture the whole spec is written against, pinned so a later edit cannot
    quietly reshape it. `prod/01` carries the stray `cpptraj` run that put it in a cohort
    of its own -- removing it would make the reconciliation task pass for the wrong
    reason."""
    equil = sorted(p.name for p in (sys021_tree / "equil").iterdir())
    prod = sorted(p.name for p in (sys021_tree / "prod").iterdir())
    assert equil == ["01", "02", "03", "04", "05"]
    assert prod == ["01", "02", "03", "04", "05"]
    assert (sys021_tree / "prod" / "01" / "cpptraj.in").exists()
    # rep 01 ran one chunk further than the rest, and every rep has one queued chunk.
    assert (sys021_tree / "prod" / "01" / "nvt_prod_0003.mdout").exists()
    assert not (sys021_tree / "prod" / "01" / "nvt_prod_0004.mdout").exists()
    assert (sys021_tree / "prod" / "01" / "nvt_prod_0004.mdin").exists()
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_lineages.py -k sys021_fixture`
Expected: FAIL — `fixture 'sys021_tree' not found`.

- [ ] **Step 3: Extend the helper**

Replace `tests/conftest.py:33-45` with:

```python
class RunSpec(NamedTuple):
    """What to write on disk for one run.

    `elapsed_ps=None` writes NO mdout, which is how a queued run -- an mdin that was set
    up and never executed -- is expressed. Every other field only matters when an mdout is
    written. `inpcrd` becomes the File Assignments line AMBER itself records, which is the
    evidence P2.4's handoff proposal reads; None omits the whole block, which is what a
    clipped or absent assignment looks like.
    """
    mdin: str
    elapsed_ps: Optional[float] = None
    begin_ps: float = 0.0
    dt: float = 0.002
    inpcrd: Optional[str] = None
    frames: int = 5


def _mdout_text(spec: RunSpec) -> str:
    """The smallest mdout carrying everything the engine reads off one.

    Three blocks, in AMBER's own order: the File Assignments block `read_mdout_header`
    parses, a CONTROL DATA block giving `imin`/`nstlim`/`dt`, and `frames` NSTEP records.

    The NSTEP times are ABSOLUTE, spanning `begin_ps` (exclusive) to
    `begin_ps + elapsed_ps` (inclusive) -- which is the whole reason `_sum_stages` cannot
    sum `time_end` directly. A fixture that wrote elapsed times here would let the wrong
    formula pass.
    """
    assign = ""
    if spec.inpcrd is not None:
        assign = (
            "File Assignments:\n"
            "|   MDIN: mdin\n"
            "|  MDOUT: mdout\n"
            f"| INPCRD: {spec.inpcrd}\n"
            "|   PARM: prmtop\n"
        )
    head = (
        f"{assign}\n"
        "   2.  CONTROL  DATA  FOR  THE  RUN\n"
        f"     imin    = 0, nstlim  = {int(spec.elapsed_ps / spec.dt)}, dt = {spec.dt:.5f}\n"
        f" begin time read from input coords = {spec.begin_ps:.3f} ps\n\n"
        "   4.  RESULTS\n\n"
    )
    step_of = spec.elapsed_ps / spec.frames
    body = ""
    for i in range(1, spec.frames + 1):
        t = spec.begin_ps + step_of * i
        body += (
            f" NSTEP = {int(step_of * i / spec.dt):>8}   TIME(PS) = {t:>11.3f}"
            f"  TEMP(K) =   300.00  PRESS =     0.0\n"
            " Etot   =    -1000.0000  EKtot   =      200.0000  EPtot      =    -1200.0000\n"
            "  ----------------------------------------------------------------\n"
        )
    return head + body + "\n      5.  TIMINGS\n"


def write_run_tree(root: Path, runs) -> Path:
    """Write the files for each entry of `runs`, creating directories as needed.

    An entry is either a bare posix stem -- the original behaviour, one role-matched mdin
    and nothing else -- or a `(stem, RunSpec)` pair spelling out exactly what to write.

    The bare form still writes mdin ONLY. That was a deliberate speed choice and it stays
    the default, but it means every tree built from it reads as entirely `queued` once
    totals come from the mdout, so a fixture asserting on time MUST use the pair form.

    The bare form also picks its mdin by substring, which raises StopIteration for a stem
    named after neither min/heat/equil/prod (`18_ntp_equi`, `cpptraj`). That is why the
    pair form exists: real campaign stems do not follow this repo's fixture naming.
    """
    for entry in runs:
        stem, spec = entry if isinstance(entry, tuple) else (entry, None)
        if spec is None:
            kind = next(k for k in _REPLICA_MDIN if k in Path(stem).name)
            spec = RunSpec(mdin=_REPLICA_MDIN[kind])
        path = root / (stem + ".mdin")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(spec.mdin, encoding="utf-8")
        if spec.elapsed_ps is not None:
            (root / (stem + ".mdout")).write_text(_mdout_text(spec), encoding="utf-8")
    return root
```

Add `from typing import NamedTuple, Optional` to the imports at the top of the file.

- [ ] **Step 4: Add the `sys021_tree` fixture**

Append to `tests/conftest.py`:

```python
_PROD_MDIN = ("production\n &cntrl\n  imin = 0, irest = 1, nstlim = 2500000,\n"
              "  dt = 0.002, ntb = 2,\n /\n")
_EQUI_MDIN = ("equilibrate\n &cntrl\n  imin = 0, nstlim = 2500000, dt = 0.002,\n"
              "  temp0 = 300.0, ntb = 2,\n /\n")
_CPPTRAJ_IN = "trajin nvt_prod_0001.nc\nautoimage\ntrajout stripped.nc\n"


@pytest.fixture
def sys021_tree(tmp_path) -> Path:
    """The real campaign this spec was written against, scaled down.

    Five replicas, each an `equil/NN` directory feeding a `prod/NN` directory. Three
    things about the real tree are load-bearing and are reproduced exactly:

    * `prod/01` holds a stray `cpptraj.in`, which the extension-based file typing reads as
      an AMBER mdin. That puts `prod/01` in a run-base cohort of its own, which is what
      made the first draft of the reconciliation rule refuse this tree entirely;
    * every replica has one final chunk with an mdin and no mdout -- queued, never run --
      which is the 25 ns the old totals counted as simulated;
    * replica 01 completed one chunk more than 02-05, which is the only genuine asymmetry
      in the campaign and must survive as a finding rather than as a phantom missing run.

    Each prod chunk is 5000 ps, matching the real `nstlim=2500000, dt=0.002`. Times are
    absolute and continuous within a replica, so a totals rule that sums `time_end`
    instead of elapsed time gives a visibly wrong number here.
    """
    runs = []
    for n in ("01", "02", "03", "04", "05"):
        # Equilibration: one 5000 ps run, ending where production picks up.
        runs.append((f"equil/{n}/18_ntp_equi",
                     RunSpec(mdin=_EQUI_MDIN, elapsed_ps=5000.0, begin_ps=0.0,
                             inpcrd="17_ntp_equi.restrt")))
        ran = 3 if n == "01" else 2
        for i in range(1, ran + 1):
            runs.append((f"prod/{n}/nvt_prod_{i:04d}",
                         RunSpec(mdin=_PROD_MDIN, elapsed_ps=5000.0,
                                 begin_ps=5000.0 * i,
                                 inpcrd=("18_ntp_equi.restrt" if i == 1
                                         else f"nvt_prod_{i - 1:04d}.restrt"))))
        # The chunk that was queued and never ran: mdin, no mdout.
        runs.append((f"prod/{n}/nvt_prod_{ran + 1:04d}", RunSpec(mdin=_PROD_MDIN)))
    runs.append(("prod/01/cpptraj", RunSpec(mdin=_CPPTRAJ_IN)))
    return write_run_tree(tmp_path, runs)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_lineages.py -k sys021_fixture -v`
Expected: PASS.

- [ ] **Step 6: Verify no existing test regressed**

Run: `python -m pytest -q 2>&1 | tail -3`
Expected: same count as the Task 0 baseline, **plus 1**. The bare-stem path is unchanged, so every existing fixture writes exactly what it wrote before.

- [ ] **Step 7: Commit**

```bash
git add tests/conftest.py tests/test_lineages.py
git commit -m "test: a fixture helper that can write mdouts, and the sys021 tree

write_run_tree wrote mdin only, which was a deliberate speed choice and stays
the default. But nothing in P1 can be expressed without an mdout -- ran,
truncated, unusable and queued are all distinctions in that file -- and the
helper crashed outright on any stem named after neither min/heat/equil/prod,
which is every real campaign stem.

The pair form spells out what to write. Times in the generated mdout are
ABSOLUTE, as AMBER writes them, so a totals rule that sums time_end rather
than elapsed time produces a visibly wrong number against this fixture rather
than passing by luck.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

**Verify:** baseline + 1 passing; `git diff HEAD~1 --stat` touches only the two test files.

---

### Task 2: Totals come from elapsed mdout time (P1.1)

**Files:**
- Modify: `ambermeta/protocol.py:540-558` (`_sum_stages`)
- Test: `tests/test_protocol_totals_from_mdout.py` (new)

**Interfaces:**
- Consumes: `RunSpec`, `sys021_tree` from Task 1.
- Produces: `_sum_stages` returns `{"steps": float, "time_ps": float}` unchanged in shape. New module-level helper `_elapsed_ps(stage) -> Optional[float]` in `protocol.py`, returning `None` when the stage contributed nothing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_protocol_totals_from_mdout.py`:

```python
# tests/test_protocol_totals_from_mdout.py
"""Totals are what ran, not what was queued.

Pins the arithmetic of `SimulationProtocol._sum_stages` after it stopped reading the
mdin. What is deliberately NOT asserted here: which steps carry the `queued` marker (that
is test_protocol_queued.py) and anything about lineages.

The formula is `stats.time_end - mdout_header.begin_time_ps`. The two obvious wrong
answers both have a test below, because both produce plausible-looking numbers:
summing `time_end` treats an absolute clock reading as a duration, and
`time_end - time_start` is short by one ntpr interval per run.
"""
from __future__ import annotations

from ambermeta.protocol import auto_discover


# --- the core arithmetic ---

def test_a_queued_run_contributes_no_time(sys021_tree):
    """Five chunks were set up and never executed. The old rule read nstlim x dt off the
    mdin and counted all five, which on the real campaign was 25 ns of simulation that
    never happened, reported with ok: true."""
    totals = auto_discover(str(sys021_tree), recursive=True).totals()
    # 5 equil x 5000 + (3 + 2 + 2 + 2 + 2) prod x 5000
    assert totals["time_ps"] == 80000.0


def test_the_total_is_not_the_sum_of_absolute_end_times(sys021_tree):
    """`stats.time_end` is an absolute AMBER clock reading. Summing it directly gave
    304,600 ps against a true 100,000 ps on the back-compat fixture -- a worse error than
    the one being fixed. This asserts the number is the elapsed sum, not the absolute one."""
    totals = auto_discover(str(sys021_tree), recursive=True).totals()
    absolute_sum = 5 * 5000.0 + sum(
        5000.0 * i for reps in ((3,), (2,), (2,), (2,), (2,)) for ran in reps
        for i in range(2, ran + 2))
    assert totals["time_ps"] != absolute_sum
    assert totals["time_ps"] == 80000.0


def test_steps_are_derived_from_elapsed_time_and_dt(sys021_tree):
    """The final NSTEP is not retrievable -- ThermoStats parses the key and discards it,
    and MdoutMetadata.nstlim is the control-data intent, identical to the mdin's. So
    steps-that-ran is elapsed/dt and there is no other source."""
    totals = auto_discover(str(sys021_tree), recursive=True).totals()
    assert totals["steps"] == 80000.0 / 0.002
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_protocol_totals_from_mdout.py -v`
Expected: FAIL on `test_a_queued_run_contributes_no_time` — the current rule reads the mdin, so every stem including the queued ones contributes `2500000 × 0.002 = 5000 ps`, giving `100000.0`.

- [ ] **Step 3: Implement**

Add above `SimulationProtocol` in `ambermeta/protocol.py`:

```python
def _elapsed_ps(stage: "SimulationStage") -> Optional[float]:
    """How much simulated time this stage actually produced, or None.

    None means "contributed nothing", and it covers four different situations that all
    have to be told apart by the caller for the note it writes, but not here:

    * queued -- an mdin with no mdout. The run was set up and never executed. Counting it
      was the bug: on the campaign this was written against it was 25 ns of simulation
      that never happened, reported with ok: true;
    * minimisation -- a min mdout prints `NSTEP ENERGY RMS GMAX`, never `TIME(PS)`, so it
      has no elapsed time and never had one. It contributed 0 under the old rule too
      (no nstlim/dt in the mdin), so this is not a change;
    * unreadable -- `parse_mdout` catches nothing and returns a default-valued object
      rather than raising, so a malformed-but-present mdout arrives as `stats.count == 0`
      rather than as `stage.mdout is None`;
    * no stated begin -- the `begin time read from input coords` line is absent for
      irest=0 runs. Falling back to 0.0 would make an absolute time look like an elapsed
      one, which is the 304,600-ps-against-100,000 bug, so silence is the only truthful
      answer.

    `time_end` is ABSOLUTE. `time_end - time_start` is NOT the alternative: `time_start`
    is the first PRINTED frame, one ntpr interval after the true begin, which is short by
    one interval per run -- the trap already documented at `_check_stage_pair`.
    """
    if stage.mdout is None or stage.mdout.details is None:
        return None
    details = stage.mdout.details
    if getattr(details, "run_type", None) == "Minimization":
        return None
    stats = getattr(details, "stats", None)
    if stats is None or getattr(stats, "count", 0) == 0:
        return None
    if stage.mdout_header is None:
        return None
    begin = getattr(stage.mdout_header, "begin_time_ps", None)
    end = getattr(stats, "time_end", None)
    if begin is None or end is None:
        return None
    elapsed = float(end) - float(begin)
    return elapsed if elapsed > 0 else None
```

Replace the body of `_sum_stages` (keeping the existing docstring and **extending** it):

```python
    @staticmethod
    def _sum_stages(stages: List[SimulationStage]) -> Dict[str, float]:
        """`steps` and `time_ps` over any set of stages, counting only what ran.

        Sourced from the mdout, not the mdin: the mdin states intent and a run that was
        queued and never started, or started and was killed at 60%, states the same
        intent as one that finished. See `_elapsed_ps` for what "ran" means and for why
        the formula is `time_end - begin_time_ps`.

        Accumulated with ``+=`` rather than ``sum()`` on purpose: CPython 3.12 made
        ``builtins.sum`` compensated, and CI's matrix is 3.9 *and* 3.12, so a float total
        built with ``sum()`` can differ in its last bits between the two jobs -- on the one
        artifact every lineage change is told to keep byte-stable.
        """
        total_steps = 0.0
        total_time = 0.0
        for stage in stages:
            elapsed = _elapsed_ps(stage)
            if elapsed is None:
                continue
            total_time += elapsed
            dt = None
            if stage.mdout and stage.mdout.details:
                dt = getattr(stage.mdout.details, "dt", None)
            if not dt and stage.mdin and stage.mdin.details:
                dt = getattr(stage.mdin.details, "dt", None)
            if isinstance(dt, (int, float)) and dt > 0:
                total_steps += elapsed / float(dt)
        return {"steps": total_steps, "time_ps": total_time}
```

Ensure `Optional` is imported in `protocol.py` (it is).

- [ ] **Step 4: Run the new test to verify it passes**

Run: `python -m pytest tests/test_protocol_totals_from_mdout.py -v`
Expected: PASS, all three.

- [ ] **Step 5: Run the back-compat golden — it must NOT move**

Run: `python -m pytest tests/test_lineage_backcompat.py -v`
Expected: **PASS with no golden regeneration.** The fixture's five chunks read 20920/40920/60920/80920/100920 ps with a 920 ps begin, and `sum(time_end - begin_time_ps) == 100000.0`, `sum(elapsed/dt) == 25000000.0` — exactly what `tests/data/lineage_backcompat/summary.json` holds.

**If this fails, the formula is wrong. Do not regenerate the golden — diagnose.** Print the per-stage `(time_end, begin_time_ps, dt)` and compare against the stated 100,000 ps.

- [ ] **Step 6: Run the whole suite and triage the expected failures**

Run: `python -m pytest -q 2>&1 | tail -30`

Expect failures in tests whose fixtures are mdin-only and assert on time. The known one is `tests/test_lineage_totals.py:67` (`breakdown["rep2"]["time_ps"] < breakdown["rep1"]["time_ps"]`), which degenerates to `0.0 < 0.0`.

Fix by converting the fixtures those tests use to the pair form. For `crashed_replica_tree`, give each run `RunSpec(mdin=..., elapsed_ps=1000.0, begin_ps=1000.0*i)` so rep2's single chunk really is shorter than rep1's three. Update `tests/conftest.py` and re-run.

List every test you changed and why in the commit body.

- [ ] **Step 7: Commit**

```bash
git add ambermeta/protocol.py tests/test_protocol_totals_from_mdout.py tests/conftest.py tests/test_lineage_totals.py
git commit -m "feat(core): totals count what ran, not what was queued

_sum_stages read length_steps x dt off the mdin and never asked whether the
run produced output. On the campaign this was written against that counted
five queued chunks -- 25 ns of simulation that never happened -- and rounded
every wall-clock-killed run up to its full intent.

Totals now come from the mdout, as elapsed time:

    time_end - mdout_header.begin_time_ps

time_end is an ABSOLUTE clock reading. Summing it directly gives 304,600 ps
against a true 100,000 ps on the back-compat fixture. time_end - time_start
is not the alternative either -- time_start is the first PRINTED frame, one
ntpr interval late, giving 99,500 ps. The trap is already documented at
_check_stage_pair:451-456.

The chosen formula reproduces tests/data/lineage_backcompat/summary.json
exactly, so no golden moved and none was regenerated.

BEHAVIOUR CHANGE: any project holding a queued or truncated run now reports
a smaller total than before. This is intended and is the point of the change.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

**Verify:** `python -m pytest -q` green; `git status --porcelain tests/data/` empty (no golden touched).

---

### Task 3: Queued runs carry a status and are reported (P1.2)

**Files:**
- Modify: `ambermeta/simulation.py` — `Step` dataclass, `_step_payload`, `payload_to_simulation`
- Modify: `ambermeta/gui/api/core_bridge.py:79` (`document_to_payload` whitelist), `_flatten_simulation`
- Modify: `ambermeta/gui/api/schemas.py` (`StepModel`), `ambermeta/gui/api/document.py` (`_sim_to_model`)
- Modify: `ambermeta/protocol.py` — `SimulationStage.status`, `sequence_findings` reporting
- Modify: `ambermeta/cli.py` — the per-lineage print
- Test: `tests/test_protocol_queued.py` (new), `tests/test_simulation.py` (two added)

**Interfaces:**
- Consumes: `_elapsed_ps` from Task 2.
- Produces: `Step.status: Optional[str] = None` (only ever `None` or `"queued"`); `SimulationStage.status: Optional[str] = None`; `StepModel.status: Optional[str]`.

> **The emit-when-set rule is load-bearing here.** `HAND_WRITTEN_MANIFEST`'s `st_prod_003` has an mdin and no mdout — it *is* a queued step — and `manifest_payload.json:85-99` has no `status` key and is compared with `==`. So `status` must default to `None`, be emitted only when set, and **must not be inferred inside `_step_payload`**. Inference belongs in `discover_draft` and in the engine, never at payload time.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_protocol_queued.py`:

```python
# tests/test_protocol_queued.py
"""A run that was set up and never executed stays in the record, costing nothing.

Deleting it would hide that a campaign was cut short; counting it was the bug. What is
deliberately NOT asserted here: the arithmetic (test_protocol_totals_from_mdout.py).
"""
from __future__ import annotations

from ambermeta.protocol import auto_discover


def test_a_stem_with_an_mdin_and_no_mdout_is_marked_queued(sys021_tree):
    protocol = auto_discover(str(sys021_tree), recursive=True)
    queued = sorted(s.name for s in protocol.stages if s.status == "queued")
    assert queued == [
        "prod/01/nvt_prod_0004", "prod/02/nvt_prod_0003", "prod/03/nvt_prod_0003",
        "prod/04/nvt_prod_0003", "prod/05/nvt_prod_0003",
    ]


def test_a_run_that_produced_output_carries_no_status(sys021_tree):
    """Emit-when-set: only the non-default value is ever recorded, so an ordinary
    document's artifacts are byte-identical to what they were before the field existed."""
    protocol = auto_discover(str(sys021_tree), recursive=True)
    ran = [s for s in protocol.stages if s.name == "prod/01/nvt_prod_0001"]
    assert ran and ran[0].status is None


def test_the_artifact_reports_queued_runs_beside_the_completed_ones(sys021_tree):
    protocol = auto_discover(str(sys021_tree), recursive=True)
    assert protocol.to_dict()["totals"]["queued_count"] == 5.0
```

Add to `tests/test_simulation.py`:

```python
def test_status_round_trips_through_the_v2_payload():
    sim = Simulation(name="s", phases=[Phase(id="p1", name="Production", role="production",
                                             steps=[Step(id="s1", name="prod_0002",
                                                         status="queued")])])
    payload = simulation_to_payload(sim)
    assert payload["phases"][0]["steps"][0]["status"] == "queued"
    assert payload_to_simulation(payload) == sim


def test_a_step_with_no_status_keeps_the_payload_it_always_had():
    sim = Simulation(name="s", phases=[Phase(id="p1", name="Production", role="production",
                                             steps=[Step(id="s1", name="prod_0001")])])
    assert "status" not in simulation_to_payload(sim)["phases"][0]["steps"][0]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_protocol_queued.py tests/test_simulation.py -k status -v`
Expected: FAIL — `Step.__init__() got an unexpected keyword argument 'status'`.

- [ ] **Step 3: Add the field in all six places**

`ambermeta/simulation.py`, on `Step` (beside `lineage`):

```python
    # Whether this run produced output. The only non-default value is "queued": an mdin
    # that was set up and never executed. It lives on Step rather than being derived at
    # read time because _adopt_legacy_restart_paths rebuilds InputCoords wholesale on
    # every load, and anything stored there is dropped on the next one.
    #
    # NOT inferred in _step_payload. The hand-written manifest fixture holds a step with
    # an mdin and no mdout whose golden block has no status key and is compared with ==;
    # inferring at payload time would rewrite it. Inference belongs to discover and to the
    # engine, which have the files in front of them.
    status: Optional[str] = None
```

In `_step_payload`, beside the `rst`/`lineage` blocks:

```python
    if step.status is not None:
        data["status"] = step.status
```

In `payload_to_simulation`, beside the `lineage` read:

```python
    # An unrecognised spelling reads as no status rather than raising, matching the
    # "a skipped file costs a note and exit 0" fault tolerance the rest of the loader has.
    status = s.get("status")
    status = status if status == "queued" else None
```

and pass `status=status` to the `Step(...)` construction.

`ambermeta/gui/api/core_bridge.py:79` — add to the whitelist loop:

```python
    for provenance in ("lineage", "step_id", "parent_id", "status"):
```

(the loop's existing `if val:` truthiness guard keeps `test_an_untagged_step_adds_no_key_to_the_engine_payload` green, because the default is `None`).

Add `status` to `_flatten_simulation`'s dict literal, to `schemas.StepModel` (`status: Optional[str] = None`, with a comment saying only `"queued"` is ever emitted), and to `document._sim_to_model`'s field-by-field construction.

`ambermeta/protocol.py` — add `status: Optional[str] = None` to `SimulationStage`, set it in **both** engine entry points (`auto_discover`'s scan branch at ~`:2016` and `_manifest_to_stages` at ~`:1194`) when the group has an mdin and no mdout, and add `queued_count` to `totals()` emit-when-nonzero:

```python
        queued = sum(1 for s in self.stages if s.status == "queued")
        if queued:
            out["queued_count"] = float(queued)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_protocol_queued.py tests/test_simulation.py -v`
Expected: PASS.

- [ ] **Step 5: Add the plumbing test the repo requires for a new Step field**

Add to `tests/test_lineage_plumbing.py`, matching its existing style:

```python
def test_a_queued_status_reaches_the_engine_payload():
    """Adding a field to Step is a four-place change and three of the four fail silently:
    validate_manifest rejects no unknown key and pydantic's extra='ignore' drops one. This
    is the test that catches a status that never left the model."""
    sim = Simulation(name="s", phases=[Phase(id="p1", name="Production", role="production",
                                             steps=[Step(id="s1", name="prod_0002",
                                                         status="queued")])])
    payload = document_to_payload(sim)
    assert payload["stages"][0]["status"] == "queued"
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q 2>&1 | tail -5`
Expected: green. Pay particular attention to `test_lineage_backcompat.py::test_the_manifest_payload_is_byte_identical` — it must still pass, which is what the emit-when-set rule buys.

- [ ] **Step 7: Commit**

```bash
git add -A ambermeta tests
git commit -m "feat(core): a queued run stays in the record and costs nothing

A stem with an mdin and no mdout was indistinguishable from one that ran.
Step and SimulationStage now carry an optional status whose only non-default
value is \"queued\", and totals report queued_count beside the rest.

Emit-when-set throughout, and NOT inferred at payload time: the hand-written
manifest fixture holds a step with an mdin and no mdout whose golden block
has no status key and is compared with ==. Inference belongs to discover and
to the engine, which have the files in front of them.

Added in six places, because three of them fail silently -- the model, both
engine entry points, document_to_payload's whitelist, _flatten_simulation,
StepModel and _sim_to_model -- plus the plumbing test that catches a field
that never leaves the model.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

**Verify:** `python -m pytest -q` green; `git status --porcelain tests/data/` empty.

---

### Task 4: Never write an edge that crosses a run directory (P1.3)

**Files:**
- Modify: `ambermeta/gui/api/core_bridge.py:495-527` (the `prev_by_lineage` chain)
- Test: `tests/test_gui_core_bridge_sim.py` (modify one, add two)

**Interfaces:**
- Consumes: `sys021_tree`.
- Produces: no new API. `discover_draft`'s edge set changes.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_gui_core_bridge_sim.py`:

```python
def test_discover_draft_never_chains_across_a_run_directory(sys021_tree):
    """The nine edges this removes were the whole reason a 1097-run campaign published as
    one serial 5.055 us trajectory. They self-validated, too: resolve_input_coords hands a
    source="step" consumer the PRODUCER'S OWN restart, so _check_stage_pair compared a run's
    end time against its own output and saw observed_gap_ps = 0.0 every time."""
    sim = core_bridge.discover_draft(str(sys021_tree), recursive=True)["simulation"]
    by_id = {s.id: s for _, s in iter_steps(sim)}
    for _, step in iter_steps(sim):
        if step.input_coords and step.input_coords.source == "step":
            producer = by_id[step.input_coords.ref]
            assert producer.name.rpartition("/")[0] == step.name.rpartition("/")[0], (
                f"{step.name} reads a restart written by {producer.name}")


def test_discover_draft_still_chains_within_one_directory(sys021_tree):
    """The within-directory chain is what makes a chunked run a chain, and it cannot be
    wrong about membership because it never leaves the directory. Removing it would gut the
    default output of every existing single-replica project."""
    sim = core_bridge.discover_draft(str(sys021_tree), recursive=True)["simulation"]
    by_id = {s.id: s for _, s in iter_steps(sim)}
    edges = {s.name: by_id[s.input_coords.ref].name
             for _, s in iter_steps(sim)
             if s.input_coords and s.input_coords.source == "step"}
    assert edges["prod/01/nvt_prod_0002"] == "prod/01/nvt_prod_0001"
    assert edges["prod/01/nvt_prod_0003"] == "prod/01/nvt_prod_0002"
    # The head of a directory reads the starting structure, not the previous directory.
    assert "prod/01/nvt_prod_0001" not in edges
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_gui_core_bridge_sim.py -k never_chains_across -v`
Expected: FAIL — `prod/01/nvt_prod_0001 reads a restart written by equil/05/18_ntp_equi`.

- [ ] **Step 3: Implement**

In `core_bridge.discover_draft`, replace the `prev_by_lineage` keying. Change the dict to be keyed on the run **directory** rather than the lineage bucket:

```python
    # Keyed on the run DIRECTORY, not on the lineage bucket. On an untagged tree every
    # stem shared the UNTAGGED bucket, which is exactly how one flat chain came to run
    # equil/01 -> equil/02 -> ... -> prod/05: nine edges nobody asserted, published with
    # ok: true, and self-validating because resolve_input_coords hands the consumer the
    # producer's own restart so the gap is always 0.0.
    #
    # A directory boundary is the only boundary discovery can justify. Within one, the
    # chunked chain prod_0001 -> prod_0002 is what the numbering means. Across one, the
    # evidence lives in the mdout's File Assignments block, and that is PROPOSED rather
    # than written -- see the handoff proposal.
    prev_by_directory: Dict[str, str] = {}
```

and at the point the edge is created, replace the lookup:

```python
        directory = stem.rpartition("/")[0]
        previous = prev_by_directory.get(directory)
        if previous is None:
            step.input_coords = InputCoords(source="starting_structure")
        else:
            step.input_coords = InputCoords(source="step", ref=previous)
        prev_by_directory[directory] = step.id
```

Keep `phase_index_by_lineage` and the `multi_lineage` phase grouping untouched — Task 7 changes how `multi_lineage` is derived, not what it does.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_gui_core_bridge_sim.py -v`
Expected: two new PASS. **`test_discover_draft_leaves_an_ambiguous_tree_untagged_and_serially_chained` will FAIL** — it asserts `300K/rep2/prod_0001` reads `300K/rep1/prod_0001` plus two more crossings.

- [ ] **Step 5: Update that test to the new contract**

Rewrite its assertion to expect **no** cross-directory edges, and rename it to
`test_discover_draft_leaves_an_ambiguous_tree_untagged_and_unchained`. Its docstring must record the change: the nested sweep now yields four single-run directories with no edges at all, because nothing justifies one.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q 2>&1 | tail -5`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add -A ambermeta tests
git commit -m "feat(gui): discovery stops chaining across run directories

prev_by_lineage was keyed on the lineage bucket, so on an untagged tree every
stem shared one UNTAGGED bucket and the chain ran straight through the tree:
equil/01 -> equil/02 -> ... -> equil/05 -> prod/01 -> ... -> prod/05. Nine
edges on the campaign this was written against, none of them asserted by
anyone, all published with ok: true.

They self-validated, which is why nothing caught them: resolve_input_coords
hands a source=\"step\" consumer the PRODUCER'S OWN restart, so
_check_stage_pair compared a run's end time against its own output file and
saw observed_gap_ps = 0.0 every time.

Keyed on the run directory instead. Within a directory the chunked chain is
what the numbering means; across one the only evidence is the mdout's File
Assignments block, which is proposed rather than written.

BEHAVIOUR CHANGE: a tree of single-run directories now discovers with no
edges at all rather than one serial chain.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

**Verify:** `python -m pytest -q` green.

---

### Task 5: Report the totals delta against a prior summary.json (P1.1)

**Files:**
- Modify: `ambermeta/cli.py` — the `plan` write path
- Test: `tests/test_cli_totals_delta.py` (new)

**Interfaces:**
- Consumes: Task 2's totals.
- Produces: `_totals_delta(previous: dict, current: dict) -> Optional[str]` in `cli.py`.

> The v2 manifest stores no totals — `simulation_to_payload` emits version/simulation/phases/steps and nothing else — so the comparison is against a previously written `summary.json`, which is where totals live.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_totals_delta.py
"""When plan is about to contradict a number it wrote before, it says so.

The rule changed under existing projects: any tree holding a queued or truncated run now
reports less than it did. A user who quoted the old figure gets told, once, at the moment
the file is overwritten -- not by noticing later that two artifacts disagree.
"""
from __future__ import annotations

import json

from ambermeta.cli import main


def test_plan_reports_the_delta_when_it_contradicts_an_earlier_summary(sys021_tree, capsys):
    out = sys021_tree / "out"
    out.mkdir()
    (out / "summary.json").write_text(json.dumps(
        {"totals": {"steps": 50000000.0, "time_ps": 100000.0}, "stages": []}),
        encoding="utf-8")
    main(["plan", "--recursive", str(sys021_tree), "--output", str(out)])
    printed = capsys.readouterr().out
    assert "totals changed since the last summary.json" in printed
    assert "100000.000" in printed and "80000.000" in printed


def test_plan_says_nothing_when_there_is_no_earlier_summary(sys021_tree, capsys):
    """No prior claim, nothing to contradict."""
    out = sys021_tree / "out"
    out.mkdir()
    main(["plan", "--recursive", str(sys021_tree), "--output", str(out)])
    assert "totals changed" not in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_cli_totals_delta.py -v`
Expected: FAIL — the string is not printed.

- [ ] **Step 3: Implement**

Add to `ambermeta/cli.py`:

```python
def _totals_delta(previous: Dict[str, Any], current: Dict[str, float]) -> Optional[str]:
    """A line for each total that moved, or None.

    Compared against summary.json rather than against the manifest because the v2
    manifest stores no totals and this change is not adding any -- the format stays as it
    is. Absent or unreadable prior artifacts mean no prior claim, hence nothing to say;
    an unreadable one is not an error worth failing a plan over.
    """
    before = (previous or {}).get("totals") or {}
    lines = []
    for key in ("steps", "time_ps"):
        old, new = before.get(key), current.get(key)
        if isinstance(old, (int, float)) and isinstance(new, (int, float)) and old != new:
            lines.append(f"  {key:<9} {float(old):.3f} -> {float(new):.3f}")
    if not lines:
        return None
    queued = int(current.get("queued_count") or 0)
    reason = (f"  reason    {queued} queued run(s) no longer counted "
              f"(mdin present, no mdout)" if queued else
              "  reason    totals now come from elapsed mdout time, not the mdin")
    return ("totals changed since the last summary.json in this directory:\n"
            + "\n".join(lines) + "\n" + reason)
```

Call it in the `plan` write path immediately before `summary.json` is written, reading any existing file with a `try/except (OSError, ValueError)` that yields `{}`, and `_out(...)` the result through `Colors.warning` when non-None.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_cli_totals_delta.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q 2>&1 | tail -5`
Expected: green. `tests/test_cli_protocol_output.py` asserts exact printed lines — confirm none of them moved.

- [ ] **Step 6: Commit**

```bash
git add -A ambermeta tests
git commit -m "feat(cli): plan says when it contradicts a total it wrote before

The rule changed under existing projects: any tree holding a queued or
truncated run reports less than it did. Compared against summary.json, not
against the manifest -- the v2 manifest stores no totals and this change is
not adding any.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

**Verify:** `python -m pytest -q` green.

---

### Task 6: Reconcile lineage cohorts (P2.1)

**Files:**
- Modify: `ambermeta/lineages.py:357-384` (`infer_lineages_from_layout` body; docstring extended)
- Test: `tests/test_lineages.py` (add a section)

**Interfaces:**
- Produces: `infer_lineages_from_layout(run_names) -> Dict[str, str]` — **signature unchanged**, it is re-exported at `ambermeta/__init__.py:22` and documented in `docs/api.md:107`.

> **This rule replaced a first draft that provably refused `sys021`.** `prod/01` also holds `cpptraj`, so its base set is `{cpptraj, nvt_prod}` against `prod/02..05`'s `{nvt_prod}`; it is alone in its cohort, dropped by `len(dirs) > 1`, and the surviving prod cohort yields `{02,03,04,05}` against equil's `{01..05}`. Equality refuses. Nesting plus absorption does not.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_lineages.py` under a new `# --- cohort reconciliation ---` banner:

```python
def test_a_prep_tree_beside_a_production_tree_is_one_campaign():
    """The shape the whole feature exists for, and the one the first draft of this rule
    refused. equil/* and prod/* run different sets of things, so they are rival cohorts
    under the old one-cohort rule and the campaign came back untagged."""
    names = [f"equil/{n}/18_ntp_equi" for n in ("01", "02", "03", "04", "05")]
    names += [f"prod/{n}/nvt_prod_{i:04d}"
              for n in ("01", "02", "03", "04", "05") for i in (1, 2)]
    tags = infer_lineages_from_layout(names)
    assert tags["equil/01/18_ntp_equi"] == "01"
    assert tags["prod/01/nvt_prod_0001"] == "01"
    assert tags["prod/05/nvt_prod_0002"] == "05"
    assert set(tags.values()) == {"01", "02", "03", "04", "05"}


def test_a_stray_analysis_file_does_not_cost_its_directory_its_tag():
    """prod/01 also holds a cpptraj run, which the extension-based typing reads as an
    mdin. That put it in a cohort of one, where len(dirs) > 1 drops it. Absorption exists
    for exactly this: its segment at the agreed index is already a reconciled tag."""
    names = [f"equil/{n}/18_ntp_equi" for n in ("01", "02", "03", "04", "05")]
    names += [f"prod/{n}/nvt_prod_0001" for n in ("01", "02", "03", "04", "05")]
    names += ["prod/01/cpptraj"]
    tags = infer_lineages_from_layout(names)
    assert tags["prod/01/nvt_prod_0001"] == "01"
    assert tags["prod/01/cpptraj"] == "01"


def test_a_member_missing_from_one_cohort_does_not_refuse_the_tree():
    """A replica that never reached production is still a replica. Nesting, not equality:
    the prod cohort's tag set is a subset of the equil cohort's."""
    names = [f"equil/{n}/18_ntp_equi" for n in ("01", "02", "03")]
    names += [f"prod/{n}/nvt_prod_0001" for n in ("01", "02")]
    tags = infer_lineages_from_layout(names)
    assert set(tags.values()) == {"01", "02", "03"}
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_lineages.py -k "prep_tree or stray_analysis or missing_from_one" -v`
Expected: all three FAIL with `KeyError` — the function returns `{}`.

- [ ] **Step 3: Implement**

Replace `ambermeta/lineages.py:366-384` (everything from the `cohorts` construction to the return) with:

```python
    cohorts: Dict[FrozenSet[str], List[str]] = {}
    for directory, runs in candidates.items():
        cohorts.setdefault(frozenset(_run_base(r) for r in runs), []).append(directory)

    # Each cohort of more than one directory reports its OWN varying segment, and a cohort
    # that cannot report one contributes nothing rather than refusing the whole tree --
    # a prep directory at a different depth must not be able to veto the replicas.
    #
    # Per cohort, never on the union: `equil/01..05` unioned with `prod/01..05` varies in
    # TWO segments at once (equil|prod at 0, 01..05 at 1) and the single-varying-segment
    # rule below refuses it. The cohorts each vary in one, and agree on which one.
    reports: List[Tuple[int, Dict[str, str]]] = []
    for dirs in cohorts.values():
        if len(dirs) < 2:
            continue
        segments = {d: d.split("/") for d in dirs}
        depths = {len(s) for s in segments.values()}
        if len(depths) != 1:
            continue
        varying = [i for i in range(depths.pop())
                   if len({segments[d][i] for d in dirs}) > 1]
        if len(varying) != 1:
            continue
        reports.append((varying[0], {d: segments[d][varying[0]] for d in dirs}))

    if not reports:
        return {}
    # Two cohorts naming their member at different depths are not one campaign.
    if len({index for index, _ in reports}) != 1:
        return {}
    index = reports[0][0]

    # Nested, not equal. A member that never reached production appears in the equil
    # cohort and not the prod one, and that is one campaign with a short member -- exactly
    # the crashed replica this feature exists to surface. Two DISJOINT sets are still two
    # experiments and are still refused, because neither contains the other.
    tag_sets = [set(mapping.values()) for _, mapping in reports]
    reconciled = max(tag_sets, key=len)
    if any(not tags <= reconciled for tags in tag_sets):
        return {}

    tagged = {d: tag for _, mapping in reports for d, tag in mapping.items()}

    # A directory alone in its cohort was dropped above. It is absorbed only when the tree
    # has already decided what the tags are and this directory's segment is one of them --
    # which is how a stray cpptraj.in stops costing prod/01 its membership, while a genuine
    # `common/` prep directory (whose segment is "common", not a tag) stays untagged.
    for dirs in cohorts.values():
        if len(dirs) != 1:
            continue
        parts = dirs[0].split("/")
        if len(parts) > index and parts[index] in reconciled:
            tagged[dirs[0]] = parts[index]

    return {f"{d}/{run}": tag for d, tag in tagged.items() for run in candidates[d]}
```

Add `Tuple` to the `typing` import. Extend the docstring: replace the "two rival families" bullet with a description of nesting-plus-absorption, keeping the refusals list accurate.

- [ ] **Step 4: Run the new tests**

Run: `python -m pytest tests/test_lineages.py -v`
Expected: PASS, including every existing refusal — `test_two_rival_families_tag_neither`, `test_a_shared_prep_directory_stays_untagged_and_out_of_the_count`, `test_runs_at_the_tree_root_fail_the_predicate…`, `test_a_single_lineage_in_a_subdirectory_stays_untagged`, `test_a_prep_run_at_a_different_depth_does_not_block_the_replicas`, and the nested-sweep refusal.

- [ ] **Step 5: Run the four call sites' tests**

Run: `python -m pytest tests/test_continuity_p1.py tests/test_gui_core_bridge_sim.py tests/test_lineage_totals.py tests/test_gui_bulk_lineage.py -q`
Expected: green. Widening inference also feeds `detect_numeric_sequences` via `smart_group_files`, so sequence-note assertions are part of this task's verification.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q 2>&1 | tail -5`

- [ ] **Step 7: Update the docs that state the old rule**

`docs/manifest.md:401` (the "two rival cohorts" table row), `docs/architecture.md:121`, `docs/api.md:107` and `:326`. Each must describe nesting and absorption. Leaving them is a new instance of exactly the problem Task 10 fixes.

- [ ] **Step 8: Commit**

```bash
git add -A ambermeta tests docs
git commit -m "feat(core): lineage inference reconciles cohorts instead of demanding one

The rule required exactly ONE directory cohort with more than one member,
so a prep tree beside a production tree -- equil/01..05 feeding prod/01..05,
which run different sets of things -- came back untagged. That is the
canonical multi-replica layout and the shape the feature exists for.

Cohorts now each report their own varying segment, must agree on which one,
and reconcile by NESTING rather than equality. Two disjoint sets are still
two experiments and are still refused. A member present in one cohort and
absent from another is one campaign with a short member, which is exactly
the crashed replica the sequence-hole finding exists to surface.

A directory left alone in its cohort is absorbed when its segment is already
a reconciled tag. This is not cosmetic: a single stray cpptraj.in gives
prod/01 a run-base set of its own, dropping it, and the surviving prod cohort
then yields {02,03,04,05} against equil's {01..05} -- which an equality rule
refuses. Verified against the real tree before this was written.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

**Verify:** `python -m pytest -q` green; `grep -rn "two rival cohorts" docs/` returns nothing stale.

---

### Task 7: A proposal object, and Discover stops writing tags (P2.2)

**Files:**
- Modify: `ambermeta/gui/api/core_bridge.py` (`discover_draft`), `schemas.py` (`DiscoverResult`, new `LineageProposal`), `routes.py` (`POST /steps/infer-lineages` returns a proposal)
- Test: `tests/test_gui_proposal.py` (new)

**Interfaces:**
- Produces: `core_bridge.build_lineage_proposal(sim, segment_index=None) -> Optional[dict]` returning
  `{"segment_index": int, "segments": List[List[str]], "members": [{"tag": str, "step_ids": List[str], "sources": [{"directory": str, "run_count": int}]}]}`.
- Produces: `schemas.LineageProposal`, `schemas.ProposedMember`, `schemas.ProposedSource`; `DiscoverResult.proposal: Optional[LineageProposal] = None` (**optional**, or `App.workflows.test.tsx:20`'s annotated literal breaks).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gui_proposal.py
"""Discover proposes a grouping and writes none of it.

The tool already silently claimed a serial chain nobody asserted; this is the surface that
makes "declaration, not inference" literally true. What is deliberately NOT asserted here:
the arithmetic of the inference itself (tests/test_lineages.py).
"""
from __future__ import annotations

from ambermeta.gui.api import core_bridge
from ambermeta.simulation import iter_steps


def test_discover_proposes_five_members_and_tags_nothing(sys021_tree):
    out = core_bridge.discover_draft(str(sys021_tree), recursive=True)
    assert [m["tag"] for m in out["proposal"]["members"]] == ["01", "02", "03", "04", "05"]
    assert all(step.lineage is None for _, step in iter_steps(out["simulation"]))


def test_the_proposal_names_the_directories_each_member_is_built_from(sys021_tree):
    out = core_bridge.discover_draft(str(sys021_tree), recursive=True)
    first = out["proposal"]["members"][0]
    assert sorted(s["directory"] for s in first["sources"]) == ["equil/01", "prod/01"]


def test_a_tree_the_inference_refuses_gets_no_proposal(nested_sweep_tree):
    out = core_bridge.discover_draft(str(nested_sweep_tree), recursive=True)
    assert out["proposal"] is None
    card, = [s for s in out["suggestions"] if s["kind"] == "needs_you"]
    assert "could not tell" in card["evidence"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_gui_proposal.py -v`
Expected: FAIL — `KeyError: 'proposal'`.

- [ ] **Step 3: Implement**

In `core_bridge.py`, add `build_lineage_proposal` and change `discover_draft` so that:

1. `tags = infer_lineages_from_layout(run_stems)` is computed as today.
2. **`step.lineage` is no longer assigned from it.**
3. `multi_lineage` is re-derived from the proposal: `multi_lineage = len({t for t in tags.values()}) >= 2`. This keeps phase-major grouping exactly as it is — without it, `test_discover_draft_groups_same_role_steps_from_every_lineage_into_one_phase` and `test_discover_draft_opens_a_new_phase_when_a_role_recurs` both break.
4. The returned dict gains `"proposal"`, and when `tags` is empty a `needs_you` suggestion card is appended **in `discover_draft`**, not in `build_suggestions` (which is called from three places and has no access to the scan; its comment at `:331-335` records why).

Declare `LineageProposal` / `ProposedMember` / `ProposedSource` on `schemas.py` and add `proposal: Optional[LineageProposal] = None` to `DiscoverResult`. Add `kind: "needs_you"` to whatever `Suggestion.kind` validates against.

Repoint `POST /steps/infer-lineages` to return the proposal rather than applying tags, keeping the leading `"No lineages inferred"` substring in its refusal message (`test_gui_bulk_lineage.py:213,222` assert on it).

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_gui_proposal.py tests/test_gui_core_bridge_sim.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q 2>&1 | tail -10`
Expected: green. `test_gui_bulk_lineage.py`'s infer-lineages tests will need their assertions moved from "tags were applied" to "a proposal came back"; update them and say so in the commit.

- [ ] **Step 6: Commit**

```bash
git add -A ambermeta tests
git commit -m "feat(gui): Discover proposes a grouping and writes none of it

Inference applied tags with no confirmation, which on an ambiguous tree is a
claim nobody made. discover_draft now returns a proposal -- members, their tag,
their step ids, and the directories each is built from -- and leaves
Step.lineage None until the user accepts.

multi_lineage is re-derived from the proposal rather than from written tags,
so phase-major layout is unchanged; only the tags are withheld.

A tree the inference refuses gets a needs_you card instead of the silence it
got before. Built in discover_draft, not in build_suggestions: that function
is called from three places and has no access to the scan, which its own
comment already records.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

**Verify:** `python -m pytest -q` green.

---

### Task 8: Handoffs proposed from AMBER's File Assignments (P2.4)

**Files:**
- Modify: `ambermeta/gui/api/core_bridge.py` (`discover_draft`)
- Test: `tests/test_gui_proposal.py` (add)

**Interfaces:**
- Produces: `proposal["handoffs"]: List[{"consumer_id": str, "producer_id": str, "consumer": str, "producer": str, "evidence": str}]`; `schemas.ProposedHandoff`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_handoff_proposal_reads_ambers_own_file_assignments(sys021_tree):
    """Every prod head's mdout records the restart AMBER actually read. The package has
    parsed that block since before this feature existed and had zero call sites for it."""
    out = core_bridge.discover_draft(str(sys021_tree), recursive=True)
    pairs = {h["consumer"]: h["producer"] for h in out["proposal"]["handoffs"]}
    assert pairs["prod/01/nvt_prod_0001"] == "equil/01/18_ntp_equi"
    assert pairs["prod/05/nvt_prod_0001"] == "equil/05/18_ntp_equi"
    assert len(pairs) == 5


def test_a_clipped_assignment_proposes_nothing_rather_than_guessing(tmp_path):
    """MdoutHeader.assignment returns None when AMBER clipped the value at the field
    width, which is common for long paths. That is no evidence, not no producer."""
    from tests.conftest import RunSpec, write_run_tree
    tree = write_run_tree(tmp_path, [
        ("a/prod_0001", RunSpec(mdin="production\n &cntrl\n imin=0, nstlim=100, dt=0.002,\n /\n",
                                elapsed_ps=100.0, inpcrd=None)),
        ("b/prod_0001", RunSpec(mdin="production\n &cntrl\n imin=0, nstlim=100, dt=0.002,\n /\n",
                                elapsed_ps=100.0, begin_ps=100.0, inpcrd=None)),
    ])
    out = core_bridge.discover_draft(str(tree), recursive=True)
    assert (out["proposal"] or {}).get("handoffs", []) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_gui_proposal.py -k handoff -v`
Expected: FAIL — `KeyError: 'handoffs'`.

- [ ] **Step 3: Implement**

In `discover_draft`, after the steps are built, read each run's mdout header and match its `INPCRD` assignment to a step that writes that file:

```python
    # AMBER wrote down which restart it actually read. `read_mdout_header` has parsed that
    # block since before lineages existed and nothing has ever called `assignment()` --
    # the ground truth for "which equilibration fed which production run" was being
    # discarded on every scan.
    #
    # Proposed, never written, and only across a directory boundary: within one, the
    # chunked chain already covers it. `assignment` returns None when AMBER clipped the
    # value at the field width, which is common for long paths -- that is no evidence, not
    # no producer, so such a step simply gets no proposed edge.
    #
    # Fault tolerance matches the mdin parse above: a header that will not read costs this
    # one edge, not the scan.
    writes = {Path(s.rst).name: s.id for _, s in iter_steps(sim) if s.rst}
    handoffs = []
    for stem, step in step_by_stem.items():
        mdout = grouped.get(stem, {}).get("mdout")
        if not mdout:
            continue
        try:
            header = read_mdout_header(mdout)
        except (IOError, OSError, ValueError, LookupError):
            continue
        named = header.assignment("INPCRD") if header else None
        if not named:
            continue
        producer_id = writes.get(Path(named).name)
        directory = stem.rpartition("/")[0]
        if not producer_id or producer_id == step.id:
            continue
        producer = by_id[producer_id]
        if producer.name.rpartition("/")[0] == directory:
            continue  # already covered by the within-directory chain
        handoffs.append({
            "consumer_id": step.id, "producer_id": producer_id,
            "consumer": step.name, "producer": producer.name,
            "evidence": f"mdout File Assignments: INPCRD: {named}",
        })
```

Declare `ProposedHandoff` on `schemas.py` and add `handoffs: List[ProposedHandoff] = []` to `LineageProposal`.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_gui_proposal.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q 2>&1 | tail -5`

- [ ] **Step 6: Commit**

```bash
git add -A ambermeta tests
git commit -m "feat(gui): propose the equil->prod handoffs AMBER already recorded

MdoutHeader.file_assignments has parsed AMBER's File Assignments block since
before lineages existed, and assignment() had ZERO call sites -- the ground
truth for which equilibration fed which production run was read off every
mdout and thrown away.

It now drives a handoff proposal. Proposed, never written; only across a
directory boundary, since within one the chunked chain already covers it; and
a clipped assignment proposes nothing rather than guessing, because a value
AMBER truncated at the field width is no evidence, not a missing producer.

No content hashing is introduced. AMBER's record says what the run READ,
which is better evidence than what happens to match byte for byte.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

**Verify:** `python -m pytest -q` green.

---

### Task 9: Discover preserves existing tags (P2.5)

**Files:**
- Modify: `ambermeta/gui/api/routes.py` (`discover_document`), `schemas.py` (`DiscoverResult.warnings` already exists)
- Test: `tests/test_gui_api_sim.py` (add)

**Interfaces:**
- Consumes: `store.snapshot()`'s currently-unused `sim0`.
- Produces: no new route.

> Step ids are fresh `uuid4().hex[:8]` on every Discover, so identity must be `Step.name` — the path-prefixed posix stem, which is what `apply_inferred_lineages` already keys on. Tags must be re-applied in **one** operation: `store.replace(..., reset_history=False)` already costs one undo frame, and `set_lineages`' docstring records that a loop of per-step writes evicts the Discover result being annotated.

- [ ] **Step 1: Write the failing test**

```python
def test_rediscovering_keeps_the_tags_already_declared(sys021_tree):
    """Discover is the most prominent button in the top bar and the natural reflex after
    adding files. It replaced the document wholesale, so every tag vanished with no warning
    -- recoverable with Ctrl+Z, but nothing said so."""
    client = _client(sys021_tree)
    client.post("/api/document/discover", json={"recursive": True})
    doc = client.get("/api/document").json()["simulation"]
    ids = [s["id"] for p in doc["phases"] for s in p["steps"]
           if s["name"].startswith("equil/01/") or s["name"].startswith("prod/01/")]
    client.patch("/api/steps/lineage", json={"ids": ids, "lineage": "01"})

    body = client.post("/api/document/discover", json={"recursive": True}).json()
    after = body["document"]["simulation"]
    tagged = {s["name"] for p in after["phases"] for s in p["steps"] if s["lineage"] == "01"}
    assert "prod/01/nvt_prod_0001" in tagged
    assert body["warnings"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_gui_api_sim.py -k rediscovering -v`
Expected: FAIL — `tagged` is empty.

- [ ] **Step 3: Implement**

In `routes.discover_document`, capture the pre-existing tags by name before replacing, then re-apply them to the new simulation **before** `store.replace`:

```python
    # Discover replaced the document wholesale, so re-running it -- the natural reflex
    # after adding files -- silently discarded every tag the user had declared. Recoverable
    # with Ctrl+Z because reset_history=False, but nothing in the UI said so.
    #
    # Matched on Step.name, which is the path-prefixed run stem: step ids are freshly
    # generated on every scan, so they cannot identify anything across one. Re-applied
    # before the replace so this costs the same single undo frame Discover always cost --
    # a loop of PATCHes afterwards would evict the very result being annotated.
    previous = {step.name: step.lineage
                for _, step in iter_steps(sim0) if step.lineage} if sim0 else {}
    carried, dropped = 0, []
    for _, step in iter_steps(out["simulation"]):
        tag = previous.pop(step.name, None)
        if tag is not None:
            step.lineage = tag
            carried += 1
    dropped = sorted(previous)
    warnings = list(out.get("warnings") or [])
    if dropped:
        warnings.append(
            f"{len(dropped)} run(s) carried a lineage tag that this scan did not find "
            f"again, so their tags were dropped: {', '.join(dropped[:5])}"
            + (" ..." if len(dropped) > 5 else ""))
```

The report goes in **`DiscoverResult.warnings`**, not `DocumentResponse.warnings` — `store.replace()` clears the latter first thing, and `docs/gui.md:481` states as contract that Discover always reports an empty list there.

- [ ] **Step 4: Run the test**

Run: `python -m pytest tests/test_gui_api_sim.py -k rediscovering -v`
Expected: PASS.

- [ ] **Step 5: Add the dropped-tag test**

```python
def test_a_tag_on_a_run_that_vanished_is_reported_not_silently_dropped(sys021_tree):
    client = _client(sys021_tree)
    client.post("/api/document/discover", json={"recursive": True})
    doc = client.get("/api/document").json()["simulation"]
    victim = [s for p in doc["phases"] for s in p["steps"]
              if s["name"] == "prod/05/nvt_prod_0002"][0]
    client.patch("/api/steps/lineage", json={"ids": [victim["id"]], "lineage": "05"})
    for suffix in (".mdin", ".mdout"):
        (sys021_tree / "prod" / "05" / f"nvt_prod_0002{suffix}").unlink()
    body = client.post("/api/document/discover", json={"recursive": True}).json()
    assert any("did not find again" in w for w in body["warnings"])
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q 2>&1 | tail -5`

- [ ] **Step 7: Commit**

```bash
git add -A ambermeta tests
git commit -m "fix(gui): re-running Discover no longer discards every lineage tag

store.replace() swaps the document wholesale, so Discover -- the most
prominent button in the top bar, and the natural reflex after adding files --
silently dropped all of them. Recoverable with Ctrl+Z because
reset_history=False, but nothing said so.

Matched on Step.name, the path-prefixed run stem, because step ids are freshly
generated on every scan. Re-applied before the replace so this still costs the
one undo frame Discover always cost; a loop of PATCHes afterwards would evict
the result being annotated, which set_lineages' docstring already warns about.

Tags whose run the new scan did not find are reported in DiscoverResult
rather than dropped. They cannot go in DocumentResponse.warnings --
store.replace clears that first, and docs/gui.md:481 states as contract that
Discover always reports an empty list there.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

**Verify:** `python -m pytest -q` green.

---

### Task 10: Fix the documentation and wire contracts that state the opposite (P1.4)

**Files:**
- Modify: `ambermeta/gui/api/schemas.py:70-73`, `:200-203`; `ambermeta/gui/api/routes.py:409-412`
- Modify: `docs/gui.md:146`, `:348`, `:481`, `:489`; `README.md:267`, `:315`

No test covers prose. This task is verified by reading.

- [ ] **Step 1: Correct the two schema comments**

`schemas.py:70-73` — replace *"Written by `discover`'s inference or by editing the manifest, so the GUI only displays it"* with a statement that `PATCH /steps/lineage` and `PUT /steps/{id}` both write it, and that `discover` now only *proposes* it.

`schemas.py:200-203` — replace *"The tag is read-only at this surface today: no route writes it."* outright. `routes.py:357-358` writes it and `tests/test_gui_bulk_lineage.py:59-65` covers it. Note in the replacement comment that this staleness is the likely reason the frontend never grew a tagging control.

- [ ] **Step 2: Correct the refusal message**

`routes.py:409-412` currently blames the run names. Keep the leading `"No lineages inferred"` (two tests assert that substring) and replace the reason with one that is true — the cohorts could not be reconciled — and point at `Define replicas…` rather than at bands that cannot render.

- [ ] **Step 3: Correct the docs**

- `docs/gui.md:146` and `:489`: delete *"These inline editors are stubs today"* / *"Step and phase inline editing is stubbed."* `StepInspector.tsx:33-225` implements name, topology, the Source select, "Continues from", the `reads:` readback and the reverse consumer list, shipped in PR 2a.
- `docs/gui.md:348`: add `lineage` to the `PUT /api/steps/{id}` request-body row.
- `docs/gui.md:481`: still true after Task 9 (the report goes in `DiscoverResult`) — confirm and leave.
- `README.md:267` and `:315`: same stub claim, same deletion.

- [ ] **Step 4: Verify by grep**

```bash
grep -rn "stubs today\|inline editing is stubbed\|only displays it\|no route writes it" docs/ README.md ambermeta/
```
Expected: **no output**.

- [ ] **Step 5: Commit**

```bash
git add -A docs README.md ambermeta
git commit -m "docs: stop claiming the step inspector is a stub and the tag read-only

Four sources stated the opposite of the code, and the cost was concrete: a
user looking for continuation editing read docs/gui.md, was told the editors
were stubs, and never opened the Inspector that has implemented them since
PR 2a.

The schemas.py comments are the more consequential pair -- 'the GUI only
displays it' and 'no route writes it' are what whoever built the frontend was
told about a field two routes write, which is the likeliest reason no tagging
affordance was ever grown.

Nothing in CI verifies any of this: cli-docs-sync covers docs/cli.md alone.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

**Verify:** the grep in Step 4 returns nothing; `python -m pytest -q` green.

---

### Task 11: The ProposalStrip component (P2.2, P2.3, P2.6)

**Files:**
- Create: `ambermeta/gui/frontend/src/components/Canvas/ProposalStrip.tsx`, `ProposalStrip.test.tsx`
- Modify: `src/types/index.ts`, `src/api/client.ts`, `src/api/hooks.ts`, `src/test/server.ts`

**Interfaces:**
- Consumes: `LineageProposal` from Task 7/8.
- Produces: `<ProposalStrip proposal={p} mode="proposed" | "manual" onClose={fn} />`.
- Produces types `LineageProposal`, `ProposedMember`, `ProposedSource`, `ProposedHandoff` in `types/index.ts`; `DiscoverResult.proposal?: LineageProposal | null`.

> Render it as a `Modal`. `Modal` increments a global open-modal counter that `App.tsx` uses to suspend Ctrl+Z (`useUndoShortcuts({ enabled: !modalOpen })`); rendered inline in the Canvas, undo stays live and a user mid-review can rewind the document underneath the strip. `Modal` is `w-[min(560px,92vw)] max-h-[85vh] overflow-auto`, so the member table needs `font-mono text-xs` and its own `overflow-x-auto`.

- [ ] **Step 1: Add the types and the client call**

`types/index.ts`:

```ts
export interface ProposedSource { directory: string; run_count: number; }
export interface ProposedMember { tag: string; step_ids: string[]; sources: ProposedSource[]; }
export interface ProposedHandoff {
  consumer_id: string; producer_id: string;
  consumer: string; producer: string; evidence: string;
}
export interface LineageProposal {
  segment_index: number;
  segments: string[][];
  members: ProposedMember[];
  handoffs: ProposedHandoff[];
}
```

and add `proposal?: LineageProposal | null;` to `DiscoverResult` — **optional**, because `App.workflows.test.tsx:20` annotates a literal with that type.

`client.ts`: change `inferLineages` to `(segmentIndex?: number) => post<LineageProposal | null>("/steps/infer-lineages", { segment_index: segmentIndex })`.

`hooks.ts`: `useInferLineages` becomes a bare `useMutation` returning the proposal, not `docMutation`.

`test/server.ts`: add a default handler for `POST /api/steps/infer-lineages` and for `PATCH /api/steps/lineage`. `setup.ts` uses `onUnhandledRequest: "error"`, so without these every test rendering the Canvas fails opaquely.

- [ ] **Step 2: Write the failing test**

Create `ProposalStrip.test.tsx`:

```tsx
/**
 * What the strip claims and what it sends.
 *
 * The two failures it exists to prevent: applying anything the user did not accept, and
 * reporting success after a partial apply. Five tags are five PATCHes and five undo
 * frames -- a failure on the third leaves two applied, and saying "done" there is worse
 * than saying nothing.
 */
import { it, expect, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { QueryClientProvider } from "@tanstack/react-query";
import { ProposalStrip } from "./ProposalStrip";
import type { LineageProposal } from "@/types";

afterEach(() => queryClient.clear());

const proposal: LineageProposal = {
  segment_index: 1,
  segments: [["equil", "prod"], ["01", "02"]],
  members: [
    { tag: "01", step_ids: ["a1", "a2"], sources: [
      { directory: "equil/01", run_count: 18 }, { directory: "prod/01", run_count: 202 }] },
    { tag: "02", step_ids: ["b1"], sources: [
      { directory: "equil/02", run_count: 18 }, { directory: "prod/02", run_count: 201 }] },
  ],
  handoffs: [],
};

function show(p: LineageProposal = proposal, mode: "proposed" | "manual" = "proposed") {
  return render(
    <QueryClientProvider client={queryClient}>
      <ProposalStrip proposal={p} mode={mode} onClose={() => {}} />
    </QueryClientProvider>);
}

it("names each proposed member and the directories it is built from", async () => {
  show();
  expect(await screen.findByText("01")).toBeInTheDocument();
  expect(screen.getByText(/equil\/01 \(18\)/)).toBeInTheDocument();
  expect(screen.getByText(/prod\/01 \(202\)/)).toBeInTheDocument();
});

it("sends one bulk request per tag, carrying that tag's step ids", async () => {
  const seen: unknown[] = [];
  server.use(http.patch("/api/steps/lineage", async ({ request }) => {
    seen.push(await request.json());
    return HttpResponse.json({ simulation: { name: "s", phases: [] }, warnings: [] });
  }));
  show();
  await userEvent.click(screen.getByRole("button", { name: "Accept" }));
  await waitFor(() => expect(seen).toHaveLength(2));
  expect(seen[0]).toEqual({ ids: ["a1", "a2"], lineage: "01" });
  expect(seen[1]).toEqual({ ids: ["b1"], lineage: "02" });
});

it("applies nothing when the user declines", async () => {
  let calls = 0;
  server.use(http.patch("/api/steps/lineage", () => { calls += 1;
    return HttpResponse.json({ simulation: { name: "s", phases: [] }, warnings: [] }); }));
  show();
  await userEvent.click(screen.getByRole("button", { name: "Not replicas" }));
  expect(calls).toBe(0);
});

it("reports a partial apply rather than claiming success", async () => {
  let calls = 0;
  server.use(http.patch("/api/steps/lineage", () => {
    calls += 1;
    return calls === 1
      ? HttpResponse.json({ simulation: { name: "s", phases: [] }, warnings: [] })
      : HttpResponse.json({ detail: "no such step" }, { status: 404 });
  }));
  show();
  await userEvent.click(screen.getByRole("button", { name: "Accept" }));
  expect(await screen.findByText(/applied 1 of 2/i)).toBeInTheDocument();
});

it("lets the user retag a member before applying", async () => {
  const seen: unknown[] = [];
  server.use(http.patch("/api/steps/lineage", async ({ request }) => {
    seen.push(await request.json());
    return HttpResponse.json({ simulation: { name: "s", phases: [] }, warnings: [] });
  }));
  show();
  const field = screen.getByLabelText("tag for 01");
  await userEvent.clear(field);
  await userEvent.type(field, "rep1");
  await userEvent.click(screen.getByRole("button", { name: "Accept" }));
  await waitFor(() => expect(seen).toHaveLength(2));
  expect(seen[0]).toEqual({ ids: ["a1", "a2"], lineage: "rep1" });
});

it("offers the segment picker in manual mode", async () => {
  show(proposal, "manual");
  expect(await screen.findByRole("button", { name: "equil|prod" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "01…02" })).toBeInTheDocument();
});
```

- [ ] **Step 3: Run to verify failure**

Run: `cd ambermeta/gui/frontend && npx vitest run src/components/Canvas/ProposalStrip.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement `ProposalStrip.tsx`**

Build it from `Modal` + raw `<button>`/`<input>` with inline Tailwind (there is no `Select`, `Table` or `Tabs` primitive in `components/common/`; follow `SimHeader.tsx:50-61` and `PlanModal.tsx:166-175`). Requirements:

- Header line: `"{n} run directories look like {m} repeated members"`, and in manual mode `"Which part of the path names the replica?"`.
- Segment picker: one button per index in `proposal.segments`, labelled by joining that segment's distinct values with `|` (truncating past three with `…`), the active one styled with `text-accent`. Clicking calls `useInferLineages(index)` and replaces the shown proposal. Always visible in `manual` mode; behind a `[Change ▾]` toggle in `proposed` mode.
- Member rows: an editable `<input aria-label={\`tag for ${member.tag}\`}>` seeded with the proposed tag, then `sources.map(s => \`${s.directory} (${s.run_count})\`).join(" + ")` in `font-mono text-xs`, inside a `div` with `overflow-x-auto`.
- Handoff block, when `handoffs.length > 0`: the pairs plus `[Wire these]` / `[Leave unlinked]`, with its own accepted/declined state.
- `[Accept]` / `[Not replicas]` (proposed) or `[Apply]` / `[Cancel]` (manual).
- **Accept applies tags first, then handoffs** — one `PATCH /steps/lineage` per distinct tag, awaited in sequence, then one `PUT /steps/{id}` per accepted handoff. Tagging first is what makes each handoff intra-member, so `_check_continues_from` raises no "branch, not a continuation" warning and `_sever_crossed_refs` deletes nothing.
- Count successes; on any failure render `"applied {k} of {n}"` and stop. **Do not attach a `useUndoOffer` toast** — `setDocument` calls `expireEditToasts()` on every response, so a toast raised between calls is destroyed by the next, and one Undo click pops only one of N snapshots.

- [ ] **Step 5: Run the tests**

Run: `npx vitest run src/components/Canvas/ProposalStrip.test.tsx`
Expected: all six PASS.

- [ ] **Step 6: Type-check**

Run: `npx tsc --noEmit`
Expected: clean. `noUnusedLocals`/`noUnusedParameters` are on — vitest green does not imply this passes.

- [ ] **Step 7: Commit**

```bash
git add -A ambermeta/gui/frontend/src
git commit -m "feat(gui): a proposal strip that shows the grouping before applying it

One component in two modes: proposed, driven by what discovery inferred, and
manual, driven by a path-segment picker the user drives. Member rows are
editable before Apply, which covers the irregular remainder a segment picker
cannot express.

Rendered as a Modal deliberately. Modal increments the global open-modal
counter App.tsx uses to suspend Ctrl+Z; inline in the Canvas, undo stays live
and a user mid-review can rewind the document underneath the strip.

Accept applies tags FIRST and handoffs second. The reverse order makes
_sever_crossed_refs delete the edges just written, while tagging first leaves
every handoff intra-member so _check_continues_from raises nothing.

Five tags are five requests and five undo frames, so a failure partway leaves
work applied. The strip says \"applied k of n\" rather than claiming success,
and raises no Undo toast -- setDocument expires edit toasts on every response,
so one raised between calls is destroyed by the next.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

**Verify:** `npx vitest run` green; `npx tsc --noEmit` clean.

---

### Task 12: Wire the strip in, and remove the old Infer button (P2.2, P2.3)

**Files:**
- Modify: `src/App.tsx`, `src/components/TopBar/TopBar.tsx`, `src/components/TopBar/TopBar.test.tsx`, `src/components/Canvas/SimHeader.tsx`
- Modify: `src/App.workflows.test.tsx` (its `DiscoverResult` literal)

- [ ] **Step 1: Write the failing test**

Add to `TopBar.test.tsx`:

```tsx
it("offers a way to declare replicas whatever state the document is in", async () => {
  const onDefineReplicas = vi.fn();
  renderTopBar({ onDefineReplicas });
  await userEvent.click(screen.getByRole("button", { name: "Define replicas…" }));
  expect(onDefineReplicas).toHaveBeenCalled();
});
```

Add to `App.workflows.test.tsx`:

```tsx
it("shows the proposal after Discover instead of applying it", async () => {
  renderApp();
  await userEvent.click(screen.getByRole("button", { name: "Discover" }));
  await userEvent.click(await screen.findByRole("button", { name: "Scan" }));
  expect(await screen.findByText(/repeated members/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/components/TopBar/TopBar.test.tsx src/App.workflows.test.tsx`
Expected: FAIL — no such button.

- [ ] **Step 3: Implement**

- `TopBar.tsx`: add `onDefineReplicas: () => void` to `Props` (a 7th) and a `Define replicas…` button beside Discover. **`TopBar.test.tsx:14-15` passes all six explicitly** — update that helper to pass seven, or the file will not type-check.
- `App.tsx`: hold `proposal` and `stripMode` state; set them from the Discover response's `proposal`; open the strip in `manual` mode from `onDefineReplicas`, fetching via `useInferLineages()`.
- `SimHeader.tsx:122-130`: **delete** the old "Infer lineages" button. It calls `POST /steps/infer-lineages` and wrote tags with no preview; leaving it ships two contradictory affordances. Remove its `useInferLineages` import too — `noUnusedLocals` makes a dangling import a hard build failure.
- `App.workflows.test.tsx:20`: its literal is annotated `DiscoverResult`; add `proposal: null` or rely on the field being optional (Task 11 made it optional — confirm).

- [ ] **Step 4: Run the tests**

Run: `npx vitest run`
Expected: green.

- [ ] **Step 5: Type-check and build**

Run: `npx tsc --noEmit && npm run build`
Expected: both clean. (The bundle diff is committed in Task 14, not here.)

- [ ] **Step 6: Revert the bundle for now**

```bash
cd /home/bonus/git/ambermeta && git checkout -- ambermeta/gui/static
```

- [ ] **Step 7: Commit**

```bash
git add -A ambermeta/gui/frontend/src
git commit -m "feat(gui): Define replicas in the top bar, and one inference affordance

SimHeader shipped an \"Infer lineages\" button that wrote tags with no preview.
Leaving it beside the proposal strip would ship two contradictory affordances,
so it is removed; the route stays, repointed to return a proposal.

Define replicas... sits in the top bar rather than in SimHeader because
discoverability is the whole complaint -- a muted link inside the simulation
header is precisely what went unnoticed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

**Verify:** `npx vitest run` green; `npx tsc --noEmit` clean; `git status --porcelain ambermeta/gui/static` empty.

---

### Task 13: Render the per-lineage payoff (P2.6)

**Files:**
- Modify: `src/components/TopBar/ValidationPanel.tsx`, `ValidationPanel.test.tsx`

> No API change is needed. `build_validation_report` already returns `"lineages": protocol.lineage_totals() or None` and `ValidationReport.lineages: Optional[Dict[str, LineageTotals]]` is already declared, as is `types/index.ts:56,66`. The data has been on the wire and unrendered.

- [ ] **Step 1: Write the failing test**

```tsx
it("breaks the totals down per lineage when the document declares more than one", async () => {
  await showPanel({
    ...emptyValidationReport,
    totals: { stage_count: 5, time_ps: 80000, lineage_count: 5 },
    lineages: {
      "01": { steps: 10000000, time_ps: 20000, step_count: 4 },
      "02": { steps: 7500000, time_ps: 15000, step_count: 3 },
    },
  });
  expect(await screen.findByText("01")).toBeInTheDocument();
  expect(screen.getByText(/4 runs/)).toBeInTheDocument();
  expect(screen.getByText(/20000\.000 ps/)).toBeInTheDocument();
});

it("says nothing about lineages when the report carries none", async () => {
  await showPanel(emptyValidationReport);
  expect(screen.queryByText("Lineages")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/components/TopBar/ValidationPanel.test.tsx`
Expected: FAIL on the first.

- [ ] **Step 3: Implement**

Add a `Lineages` section rendering one row per member: tag, `step_count` runs, `time_ps` at `.3f`. **Guard with `report?.lineages` exactly as the existing code guards `report?.coherence ?? []`** — `App.workflows.test.tsx:59-61`'s validate mock is a raw literal missing both `lineages` and `coherence`, so the field is `undefined` at runtime even though the type says `Record | null`.

- [ ] **Step 4: Run the tests**

Run: `npx vitest run`
Expected: green.

- [ ] **Step 5: Type-check**

Run: `npx tsc --noEmit`

- [ ] **Step 6: Commit**

```bash
git add -A ambermeta/gui/frontend/src
git commit -m "feat(gui): show the per-lineage breakdown that was already on the wire

ValidationReport.lineages, PlanResult.lineages and totals.lineage_count have
been computed, serialised and typed in types/index.ts since PR 2b, and read by
nothing: the panel rendered stage_count and time_ps alone. The CLI printed the
breakdown; the GUI did not.

Guarded on report?.lineages rather than on the declared type, because
App.workflows.test.tsx's validate mock is a raw literal and the field is
undefined at runtime -- the same reason coherence is already guarded.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

**Verify:** `npx vitest run` green; `npx tsc --noEmit` clean.

---

### Task 14: Rebuild the bundle and verify the whole change

**Files:**
- Modify: `ambermeta/gui/static/**` (generated)

- [ ] **Step 1: Rebuild**

```bash
cd /home/bonus/git/ambermeta/ambermeta/gui/frontend
npm ci && npm run build
```

- [ ] **Step 2: Stage with deletions**

```bash
cd /home/bonus/git/ambermeta
git add -A ambermeta/gui/static
git status --porcelain ambermeta/gui/static
```

Expected: the old `index-*.js` / `index-*.css` show as **deleted** and new content-hashed names as added. `emptyOutDir: true` wipes the directory, so `git add` without `-A` would leave the deletions unstaged. Do **not** hand-edit `static/index.html` — `.gitattributes` pins it to LF and a CRLF slip took CI down once already (`f745220`).

- [ ] **Step 3: Commit the bundle on its own**

```bash
git commit -m "build(gui): rebuild static bundle for the proposal strip and lineage panel

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Full verification**

```bash
cd /home/bonus/git/ambermeta
python -m pytest -q 2>&1 | tail -3
cd ambermeta/gui/frontend && npm test 2>&1 | tail -3
npx tsc --noEmit && echo "tsc clean"
cd /home/bonus/git/ambermeta
python scripts/export_cli_help.py --check || echo "docs/cli.md check skipped (needs Python 3.11)"
git status --porcelain
```

Expected: pytest green above the Task 0 baseline, vitest green above its baseline, `tsc clean`, `git status` empty.

- [ ] **Step 5: Confirm nothing regenerated a golden**

```bash
git diff --stat main -- tests/data/
```
Expected: **empty**. If a golden moved, the P1.1 formula is wrong — go back to Task 2 Step 5.

- [ ] **Step 6: End-to-end against the real tree (read-only)**

```bash
cd /home/bonus/git/ambermeta
timeout 600 python -m ambermeta.cli discover /store7/gentile/data/simulations/sys021 --recursive \
  --write /tmp/claude-580/-home-bonus-git-ambermeta/354bce2d-2315-4e6f-83c2-ae9a1f3a38aa/scratchpad/sys021.yaml
grep -c "lineage:" /tmp/claude-580/-home-bonus-git-ambermeta/354bce2d-2315-4e6f-83c2-ae9a1f3a38aa/scratchpad/sys021.yaml
grep -c "status: queued" /tmp/claude-580/-home-bonus-git-ambermeta/354bce2d-2315-4e6f-83c2-ae9a1f3a38aa/scratchpad/sys021.yaml
```

**Write nothing into `/store7`.** Expected: `status: queued` appears **5** times. `lineage:` appears **0** times from `discover` alone — tags are proposed, not written, which is the point.

**Verify:** every command above green; working tree clean.

---

## Self-Review

**Spec coverage.** P1.1 → Tasks 2, 5. P1.2 → Task 3. P1.3 → Task 4. P1.4 → Task 10. P2.1 → Task 6. P2.2 → Task 7 (backend), 11–12 (frontend). P2.3 → Tasks 11–12; the spec's "`showBands` stays as it is" is honoured by no task touching `PhaseSection.tsx`. P2.4 → Tasks 8, 11 (the wire-these flow). P2.5 → Task 9. P2.6 → Task 13. Fixture prerequisite → Task 1. Bundle → Task 14.

**Known gap, recorded rather than hidden.** The spec's P1.3 rule is enforced **at discovery only**. `relink_restarts` (`simulation.py:306-361`) and `repair_dangling_refs` (`:364-407`) also create `input_coords.ref`s and are keyed on lineage, not directory — so on an untagged document a reorder or a delete can still re-create a cross-directory edge. `document.py:394` auto-chains a newly created step to its phase neighbour for the same reason. Closing those is a separate change; it is out of this plan's scope and belongs in the spec's "Out of scope" list.

**Type consistency.** `RunSpec` (Task 1) is used with the same field names in Tasks 2, 3, 8. `Step.status` / `SimulationStage.status` / `StepModel.status` are all `Optional[str]` valued `None` or `"queued"` (Task 3), read in Tasks 5 and 14. `build_lineage_proposal`'s dict keys (Task 7) match `LineageProposal` in `types/index.ts` (Task 11) field for field, and `handoffs` is added by Task 8 to both sides. `useInferLineages` changes signature once, in Task 11, and its only two call sites are updated in Tasks 11 and 12.

**Ordering constraint.** Task 1 must precede 2, 3, 4, 7, 8, 9. Task 7 must precede 8 and 11. Task 11 must precede 12. Task 14 must be last.
