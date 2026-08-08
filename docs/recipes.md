# Recipes

Short, copy-paste CLI one-liners for common jobs. All examples run from inside the sample data directory `tests/data/amber/md_test_files/` (a 64,528-atom glycoprotein system with a five-run `ntp_prod_0001..0005` production sequence):

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
  - ntp_prod_0002  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0001 (ntp_prod_0001.rst)  (mdin=ntp_prod_0002.mdin, mdout=ntp_prod_0002.mdout)
  - ntp_prod_0003  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0002 (ntp_prod_0002.rst)  (mdin=ntp_prod_0003.mdin, mdout=ntp_prod_0003.mdout)
  - ntp_prod_0004  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0003 (ntp_prod_0003.rst)  (mdin=ntp_prod_0004.mdin, mdout=ntp_prod_0004.mdout)
  - ntp_prod_0005  topology=CH3L1_HUMAN_6NAG.top  input=restart of ntp_prod_0004 (ntp_prod_0004.rst)  (mdin=ntp_prod_0005.mdin, mdout=ntp_prod_0005.mdout)

Suggestions:
  - [applied] CH3L1_HUMAN_6NAG.crd set as the starting structure
  - [applied] Phase roles inferred from file content/names

Wrote v2 draft manifest: sim.yaml (yaml)
```

Builds a topology pool, infers phase roles, and chains each step's input coordinates off the previous step's restart (`input=restart of <step name>`) — the previous step **of the same lineage**, where the layout names members. In the file itself that chain is stored as a step id reference; the ids are freshly generated each run, so don't expect them to be stable across runs. Edit `sim.yaml` by hand, or refine it in the GUI, before committing to it.

### Discover a replica tree

```bash
ambermeta discover runs/ --write replicas.yaml
```

```
Phase: Production [production]
  - rep1/prod_0001  input=starting structure  ...
  - rep1/prod_0002  input=restart of rep1/prod_0001 (rep1/prod_0001.rst)  ...
  - rep2/prod_0001  input=starting structure  ...
  - rep2/prod_0002  input=restart of rep2/prod_0001 (rep2/prod_0001.rst)  ...
  - rep3/prod_0001  input=starting structure  ...
  - rep3/prod_0002  input=restart of rep3/prod_0001 (rep3/prod_0001.rst)  ...

Suggestions:
  ...
  - [applied] Runs carry 3 declared lineage(s)
```

`rep1/`, `rep2/`, `rep3/` are sibling directories whose run sets the inference can reconcile, so each is tagged as a member and gets its own chain from the starting structure — no `rep1/prod_0002 → rep2/prod_0001` edge. The tags land in the manifest as `lineage:` on each step. An ambiguous layout is left untagged rather than guessed at; the rule and everything it refuses is in [manifest §9.1](manifest.md#91-how-discover-infers-members).

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

Checks the whole Simulation: restart-to-input-coordinate continuity between consecutive steps, gaps in a numbered run sequence, and missing files. Add `--strict` to fail on warnings too, or `--format json` for CI parsing.

On a manifest declaring lineages, "consecutive" means consecutive within a member, and a numbered-sequence hole is reported per member — so a replica that stopped early is named (`rep2/prod sequence is missing member(s) 2, 3`) instead of being averaged away, and replicas numbered on offset scales raise nothing. Do **not** reach for `--allow-gaps` to quieten a replica tree; see [tutorials §2](tutorials.md#2-validate-continuity-and-catch-a-sequence-hole).

### Convert a manifest between YAML and JSON

```bash
ambermeta export sim.yaml -o sim.json
```

```
Wrote v2 manifest: sim.json (json)
```

Re-emits the manifest as canonical v2 in the format implied by the `-o` extension; add `--format json` or `--format yaml` to force it. Omit `-o` to pretty-print the JSON to stdout instead. YAML and JSON are the only manifest formats.

### Export all publication artifacts in one run

```bash
ambermeta plan . --manifest sim.yaml \
  --summary-path protocol.json \
  --methods-summary-path methods.json \
  --stats-csv stats.csv
```

```
...
Wrote summary: /abs/path/protocol.json
Wrote methods_summary: /abs/path/methods.json
Wrote stats_csv: /abs/path/stats.csv
```

`methods.json` is the Materials-&-Methods summary; `stats.csv` is one row per step (temperature/pressure/density/energy as mean ± σ); `protocol.json` is the full record. The command first prints the same `Simulation summary` block as `discover`, then writes the three artifacts. Each one needs its own path — aiming two at the same file is a hard error (exit `2`).

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

The flat-discovery engine: groups files by stem, infers stage roles from path/content, and prints the classic per-stage "Protocol summary" without ever writing a manifest.

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

Avoids repeating a topology on each stage in the flat-discovery path. In a v2 manifest the equivalent is a single entry in the Simulation's `topologies:` pool, referenced by id from every step (see the [manifest schema](manifest.md)).

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
ambermeta init . --output template.yaml
```

```
Created template.yaml (v2)
```

Emits a Simulation → Phase → Step skeleton with inline comments — `init` writes nothing else, and never scans the directory. Add `--force` to overwrite an existing file without the confirmation prompt. To draft a manifest from real files, use `discover` above.

---

## See also

- [CLI reference](cli.md) · [Tutorials](tutorials.md) · [Manifest schema](manifest.md)
