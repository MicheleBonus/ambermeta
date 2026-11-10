"""An mdout that never stated a time step is not compared against the mdin's.

`MdoutMetadata.dt` starts at 0.001 and is overwritten only when the mdout's CONTROL DATA
is read. A 0-byte mdout (a job that has just started, or one killed before pmemd wrote
anything) or one a node crash left full of NUL bytes keeps that default, and the step
check compared it with the mdin: "Timestep differs between mdin and mdout (0.002 ps per
step vs 0.001 ps per step)", a finding about a value the mdout never contained, next to
the correct "did not finish" note. AMBER prints `dt` in the same "Molecular dynamics"
block as `nstlim`, so an mdout that states no `nstlim` stated no MD control data.
"""
from __future__ import annotations

from ambermeta.protocol import auto_discover

MDIN = ("production\n &cntrl\n  imin = 0, irest = 1, ntx = 5,\n"
        "  nstlim = 500000, dt = 0.002,\n /\n")


def _stage(tmp_path, mdout_bytes):
    (tmp_path / "prod.mdin").write_text(MDIN, encoding="utf-8")
    (tmp_path / "prod.mdout").write_bytes(mdout_bytes)
    manifest = [{"name": "prod", "mdin": "prod.mdin", "mdout": "prod.mdout"}]
    return auto_discover(str(tmp_path), manifest=manifest,
                         skip_cross_stage_validation=True).stages[0]


def test_an_empty_mdout_is_not_said_to_differ_in_timestep(tmp_path):
    stage = _stage(tmp_path, b"")

    assert not any("Timestep differs" in v for v in stage.validation)


def test_a_nul_filled_mdout_is_not_said_to_differ_in_timestep(tmp_path):
    stage = _stage(tmp_path, b"\x00" * 4096)

    assert not any("Timestep differs" in v for v in stage.validation)
    # The run still reads as unfinished: that note is about what the file lacks.
    assert any("no completion marker" in v for v in stage.validation)


def test_a_stated_mdout_timestep_is_still_compared(sample_md_data_dir):
    # ntp_prod_0001.mdout states nstlim and dt = 0.004; an mdin claiming 0.002 differs.
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        shutil.copy(sample_md_data_dir / "ntp_prod_0001.mdout", d)
        with open(f"{d}/ntp_prod_0001.mdin", "w", encoding="utf-8") as fh:
            fh.write(MDIN)
        stage = auto_discover(d, manifest=[{"name": "p", "mdin": "ntp_prod_0001.mdin",
                                            "mdout": "ntp_prod_0001.mdout"}],
                              skip_cross_stage_validation=True).stages[0]

    assert any("Timestep differs" in v for v in stage.validation)
