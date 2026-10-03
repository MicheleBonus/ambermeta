"""`num_solute_residues` counts the solute, not LEaP's IPTRES pointer.

LEaP files the ions it adds before the solvent, so SOLVENT_POINTERS' IPTRES (the last
residue before the solvent) counts them: 443 on the sample topology, of which 72 are K+
and Cl-. Up to 1.2 the field was IPTRES itself.
"""
from __future__ import annotations

from ambermeta.legacy_extractors.prmtop import _solute_residues, extract_prmtop_metadata


def test_ions_and_water_before_iptres_are_not_solute():
    labels = ["ACE", "ALA", "NME", "Na+", "Cl-", "WAT", "WAT", "WAT"]
    assert _solute_residues(labels, 6) == 3


def test_without_labels_the_pointer_is_all_there_is():
    assert _solute_residues(None, 12) == 12
    assert _solute_residues(["ALA"], 0) == 0


def test_the_sample_topology_has_371_solute_residues(sample_md_data_dir):
    md = extract_prmtop_metadata(str(sample_md_data_dir / "CH3L1_HUMAN_6NAG.top"))
    ions = md.residue_composition["K+"] + md.residue_composition["Cl-"]
    assert ions == 72
    assert md.num_solute_residues == 443 - ions == 371


def test_the_raw_iptres_is_kept_under_its_own_key(sample_md_data_dir):
    """PR #93 review, M4: the field changed meaning, so LEaP's pointer stays available."""
    md = extract_prmtop_metadata(str(sample_md_data_dir / "CH3L1_HUMAN_6NAG.top"))
    assert md.iptres == 443
