from ambermeta.errors import AmberMetaError, FileLoadError, classify_exception
from ambermeta.protocol import SimulationStage


def test_fileloaderror_fields():
    e = FileLoadError(kind="mdout", path="/x/p.mdout", error_type="missing", message="nope")
    assert e.kind == "mdout"
    assert e.error_type == "missing"


def test_classify_exception_maps_types():
    assert classify_exception(FileNotFoundError()) == "missing"
    assert classify_exception(PermissionError()) == "permission"
    assert classify_exception(UnicodeDecodeError("utf-8", b"", 0, 1, "x")) == "decode"
    assert classify_exception(ValueError()) == "malformed"
    assert classify_exception(OSError()) == "malformed"


def test_ambermetaerror_is_exception():
    assert issubclass(AmberMetaError, Exception)


def test_stage_degraded_property():
    stage = SimulationStage(name="prod")
    assert stage.degraded is False
    stage.load_errors.append(FileLoadError("mdout", "/x", "missing", "nope"))
    assert stage.degraded is True


import json
import os

import pytest

from ambermeta.protocol import load_protocol_from_manifest


def _write(p, text=""):
    with open(p, "w") as fh:
        fh.write(text)


def test_manifest_bad_mdout_keeps_stage(tmp_path):
    prmtop = tmp_path / "s.prmtop"; _write(prmtop, "%VERSION\n%FLAG TITLE\n")
    mdin = tmp_path / "s.mdin"; _write(mdin, "&cntrl\n nstlim=1000, dt=0.002,\n/\n")
    mdout = tmp_path / "s.mdout"
    with open(mdout, "wb") as fh:
        fh.write(b"\x00\x01\x02not a real mdout")
    manifest = {"prod": {"prmtop": str(prmtop), "mdin": str(mdin), "mdout": str(mdout)}}
    mpath = tmp_path / "manifest.json"
    _write(mpath, json.dumps(manifest))

    protocol = load_protocol_from_manifest(str(mpath), directory=str(tmp_path))
    assert len(protocol.stages) == 1
    stage = protocol.stages[0]
    assert stage.mdin is not None
    assert stage.name == "prod"


def test_manifest_missing_file_graceful(tmp_path):
    # A missing prmtop (a parser that raises on absence) must be recorded as a
    # per-file load error and must NOT abort building the stage.
    mdin = tmp_path / "s.mdin"; _write(mdin, "&cntrl\n nstlim=10, dt=0.002,\n/\n")
    manifest = {"prod": {"mdin": str(mdin), "prmtop": str(tmp_path / "absent.prmtop")}}
    mpath = tmp_path / "manifest.json"
    _write(mpath, json.dumps(manifest))

    protocol = load_protocol_from_manifest(str(mpath), directory=str(tmp_path))
    assert len(protocol.stages) == 1
    stage = protocol.stages[0]
    assert stage.mdin is not None  # readable file survived
    errs = stage.load_errors
    assert any(e.kind == "prmtop" and e.error_type == "missing" for e in errs)


def test_manifest_strict_raises_on_missing(tmp_path):
    prmtop = tmp_path / "s.prmtop"; _write(prmtop, "%VERSION\n")
    manifest = {"prod": {"prmtop": str(prmtop), "mdout": str(tmp_path / "absent.mdout")}}
    mpath = tmp_path / "manifest.json"
    _write(mpath, json.dumps(manifest))

    with pytest.raises(AmberMetaError):
        load_protocol_from_manifest(str(mpath), directory=str(tmp_path), strict=True)


from ambermeta.protocol import auto_discover


def test_discovery_bad_file_keeps_going(tmp_path):
    (tmp_path / "min.mdin").write_text("&cntrl\n imin=1,\n/\n")
    (tmp_path / "prod_001.mdin").write_text("&cntrl\n nstlim=10, dt=0.002,\n/\n")
    (tmp_path / "prod_001.mdout").write_bytes(b"\x00\x01\x02garbage")
    protocol = auto_discover(str(tmp_path), recursive=True)
    assert len(protocol.stages) >= 1


def test_discovery_strict_raises(tmp_path, monkeypatch):
    (tmp_path / "prod_001.mdin").write_text("&cntrl\n nstlim=10,\n/\n")
    from ambermeta.parsers.mdin import MdinParser

    def boom(self):
        raise ValueError("synthetic parse failure")
    monkeypatch.setattr(MdinParser, "parse", boom)
    with pytest.raises(AmberMetaError):
        auto_discover(str(tmp_path), recursive=True, strict=True)


def test_listdir_permission_denied_does_not_crash(tmp_path, monkeypatch):
    (tmp_path / "prod_001.mdin").write_text("&cntrl\n/\n")

    def denied(path, *a, **k):
        raise PermissionError(f"denied: {path}")
    monkeypatch.setattr(os, "listdir", denied)
    protocol = auto_discover(str(tmp_path), recursive=False)
    assert protocol is not None


from ambermeta.cli import main


def test_cli_plan_degraded_exits_zero(tmp_path, capsys):
    (tmp_path / "prod_001.mdin").write_text("&cntrl\n nstlim=10, dt=0.002,\n/\n")
    (tmp_path / "prod_001.mdout").write_bytes(b"\x00\x01garbage")
    rc = main(["plan", str(tmp_path), "--recursive"])
    assert rc == 0


def test_cli_plan_strict_exits_one(tmp_path, monkeypatch, capsys):
    (tmp_path / "prod_001.mdin").write_text("&cntrl\n/\n")
    from ambermeta.parsers.mdin import MdinParser

    def boom(self):
        raise ValueError("synthetic")
    monkeypatch.setattr(MdinParser, "parse", boom)
    rc = main(["plan", str(tmp_path), "--recursive", "--strict"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "Traceback" not in captured.err


def test_main_converts_unexpected_exception_cleanly(tmp_path, monkeypatch, capsys):
    import ambermeta.cli as cli

    def boom(args):
        raise RuntimeError("kaboom internal")
    monkeypatch.setattr(cli, "_info_command", boom)
    f = tmp_path / "x.prmtop"; f.write_text("%VERSION\n")
    rc = cli.main(["info", str(f)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "Traceback" not in captured.out and "Traceback" not in captured.err
    assert "Unexpected error" in (captured.out + captured.err)


def test_main_converts_ambermetaerror_cleanly(tmp_path, monkeypatch, capsys):
    import ambermeta.cli as cli

    def boom(args):
        raise AmberMetaError("manifest references missing files")
    monkeypatch.setattr(cli, "_plan_command", boom)
    rc = cli.main(["plan", str(tmp_path), "--recursive"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "manifest references missing files" in (captured.out + captured.err)
    assert "Traceback" not in (captured.out + captured.err)
