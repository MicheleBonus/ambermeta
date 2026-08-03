"""Regenerate the back-compat goldens next to this script.

Run from the repository root::

    python tests/data/lineage_backcompat/regenerate.py

It reuses ``tests/test_lineage_backcompat.py``'s own pipeline and normaliser, so a golden
can never be produced by a different invocation than the one the tests check. It prints
the stats-CSV hash; paste it into ``STATS_CSV_SHA256``.

Regenerating is how you *accept* an output change, so only do it when you can say in the
commit message why an untagged document's output was allowed to move.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

# The repo root, ahead of anything an editable install may point at: `import ambermeta`
# otherwise resolves to whichever clone was last `pip install -e`'d, and the goldens would
# describe that tree instead of this one.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import ambermeta.protocol as _protocol  # noqa: E402

if Path(_protocol.__file__).resolve().parent.parent != ROOT:
    raise SystemExit(f"wrong ambermeta: {_protocol.__file__}")

from tests.test_lineage_backcompat import (  # noqa: E402
    GOLDEN_DIR, _with_stable_ids, load_normalised, manifest_payload_json, normalise,
    run_pipeline,
)


def main() -> int:
    sample_dir = ROOT / "tests" / "data" / "amber" / "md_test_files"
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / "run"
        run_dir.mkdir()
        run_pipeline(run_dir, sample_dir)

        for name, embeds_paths in (("summary.json", True),
                                   ("methods_summary.json", False)):
            payload = load_normalised(run_dir, name, embeds_paths=embeds_paths)
            (GOLDEN_DIR / name).write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {GOLDEN_DIR / name}")

        from ambermeta.simulation import load_simulation, simulation_to_payload
        draft = _with_stable_ids(
            simulation_to_payload(load_simulation(str(run_dir / "draft.yaml"))))
        (GOLDEN_DIR / "draft_payload.json").write_text(
            json.dumps(draft, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {GOLDEN_DIR / 'draft_payload.json'}")

        text = normalise((run_dir / "stats.csv").read_text(encoding="utf-8"), run_dir)
        print("STATS_CSV_SHA256 =", hashlib.sha256(text.encode("utf-8")).hexdigest())

        payload_json = manifest_payload_json(Path(tmp))
        (GOLDEN_DIR / "manifest_payload.json").write_text(
            payload_json + "\n", encoding="utf-8")
        print(f"wrote {GOLDEN_DIR / 'manifest_payload.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
