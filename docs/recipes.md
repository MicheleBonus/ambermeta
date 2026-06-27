# Recipes

Short, copy-paste CLI one-liners for common jobs. For the full flag set see the [CLI reference](cli.md); for step-by-step context see the [tutorials](tutorials.md).

---

### Bootstrap a manifest from a directory

```bash
ambermeta init runs/ --auto --output manifest.yaml --validate --force
```

Scans recursively, groups files into stages (one per file group), classifies topology (normal vs. HMR), writes the canonical manifest, and runs the parsers so you catch problems immediately.

### Preview the grouping without writing anything

```bash
ambermeta init runs/ --auto --dry-run
```

### Reconstruct and summarize a directory — no manifest needed

```bash
ambermeta plan runs/ --recursive --auto-detect-restarts
```

### Export all publication artifacts in one run

```bash
ambermeta plan runs/ --manifest manifest.yaml \
  --summary-path protocol.json \
  --methods-summary-path methods.json \
  --stats-csv stats.csv
```

`methods.json` is the Materials-&-Methods summary; `stats.csv` is one row per stage (temperature/pressure/density/energy as mean ± σ); `protocol.json` is the full record.

### Validate a tree as a CI gate (non-zero exit on problems)

```bash
ambermeta validate --strict runs/*.{prmtop,parm7,top,mdin,in,mdout,out,nc,rst,rst7,ncrst}
```

`--strict` turns warnings into a failing exit code. If your shell doesn't expand a glob (no matches), run one invocation per type.

### Inspect one file as JSON and pipe into jq

```bash
ambermeta info --format json prod.mdout | jq '.stats'
ambermeta info --format json system.prmtop | jq '{atoms: .natom, hmr: .hmr_active}'
```

### Share one topology across every stage

```bash
ambermeta plan runs/ --recursive --prmtop systems/complex.prmtop
```

Avoids repeating `prmtop` on each stage; equivalent to a top-level `global_prmtop` in a manifest.

### Filter discovery to production runs only

```bash
ambermeta plan runs/ --recursive --pattern 'prod_.*' --stats-csv prod_stats.csv
```

`--pattern` (a regex) applies only in `--recursive` mode.

### Strict mode — fail on the first unreadable file

```bash
ambermeta plan runs/ --recursive --strict
```

Default behavior skips a bad file and continues (exit `0`); `--strict` makes the first one a clean hard error (exit `1`, no traceback).

### Quiet + file logging for unattended pipelines

```bash
ambermeta --quiet --log-file run.log plan runs/ --recursive --summary-path out.json
```

`--quiet` suppresses stdout (errors/usage still go to stderr); `--log-file` keeps a record.

### YAML summary instead of JSON

```bash
ambermeta plan runs/ --manifest manifest.yaml --summary-path summary.yaml --summary-format yaml
```

---

## See also

- [CLI reference](cli.md) · [Tutorials](tutorials.md) · [Manifest schema](manifest.md)
