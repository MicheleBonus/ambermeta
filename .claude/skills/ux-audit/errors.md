# Error-handling pass

This pass uses the `pr-review-toolkit:silent-failure-hunter` agent from the pr-review-toolkit plugin. If that agent type is not available, write "errors not audited: pr-review-toolkit unavailable" in the report and stop this pass.

The agent is built to review a diff, so point it at whole files instead. Dispatch one agent per area, all in one message so they run in parallel:
- `ambermeta/legacy_extractors/` and `ambermeta/parsers/`
- `ambermeta/protocol.py`, `ambermeta/mdout_header.py`, `ambermeta/netcdf_backend.py`
- `ambermeta/cli.py`
- `ambermeta/gui/api/` (`routes.py`, `core_bridge.py`, `document.py`)

Give each agent this brief, with its area filled in:

> Review `<area>` in the AmberMeta repository for silent failures: whole files, not a diff. AmberMeta's fault tolerance is deliberate. An expected file problem becomes a `FileLoadError`, a validation note or an INFO note, and `plan` carries on (`docs/architecture.md` §8). That is reporting, not swallowing.
>
> Report the cases where an error leaves no trace a user can see:
> - an exception turned into `None`, a zero or a default that is then shown as if it were real data;
> - a broad `except` that records nothing;
> - a fallback that changes a result without a note saying so.
>
> For each case, give file:line, the input that triggers it, and what the user would see.

When the agents return, check each claimed symptom yourself: run the tool through `sh am` on the matching input in `bad/`, or build one. Report the ones you reproduce as numbered findings with `area: errors`. List the rest under a final heading, "Unconfirmed (code reading only)", one line each: file:line, the claim, and what you tried.
