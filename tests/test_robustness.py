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
