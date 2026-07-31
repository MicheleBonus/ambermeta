"""AmberMeta GUI API package.

Deliberately imports nothing. ``core_bridge`` is the CLI's engine facade on the
plan/discover/validate paths, and eagerly importing ``.routes`` here made every
one of those commands require the ``gui`` extra. Import submodules directly:

    from ambermeta.gui.api import core_bridge
    from ambermeta.gui.api.routes import router
"""
