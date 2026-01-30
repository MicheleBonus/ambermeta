"""
AmberMeta GUI - Web-based graphical interface for protocol building.

This module provides a FastAPI-based web server with a React frontend
for intuitive simulation protocol manifest building.

Usage:
    ambermeta gui [directory] [--port PORT] [--no-browser]
"""

from .server import run_gui, create_app

__all__ = ["run_gui", "create_app"]
