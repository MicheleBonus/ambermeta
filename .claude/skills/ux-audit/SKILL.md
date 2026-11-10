---
name: ux-audit
description: Use when auditing AmberMeta's CLI or GUI the way a user meets it (usability, confusing or misleading output, crashes, wrong results, commands that disagree, swallowed errors), or when asked to look for quirks, papercuts or bugs in the tool itself rather than in a diff. Takes an optional scope - cli, gui or errors - and does all three without one.
---

# Auditing AmberMeta as a user

Run the real tool from this checkout against a fixed set of inputs, and report each problem in a form someone can act on without investigating again. The audit reports; it does not fix.

Scope from the argument: `cli`, `gui`, `errors`, or all three when none is given.

## 1. Set up (every scope)

```bash
python .claude/skills/ux-audit/make_fixtures.py "<scratchpad>/ux-audit"
```

Use a Python that has the test dependencies. The script copies the sample data into `run/`, `hole/`, `replicas/` and `space dir ü/`, writes one broken input per problem into `bad/`, and writes a runner `am`. The runner exists because an installed `ambermeta` executable can import a different clone. The script prints which module the runner imports; it must be this repo.

Work inside the fixture directory and call the tool as `sh am <args>`. `discover --write`, `init` and `export -o` write files, and they must not land in the repo.

Before calling anything a bug, read what the tool promises: `sh am <cmd> --help`, `docs/cli.md` (exit codes, environment variables), and the contracts in `docs/architecture.md` §10. These are documented behaviour, so on their own they are at most a `design-question`:
- v1 manifests and `.toml`/`.csv` manifests are refused with a hint; there is no migration.
- `plan` and `discover` are fault-tolerant (errors recorded, exit 0); `--strict` makes them fail.
- A replica head with no declared producer gets an INFO "not measured" note.
- Each run gets its own findings, so a problem shared by five runs is listed five times.
- `discover` and `plan --recursive` can assign different roles to the same run.
- The GUI is localhost-only, single-user and desktop-only. There is no TUI.

## 2. CLI (`cli`)

Take the subcommands from `sh am --help` and give each one this pass:
- **Help:** it renders, its examples run as written, every option is explained.
- **Inputs:** the happy path on `run/`, then `hole/`, `replicas/`, `space dir ü/`, each file in `bad/`, a missing path, and a directory where a file is expected.
- **Exit codes and errors:** codes match `docs/cli.md`; no tracebacks; errors go to stderr and say what to do next.
- **Output:** every `--format` value, with and without `-o`, and piped through `| cat`. On Windows a pipe uses cp1252. If something crashes only there, re-run it with `PYTHONUTF8=1` and record it as an encoding bug.
- **Agreement:** the same directory through `discover`, `plan --recursive`, `plan -m` and `validate --manifest`.
- **Writing files:** overwriting without `--force`, a missing parent directory, and the same command run twice then diffed (is the output deterministic?).
- **Globals:** `--log-level` and `-q` before and after the subcommand, `NO_COLOR`, `--version`.

## 3. GUI (`gui`)

Read `gui.md` in this directory and follow it.

## 4. Error handling (`errors`)

Read `errors.md` in this directory and follow it.

## 5. Report

Write the report to `.claude/ux-audit/reports/<YYYY-MM-DD>-<scope>.md` (git does not track it). If that name is taken by an earlier run today, add `-2`, `-3`, and so on, so the earlier report stays as the baseline. If an earlier report exists, compare with the latest one of the same scope and set each finding's status to `new`, `still open` or `fixed`.

Reproduce every finding a second time before writing it down. Each finding has exactly this shape:

```
### <n>. <the claim, in one line>
kind: bug | inconsistency | design-question    severity: high | medium | low    area: cli | gui | errors    status: new
repro: <exact commands, using `sh am` and the fixture paths>
observed: <verbatim output, at most 5 lines>
expected: <the behaviour> (source: exactly one of <docs file:line | help text | how another command behaves | judgement>)
where: <file:line, when you found it>
```

- **kind:**
  - `bug`: a crash, a wrong result, or behaviour that contradicts the cited source.
  - `inconsistency`: two commands or surfaces disagree about the same input.
  - `design-question`: it works as documented but confuses.
- **severity:**
  - `high`: a crash, a wrong scientific result, or a file lost or overwritten.
  - `medium`: misleading output or a wrong exit code.
  - `low`: polish.

Order the findings by severity. After them come the "Unconfirmed" list from the errors pass (if it ran) and a short list of what works well.

## 6. After the audit

Don't fix anything during the audit. Offer two next steps: turn the high findings into failing tests and fix them with superpowers:test-driven-development, or file them as GitHub issues. Ask before creating anything on GitHub.
