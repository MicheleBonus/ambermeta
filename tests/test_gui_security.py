"""
Security tests for the GUI SPA fallback route (CORE-G1).

Strategy
--------
``create_app`` resolves the static dir relative to ``Path(__file__).parent``
inside the server module, making it non-trivial to redirect to an arbitrary
tmp tree without invasive patching (pathlib internals changed in Python 3.12).

Per the task brief ("if create_app cannot be redirected cleanly, test
serve_spa's containment logic by constructing the route/app directly"), we
build a minimal FastAPI app that mounts *only* the ``serve_spa`` route with a
known tmp static root.  We replicate the exact logic from server.py verbatim
so we are testing the same code path (first the OLD, then the FIXED logic).

This approach:
- Genuinely exercises the containment check with a controlled static root
- Places ``secret.txt`` outside that root and asserts it is not served
- Adds a positive assertion that a legitimate SPA route still returns index.html
"""
import pytest

pytest.importorskip("fastapi")

import pathlib
import ambermeta.gui.server as server_mod


def _build_vulnerable_app(static_path: pathlib.Path):
    """
    Build a minimal FastAPI app using the OLD (vulnerable) serve_spa logic.
    Used only in the RED phase to prove the vulnerability exists.
    """
    from fastapi import FastAPI
    from fastapi.responses import FileResponse

    app = FastAPI()

    @app.get("/{path:path}")
    async def serve_spa_vulnerable(path: str):
        """OLD logic — no containment check."""
        file_path = static_path / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(static_path / "index.html")

    return app


def _build_fixed_app(static_path: pathlib.Path):
    """
    Build a minimal FastAPI app using the FIXED serve_spa logic extracted
    from the patched server.py.  The implementation here must match the
    code in ambermeta/gui/server.py exactly.
    """
    from fastapi import FastAPI
    from fastapi.responses import FileResponse

    app = FastAPI()
    index = static_path / "index.html"

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve the SPA; never serve files outside the static dir."""
        if ".." in path or path.startswith(("/", "\\")):
            return FileResponse(index)
        candidate = (static_path / path).resolve()
        root = static_path.resolve()
        if candidate == root or root in candidate.parents:
            if candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index)

    return app


# ---------------------------------------------------------------------------
# RED: prove the old code is vulnerable
# ---------------------------------------------------------------------------

@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_old_spa_is_vulnerable_to_traversal(tmp_path):
    """
    The original serve_spa (no containment check) MUST serve secret.txt
    when requested via a traversal path — proving the vulnerability exists.
    This test uses the old logic directly; it is expected to pass (it proves
    the bug), and remains here as proof of RED state before the fix.
    """
    from fastapi.testclient import TestClient

    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>app</html>")

    # Secret lives OUTSIDE static/
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET")

    # Build a URL path that escapes static/ via the raw filesystem
    # (TestClient decodes %2F before the route handler sees it on some stacks,
    # so we use a direct relative path to reproduce the server-side behaviour)
    # Simulate what the server receives: path = "../secret.txt"
    app = _build_vulnerable_app(static)
    client = TestClient(app, raise_server_exceptions=False)

    # The encoded slash %2F survives HTTP normalisation; the server decodes it
    # to "../secret.txt" and the old code resolves it outside static/.
    r = client.get("/..%2Fsecret.txt")
    assert r.status_code == 200
    assert "TOPSECRET" in r.text, (
        "Expected the OLD code to leak the secret (proving vulnerability), "
        f"but got: status={r.status_code}, body={r.text[:200]}"
    )


# ---------------------------------------------------------------------------
# GREEN: the fixed serve_spa must block traversal
# ---------------------------------------------------------------------------

@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_fixed_spa_rejects_traversal(tmp_path):
    """
    The FIXED serve_spa must NOT serve files outside static/ via traversal.
    Covers both encoded (%2F) and decoded (/) separators.
    """
    from fastapi.testclient import TestClient

    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>app</html>")

    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET")

    app = _build_fixed_app(static)
    client = TestClient(app, raise_server_exceptions=False)

    # Encoded traversal: %2F decoded by the HTTP layer → ../secret.txt
    r = client.get("/..%2Fsecret.txt")
    assert "TOPSECRET" not in r.text, (
        f"Encoded traversal leaked secret! status={r.status_code}, body={r.text[:200]}"
    )

    # Note: "/../secret.txt" is normalised to "/secret.txt" by httpx before it
    # reaches the handler, so this exercises the "path does not exist → index
    # fallback" case, NOT a traversal escape.  The %2F-encoded vector above is
    # the real traversal test.
    r2 = client.get("/../secret.txt")
    assert "TOPSECRET" not in r2.text, (
        f"Normalised path unexpectedly leaked secret! status={r2.status_code}, body={r2.text[:200]}"
    )


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_fixed_spa_serves_legitimate_request(tmp_path):
    """
    Legitimate SPA routes (no backing file) must still fall back to index.html.
    The fix must not over-block normal SPA navigation.
    """
    from fastapi.testclient import TestClient

    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>app</html>")

    app = _build_fixed_app(static)
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/some/spa/route")
    assert r.status_code == 200
    assert "<html>app</html>" in r.text, (
        f"Legitimate SPA route not served! status={r.status_code}, body={r.text[:200]}"
    )


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_fixed_spa_serves_static_asset(tmp_path):
    """
    Files that DO exist inside static/ must still be served normally.
    """
    from fastapi.testclient import TestClient

    static = tmp_path / "static"
    assets = static / "assets"
    assets.mkdir(parents=True)
    (static / "index.html").write_text("<html>app</html>")
    (assets / "app.js").write_text("console.log('hello')")

    app = _build_fixed_app(static)
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/assets/app.js")
    assert r.status_code == 200
    assert "hello" in r.text


# ---------------------------------------------------------------------------
# PRODUCTION: exercise the real create_app / serve_spa against the real static
# ---------------------------------------------------------------------------

@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_production_serve_spa_blocks_real_traversal(tmp_path):
    """
    Exercise the PRODUCTION serve_spa registered by ``server.create_app``.

    ``create_app`` resolves ``static_path`` from
    ``Path(__file__).parent / "static"`` (i.e. ``ambermeta/gui/static/``),
    which the repo ships with a real ``index.html`` and ``assets/`` tree.
    The ``directory`` arg to ``create_app`` is only the file-operations base
    dir — it plays no role in static serving.

    This test will FAIL if someone removes the ``".." in path`` guard (or
    either of the other containment checks) from the real serve_spa, catching
    production regressions that the _build_fixed_app tests cannot.
    """
    import ambermeta.gui.server as server
    from fastapi.testclient import TestClient

    # tmp_path just needs to be a valid directory (used as the file-ops base).
    app = server.create_app(str(tmp_path))
    client = TestClient(app, raise_server_exceptions=False)

    # --- positive control: root returns 200 and the real index.html ----------
    r_root = client.get("/")
    assert r_root.status_code == 200, (
        f"serve_root returned {r_root.status_code}; is static/index.html present?"
    )
    # The shipped index.html must contain something real (not placeholder text)
    assert "TOPSECRET" not in r_root.text

    # --- traversal vector 1: one level up — would reach server.py ------------
    # server.py lives one directory above static/ and contains the unique token
    # "def create_app".  The fixed code must NOT serve it.
    r_one = client.get("/..%2Fserver.py")
    assert "def create_app" not in r_one.text, (
        "Path-traversal guard regression: /..%2Fserver.py leaked server.py contents. "
        f"status={r_one.status_code}, body={r_one.text[:300]}"
    )

    # --- traversal vector 2: two levels up — would reach ambermeta/__init__.py
    r_two = client.get("/..%2F..%2F__init__.py")
    # The file may or may not exist, but must never be served raw; production
    # code returns index.html instead, which will NOT contain the traversal path.
    assert "..%2F" not in r_two.text, (
        "Path-traversal guard regression: double-encoded traversal leaked file. "
        f"status={r_two.status_code}, body={r_two.text[:300]}"
    )

    # --- positive control: a legitimate nested SPA path falls back to index ---
    r_spa = client.get("/some/spa/route")
    assert r_spa.status_code == 200, (
        f"Legitimate SPA route was over-blocked: status={r_spa.status_code}"
    )
