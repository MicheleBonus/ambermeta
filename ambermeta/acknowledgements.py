"""Findings the user has settled: matching a manifest's `acknowledged` list to a report.

A finding could only be dismissed in the GUI, which recorded nothing, so the same missing
run came back on every Validate, failed every `--strict` run and sat in the methods summary
with no word of explanation. An acknowledgement is the user's answer, kept in the manifest:
the finding's exact text and a note saying why it stands.

The text is the `title: evidence` line `validate` prints for a card, and the message for a
replica-coherence warning, so it can be copied from the terminal. Matching on the exact
text is deliberate: a finding whose text changes (new data, a rerun, new wording) is a new
finding and shows again rather than staying hidden under an old note, and an
acknowledgement that matches nothing any more is reported as stale.

What can be acknowledged is what `--strict` fails on: the problem cards below and coherence
warnings. A coherence *error* (members of different sizes, or minimisation beside dynamics)
is a category error that fails with or without `--strict`, and no note changes that.

Core, not GUI: the CLI and the GUI's validate both reach it through
`core_bridge.validate_simulation`.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

#: The suggestion kinds that are problems (the findings block, `--strict`), as opposed to
#: `[applied]` inferences.
PROBLEM_KINDS = ("continuity_gap", "missing_run",
                 "step_check", "unfinished_run", "input_mismatch")


def finding_text(item: Dict[str, Any]) -> str:
    """The text a finding is known by: `title: evidence`, or a coherence message."""
    if "title" not in item and "message" in item:
        return str(item["message"])
    return f"{item.get('title')}: {item.get('evidence')}"


def apply_acknowledgements(report: Dict[str, Any], acknowledged: Iterable[Any]) -> None:
    """Mark each acknowledged finding in `report`, and list what matched and what did not.

    A matching problem card or coherence warning gains `"acknowledged": <note>`.
    `report["acknowledged"]` lists the acknowledgements that matched a finding and
    `report["stale_acknowledgements"]` the ones that matched none, both as
    `{"finding", "note"}` in manifest order.
    """
    entries = list(acknowledged or [])
    notes = {a.finding: a.note for a in entries}
    matched = set()
    for card in report.get("suggestions") or []:
        if card.get("kind") in PROBLEM_KINDS:
            text = finding_text(card)
            if text in notes:
                card["acknowledged"] = notes[text]
                matched.add(text)
    for finding in report.get("coherence") or []:
        if finding.get("severity") == "warning":
            text = finding_text(finding)
            if text in notes:
                finding["acknowledged"] = notes[text]
                matched.add(text)
    report["acknowledged"] = [{"finding": a.finding, "note": a.note}
                              for a in entries if a.finding in matched]
    report["stale_acknowledgements"] = [{"finding": a.finding, "note": a.note}
                                        for a in entries if a.finding not in matched]


def open_problems(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The problem cards nobody has acknowledged."""
    return [s for s in (report.get("suggestions") or [])
            if s.get("kind") in PROBLEM_KINDS and not s.get("acknowledged")]
