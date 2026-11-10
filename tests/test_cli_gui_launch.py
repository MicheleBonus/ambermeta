"""`ambermeta gui` on a port it cannot use.

It printed `Server: http://127.0.0.1:<port>` first and only then tried to bind, so a busy
port came out as that URL followed by uvicorn's raw bind error (in the OS language). The
URL led to whatever already held the port -- in practice another AmberMeta GUI, serving
another directory, so an edit made there landed in the wrong document. A port number
outside 1-65535 got the banner and then a traceback.
"""
from __future__ import annotations

import socket

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from ambermeta.cli import main  # noqa: E402


@pytest.fixture
def busy_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    try:
        yield s.getsockname()[1]
    finally:
        s.close()


def test_a_busy_port_is_refused_before_any_url_is_printed(tmp_path, busy_port, capsys):
    rc = main(["gui", str(tmp_path), "--port", str(busy_port), "--no-browser"])

    captured = capsys.readouterr()
    shown = captured.out + captured.err
    assert rc == 1
    assert f"{busy_port}" in shown and "in use" in shown
    assert "Server: http" not in shown


@pytest.mark.parametrize("port", ["0", "70000"])
def test_a_port_number_outside_the_valid_range_is_refused(tmp_path, port, capsys):
    rc = main(["gui", str(tmp_path), "--port", port, "--no-browser"])

    captured = capsys.readouterr()
    shown = captured.out + captured.err
    assert rc == 1
    assert "1" in shown and "65535" in shown
    assert "Server: http" not in shown
    assert "Traceback" not in shown
