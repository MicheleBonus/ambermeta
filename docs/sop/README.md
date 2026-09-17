# SOP and companion findings

Two documents, built from this directory:

| Source | Output | What it is |
|---|---|---|
| `ambermeta-sop.tex` | `ambermeta-sop.pdf` (6 pp) | The procedure depositors follow, one system at a time. GUI-first. |
| `replica-layouts.tex` | `replica-layouts.pdf` (3 pp) | What the deposited corpus actually looks like, which replica layouts AmberMeta detects, and why the other two are declined. |

Both share `preamble.tex`.

## Building

```bash
latexmk -pdf ambermeta-sop.tex
latexmk -pdf replica-layouts.tex
latexmk -c                        # clean aux files, keep the PDFs
```

Use `-c`, not `-C`: the uppercase form also deletes `ambermeta-sop.pdf` and
`replica-layouts.pdf`, which are tracked in git.

Only packages shipped with a distro TeX Live are used — no `tlmgr`, no manual package
installation. Notably **not** `tcolorbox[most]`, whose `skins` library pulls in
`tikzfill`, which SUSE's TeX Live 2025 does not package.

## Figures

`figures/*.png` are real screenshots of the GUI running against the deposited corpus at
`/store7/gentile/data/simulations`, captured headlessly so they can be regenerated
without a desktop session:

1. Start `ambermeta gui <system> --port <p> --no-browser`.
2. Drive the REST API to set the state you want to show — `POST /api/document/discover`,
   `POST /api/steps/infer-lineages`, then one `PATCH /api/steps/lineage` per member. The
   document lives server-side, so the browser renders whatever state the API left.
3. Run Firefox in kiosk mode on an `Xvfb` display, wait for the panes to settle, and
   capture with ImageMagick's `import -window root`.

Step 3 is deliberate rather than convenient. Firefox's own `--screenshot` fires on the
page `load` event, which lands before React has resolved the file tree and the
validation pass — those panes come out reading "Loading…" and "No suggestions right
now." An `Xvfb` display allows an explicit wait before the capture, so the figures show
the app as a user actually sees it.

Which system each figure uses is recorded in the caption context; `sys023` for the
walkthrough (a clean chunked chain) and `sys004`/`sys011` for the replica cases.
