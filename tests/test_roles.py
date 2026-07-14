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
