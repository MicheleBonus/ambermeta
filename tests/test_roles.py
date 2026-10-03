# tests/test_roles.py
from ambermeta.roles import classify_role, CANONICAL_ROLES


class _Details:
    def __init__(self, cntrl=None, imin=None):
        self.cntrl_parameters = cntrl or {}
        self.imin = imin


def test_canonical_tokens_only():
    assert CANONICAL_ROLES == ("minimization", "heating", "equilibration", "production")


def test_name_matching_is_word_bounded_and_path_aware():
    # standard recursive tree — the divergence case from the audit
    assert classify_role("min/step1") == "minimization"
    assert classify_role("equil/step1") == "equilibration"
    assert classify_role("prod/run") == "production"
    # startswith false positives are gone
    assert classify_role("minor_tweak") == ""
    assert classify_role("product_notes") == ""


def test_ambiguous_bare_tokens_are_not_forced():
    # bare md/run are too ambiguous to be roles from the name alone
    assert classify_role("md") == ""
    assert classify_role("run_1") == ""
    # therm/anneal DO map to heating
    assert classify_role("therm") == "heating"


def test_content_imin_is_authoritative_over_name():
    d = _Details(cntrl={"imin": 1})
    assert classify_role("prod_001", mdin_details=d) == "minimization"


def test_content_heuristics_are_reachable():
    assert classify_role("run", mdin_details=_Details(cntrl={"ntr": 1})) == "equilibration"
    assert classify_role("run", mdin_details=_Details(cntrl={"tempi": 0, "temp0": 300})) == "heating"
    assert classify_role("run", mdin_details=_Details(cntrl={"nstlim": 1_000_000})) == "production"
    assert classify_role("run") == ""


from ambermeta.protocol import infer_stage_role_from_path
from ambermeta.cli import _suggest_stage_role


def test_gui_and_cli_agree_on_the_same_stems():
    for stem in ["min/step1", "equil/step1", "prod/run", "minor_tweak",
                 "product_notes", "md", "therm", "01_min", "heat"]:
        gui = infer_stage_role_from_path(stem) or ""
        cli = _suggest_stage_role(stem)
        assert gui == cli, f"divergence on {stem!r}: gui={gui!r} cli={cli!r}"


def test_full_canonical_words_self_classify():
    assert classify_role("minimization") == "minimization"
    assert classify_role("minimize") == "minimization"
    assert classify_role("equilibration") == "equilibration"
    assert classify_role("equilibrate") == "equilibration"
    assert classify_role("production") == "production"
    assert classify_role("heating") == "heating"
    # no new false positives
    assert classify_role("minor_tweak") == ""
    assert classify_role("product_notes") == ""


# ---------------------------------------------------------------------------
# 1.3.0: a digit ends a cue, `equi` is a cue, ensemble words rank below production
# ---------------------------------------------------------------------------

import pytest


@pytest.mark.parametrize("name,role", [
    # a digit right after the cue
    ("eq0001", "equilibration"), ("eq1", "equilibration"), ("equil0001", "equilibration"),
    ("prod1", "production"), ("prod0001", "production"), ("min1", "minimization"),
    ("heat1", "heating"), ("heat_1", "heating"), ("heating_1", "heating"),
    # `equi`
    ("equi_01", "equilibration"), ("ntp_equi", "equilibration"),
    ("18_ntp_equi", "equilibration"),
    # ensemble words are weaker than production
    ("nvt_prod_0001", "production"), ("npt_prod_0001", "production"),
    ("equil_nvt", "equilibration"), ("nvt_eq", "equilibration"),
    ("npt_02", "equilibration"), ("md_nvt_red_06", "equilibration"),
    # unchanged spellings
    ("eq_0001", "equilibration"), ("eq.0002", "equilibration"), ("01_eq", "equilibration"),
    ("prod_01", "production"), ("md_prod_01", "production"), ("ntp_prod_0001", "production"),
    ("prod_0002_eq", "equilibration"), ("eq_prod_0002", "equilibration"),
    ("heat_eq_0002", "heating"), ("eq_T299.9_0002", "equilibration"),
    ("pre_prod_0002", "production"),
    # still no cue
    ("reeq_0002", ""), ("relax_0002", ""), ("seq1", ""), ("system1", ""),
    ("admin1", ""), ("product2", ""), ("md", ""), ("run_1", ""),
])
def test_name_cue_table(name, role):
    assert classify_role(name) == role


def test_the_directory_cue_still_wins_over_the_file_name():
    assert classify_role("prod/nvt_eq_0001") == "production"
    assert classify_role("equil/prod1") == "equilibration"
    assert classify_role("eq/prod_0001") == "equilibration"


def test_phase_words_keep_ensemble_stages_apart():
    from ambermeta.roles import phase_word
    assert phase_word("npt") == "npt" and phase_word("nvt") == "nvt"
    assert phase_word("prod1") == phase_word("prod2") == "prod"
    assert phase_word("eq1") != phase_word("prod1")
