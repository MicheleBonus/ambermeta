"""A previous summary that cannot be read is said so, instead of reading as "unchanged".

`plan` (and the GUI's Plan) compare the totals they are about to write with the
summary.json already at that path, and print "totals changed since the last
summary.json" when they moved. Any problem reading the old file was "no prior claim",
which is the right call for a first run but not for a file that is there and broken:

- A summary re-saved with a UTF-8 BOM (Windows PowerShell 5's `Out-File -Encoding utf8`)
  failed `json.load` and the comparison silently never happened.
- A summary truncated by a full disk was the same: silence, which reads as "the totals
  did not change", the one claim nothing had checked.
"""
from __future__ import annotations

import json

from ambermeta.cli import main
from ambermeta.protocol import read_prior_summary, totals_delta

CURRENT = {"steps": 2_500_000.0, "time_ps": 10_000.0}
PRIOR = {"totals": {"steps": 2_500_000.0, "time_ps": 8_000.0}}


def test_a_prior_summary_with_a_bom_is_compared(tmp_path):
    path = tmp_path / "summary.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(PRIOR).encode("utf-8"))

    delta = totals_delta(read_prior_summary(str(path)), CURRENT, str(path))

    assert delta and delta.startswith("totals changed since the last summary.json")


def test_a_truncated_prior_summary_is_reported_as_not_compared(tmp_path):
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(PRIOR)[:15], encoding="utf-8")

    delta = totals_delta(read_prior_summary(str(path)), CURRENT, str(path))

    assert delta is not None
    assert "not compared" in delta and "could not be read" in delta
    assert str(path) in delta


def test_no_prior_summary_still_says_nothing(tmp_path):
    path = tmp_path / "summary.json"

    assert totals_delta(read_prior_summary(str(path)), CURRENT, str(path)) is None


def test_plan_prints_it(sample_md_data_dir, tmp_path, capsys):
    summary = tmp_path / "summary.json"
    summary.write_text('{"totals": {"steps": 1', encoding="utf-8")

    rc = main(["plan", str(sample_md_data_dir), "--recursive", "--summary-path", str(summary)])

    assert rc == 0
    assert "could not be read" in capsys.readouterr().out
