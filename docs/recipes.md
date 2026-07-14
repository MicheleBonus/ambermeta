# Recipes

Short, copy-paste CLI one-liners for common jobs. All examples run from inside the sample data directory `tests/data/amber/md_test_files/` (a 64,528-atom glycoprotein system with a six-member `ntp_prod_0001..0005` production sequence):

```bash
cd tests/data/amber/md_test_files
```

For the full flag set see the [CLI reference](cli.md); for step-by-step context see the [tutorials](tutorials.md); for the manifest shape see the [manifest schema](manifest.md).

---

### Draft a v2 manifest from a directory

```bash
ambermeta discover . --write sim.yaml
```

```
Simulation summary
==================
Topologies (pool): 1
  - top_CH3L1_HUMAN_6NAG [normal]  CH3L1_HUMAN_6NAG.top
Starting structure: CH3L1_HUMAN_6NAG.crd
Phases: 1

Phase: Production [production]
  - ntp_prod_0001  topology=CH3L1_HUMAN_6NAG.top  input=starting structure  (mdin=ntp_prod_0001.mdin, mdout=ntp_prod_0001.mdout)
  - ntp_prod_0002  topology=CH3L1_HUMAN_6NAG.top  input=step b2b649c0  (mdin=ntp_prod_0002.mdin, mdout=ntp_prod_0002.mdout)
  - ntp_prod_0003  topology=CH3L1_HUMAN_6NAG.top  input=step abe19957  (mdin=ntp_prod_0003.mdin, mdout=ntp_prod_0003.mdout)
  - ntp_prod_0004  topology=CH3L1_HUMAN_6NAG.top  input=step 4aa9b53f  (mdin=ntp_prod_0004.mdin, mdout=ntp_prod_0004.mdout)
  - ntp_prod_0005  topology=CH3L1_HUMAN_6NAG.top  input=step e50d2b7d  (mdin=ntp_prod_0005.mdin, mdout=ntp_prod_0005.mdout)

Suggestions:
  - [applied] CH3L1_HUMAN_6NAG.crd set as the starting structure
  - [applied] Phase roles inferred from file content/names

Wrote v2 draft manifest: sim.yaml (yaml)
```

Builds a topology pool, infers phase roles, and chains each step's input coordinates off the previous step's restart (`input=step <id>`). The `<id>` values are freshly generated each run — don't expect them to be stable across runs. Edit `sim.yaml` by hand, or refine it in the GUI, before committing to it.

### Preview the draft without writing anything

```bash
ambermeta discover .
```

Same summary and suggestions, no file written. Add `--pattern 'prod_.*'` to restrict which files are scanned, or `--no-recursive` to stay in the top-level directory.

### Validate a manifest's continuity and sequence holes

```bash
ambermeta validate --manifest sim.yaml
```

```
Simulation validation

Validation: OK
```

Checks the whole Simulation (a v1 flat manifest auto-migrates first): restart-to-input-coordinate continuity between consecutive steps, gaps in a numbered run sequence, and missing files. Add `--strict` to fail on warnings too, or `--format json` for CI parsing.

### Upgrade a v1 manifest to canonical v2

```bash
ambermeta export old_manifest.yaml --to v2 -o sim.yaml
```

Reads any manifest — including a legacy flat `stages:` list with `global_prmtop`/`hmr_prmtop` — and re-emits it as a v2 `Simulation` document (`global_prmtop` becomes a `normal` pool entry, `hmr_prmtop` an `hmr` entry, `initial_coordinates` becomes the starting structure). Add `--format yaml` (or `json`) to control the output syntax — v2 writes JSON/YAML only; omit `-o` to print JSON to stdout instead.

### Convert a v2 manifest to legacy flat (for downstream tooling)

```bash
ambermeta export sim.yaml --to legacy -o legacy.yaml
```

```
Wrote legacy manifest: legacy.yaml (yaml)
```

`--to legacy` also accepts `--format toml` or `--format csv`, which v2 itself does not support (`write_simulation` writes JSON/YAML only). Useful for scripts still built on the old flat shape, or as the input to `plan --manifest` below.

### Export all publication artifacts in one run

```bash
ambermeta plan . --manifest legacy.yaml \
  --summary-path protocol.json \
  --methods-summary-path methods.json \
  --stats-csv stats.csv
```

`methods.json` is the Materials-&-Methods summary; `stats.csv` is one row per step (temperature/pressure/density/energy as mean ± σ); `protocol.json` is the full record. This publication-export path (`--summary-path`/`--methods-summary-path`/`--stats-csv`) reads the flat protocol engine, so point `--manifest` at a legacy manifest — as produced by `export --to legacy` above, or `init --auto` below — rather than a v2 one.

### Reconstruct and summarize a directory — no manifest needed

```bash
ambermeta plan . --recursive --auto-detect-restarts
```

```
Scanning .../tests/data/amber/md_test_files recursively for simulation files...
Discovered 7 stage(s).

Protocol summary
================
Stages: 7
Total steps: 25000000
Total simulated time (ps): 100000.000
...
```

The retained flat-discovery engine: groups files by stem, infers stage roles from path/content, and prints the classic per-stage "Protocol summary" without ever writing a manifest.

### Validate a tree as a CI gate (non-zero exit on problems)

```bash
ambermeta validate --strict CH3L1_HUMAN_6NAG.top ntp_prod_0001.mdout
```

```
Validation Results
==================================================

OK: CH3L1_HUMAN_6NAG.top

OK: ntp_prod_0001.mdout

==================================================
Validation PASSED
```

`--strict` turns warnings into a failing exit code. Works on individual files as shown, or point it at a manifest with `--manifest` instead (see above).

### Inspect one file as JSON and pipe into jq

```bash
ambermeta info --format json CH3L1_HUMAN_6NAG.top | jq '{atoms: .natom, hmr: .hmr_active}'
# => {"atoms": 64528, "hmr": false}
ambermeta info --format json ntp_prod_0001.mdout | jq '.stats'
```

### Share one topology across every discovered run

```bash
ambermeta plan . --recursive --prmtop CH3L1_HUMAN_6NAG.top
```

Avoids repeating a topology on each stage in the retained flat-discovery path. In a v2 manifest the equivalent is a single entry in the Simulation's `topologies:` pool, referenced by id from every step (see the [manifest schema](manifest.md)).

### Filter discovery to production runs only

```bash
ambermeta plan . --recursive --pattern 'prod_.*' --stats-csv prod_stats.csv
```

`--pattern` (a regex) applies in `--recursive` mode; `discover` accepts the same flag when drafting a v2 manifest.

### Strict mode — fail on the first unreadable file

```bash
ambermeta plan . --recursive --strict
```

Default behavior skips a bad file and continues (exit `0`); `--strict` makes the first one a clean hard error (exit `1`, no traceback).

### Quiet + file logging for unattended pipelines

```bash
ambermeta --quiet --log-file run.log plan . --recursive --summary-path out.json
```

`--quiet` suppresses stdout (errors/usage still go to stderr); `--log-file` keeps a record.

### Generate a commented v2 template to hand-edit

```bash
ambermeta init . --v2 --output template.yaml
```

```
Created template.yaml (v2)
```

Emits a Simulation → Phase → Step skeleton with inline comments instead of the v1 flat template; drop `--v2` for the classic `--template {minimal,standard,comprehensive}` manifests.

---

## See also

- [CLI reference](cli.md) · [Tutorials](tutorials.md) · [Manifest schema](manifest.md)
