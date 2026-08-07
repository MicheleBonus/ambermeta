# CLI reference

**The `ambermeta` command line is the complete, headless interface to the engine** — everything AmberMeta does is reachable here, no GUI required. It is the right surface for scripting, CI gates, and cluster/SSH work.

Eight commands sit under one entry point:

| Command | Purpose |
|---|---|
| [`plan`](#plan) | Build and summarize a v2 manifest, or a discovered/interactive protocol; export reproducibility artifacts |
| [`discover`](#discover) | Scan a directory into a **Simulation draft** (topology pool + phases + steps) |
| [`validate`](#validate) | Validate individual files, or a whole Simulation manifest with `--manifest` |
| [`export`](#export) | Re-emit a **v2** manifest, optionally converting its format (JSON ⇄ YAML) |
| [`init`](#init) | Write a starting v2 manifest template to hand-edit |
| [`info`](#info) | Print parsed metadata for a single file |
| [`gui`](#gui) | Launch the browser GUI |
| [`completion`](#completion) | Emit a shell-completion script |

> The help blocks below are generated directly from `ambermeta/cli.py::build_parser()` and checked in CI (`scripts/export_cli_help.py --check`) — every command, `discover` and `export` included. The generator pins Python 3.11, because argparse renders help differently across releases and the output is embedded verbatim; run it on 3.11 or the check fails on a diff you did not write.

---

## Install & completion

```bash
python -m pip install -e .
ambermeta --help
```

Generate a completion script for your shell:

```bash
# bash
mkdir -p ~/.local/share/bash-completion/completions
ambermeta completion bash > ~/.local/share/bash-completion/completions/ambermeta
source ~/.bashrc

# zsh
mkdir -p ~/.zfunc
ambermeta completion zsh > ~/.zfunc/_ambermeta
echo 'fpath=(~/.zfunc $fpath)' >> ~/.zshrc
autoload -Uz compinit && compinit

# fish
mkdir -p ~/.config/fish/completions
ambermeta completion fish > ~/.config/fish/completions/ambermeta.fish
```

---

## Global options

These apply before the subcommand:

| Option | Effect |
|---|---|
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | Logging verbosity (default `INFO`) |
| `--log-file PATH` | Also write logs to a file |
| `-q`, `--quiet` | Suppress stdout; errors/usage still go to stderr |

<!-- BEGIN_CLI_HELP:root -->
```text
usage: ambermeta [-h] [--log-level {DEBUG,INFO,WARNING,ERROR}]
                 [--log-file LOG_FILE] [-q]
                 {plan,discover,validate,info,export,init,gui,completion} ...

AmberMeta - Simulation provenance engine for AMBER molecular dynamics.

Extract, organize, and validate metadata from AMBER simulation files.
Supports prmtop, mdin, mdout, mdcrd (NetCDF), and restart files.

positional arguments:
  {plan,discover,validate,info,export,init,gui,completion}
    plan                Build and summarize a SimulationProtocol from
                        manifest, recursive discovery, or explicit interactive
                        mode
    discover            Discover files into a Simulation draft
                        (Sim→Phase→Step) and optionally write a v2 manifest
    validate            Validate simulation files without building full
                        protocol
    info                Display detailed metadata for a single file
    export              Re-emit a v2 manifest, optionally converting its
                        format
    init                Generate a starting v2 manifest file
    gui                 Launch web-based GUI for building protocol manifests
    completion          Print shell completion script for bash, zsh, or fish

options:
  -h, --help            show this help message and exit
  --log-level {DEBUG,INFO,WARNING,ERROR}
                        Set logging level (default: INFO)
  --log-file LOG_FILE   Write logs to a file in addition to stderr
  -q, --quiet           Suppress all output except errors

Commands:
  plan      Build a simulation protocol from manifest or auto-discovery
  discover  Discover files into a Simulation draft (v2) and optionally write a manifest
  validate  Quick validation of simulation files
  info      Display detailed metadata for a single file
  init      Generate a starting v2 manifest file
  export    Re-emit a v2 manifest, optionally converting its format (json/yaml)

Examples:
  ambermeta plan -m manifest.yaml           Build protocol from manifest
  ambermeta plan . --recursive              Auto-discover files recursively
  ambermeta plan . --interactive            Prompt for stage definitions
  ambermeta plan -m manifest.yaml \
    --methods-summary-path methods.json     Export publication-ready summary
  ambermeta discover . --write sim.yaml       Draft a v2 manifest from a directory
  ambermeta validate system.prmtop *.mdout  Validate multiple files
  ambermeta validate --manifest sim.yaml      Validate a whole simulation (continuity/gaps)
  ambermeta info --format json system.prmtop  Show metadata as JSON
  ambermeta init -o template.yaml           Write a starting v2 manifest template
  ambermeta export sim.yaml -o sim.json       Convert a v2 manifest to JSON

File Types:
  prmtop:  .prmtop, .top, .parm7    (topology/parameters)
  mdin:    .mdin, .in               (input control)
  mdout:   .mdout, .out             (output log)
  mdcrd:   .nc, .mdcrd, .crd        (trajectory)
  inpcrd:  .rst, .rst7, .ncrst      (coordinates/restart)

For documentation, visit: https://github.com/MicheleBonus/ambermeta
```
<!-- END_CLI_HELP:root -->

```bash
ambermeta --log-level DEBUG plan . --recursive
ambermeta --quiet plan . --recursive --summary-path out.json
```

---

## `plan`

Build and summarize a protocol from a manifest, recursive discovery, or interactive prompts — and export artifacts. **Pick exactly one mode:** `--manifest`, `--recursive`, or `--interactive`.

```bash
ambermeta plan [directory] [options]
```

<!-- BEGIN_CLI_HELP:plan -->
```text
usage: ambermeta plan [-h] [-m MANIFEST] [--skip-cross-stage-validation]
                      [--strict] [--recursive] [--interactive] [-v]
                      [--summary-path SUMMARY_PATH]
                      [--summary-format {json,yaml}]
                      [--methods-summary-path METHODS_SUMMARY_PATH]
                      [--stats-csv STATS_CSV] [--no-expand-env]
                      [--pattern PATTERN] [--auto-detect-restarts]
                      [--prmtop PRMTOP]
                      [directory]

Build and summarize a SimulationProtocol from manifest, recursive discovery,
or explicit interactive mode. Interactive mode prompts for stage roles, file
paths, restart (inpcrd) paths, and expected gap/tolerance values.

positional arguments:
  directory             Directory containing the files referenced by the
                        manifest (default: current directory)

options:
  -h, --help            show this help message and exit
  -m MANIFEST, --manifest MANIFEST
                        Path to a YAML or JSON manifest describing stages and
                        file paths
  --skip-cross-stage-validation
                        Skip the continuity checks between consecutive stages
                        (they run by default)
  --strict              Abort on the first unreadable/malformed input file
                        instead of skipping it, and exit 1 if any continuity
                        or sequence finding was reported. Default is to skip
                        the file, print the findings and exit 0.
  --recursive           Auto-discover simulation files recursively (no
                        interactive prompts). Files are grouped by stem
                        (filename without extension) and stage roles are
                        inferred from directory names (equil→equilibration,
                        prod→production).
  --interactive         Enable interactive prompt mode for manually defining
                        stages.
  -v, --verbose         Show detailed metadata, warnings, and continuity
                        information for each stage
  --summary-path SUMMARY_PATH
                        Path to write a structured protocol summary (JSON or
                        YAML)
  --summary-format {json,yaml}
                        Force the structured summary format (default: inferred
                        from file extension)
  --methods-summary-path METHODS_SUMMARY_PATH
                        Write a Materials & Methods-ready JSON summary with
                        reproducibility-critical metadata (software versions,
                        MD settings, system composition, and trajectory
                        cadence) while omitting energies and other
                        nonessential arrays
  --stats-csv STATS_CSV
                        Export per-stage statistics to a CSV file
  --no-expand-env       Disable environment variable expansion in manifest
                        paths
  --pattern PATTERN     Regex pattern to filter discovered files (e.g.,
                        'prod_.*' for production runs)
  --auto-detect-restarts
                        Automatically detect and link restart files between
                        stages
  --prmtop PRMTOP       Global prmtop file to use for all stages (avoids
                        specifying it per stage)
```
<!-- END_CLI_HELP:plan -->

### Modes

| Mode | Flag | Behavior |
|---|---|---|
| Manifest | `-m/--manifest FILE` | Load a v2 manifest and summarize it |
| Discovery | `--recursive` | Group files by stem and infer roles; `--pattern REGEX` filters (this mode only) |
| Interactive | `--interactive` | Prompt for each stage's files, role, restart, and gap/tolerance |

### `plan -m` requires a v2 manifest

`-m/--manifest` always loads the file through `ambermeta.simulation.load_simulation` — the same reader `discover --write`, `export`, and `validate --manifest` use — and prints the **Simulation → Phase → Step structure**, plus continuity/sequence-hole findings. A manifest without a top-level `steps` key (e.g. an old flat `stages:` file) isn't v2-shaped and fails to load; use `--recursive` (below) or [`discover`](#discover) to build a fresh v2 manifest from a directory instead.

`--recursive` discovery under `plan` is a separate, still-supported flat engine (auto-discovery straight from files on disk, no manifest involved) and always prints the classic per-stage **Protocol summary**; use [`discover`](#discover) for the new Simulation-draft view of a directory.

### Exports (all three modes)

| Flag | Output |
|---|---|
| `--summary-path FILE` | Full protocol summary (JSON/YAML; `--summary-format` forces the format) |
| `--methods-summary-path FILE` | Materials-&-Methods JSON: software, MD engine settings, system composition, restraints |
| `--stats-csv FILE` | Per-stage statistics (one row per stage) |

> **Intent and execution are different numbers, and the bundle carries both.**
> `methods_summary.json` describes the **protocol that was specified**: everything under a
> stage's `md_engine` — `cntrl_parameters`, `run_length_steps`, and `run_length_ps`
> (`run_length_steps × timestep_ps`) — is read from the input deck and states what the run
> was *asked* to do. `summary.json`'s `totals` and `stats.csv`'s `duration_ns` describe what
> the run *did*: they are measured from each mdout's own frames and count nothing for a run
> that was queued and never started, or that was killed part-way.
>
> The two therefore disagree, correctly, for any truncated run: a chunk that declared
> `nstlim = 2500000, dt = 0.002` reports `run_length_ps: 5000.0` in the methods summary and
> contributes 3000 ps to the totals if that is where it stopped. Quote `run_length_ps` when
> writing up the protocol; quote the totals when reporting sampling.

The CSV header is exactly:

```text
stage_name,stage_role,time_start_ps,time_end_ps,duration_ns,frame_count,temp_avg,temp_std,pressure_avg,pressure_std,density_avg,density_std,etot_avg,etot_std
```

### Behavior

- **Fault-tolerant by default.** A missing/malformed/unreadable file is skipped, the error is recorded against its stage, a skip summary is printed, and the run exits `0`. `--strict` makes the first bad file a hard error (clean message, exit `1`, no traceback). A stage keeps every file that *did* parse.
- **Findings are reported on every mode.** A continuity or sequence finding — a gap, or a member that stopped early — is printed under "Continuity / sequence findings" by `--manifest`, `--recursive` and `--interactive` alike, and lands in `summary.json` under `findings` when there is one. The key is absent when there is nothing to report, so a summary for a document with no holes is the file it always was.
- **`--strict` also fails on a finding.** It exits `1` when any `continuity_gap` or `missing_run` was reported, which is what `validate --manifest --strict` has always done. Before this the two commands disagreed about the same manifest: `validate --strict` exited `1` on a crashed replica and `plan --strict` exited `0`. The artifacts are still written either way — a pipeline that stops on a finding still wants the summary that names it.
- **Cross-stage validation** runs by default; `--skip-cross-stage-validation` turns it off. A manifest cannot switch it on or off — a v2 manifest has no `settings` block, so this is a CLI-flag decision only.

#### `--recursive` (flat discovery, retained engine)

```text
$ ambermeta plan tests/data/amber/md_test_files --recursive

Scanning .../md_test_files recursively for simulation files...
Discovered 7 stage(s).

Protocol summary
================
Stages: 7
Total steps: 25000000
Total simulated time (ps): 100000.000

- ntp_prod_0001
  intent: production
  result: Completed
  mdin: steps=5000000, dt=0.004 ps
  mdout: status=complete, steps=5000000, dt=0.004 ps, thermostat=Langevin @ 300 K, barostat=Berendsen, box=RECTILINEAR
  inpcrd: atoms=64528, box, time=20920 ps
  stats: frames=200, time=1020–20920 ps, temp=300.43 ± 1.25 K, density=1.0370 ± 0.0012 g/cc
  restart: .../ntp_prod_0001.rst
  evidence: INFO: Part of sequence 'ntp_prod' (item 2 of 6); INFO: stage_role 'production' inferred from mdin file; ...
  note: INFO: Part of sequence 'ntp_prod' (item 2 of 6)
  note: INFO: stage_role 'production' inferred from mdin file
```

(Output trimmed to one stage; `CH3L1_HUMAN_6NAG` and `ntp_prod_0000..0005` are the other six.)

#### `-m` on a v2 manifest

Given a v2 manifest built by [`discover --write`](#discover) (`sim.yaml`, sitting next to the sample data so its relative file paths resolve):

```text
$ ambermeta plan tests/data/amber/md_test_files -m sim.yaml

Simulation summary
==================
Topologies (pool): 1
  - top_CH3L1_HUMAN_6NAG [normal]  CH3L1_HUMAN_6NAG.top
Starting structure: CH3L1_HUMAN_6NAG.crd
Phases: 1

Phase: Production [production]
  - ntp_prod_0001  topology=CH3L1_HUMAN_6NAG.top  input=starting structure  (mdin=ntp_prod_0001.mdin, mdout=ntp_prod_0001.mdout)
  - ntp_prod_0002  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0001 (ntp_prod_0001.rst)  (mdin=ntp_prod_0002.mdin, mdout=ntp_prod_0002.mdout)
  - ntp_prod_0003  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0002 (ntp_prod_0002.rst)  (mdin=ntp_prod_0003.mdin, mdout=ntp_prod_0003.mdout)
  - ntp_prod_0004  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0003 (ntp_prod_0003.rst)  (mdin=ntp_prod_0004.mdin, mdout=ntp_prod_0004.mdout)
  - ntp_prod_0005  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0004 (ntp_prod_0004.rst)  (mdin=ntp_prod_0005.mdin, mdout=ntp_prod_0005.mdout)

Validation: OK
```

(`input=restart of <step> (<file>)` is the continuity chain, resolved to the producing step's name and its output restart. The healthy 20 ns inter-run gaps between the sample sequence's runs fall inside the expected window and are not flagged, so there are no continuity findings.)

#### `-m` on a pre-v2 manifest

A manifest without a top-level `steps` key (e.g. an old flat `stages:`/`global_prmtop:` file) fails to load — the same "not a v2 manifest" error [`export`](#export) shows below:

```text
$ ambermeta plan tests/data/amber/md_test_files -m old_manifest.yaml

ERROR: old_manifest.yaml is not a v2 manifest (no 'steps' key). Rebuild it with `ambermeta discover <dir> --write <path>`.
```

---

## `discover`

**New.** Discover-as-draft: scan a directory into a **Simulation draft** using the same engine the GUI's *Discover* button calls (`ambermeta.gui.api.core_bridge.discover_draft`) — a topology pool, phases inferred by role, and steps with per-step topology binding and input-coordinate sources. Prints the draft plus any suggestions; with `--write`, saves it as a v2 manifest you can hand-edit.

```bash
ambermeta discover [directory] [options]
```

<!-- BEGIN_CLI_HELP:discover -->
```text
usage: ambermeta discover [-h] [--recursive | --no-recursive]
                          [--pattern PATTERN] [--write WRITE]
                          [--format {json,yaml}]
                          [directory]

Scan a directory into a draft Simulation using the same discover-as-draft
engine as the GUI: a topology pool, phases inferred by role, and steps with
per-step topology binding and input-coordinate sources. Prints the draft and
any suggestions; with --write, saves a v2 manifest you can edit.

positional arguments:
  directory             Directory to scan (default: current directory)

options:
  -h, --help            show this help message and exit
  --recursive, --no-recursive
                        Recurse into subdirectories (default: on; use --no-
                        recursive to disable)
  --pattern PATTERN     Regex filter for discovered files
  --write WRITE         Write the draft to this path as a v2 manifest
  --format {json,yaml}  Format for --write (default: inferred from extension,
                        else json)
```
<!-- END_CLI_HELP:discover -->

`--recursive`/`--no-recursive` is an `argparse.BooleanOptionalAction` pair (recursion is on by default).

```text
$ ambermeta discover tests/data/amber/md_test_files

Simulation summary
==================
Topologies (pool): 1
  - top_CH3L1_HUMAN_6NAG [normal]  CH3L1_HUMAN_6NAG.top
Starting structure: CH3L1_HUMAN_6NAG.crd
Phases: 1

Phase: Production [production]
  - ntp_prod_0001  topology=CH3L1_HUMAN_6NAG.top  input=starting structure  (mdin=ntp_prod_0001.mdin, mdout=ntp_prod_0001.mdout)
  - ntp_prod_0002  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0001 (ntp_prod_0001.rst)  (mdin=ntp_prod_0002.mdin, mdout=ntp_prod_0002.mdout)
  - ntp_prod_0003  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0002 (ntp_prod_0002.rst)  (mdin=ntp_prod_0003.mdin, mdout=ntp_prod_0003.mdout)
  - ntp_prod_0004  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0003 (ntp_prod_0003.rst)  (mdin=ntp_prod_0004.mdin, mdout=ntp_prod_0004.mdout)
  - ntp_prod_0005  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0004 (ntp_prod_0004.rst)  (mdin=ntp_prod_0005.mdin, mdout=ntp_prod_0005.mdout)

Suggestions:
  - [applied] CH3L1_HUMAN_6NAG.crd set as the starting structure
  - [applied] Phase roles inferred from file content/names
```

`ntp_prod_0000` (a bare restart with no `mdin`/`mdout`) isn't turned into a step at all — a step needs at least an `mdin`/`mdout` pair to be a "run"; it is simply excluded from the draft. `CH3L1_HUMAN_6NAG.crd` is picked as the starting structure because it is single-frame coordinates. The printed `input=restart of <step> (<file>)` names the *producing step* and the restart it resolves to, not the raw id: step ids (`10428ec4`, ... in the manifest below) are `uuid4` slices, regenerated on every run, so nothing user-facing prints them and nothing should depend on them being stable across invocations of `discover`.

### Replica trees

When the layout names members — sibling directories whose run sets the inference can reconcile — `discover` tags each
step with a `lineage` and chains each member separately from the starting structure:

```text
$ ambermeta discover runs/

Phase: Production [production]
  - rep1/prod_0001  topology=...  input=starting structure  (mdin=rep1/prod_0001.mdin, ...)
  - rep1/prod_0002  topology=...  input=restart of rep1/prod_0001 (rep1/prod_0001.rst)  ...
  - rep2/prod_0001  topology=...  input=starting structure  (mdin=rep2/prod_0001.mdin, ...)
  - rep2/prod_0002  topology=...  input=restart of rep2/prod_0001 (rep2/prod_0001.rst)  ...
  - rep3/prod_0001  topology=...  input=starting structure  (mdin=rep3/prod_0001.mdin, ...)
  - rep3/prod_0002  topology=...  input=restart of rep3/prod_0001 (rep3/prod_0001.rst)  ...

Suggestions:
  - [applied] CH3L1_HUMAN_6NAG.crd set as the starting structure
  - [applied] Phase roles inferred from file content/names
  - [applied] Runs carry 3 declared lineage(s)
```

There is no `rep1/prod_0002 → rep2/prod_0001` edge: each member's first run reads the starting structure.
The extra `[applied]` card names each member and its run count (and counts untagged runs separately, where
a shared prep directory failed the membership predicate). The inference is reported as data, not as a debug
mode — the tags are in the written manifest, so you can read the claim back off the document.

Two consequences worth knowing before you script against the output:

- With more than one member the draft is **phase-major**: same-role steps of every member share one phase,
  so a member's steps are not contiguous in document order. Group by `lineage`, not by position —
  [manifest §9.2](manifest.md#92-a-multi-lineage-document-is-phase-major).
- An **ambiguous** layout is left untagged rather than guessed at — including any layout that names the
  replica in the *filename* rather than in a directory. Full rule and failure modes:
  [manifest §9.1](manifest.md#91-how-discover-infers-members).

`--write` saves the draft as v2:

```text
$ ambermeta discover tests/data/amber/md_test_files --write sim.yaml --format yaml
...
Wrote v2 draft manifest: sim.yaml (yaml)
```

```yaml
version: 2
simulation:
  topologies:
  - id: top_CH3L1_HUMAN_6NAG
    path: CH3L1_HUMAN_6NAG.top
    kind: normal
  starting_structure: CH3L1_HUMAN_6NAG.crd
phases:
- id: 4ba21bbf
  name: Production
  role: production
  order: 0
steps:
- id: 10428ec4
  name: ntp_prod_0001
  phase: 4ba21bbf
  order: 0
  topology: top_CH3L1_HUMAN_6NAG
  input_coords:
    source: starting_structure
  mdin: ntp_prod_0001.mdin
  mdout: ntp_prod_0001.mdout
  mdcrd: null
  notes: []
  rst: ntp_prod_0001.rst
- id: c261aa4f
  name: ntp_prod_0002
  phase: 4ba21bbf
  order: 1
  topology: top_CH3L1_HUMAN_6NAG
  input_coords:
    source: step
    ref: 10428ec4
  mdin: ntp_prod_0002.mdin
  mdout: ntp_prod_0002.mdout
  mdcrd: null
  notes: []
  rst: ntp_prod_0002.rst
# ... ntp_prod_0003..0005 follow the same shape, each chained to the previous step
```

Note the restart is written **once**, on the step that produced it (`rst:`), and a chained consumer carries only `ref` — the id of the step it continues from. Nothing repeats the path. To find the file a chained step actually starts from, follow `ref` to the producing step and read its `rst`; `ambermeta.simulation.resolve_input_coords` does exactly that, and it is what the `input=restart of ...` line above prints. Paths are written relative to `directory` when the draft's files live under it.

Exit `0` on success; `1` if `directory` doesn't exist, or if discovery finds no phases (nothing to draft) — e.g. an empty or unrecognized directory:

```text
$ ambermeta discover /tmp/empty-dir
No simulation files discovered; nothing to draft.
```

---

## `validate`

Validate one or more files without building a full protocol, **or** validate a whole Simulation manifest with `--manifest`.

```bash
ambermeta validate [options] files...
ambermeta validate --manifest sim.yaml [options]
```

<!-- BEGIN_CLI_HELP:validate -->
```text
usage: ambermeta validate [-h] [--strict] [--format {text,json,yaml}]
                          [--manifest MANIFEST] [--allow-gaps]
                          [files ...]

Quick validation of simulation files with colored output.

positional arguments:
  files                 Files to validate (prmtop, mdin, mdout, mdcrd,
                        inpcrd). Omit when using --manifest.

options:
  -h, --help            show this help message and exit
  --strict              Treat warnings as errors
  --format {text,json,yaml}
                        Output format (default: text)
  --manifest MANIFEST   Validate a whole simulation manifest (v2) —
                        continuity, sequence holes, suggestions
  --allow-gaps          With --manifest: treat unexpected inter-step gaps as
                        allowed
```
<!-- END_CLI_HELP:validate -->

### Per-file mode

Status per file: **OK** (parsed, no warnings), **WARN** (parsed, has warnings), **ERROR** (unreadable/missing). `--strict` turns warnings into a non-zero exit.

```text
$ ambermeta validate tests/data/amber/md_test_files/ntp_prod_0001.mdin tests/data/amber/md_test_files/ntp_prod_0001.mdout

Validation Results
==================================================

OK: tests/data/amber/md_test_files/ntp_prod_0001.mdin

OK: tests/data/amber/md_test_files/ntp_prod_0001.mdout

==================================================
Validation PASSED
```

```text
$ ambermeta validate --format json tests/data/amber/md_test_files/ntp_prod_0001.mdout
{
  "status": "ok",
  "files": [
    { "file": "tests/data/amber/md_test_files/ntp_prod_0001.mdout", "status": "ok", "warnings": [], "errors": [] }
  ],
  "warnings": [],
  "errors": []
}
```

### `--manifest` mode (whole Simulation)

Loads the manifest through `load_simulation` — the manifest must be v2-shaped (a top-level `steps` key) — then runs the same continuity/sequence-hole/suggestion checks `discover` and the GUI's *Validate* panel use. File paths in the manifest resolve relative to the **manifest's own directory**, not the current working directory.

```text
$ ambermeta validate --manifest sim.yaml

Simulation validation

Validation: OK
```

```text
$ ambermeta validate --manifest sim.yaml --format json
{
  "ok": true,
  "totals": { "steps": 25000000.0, "time_ps": 100000.0, "stage_count": 5 },
  "protocol_issues": [],
  "stage_issues": [
    { "name": "ntp_prod_0001", "ok": true, "degraded": false, "errors": [], "warnings": [], "info": [], "continuity": [], "missing_files": [] },
    ...
  ],
  "suggestions": [
    {
      "id": "sug_1", "kind": "starting_structure", "severity": "applied",
      "title": "CH3L1_HUMAN_6NAG.crd set as the starting structure",
      "evidence": "single-frame coordinates; feeds the first run",
      "actions": ["Undo"]
    },
    {
      "id": "sug_2", "kind": "role_guess", "severity": "applied",
      "title": "Phase roles inferred from file content/names",
      "evidence": "Production->production",
      "actions": ["Undo"]
    }
  ]
}
```

`stage_issues[].errors` is where a missing file or bad continuity link surfaces (e.g. `missing prmtop: ...`); `suggestions[].kind` in `{"continuity_gap", "missing_run"}` is what drives the "Continuity / sequence findings" block in text mode, and what `--strict` promotes to a failing exit code. `--allow-gaps` relaxes unexpected-gap findings (`continuity_gap`) without touching sequence holes (`missing_run`).

**On a manifest that declares lineages**, both checks are scoped per member:

- Continuity compares consecutive steps **within** a member, and measures each member's first step against
  the step it actually continues from. Where no producer resolves — which is every head of a `discover`ed
  replica tree, since each reads the starting structure — it reports
  `INFO: Continuity for <name> was not measured (no producing stage resolved).` rather than staying silent.
  A member boundary is not a gap and is never a finding.
- A sequence hole is reported per member, so a replica that stopped early is named
  (`rep2/prod sequence is missing member(s) 2, 3`, with `"lineage": "rep2"` on the suggestion) instead of
  being hidden by its siblings' indices, and members numbered on offset scales raise nothing.

An `[applied]` `lineage_group` suggestion lists what the document declares, and `discover` prints its
evidence — each member and how many runs it holds. Note it describes the **document**, not an
inference: a manifest whose tags you typed by hand is reported the same way.

**The per-member breakdown.** `plan` and `validate --manifest` print each member's own share, so a
replica that stopped early is visible as a quantity beside the finding that names it:

```
Per lineage:
  rep1  3 run(s), 15000000 steps, 60000.000 ps
  rep2  1 run(s),  5000000 steps, 20000.000 ps
  rep3  3 run(s), 15000000 steps, 60000.000 ps
```

The same numbers reach `summary.json` under a top-level `lineages` key, and `totals.lineage_count`
counts the **declared** members — untagged runs form their own bucket but are not a lineage, so the
canonical `common/{min,heat,equil}` + `rep1..3/prod_*` campaign reports 3, not 4. Both keys are
absent from an untagged document's summary.

**Lineage coherence.** Where a document declares more than one member, `plan` and
`validate --manifest` also report what the members do and do not agree about:

```
Lineage coherence:
  WARN Members differ in temp0 (rep1: 300.0; rep2: 310.0).
  INFO 3 steps read the restart written by common/equil and carry 3 distinct resolved seeds.
```

Only a **category error** is fatal — different atom counts, or a member that ran no dynamics beside
one that did. Those exit `1` with or without `--strict`, because members that differ that way are not
runs of one experiment. Everything else (`temp0`, `cut`, `ntt`, `ntp`, `dt`, a repeated seed) is a
finding `--strict` escalates. The output states graph facts and never a statistical property: it will
tell you three runs read one restart and carry three distinct seeds, and it will not tell you they are
independent samples.

`--allow-gaps` is **not** the way to handle replicas — it suppresses every unstated gap in the document
including real ones inside a member, and it does not suppress overlap findings at all. Declare the members
instead. Using both is not an error.

Running the same command against a pre-v2 flat manifest (`global_prmtop`/`stages:`, no `steps` key) fails to load — the same "not a v2 manifest" error [`export`](#export) shows below:

```text
$ ambermeta validate --manifest old_manifest.yaml

ERROR: Failed to load manifest: old_manifest.yaml is not a v2 manifest (no 'steps' key). Rebuild it with `ambermeta discover <dir> --write <path>`.
```

Exit codes: `0` ok; `1` if the manifest can't be found/loaded, or the report isn't ok, or `--strict` and there are continuity/sequence findings; `2` if neither `files` nor `--manifest` is given.

---

## `export`

**New.** Read a **v2** manifest and re-emit it as canonical v2, optionally converting between JSON and YAML. The v1 flat file format cannot be read at all — `export` (like `plan -m` and `validate --manifest`) requires a v2 document and fails cleanly if it isn't one. To build a fresh v2 manifest from a directory, use [`discover --write`](#discover) or [`init`](#init).

```bash
ambermeta export <manifest> [options]
```

<!-- BEGIN_CLI_HELP:export -->
```text
usage: ambermeta export [-h] [-o OUTPUT] [--format {json,yaml}] manifest

Read a v2 manifest and re-emit it as canonical v2. Useful for converting
between json and yaml, or for pretty-printing to stdout. Without --output,
prints JSON to stdout.

positional arguments:
  manifest              Path to the v2 manifest to convert

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Write to this path (default: print JSON to stdout)
  --format {json,yaml}  Output format (default: inferred from --output
                        extension)
```
<!-- END_CLI_HELP:export -->

- Writes through `write_simulation` — **JSON or YAML only**.
- Without `-o/--output`, the result prints as JSON to stdout.

### Convert a manifest to a different format

```text
$ ambermeta export sim.yaml -o sim.json
Wrote v2 manifest: sim.json (json)
```

```json
{
  "version": 2,
  "simulation": {
    "topologies": [
      { "id": "top_CH3L1_HUMAN_6NAG", "path": "CH3L1_HUMAN_6NAG.top", "kind": "normal" }
    ],
    "starting_structure": "CH3L1_HUMAN_6NAG.crd"
  },
  "phases": [
    { "id": "ph_prod", "name": "Production", "role": "production", "order": 0 }
  ],
  "steps": [
    {
      "id": "st_prod_0001", "name": "ntp_prod_0001", "phase": "ph_prod", "order": 0,
      "topology": "top_CH3L1_HUMAN_6NAG",
      "input_coords": { "source": "starting_structure" },
      "mdin": "ntp_prod_0001.mdin", "mdout": "ntp_prod_0001.mdout", "mdcrd": null, "notes": []
    },
    {
      "id": "st_prod_0002", "name": "ntp_prod_0002", "phase": "ph_prod", "order": 1,
      "topology": "top_CH3L1_HUMAN_6NAG",
      "input_coords": { "source": "step", "ref": "st_prod_0001" },
      "mdin": "ntp_prod_0002.mdin", "mdout": "ntp_prod_0002.mdout", "mdcrd": null, "notes": []
    }
  ]
}
```

`export` re-emits the same ids the input manifest already had — it does not assign new ones (that only happens once, in `discover`, when a manifest is first drafted from a directory).

Exit `0` on success; `1` if the manifest is missing, fails to load (malformed content, unreadable file), or isn't a v2 manifest:

```text
$ ambermeta export old_v1_manifest.yaml
ERROR: Failed to load manifest: old_v1_manifest.yaml is not a v2 manifest (no 'steps' key). Rebuild it with `ambermeta discover <dir> --write <path>`.
```

---

## `init`

Write a starting **v2 template** manifest — a static, commented example to hand-edit. `init` does **not** scan `directory` or the filesystem at all; `directory` only sets where the output file is written. To build a v2 manifest from files already on disk, use [`discover --write`](#discover) instead.

```bash
ambermeta init [directory] [options]
```

<!-- BEGIN_CLI_HELP:init -->
```text
usage: ambermeta init [-h] [-o OUTPUT] [--force] [directory]

Create a template manifest.yaml: a commented v2 (Simulation -> Phase -> Step)
document to edit.

positional arguments:
  directory             Directory to write the manifest into (default: current
                        directory)

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Output manifest filename (default: manifest.yaml)
  --force               Overwrite existing output file without prompting
```
<!-- END_CLI_HELP:init -->

### The template

`init` always writes the same static, commented **v2 template**: `version: 2`, a two-entry topology pool (`normal` and `hmr`), minimization + production phases, and `input_coords` shown for both `starting_structure` and `step` sources.

```text
$ ambermeta init -o template.yaml
Created template.yaml (v2)
```

```yaml
# AmberMeta Manifest - v2 (Simulation -> Phase -> Step)
# Topologies live in a Simulation-owned pool; each step binds one by id.
# input_coords.source is one of: starting_structure | step (ref: <step id>) | path
version: 2
simulation:
  topologies:
    - id: top_wt
      path: system.prmtop
      kind: normal          # "normal" or "hmr" (hydrogen-mass-repartitioned)
    - id: top_wt_hmr
      path: system_hmr.prmtop
      kind: hmr
  starting_structure: system.inpcrd
phases:
  - { id: ph_min,  name: Minimization,  role: minimization, order: 0 }
  - { id: ph_prod, name: Production,     role: production,   order: 1 }
steps:
  - id: st_min
    phase: ph_min
    order: 0
    topology: top_wt
    input_coords: { source: starting_structure }
    mdin: min.in
    mdout: min.out
  - id: st_prod_001
    phase: ph_prod
    order: 0
    topology: top_wt_hmr
    input_coords: { source: step, ref: st_min }
    mdin: prod_001.in
    mdout: prod_001.out
    mdcrd: prod_001.nc
    gaps: { expected: null, tolerance: null }
```

`-o/--output` sets the filename (default `manifest.yaml`); `--force` overwrites an existing output file without the interactive confirmation prompt. With no terminal attached (piped or redirected stdin, CI) there is nobody to answer that prompt, so an existing output file is a clean error — `ERROR: manifest.yaml already exists. Use --force to overwrite.`, exit `1` — rather than a failed read.

---

## `info`

Print parsed metadata for a single file.

```bash
ambermeta info [options] file
```

<!-- BEGIN_CLI_HELP:info -->
```text
usage: ambermeta info [-h] [--format {text,json,yaml}] file

Parse and display detailed metadata for AMBER simulation files.

positional arguments:
  file                  File to inspect (prmtop, mdin, mdout, mdcrd, inpcrd)

options:
  -h, --help            show this help message and exit
  --format {text,json,yaml}
                        Output format (default: text)
```
<!-- END_CLI_HELP:info -->

The field names printed here are the parser metadata fields documented in the [API reference §7](api.md#7-parser-metadata-fields). Use `--format json` to feed the metadata into other tools.

```text
$ ambermeta info tests/data/amber/md_test_files/ntp_prod_0001.mdin
File Information: ntp_prod_0001.mdin
============================================================
  filename: tests/data/amber/md_test_files/ntp_prod_0001.mdin
  title: Production (20 ns)
  simulation_type: Molecular Dynamics (MD)
  length_steps: 5000000
  dt: 0.004
  restart_flag: 1
  ensemble: NPT (isotropic)
  stage_role: Production [NPT (isotropic)]
  energy_freq: 25000
  coord_freq: 25000
  restart_freq: 250000
  traj_format: NetCDF
  cutoff: 9.0
  temp_control: Langevin Dynamics
  target_temp: 300.0
  press_control: Berendsen (Isotropic)
  pbc: PBC / Constant Pressure
  constraints: H-bonds
  implicit_solvent: No
  restraints_active: False
  ...
  cntrl_parameters: {'ntx': 5, 'irest': 1, 'ntpr': 25000, 'ntwr': 250000, 'ntwx': 25000, 'nstlim': 5000000, 't': 1000.0, 'dt': 0.004, 'ntt': 3, 'gamma_ln': 1.0, 'ntp': 1, 'ntc': 2, 'ntf': 2, 'ntb': 2, 'cut': 9.0, '_namelist': 'cntrl'}
```

---

## `gui`

Launch the browser-based Simulation editor (requires the `gui` extra). See the [GUI guide](gui.md).

```bash
ambermeta gui [directory] [options]
```

<!-- BEGIN_CLI_HELP:gui -->
```text
usage: ambermeta gui [-h] [--port PORT] [--no-browser] [--host HOST]
                     [directory]

Launch a modern web-based graphical user interface for building simulation
protocol manifests. Features include drag-and-drop file assignment, visual
stage management, sequence detection, and export to multiple formats. Opens in
your default web browser.

positional arguments:
  directory     Directory containing simulation files (default: current
                directory)

options:
  -h, --help    show this help message and exit
  --port PORT   Server port (default: 8765)
  --no-browser  Don't automatically open the browser
  --host HOST   Server host (default: 127.0.0.1)
```
<!-- END_CLI_HELP:gui -->

```bash
ambermeta gui runs/                       # opens http://127.0.0.1:8765
ambermeta gui runs/ --port 9000 --no-browser
```

The server is **localhost-only** and confines all file access to the launch directory (`runs/` above); see [GUI guide § Security model](gui.md) for details. Exit `1` if the `gui` extra isn't installed, or `directory` doesn't exist.

---

## `completion`

Print a shell-completion script.

```bash
ambermeta completion {bash|zsh|fish}
```

<!-- BEGIN_CLI_HELP:completion -->
```text
usage: ambermeta completion [-h] {bash,zsh,fish}

Generate shell completion scripts for ambermeta commands.

positional arguments:
  {bash,zsh,fish}  Shell type for completion script

options:
  -h, --help       show this help message and exit
```
<!-- END_CLI_HELP:completion -->

The generated scripts complete all eight subcommands, including `discover` and `export`. See [Install & completion](#install--completion) for one-time setup per shell.

---

## Exit codes

| Code | Command(s) | Meaning |
|---|---|---|
| `0` | all | Success (including a fault-tolerant `plan` that skipped bad files, or a `plan`/`validate` run that reported continuity or sequence findings without `--strict`) |
| `1` | `plan`, `discover`, `validate`, `export`, `init`, `info`, `gui` | Runtime failure: unreadable/missing input, parse failure, nothing discovered, manifest not found/invalid, validation findings, a `--strict` hard stop, `--strict` with any continuity/sequence finding (on `plan` as well as `validate`), or a missing extra/directory (`gui`) |
| `2` | `plan`, `validate` | Bad invocation: `plan` with no mode selected (`--manifest`/`--recursive`/`--interactive`); `validate` with neither `files` nor `--manifest` |

---

## Environment variables

Manifest paths support `${VAR}`/`$VAR` expansion by default. Every manifest-reading command — `plan -m`, `export`, `validate --manifest` — loads through `ambermeta.simulation.load_simulation`, which shares the same underlying reader, so expansion behaves identically everywhere (`init` never reads a manifest, only writes a template):

```yaml
version: 2
simulation:
  topologies:
    - id: top_wt
      path: ${PROJECT_DIR}/system.prmtop
      kind: normal
  starting_structure: ${PROJECT_DIR}/system.inpcrd
phases:
  - { id: ph_prod, name: Production, role: production, order: 0 }
steps:
  - id: st_prod
    name: production
    phase: ph_prod
    topology: top_wt
    input_coords: { source: starting_structure }
    mdin:  ${PROJECT_DIR}/input/prod.mdin
    mdout: ${PROJECT_DIR}/output/prod.mdout
```

(Use block style for any value containing `${...}`: inside a YAML *flow* mapping — `{ path: ${VAR}/x }` — the
brace opens a nested flow collection and the document fails to parse. Quoting works too.)

Disable with `--no-expand-env` (`plan` only). Full rules in the [manifest reference §8](manifest.md#8-environment-variable-expansion).

---

## See also

- [README](../README.md) — overview and quickstart
- [Tutorials](tutorials.md) — task-oriented walkthroughs · [Recipes](recipes.md) — copy-paste one-liners
- [Manifest schema](manifest.md) · [Python API](api.md) · [GUI guide](gui.md)
