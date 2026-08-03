"""Tests for CORE-D2/D7/H2/H3/D3/D4: natural stage ordering, single-digit sequence
detection, shared global/HMR prmtop helper, and missing-file warning/raise."""
import math
import os
from pathlib import Path

import pytest

from ambermeta.protocol import (
    auto_detect_restart_chain,
    detect_numeric_sequences,
    _ordered_stems,
)


def _write_prmtop(path, sections):
    """sections: dict flag -> (format_str, [values]). Writes a minimal prmtop."""
    lines = ["%VERSION  VERSION_STAMP = V0001.000  DATE = 01/01/26"]
    for flag, (fmt, values) in sections.items():
        lines.append(f"%FLAG {flag}")
        lines.append(f"%FORMAT({fmt})")
        # one value per line keeps it simple and fixed-width safe
        for v in values:
            if isinstance(v, float):
                lines.append(f"{v:16.8E}")
            else:
                lines.append(f"{int(v):8d}")
    path.write_text("\n".join(lines) + "\n")


def test_truncated_octahedron_volume(tmp_path):
    from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
    p = tmp_path / "trunc.prmtop"
    # BOX_DIMENSIONS: beta then a,b,c
    _write_prmtop(p, {
        "POINTERS": ("10I8", [3, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0]),
        "MASS": ("5E16.8", [1.0, 1.0, 1.0]),
        "BOX_DIMENSIONS": ("5E16.8", [109.4712206, 50.0, 50.0, 50.0]),
    })
    md = extract_prmtop_metadata(str(p))
    factor = md.box_volume / (50.0 ** 3)
    assert abs(factor - 0.7698) < 1e-3  # truncated-octahedron factor, not 0.9428
    # All three angles must be equal (all set to beta from BOX_DIMENSIONS[0])
    assert md.box_angles[0] == md.box_angles[1] == md.box_angles[2]
    assert abs(md.box_angles[0] - 109.4712206) < 1e-4


def test_natural_order_unpadded():
    grouped = {f"prod_{i}": {} for i in (1, 2, 10, 11)}
    assert _ordered_stems(grouped) == ["prod_1", "prod_2", "prod_10", "prod_11"]


def test_sequence_detects_single_digits():
    seqs = detect_numeric_sequences(["prod_1", "prod_2", "prod_3"])
    assert any(len(v) == 3 for v in seqs.values())


def _write_prmtop_atoms(path, atom_names, masses):
    name_line = "".join(f"{n:<4}" for n in atom_names)
    lines = [
        "%VERSION VERSION_STAMP = V0001.000",
        "%FLAG POINTERS", "%FORMAT(10I8)", f"{len(atom_names):8d}",
        "%FLAG ATOM_NAME", "%FORMAT(20a4)", name_line,
        "%FLAG MASS", "%FORMAT(5E16.8)",
        "".join(f"{m:16.8E}" for m in masses),
    ]
    path.write_text("\n".join(lines) + "\n")


def test_hmr_detected_without_atomic_number(tmp_path):
    from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
    p = tmp_path / "hmr.prmtop"
    # No ATOMIC_NUMBER; identify H by ATOM_NAME starting with 'H'
    _write_prmtop_atoms(p,
        atom_names=["N", "H1", "H2", "CA"],
        masses=[14.01, 3.024, 3.024, 12.01])
    md = extract_prmtop_metadata(str(p))
    assert md.hmr_active is True
    assert md.hmr_detection_method == "atom_name"


def test_charge_completeness_warning(tmp_path):
    from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
    p = tmp_path / "charge.prmtop"
    # natom=3 but only 2 valid CHARGE tokens (one blank -> None)
    lines = [
        "%VERSION x", "%FLAG POINTERS", "%FORMAT(10I8)", f"{3:8d}",
        "%FLAG CHARGE", "%FORMAT(3E16.8)",
        f"{1.0:16.8E}{2.0:16.8E}            ",  # third field blank
    ]
    p.write_text("\n".join(lines) + "\n")
    md = extract_prmtop_metadata(str(p))
    assert any("charge" in w.lower() for w in md.warnings)


def test_mdout_captures_1_4_terms():
    from ambermeta.legacy_extractors.mdout import _extract_key_values
    line = " 1-4 NB =  1393.4892  1-4 EEL = 15687.4768  VDWAALS = 21666.9998"
    kv = _extract_key_values(line)
    assert kv["1-4 NB"] == 1393.4892
    assert kv["1-4 EEL"] == 15687.4768
    assert kv["VDWAALS"] == 21666.9998


def test_nbond_total_and_short_pointers(tmp_path):
    from ambermeta.legacy_extractors.prmtop import extract_prmtop_metadata
    p = tmp_path / "ptr.prmtop"
    # index2=NBONH=5, index11=nres=2, index12=NBONA=3
    _write_prmtop(p, {"POINTERS": ("10I8", [4, 0, 5, 0, 0, 0, 0, 0, 0, 0, 0, 2, 3])})
    md = extract_prmtop_metadata(str(p))
    assert md.nbond == 8  # 5 + 3, not 3

    short = tmp_path / "short.prmtop"
    _write_prmtop(short, {"POINTERS": ("10I8", [4, 0, 0])})  # < 13 entries
    md2 = extract_prmtop_metadata(str(short))  # must not raise
    assert md2.natom == 4
    assert md2.nres is None


def test_nvt_production_not_mislabeled(tmp_path):
    """CORE-P6: a title containing 'prod' and 'nvt' must classify as Production, not Equilibration."""
    from ambermeta.legacy_extractors.mdin import parse_mdin_file
    p = tmp_path / "prod.in"
    p.write_text("Production NVT run\n&cntrl\n imin=0, nstlim=5000000,\n/\n")
    md = parse_mdin_file(str(p))
    from ambermeta.legacy_extractors.mdin import _classify_stage
    assert "Production" in _classify_stage(md)


def test_inpcrd_tiny_system_box_not_velocities(tmp_path):
    from ambermeta.legacy_extractors.inpcrd import parse_inpcrd
    p = tmp_path / "tiny.rst"
    # 2 atoms -> 1 coord line (6 floats); + 1 box line. Must read as box, not vel.
    p.write_text(
        "title\n"
        "    2\n"
        "  1.0000000  2.0000000  3.0000000  4.0000000  5.0000000  6.0000000\n"
        " 10.0000000 10.0000000 10.0000000 90.0000000 90.0000000 90.0000000\n"
    )
    md = parse_inpcrd(str(p))
    assert md.has_box is True
    assert md.has_velocities is False


# ---------------------------------------------------------------------------
# CORE-H2/H3/D3/D4 — shared global/HMR prmtop helper
# ---------------------------------------------------------------------------

def test_hmr_prmtop_applied_in_discovery_branch(tmp_path, caplog):
    import ambermeta.protocol as P
    # discovery branch: manifest=None
    # Build a stage with a large-dt mdin so HMR topology is selected.
    (tmp_path / "prod.in").write_text("&cntrl\n imin=0, dt=0.004, nstlim=10,\n/\n")
    (tmp_path / "prod.out").write_text("Final Performance Info\n")
    # minimal HMR prmtop
    _write_prmtop_atoms(tmp_path / "hmr.prmtop",
                        atom_names=["N", "H1"], masses=[14.0, 3.024])
    proto = P.auto_discover(str(tmp_path), manifest=None,
                            hmr_prmtop="hmr.prmtop")
    prod = [s for s in proto.stages if "prod" in s.name][0]
    assert prod.prmtop is not None  # HMR topology applied in discovery branch


def test_missing_global_prmtop_warns(tmp_path, caplog):
    import ambermeta.protocol as P
    (tmp_path / "prod.in").write_text("&cntrl\n imin=0, nstlim=10,\n/\n")
    proto = P.auto_discover(str(tmp_path), manifest=None,
                            global_prmtop="nope.prmtop")
    # graceful mode: protocol returned, no exception
    assert proto is not None
    with pytest.raises(P.AmberMetaError):
        P.auto_discover(str(tmp_path), manifest=None,
                        global_prmtop="nope.prmtop", strict=True)


def test_hmr_inference_uses_shared_threshold():
    import ambermeta.protocol as P
    assert P.HMR_TIMESTEP_THRESHOLD_PS == 0.003
    # _collect_system must not hardcode a different number; guard via source check
    import inspect
    src = inspect.getsource(P.SimulationProtocol.to_methods_dict)
    assert "0.003" not in src  # uses the constant, not a literal


def test_restart_chain_scans_subdirs(tmp_path):
    """Behavioral test: recursive=True finds restart files in subdirectories;
    recursive=False (flat listdir) does not."""
    import shutil
    import inspect
    from ambermeta.protocol import SimulationStage, auto_detect_restart_chain
    from ambermeta.parsers.prmtop import PrmtopParser

    # Build one stage with a real prmtop so atom-count matching is available
    real_top = "tests/data/amber/md_test_files/CH3L1_HUMAN_6NAG.top"
    real_rst = "tests/data/amber/md_test_files/ntp_prod_0000.rst"
    prmtop_data = PrmtopParser(real_top).parse()

    stage = SimulationStage(name="prod_002")
    stage.prmtop = prmtop_data

    # Place the restart file inside a subdirectory (flat scan must miss it)
    sub = tmp_path / "subdir"
    sub.mkdir()
    shutil.copy(real_rst, sub / "prod_001.rst")

    # --- flat scan must NOT find it ---
    flat_result = auto_detect_restart_chain([stage], str(tmp_path), recursive=False)
    assert flat_result.get("prod_002") is None, (
        "Flat scan should not find a restart in a subdirectory"
    )

    # --- recursive scan MUST find it ---
    rec_result = auto_detect_restart_chain([stage], str(tmp_path), recursive=True)
    assert "prod_002" in rec_result, (
        "Recursive scan should find prod_001.rst in subdirectory for stage prod_002"
    )
    assert rec_result["prod_002"].endswith("prod_001.rst"), (
        f"Expected path ending in prod_001.rst, got: {rec_result['prod_002']}"
    )

    # Secondary: signature sanity check
    assert "recursive" in inspect.signature(auto_detect_restart_chain).parameters


# --- the second chainer: `plan --auto-detect-restarts` -------------------------------
#
# Everything this function finds is written back as a restart attribution, so a
# cross-replica match is a false *file* as well as a false edge. Every tree below copies
# ONE system's restart around and hands every stage ONE prmtop, because that is what a
# replica set is — and it is exactly why the function's own atom-count check cannot help:
# replicas of one system agree on every count. A fixture with differing counts would pass
# for a reason that never holds in practice.


@pytest.fixture(scope="module")
def one_system(sample_md_data_dir):
    """The repo's real prmtop, parsed once — it is 12 MB and 64528 atoms."""
    from ambermeta.parsers.prmtop import PrmtopParser
    return PrmtopParser(str(sample_md_data_dir / "CH3L1_HUMAN_6NAG.top")).parse()


def _restart_tree(tmp_path, sample_md_data_dir, prmtop, runs, restarts):
    """Build stages from `(name, lineage)` pairs and write `restarts` as .rst files.

    Names and restart stems are posix, relative to `tmp_path`, matching the
    path-prefixed stems `smart_group_files` produces.
    """
    import shutil
    from ambermeta.protocol import SimulationStage

    source = sample_md_data_dir / "ntp_prod_0001.rst"
    for stem in restarts:
        target = tmp_path / (stem + ".rst")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, target)

    stages = []
    for name, lineage in runs:
        stage = SimulationStage(name=name, lineage=lineage)
        stage.prmtop = prmtop
        stages.append(stage)
    return stages


def _detected(stages, tmp_path):
    """The mapping, with every path back to a posix stem relative to the tree."""
    found = auto_detect_restart_chain(stages, str(tmp_path), recursive=True)
    return {name: Path(os.path.relpath(path, str(tmp_path))).as_posix()
            for name, path in found.items()}


def test_auto_detect_refuses_a_restart_another_replica_wrote(
    tmp_path, sample_md_data_dir, one_system
):
    """rep2's head follows rep1's tail in document order, as replica-major trees arrive.

    Measured before the guard: `{'rep2/prod_0001': 'rep1/prod_0002.rst'}` — the design
    doc's opening failure, produced here by the name term alone (5.0, the threshold).
    """
    stages = _restart_tree(
        tmp_path, sample_md_data_dir, one_system,
        runs=[("rep1/prod_0001", "rep1"), ("rep1/prod_0002", "rep1"),
              ("rep2/prod_0001", "rep2")],
        restarts=["rep1/prod_0002"],
    )
    assert _detected(stages, tmp_path) == {}


def test_auto_detect_refuses_a_restart_lying_in_another_replicas_directory(
    tmp_path, sample_md_data_dir, one_system
):
    """The writing run need not be in the document for the file to be rep1's.

    This is the common shape, not the exotic one: a restart is left behind by a run whose
    mdout was never collected — a chunk that crashed, a queue job resumed by hand, a tree
    the user only added the surviving runs of. Nothing then *claims* `rep1/prod_0001.rst`,
    and a guard that reads only declared writers treats it as unowned and scores it for
    rep2 exactly as if it lay in rep2's own directory.

    Measured with the writer-only guard: `{'rep1/prod_0002': 'rep1/prod_0001.rst',
    'rep2/prod_0002': 'rep1/prod_0001.rst'}`. The numeric term alone scores 10.0, twice the
    threshold, and no other term is needed — so nothing else in this tree can refuse it.
    """
    stages = _restart_tree(
        tmp_path, sample_md_data_dir, one_system,
        runs=[("rep1/prod_0002", "rep1"), ("rep2/prod_0002", "rep2")],
        restarts=["rep1/prod_0001"],
    )
    assert _detected(stages, tmp_path) == {
        "rep1/prod_0002": "rep1/prod_0001.rst",
    }


def test_a_restart_in_a_directory_no_stage_occupies_still_feeds_a_replica(
    tmp_path, sample_md_data_dir, one_system
):
    """The complement, and the reason the rule is "known to be another member's".

    An `equil/` directory holding the shared restart and no collected run is the ordinary
    way a campaign starts. No declared stage places a member there, so the directory says
    nothing about membership and the edge stands — "different directory" is not evidence,
    *another member's* directory is.
    """
    stages = _restart_tree(
        tmp_path, sample_md_data_dir, one_system,
        runs=[("rep1/prod_0001", "rep1")],
        restarts=["equil/prod_0000"],
    )
    assert _detected(stages, tmp_path) == {
        "rep1/prod_0001": "equil/prod_0000.rst",
    }


def test_auto_detect_prefers_a_replicas_own_restart_over_a_neighbours(
    tmp_path, sample_md_data_dir, one_system
):
    """Both replicas hold a `prod_0001.rst`. Basename matching cannot separate them.

    Measured before the guard: rep2's second chunk was assigned *rep1's* restart — the two
    candidates scored 15.0 each and directory walk order broke the tie. Narrowing the
    candidates does not merely refuse here, it recovers the true edge.
    """
    stages = _restart_tree(
        tmp_path, sample_md_data_dir, one_system,
        runs=[("rep1/prod_0001", "rep1"), ("rep1/prod_0002", "rep1"),
              ("rep2/prod_0001", "rep2"), ("rep2/prod_0002", "rep2")],
        restarts=["rep1/prod_0001", "rep2/prod_0001"],
    )
    assert _detected(stages, tmp_path) == {
        "rep1/prod_0002": "rep1/prod_0001.rst",
        "rep2/prod_0002": "rep2/prod_0001.rst",
    }


def test_the_same_tree_untagged_keeps_the_chain_it_always_had(
    tmp_path, sample_md_data_dir, one_system
):
    """The control: with no tags the two replicas stay indistinguishable, as they always were.

    A tag is what the user declares; without one there is nothing here to honour, and an
    untagged document must come out of this function exactly as it did before lineages
    existed. This test is green either side of the fix, deliberately.

    "Exactly as before" is three things, and *not* a fourth. Both second chunks are
    chained; both first chunks are left alone (3.0, below the 5.0 threshold); and both
    winners are the **same** file, because untagged there is nothing whatever to tell the
    two consumers apart — one shared answer for two different replicas is the false edge
    this feature exists to stop, and
    `test_auto_detect_prefers_a_replicas_own_restart_over_a_neighbours` runs this identical
    tree tagged to show it stopped.

    Which file wins is the fourth thing, and it is not asserted. Both candidates are named
    `prod_0001.rst` and score 15.0 for both consumers (5.0 name + 10.0 sequence), so the
    winner is whichever one `os.walk` yielded first — a property of the filesystem, not of
    this function. Pinning it would pass here and flip on another OS or another filesystem.
    """
    stages = _restart_tree(
        tmp_path, sample_md_data_dir, one_system,
        runs=[("rep1/prod_0001", None), ("rep1/prod_0002", None),
              ("rep2/prod_0001", None), ("rep2/prod_0002", None)],
        restarts=["rep1/prod_0001", "rep2/prod_0001"],
    )
    detected = _detected(stages, tmp_path)

    assert set(detected) == {"rep1/prod_0002", "rep2/prod_0002"}
    assert detected["rep1/prod_0002"] == detected["rep2/prod_0002"]
    assert detected["rep1/prod_0002"] in {"rep1/prod_0001.rst", "rep2/prod_0001.rst"}


def test_a_shared_untagged_restart_still_feeds_a_tagged_replica(
    tmp_path, sample_md_data_dir, one_system
):
    """One equilibration feeding N replicas is a real edge, and the commonest layout there is.

    Only two *declared* tags are a boundary, so the untagged prep run continues into rep1
    and the guard must not touch it.
    """
    stages = _restart_tree(
        tmp_path, sample_md_data_dir, one_system,
        runs=[("common/equil_0001", None), ("rep1/prod_0001", "rep1")],
        restarts=["common/equil_0001"],
    )
    assert _detected(stages, tmp_path) == {
        "rep1/prod_0001": "common/equil_0001.rst",
    }


def test_a_two_digit_directory_no_longer_eats_the_run_index(
    tmp_path, sample_md_data_dir, one_system
):
    """`rep10/prod_0002` folded to `rep10_prod_0002` matched `\\d{2,}` on 10, not 0002.

    Measured before the fix: `{'rep10/prod_0002': 'rep10/prod_0009.rst'}` — 9 read as the
    predecessor of 10 and scored the ideal 10.0. Nothing else in this tree can refuse it:
    prod_0009 is no stage's output, so the lineage guard does not see it.
    """
    stages = _restart_tree(
        tmp_path, sample_md_data_dir, one_system,
        runs=[("rep10/prod_0002", "rep10")],
        restarts=["rep10/prod_0009"],
    )
    assert _detected(stages, tmp_path) == {}


def test_a_two_digit_directory_finds_its_real_predecessor(
    tmp_path, sample_md_data_dir, one_system
):
    """The other half of the same bug: measured before the fix, this returned `{}`.

    Scoring against 10 meant replica ten's own chain scored zero, so `--auto-detect-restarts`
    silently did nothing for it while working for replicas 1-9.

    One stage, which is both the flag's primary use — *find the restart this run reads* —
    and what isolates the arithmetic: with no predecessor stage there is no name term to
    rescue the match, so only the numeric term can score.
    """
    stages = _restart_tree(
        tmp_path, sample_md_data_dir, one_system,
        runs=[("rep10/prod_0002", "rep10")],
        restarts=["rep10/prod_0001"],
    )
    assert _detected(stages, tmp_path) == {
        "rep10/prod_0002": "rep10/prod_0001.rst",
    }


def test_the_name_term_alone_still_meets_the_threshold(
    tmp_path, sample_md_data_dir, one_system
):
    """`equil` carries no index, so only the name term scores: exactly 5.0, the threshold.

    Raising the threshold is the obvious way to exclude a cross-replica name match and it
    would have disabled auto-detect for every tree with no trajectory to time-match
    against. The candidate scope was narrowed instead; this pins that it was.
    """
    stages = _restart_tree(
        tmp_path, sample_md_data_dir, one_system,
        runs=[("min_0001", None), ("equil", None)],
        restarts=["min_0001"],
    )
    assert _detected(stages, tmp_path) == {"equil": "min_0001.rst"}
