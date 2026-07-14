# CLI reference

**The `ambermeta` command line is the complete, headless interface to the engine** — everything AmberMeta does is reachable here, no GUI required. It is the right surface for scripting, CI gates, and cluster/SSH work.

Eight commands sit under one entry point:

| Command | Purpose |
|---|---|
| [`plan`](#plan) | Build and summarize a manifest (v2-aware) or a discovered/interactive protocol; export reproducibility artifacts |
| [`discover`](#discover) | Scan a directory into a **Simulation draft** (topology pool + phases + steps) |
| [`validate`](#validate) | Validate individual files, or a whole Simulation manifest with `--manifest` |
| [`export`](#export) | Convert a manifest (v1 auto-migrated) to canonical **v2** or a legacy flat manifest |
| [`init`](#init) | Generate a manifest — v1 templates, `--auto` discovery, or `--v2` |
| [`info`](#info) | Print parsed metadata for a single file |
| [`gui`](#gui) | Launch the browser GUI |
| [`completion`](#completion) | Emit a shell-completion script |

> The help blocks below are generated directly from `ambermeta/cli.py::build_parser()` (or `ambermeta <cmd> --help`) and kept accurate to the shipped parser. `plan`/`init`/`validate`/`gui`/`info`/`completion` are checked in CI (`scripts/export_cli_help.py --check`); `discover`/`export` are newer commands whose help text is reproduced here from the live `--help` output but not yet wired into that checker.

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
    export              Convert a manifest to canonical v2 or a legacy flat
                        manifest
    init                Generate an example manifest file
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
  init      Generate example manifest templates
  export    Convert a manifest to canonical v2 or a legacy flat manifest

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
  ambermeta init --template standard .      Generate manifest template
  ambermeta export old.yaml -o sim.yaml       Upgrade a v1 manifest to v2

File Types:
  prmtop:  .prmtop, .top, .parm7    (topology/parameters)
  mdin:    .mdin, .in               (input control)
  mdout:   .mdout, .out             (output log)
  mdcrd:   .nc, .mdcrd, .crd        (trajectory)
  inpcrd:  .rst, .rst7, .ncrst      (coordinates/restart)

For documentation, visit: https://github.com/MicheleBonus/ambermeta
```

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
                        Skip continuity checks between consecutive stages
                        (overrides the manifest's settings.strict_validation)
  --strict              Abort on the first unreadable/malformed input file
                        instead of skipping it. Default is to skip the file
                        and continue.
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

### Modes

| Mode | Flag | Behavior |
|---|---|---|
| Manifest | `-m/--manifest FILE` | Load a manifest; honors `settings.strict_validation` |
| Discovery | `--recursive` | Group files by stem and infer roles; `--pattern REGEX` filters (this mode only) |
| Interactive | `--interactive` | Prompt for each stage's files, role, restart, and gap/tolerance |

### `plan -m` is manifest-shape-aware

`plan` inspects the **raw manifest shape**, not just its content, before deciding how to render it:

- **Actually v2-shaped** (`version: 2`, or a document with top-level `phases`/`simulation` keys) → loaded as a `Simulation` (`ambermeta.simulation.load_simulation`) and printed as the **Simulation → Phase → Step structure**, plus continuity/sequence-hole findings (the same engine `discover` and `validate --manifest` use).
- **v1 flat** (`stages: [...]`, with or without `global_prmtop`/`hmr_prmtop`) → still goes through the **retained flat engine** (`load_protocol_from_manifest`) and prints the classic per-stage **Protocol summary**, exactly as in v1. It is *not* auto-promoted to the new view here — that only happens in `validate --manifest` and `export`, which explicitly load through `load_simulation`'s tolerant reader.

`--recursive` discovery under `plan` also always uses the retained flat engine ("Protocol summary"); use [`discover`](#discover) for the new Simulation-draft view of a directory.

### Exports (manifest/recursive modes only)

| Flag | Output |
|---|---|
| `--summary-path FILE` | Full protocol summary (JSON/YAML; `--summary-format` forces the format) |
| `--methods-summary-path FILE` | Materials-&-Methods JSON: software, MD engine settings, system composition, restraints |
| `--stats-csv FILE` | Per-stage statistics (one row per stage) |

The CSV header is exactly:

```text
stage_name,stage_role,time_start_ps,time_end_ps,duration_ns,frame_count,temp_avg,temp_std,pressure_avg,pressure_std,density_avg,density_std,etot_avg,etot_std
```

### Behavior

- **Fault-tolerant by default.** A missing/malformed/unreadable file is skipped, the error is recorded against its stage, a skip summary is printed, and the run exits `0`. `--strict` makes the first bad file a hard error (clean message, exit `1`, no traceback). A stage keeps every file that *did* parse.
- **Cross-stage validation** runs unless `settings.strict_validation: false`; `--skip-cross-stage-validation` overrides the manifest and skips it unconditionally.

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
  - ntp_prod_0002  topology=CH3L1_HUMAN_6NAG.top  input=step 10428ec4  (mdin=ntp_prod_0002.mdin, mdout=ntp_prod_0002.mdout)
  - ntp_prod_0003  topology=CH3L1_HUMAN_6NAG.top  input=step c261aa4f  (mdin=ntp_prod_0003.mdin, mdout=ntp_prod_0003.mdout)
  - ntp_prod_0004  topology=CH3L1_HUMAN_6NAG.top  input=step aae0b2b3  (mdin=ntp_prod_0004.mdin, mdout=ntp_prod_0004.mdout)
  - ntp_prod_0005  topology=CH3L1_HUMAN_6NAG.top  input=step 04ec75b7  (mdin=ntp_prod_0005.mdin, mdout=ntp_prod_0005.mdout)

Validation: OK
```

(`input=step <id>` is the source step's id — the continuity chain. The healthy 20 ns inter-run gaps between the sample sequence's runs fall inside the expected window and are not flagged, so there are no continuity findings.)

#### `-m` on a v1 flat manifest — unchanged

```text
$ ambermeta plan tests/data/amber/md_test_files -m v1_manifest.yaml

Loading manifest: v1_manifest.yaml

Protocol summary
================
Stages: 7
Total steps: 25000000
Total simulated time (ps): 100000.000

- CH3L1_HUMAN_6NAG
  intent: Unknown
  result: Unknown
  prmtop: atoms=64528, box=98.34×76.05×81.23 Å, density=0.843 g/cc
  mdcrd: parsed
  evidence: INFO: using global prmtop: CH3L1_HUMAN_6NAG.top; Atom count mismatch across ['prmtop', 'mdcrd']: [64528, 0]
  ...
```

---

## `discover`

**New.** Discover-as-draft: scan a directory into a **Simulation draft** using the same engine the GUI's *Discover* button calls (`ambermeta.gui.api.core_bridge.discover_draft`) — a topology pool, phases inferred by role, and steps with per-step topology binding and input-coordinate sources. Prints the draft plus any suggestions; with `--write`, saves it as a v2 manifest you can hand-edit.

```bash
ambermeta discover [directory] [options]
```

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
  - ntp_prod_0002  topology=CH3L1_HUMAN_6NAG.top  input=step 10428ec4  (mdin=ntp_prod_0002.mdin, mdout=ntp_prod_0002.mdout)
  - ntp_prod_0003  topology=CH3L1_HUMAN_6NAG.top  input=step c261aa4f  (mdin=ntp_prod_0003.mdin, mdout=ntp_prod_0003.mdout)
  - ntp_prod_0004  topology=CH3L1_HUMAN_6NAG.top  input=step aae0b2b3  (mdin=ntp_prod_0004.mdin, mdout=ntp_prod_0004.mdout)
  - ntp_prod_0005  topology=CH3L1_HUMAN_6NAG.top  input=step 04ec75b7  (mdin=ntp_prod_0005.mdin, mdout=ntp_prod_0005.mdout)

Suggestions:
  - [applied] CH3L1_HUMAN_6NAG.crd set as the starting structure
  - [applied] Phase roles inferred from file content/names
```

`ntp_prod_0000` (a bare restart with no `mdin`/`mdout`) isn't turned into a step at all — a step needs at least an `mdin`/`mdout` pair to be a "run"; it is simply excluded from the draft. `CH3L1_HUMAN_6NAG.crd` is picked as the starting structure because it is single-frame coordinates. Step ids (`10428ec4`, ...) are randomly generated each run — do not depend on them being stable across invocations of `discover`.

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
- id: c261aa4f
  name: ntp_prod_0002
  phase: 4ba21bbf
  order: 1
  topology: top_CH3L1_HUMAN_6NAG
  input_coords:
    source: step
    ref: 10428ec4
    path: ntp_prod_0001.rst
  mdin: ntp_prod_0002.mdin
  mdout: ntp_prod_0002.mdout
  mdcrd: null
  notes: []
# ... ntp_prod_0003..0005 follow the same shape, each chained to the previous step
```

Note `input_coords` on a chained step carries **both** `ref` (the source step's id) *and* the resolved `path` (its output restart) — the manifest stays self-describing even if you inspect it outside AmberMeta. Paths are written relative to `directory` when the draft's files live under it.

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
  --manifest MANIFEST   Validate a whole simulation manifest (v1 auto-
                        migrated) — continuity, sequence holes, suggestions
  --allow-gaps          With --manifest: treat unexpected inter-step gaps as
                        allowed
```

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

Loads the manifest through `load_simulation` — **any v1 manifest is auto-migrated in memory first** — then runs the same continuity/sequence-hole/suggestion checks `discover` and the GUI's *Validate* panel use. File paths in the manifest resolve relative to the **manifest's own directory**, not the current working directory.

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

Running the same command against a v1 flat manifest (`global_prmtop`/`stages:`) works unchanged — the reader migrates it before validating:

```text
$ ambermeta validate --manifest v1_manifest.yaml

Simulation validation

Validation: OK
```

Exit codes: `0` ok; `1` if the manifest can't be found/loaded, or the report isn't ok, or `--strict` and there are continuity/sequence findings; `2` if neither `files` nor `--manifest` is given.

---

## `export`

**New.** Read any manifest — a v1 flat manifest is auto-migrated — and re-emit it as canonical **v2** or a **legacy flat** manifest. This is the command to upgrade an old manifest, or to hand a v2-authored manifest to a downstream tool that only understands the flat `stages:` shape.

```bash
ambermeta export <manifest> [options]
```

```text
usage: ambermeta export [-h] [--to {v2,legacy}] [-o OUTPUT]
                        [--format {json,yaml,toml,csv}]
                        manifest

Read any manifest (a v1 flat manifest is auto-migrated) and re-emit it. --to
v2 writes the canonical Simulation manifest (json/yaml); --to legacy writes a
flat stages: manifest (json/yaml/toml/csv) for downstream tools. Without
--output, prints JSON to stdout.

positional arguments:
  manifest              Path to the manifest to convert

options:
  -h, --help            show this help message and exit
  --to {v2,legacy}      Target representation (default: v2)
  -o OUTPUT, --output OUTPUT
                        Write to this path (default: print JSON to stdout)
  --format {json,yaml,toml,csv}
                        Output format (default: inferred from --output
                        extension)
```

- `--to v2` (default): writes through `write_simulation` — **JSON or YAML only**.
- `--to legacy`: flattens every phase's steps back into a `stages:` list (`global_prmtop`/`hmr_prmtop` from the topology pool's `normal`/`hmr` entries, `input_coords` resolved to an `inpcrd` path) — JSON/YAML/TOML/CSV.
- Without `-o/--output`, the result prints as JSON to stdout regardless of `--to`.

### Upgrade a v1 manifest to v2

```text
$ ambermeta export v1_manifest.yaml -o sim_v2.yaml --format yaml
Wrote v2 manifest: sim_v2.yaml (yaml)
```

```yaml
version: 2
simulation:
  topologies:
  - id: top_0
    path: CH3L1_HUMAN_6NAG.top
    kind: normal
  starting_structure: null
phases:
- id: ph_0
  name: Stage
  role: ''
  order: 0
- id: ph_1
  name: Production
  role: production
  order: 1
steps:
- id: st_0
  name: CH3L1_HUMAN_6NAG
  phase: ph_0
  ...
```

Unlike `discover`'s randomly generated ids, migration from a v1 manifest assigns **deterministic** ids (`top_0`, `ph_0`, `st_0`, ...) in source order — rerunning `export` on the same input reproduces the same ids.

### Downgrade a v2 manifest to legacy flat

```text
$ ambermeta export sim.yaml --to legacy
{
  "global_prmtop": "CH3L1_HUMAN_6NAG.top",
  "stages": [
    {
      "name": "ntp_prod_0001",
      "stage_role": "production",
      "prmtop": "CH3L1_HUMAN_6NAG.top",
      "mdin": "ntp_prod_0001.mdin",
      "mdout": "ntp_prod_0001.mdout",
      "inpcrd": "CH3L1_HUMAN_6NAG.crd"
    },
    {
      "name": "ntp_prod_0002",
      "stage_role": "production",
      "prmtop": "CH3L1_HUMAN_6NAG.top",
      "mdin": "ntp_prod_0002.mdin",
      "mdout": "ntp_prod_0002.mdout",
      "inpcrd": "ntp_prod_0001.rst"
    },
    ...
  ]
}
```

Exit `0` on success; `1` if the manifest is missing or fails to load (malformed content, unreadable file).

---

## `init`

Generate a manifest — a v1 template, `--auto` to bootstrap one from a directory, or `--v2` for a commented v2 template.

```bash
ambermeta init [directory] [options]
```

```text
usage: ambermeta init [-h] [-o OUTPUT]
                      [--template {minimal,standard,comprehensive}] [--auto]
                      [--format {yaml,json,toml,csv}] [--validate] [--dry-run]
                      [--force] [--v2]
                      [directory]

Create a template manifest.yaml with example stages.

positional arguments:
  directory             Directory to scan for files (default: current
                        directory)

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Output manifest filename (default: manifest.yaml)
  --template {minimal,standard,comprehensive}
                        Template complexity (default: standard)
  --auto                Non-interactive bootstrap mode: recursively discover
                        files and auto-generate grouped stages
  --format {yaml,json,toml,csv}
                        Manifest output format for --auto mode (default:
                        inferred from output extension or yaml)
  --validate            Run parsers against discovered files after writing the
                        manifest and print a concise summary
  --dry-run             Preview discovered stage grouping in --auto mode
                        without writing output files
  --force               Overwrite existing output file without prompting
                        (required for non-interactive --auto mode)
  --v2                  Emit a v2 (Simulation → Phase → Step) template
                        manifest instead of the v1 flat template
```

### `--v2`

Writes a static, commented **v2 template** (`version: 2`, a two-entry topology pool, minimization + production phases, `input_coords` shown for both `starting_structure` and `step` sources) — it does **not** scan `directory`; it's a starting point to hand-edit, the v2 counterpart of the v1 `--template` modes. Takes priority over `--auto`/`--template` if both are passed.

```text
$ ambermeta init --v2 -o template.yaml --format yaml
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

### `--auto` (v1 flat, unchanged)

`--auto` discovers files recursively and writes **one stage per file-group stem** — numbered sequences (`prod_0001`, `prod_0002`, …) stay separate, not collapsed. Topology is classified automatically: an HMR-scaled prmtop becomes top-level `hmr_prmtop`, others `global_prmtop` (HMR detection checks the `ATOMIC_NUMBER` section, falling back to atom-name patterns). Use `--dry-run` to preview without writing.

```text
$ ambermeta init tests/data/amber/md_test_files --auto --dry-run

Auto-grouped stages:
  global_prmtop: CH3L1_HUMAN_6NAG.top
  1. CH3L1_HUMAN_6NAG [unclassified]
     mdcrd: CH3L1_HUMAN_6NAG.crd
  2. ntp_prod_0000 [production]
     inpcrd: ntp_prod_0000.rst
  3. ntp_prod_0001 [production]
     mdin: ntp_prod_0001.mdin
     mdout: ntp_prod_0001.mdout
     inpcrd: ntp_prod_0001.rst
  4. ntp_prod_0002 [production]
     mdin: ntp_prod_0002.mdin
     mdout: ntp_prod_0002.mdout
     inpcrd: ntp_prod_0002.rst
  5. ntp_prod_0003 [production]
     mdin: ntp_prod_0003.mdin
     mdout: ntp_prod_0003.mdout
     inpcrd: ntp_prod_0003.rst
  6. ntp_prod_0004 [production]
     mdin: ntp_prod_0004.mdin
     mdout: ntp_prod_0004.mdout
     inpcrd: ntp_prod_0004.rst
  7. ntp_prod_0005 [production]
     mdin: ntp_prod_0005.mdin
     mdout: ntp_prod_0005.mdout
     inpcrd: ntp_prod_0005.rst

Dry run complete; no files were written.
```

The v1 flat manifest this writes (without `--dry-run`) is exactly what [`export`](#export) upgrades to v2, and what `plan -m`/`validate --manifest` auto-migrate on open — see those sections for the round trip.

> ⚠️ `--auto` is non-interactive and needs `--force` to overwrite an existing output file. `--format` only applies in `--auto` mode (it warns otherwise).

---

## `info`

Print parsed metadata for a single file.

```bash
ambermeta info [options] file
```

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

```text
usage: ambermeta completion [-h] {bash,zsh,fish}

Generate shell completion scripts for ambermeta commands.

positional arguments:
  {bash,zsh,fish}  Shell type for completion script

options:
  -h, --help       show this help message and exit
```

The generated scripts complete all eight subcommands, including `discover` and `export`. See [Install & completion](#install--completion) for one-time setup per shell.

---

## Exit codes

| Code | Command(s) | Meaning |
|---|---|---|
| `0` | all | Success (including a fault-tolerant `plan` that skipped bad files, or `validate --manifest`/`validate <files>` with no failing findings) |
| `1` | `plan`, `discover`, `validate`, `export`, `init`, `info`, `gui` | Runtime failure: unreadable/missing input, parse failure, nothing discovered, manifest not found/invalid, validation findings, a `--strict` hard stop, or a missing extra/directory (`gui`) |
| `2` | `plan`, `validate` | Bad invocation: `plan` with no mode selected (`--manifest`/`--recursive`/`--interactive`); `validate` with neither `files` nor `--manifest` |

---

## Environment variables

Manifest paths support `${VAR}`/`$VAR` expansion by default (this applies to `plan -m` and `init`'s legacy manifest-reading path; `discover`/`export`/`validate --manifest` load through `ambermeta.simulation.load_simulation`, which shares the same underlying reader):

```yaml
stages:
  - name: production
    prmtop: ${PROJECT_DIR}/system.prmtop
    mdout: ${PROJECT_DIR}/output/prod.mdout
```

Disable with `--no-expand-env` (`plan` only). Full rules in the [manifest reference §10](manifest.md#10-environment-variable-expansion).

---

## See also

- [README](../README.md) — overview and quickstart
- [Tutorials](tutorials.md) — task-oriented walkthroughs · [Recipes](recipes.md) — copy-paste one-liners
- [Manifest schema](manifest.md) · [Python API](api.md) · [GUI guide](gui.md)
