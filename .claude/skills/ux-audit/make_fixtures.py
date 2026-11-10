"""Build the fixed input set a ux-audit runs against, outside the repository.

    python .claude/skills/ux-audit/make_fixtures.py <out-dir>

Run it with a Python that has the test dependencies (the one `python -m pytest` uses).
It writes, under <out-dir>:

    am              runner: `sh am <args>` runs THIS checkout's ambermeta.cli with this Python
    run/            a clean copy of tests/data/amber/md_test_files
    hole/           the same runs with ntp_prod_0003.* removed (a sequence hole)
    replicas/       rep1/ and rep2/ sharing one topology; rep2 stopped after its first run
    space dir ü/    a two-run copy under a path with a space and a non-ASCII character
    bad/            broken and edge-case inputs, one problem per file (listed at the end)

Everything is copied, never linked: an audit that writes into a fixture must not be able
to reach tests/data. Re-running replaces <out-dir> entirely.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SAMPLE = REPO / "tests" / "data" / "amber" / "md_test_files"
TOP = "CH3L1_HUMAN_6NAG.top"
CRD = "CH3L1_HUMAN_6NAG.crd"

V1_MANIFEST = """\
global_prmtop: CH3L1_HUMAN_6NAG.top
initial_coordinates: CH3L1_HUMAN_6NAG.crd
stages:
  - name: prod_1
    mdin: ntp_prod_0001.mdin
    mdout: ntp_prod_0001.mdout
"""

MISSING_FILES_MANIFEST = """\
version: 2
simulation:
  topologies:
    - {id: top, path: missing.prmtop, kind: normal}
  starting_structure: missing.inpcrd
phases:
  - {id: ph, name: Production, role: production, order: 0}
steps:
  - id: st1
    name: prod_1
    phase: ph
    order: 0
    topology: top
    input_coords: {source: starting_structure}
    mdin: missing.mdin
    mdout: missing.mdout
"""

BAD_FILES = {
    # name: (bytes or callable(sample_dir) -> bytes, what it exercises)
    "empty.prmtop": (b"", "zero-byte topology"),
    "empty.mdin": (b"", "zero-byte mdin"),
    "empty.mdout": (b"", "zero-byte mdout"),
    "empty.nc": (b"", "zero-byte NetCDF trajectory"),
    "empty.rst": (b"", "zero-byte restart"),
    "junk.prmtop": (b"this is not a topology\n", "text that is no prmtop"),
    "random.nc": (os.urandom(4096), "random bytes with a NetCDF extension"),
    "fakehdr.nc": (b"CDF\x01" + os.urandom(2048), "NetCDF magic, then garbage"),
    "trunc.mdout": (lambda s: (s / "ntp_prod_0001.mdout").read_bytes()[:60000],
                    "mdout cut off mid-run (no completion marker)"),
    "mdin_named.mdout": (lambda s: (s / "ntp_prod_0001.mdin").read_bytes(),
                         "an mdin saved with an .mdout extension"),
    "broken.yaml": (b"version: 2\nsteps: [ {id: a, name: x\n", "YAML syntax error"),
    "broken.json": (b'{"version": 2, "steps": [', "JSON syntax error"),
    "v1.yaml": (V1_MANIFEST.encode(), "a v1 flat manifest (refused by design)"),
    "missing.yaml": (MISSING_FILES_MANIFEST.encode(), "a valid v2 manifest naming missing files"),
    "notes.toml": (b'title = "x"\n', "a TOML file passed as a manifest (refused by design)"),
}


def _copy(names, src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(src / name, dst / name)


def _run_files(index: int):
    stem = f"ntp_prod_{index:04d}"
    return [f"{stem}.mdin", f"{stem}.mdout", f"{stem}.rst"]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(sys.argv[1]).resolve()
    if out == REPO or REPO in out.parents:
        print(f"error: {out} is inside the repository; pick a scratch directory", file=sys.stderr)
        return 2
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    everything = sorted(p.name for p in SAMPLE.iterdir() if p.is_file())
    _copy(everything, SAMPLE, out / "run")
    _copy([n for n in everything if not n.startswith("ntp_prod_0003.")], SAMPLE, out / "hole")

    _copy([TOP, "ntp_prod_0000.rst"], SAMPLE, out / "replicas")
    _copy(_run_files(1) + _run_files(2), SAMPLE, out / "replicas" / "rep1")
    _copy(_run_files(1), SAMPLE, out / "replicas" / "rep2")

    _copy([TOP, CRD, "ntp_prod_0000.rst"] + _run_files(1) + _run_files(2), SAMPLE,
          out / "space dir ü")

    bad = out / "bad"
    bad.mkdir()
    for name, (content, _) in BAD_FILES.items():
        data = content(SAMPLE) if callable(content) else content
        (bad / name).write_bytes(data)

    runner = out / "am"
    runner.write_text(
        "#!/bin/sh\n"
        f'PYTHONPATH="{REPO.as_posix()}" exec "{Path(sys.executable).as_posix()}" '
        '-c "import sys; from ambermeta.cli import main; sys.exit(main())" "$@"\n',
        encoding="utf-8", newline="\n",
    )

    resolved = subprocess.run(
        [sys.executable, "-c", "import ambermeta; print(ambermeta.__file__)"],
        env={**os.environ, "PYTHONPATH": str(REPO)}, cwd=str(out),
        capture_output=True, text=True,
    )
    module = Path(resolved.stdout.strip()) if resolved.returncode == 0 else None
    if module is None or REPO not in module.parents:
        print(f"error: the runner does not import this checkout: {resolved.stdout}{resolved.stderr}",
              file=sys.stderr)
        return 1

    print(f"fixtures: {out}")
    print(f"runner:   sh '{runner.as_posix()}' <args>   (imports {module})")
    print("dirs:     run/  hole/  replicas/  'space dir ü/'")
    print("bad/:")
    for name, (_, what) in BAD_FILES.items():
        print(f"  {name:<18} {what}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
