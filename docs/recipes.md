# CLI Recipes

High-value command-line workflows for users transitioning from TUI/GUI to an automation-friendly CLI flow.

## From raw directory to manifest

Bootstrap a manifest from files already present in a simulation directory:

```bash
ambermeta init --auto --format yaml --validate /path/to/simulations
```

What this does:
- Scans files recursively and groups related stage files.
- Generates `manifest.yaml` in the target directory.
- Runs parser validation immediately so you can fix issues early.

## Validate all files before publication

Run a strict validation pass over all commonly used AMBER file types before publication:

```bash
ambermeta validate --strict /path/to/simulations/*.{prmtop,parm7,top,mdin,in,mdout,out,nc,mdcrd,crd,rst,rst7,ncrst,inpcrd}
```

Notes:
- `--strict` converts warnings into non-zero exit status for CI/pipelines.
- If your shell does not expand some globs, pass explicit file lists or run multiple commands per type.

## Export methods summary + stats CSV in one command

Generate publication-facing outputs in one run:

```bash
ambermeta plan -m /path/to/simulations/manifest.yaml \
  --methods-summary-path /path/to/simulations/methods-summary.json \
  --stats-csv /path/to/simulations/stage-stats.csv
```

Tip: add `--summary-path /path/to/simulations/protocol-summary.json` if you also want the full protocol export.
