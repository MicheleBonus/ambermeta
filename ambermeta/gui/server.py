"""
FastAPI server for the AmberMeta GUI.

This module provides the main server application and launcher function
for the web-based GUI.
"""

import os
import sys
import webbrowser
import threading
import time
from pathlib import Path
from typing import Optional

# Check for FastAPI availability
try:
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


def check_dependencies() -> None:
    """Check if required dependencies are installed."""
    if not HAS_FASTAPI:
        print("Error: GUI dependencies not installed.")
        print("Install them with: pip install ambermeta[gui]")
        sys.exit(1)


def create_app(directory: str) -> "FastAPI":
    """
    Create and configure the FastAPI application.

    Args:
        directory: Base directory for file operations

    Returns:
        Configured FastAPI application
    """
    check_dependencies()

    from .api.routes import router, set_base_directory

    # Set the base directory for file operations
    set_base_directory(directory)

    app = FastAPI(
        title="AmberMeta GUI",
        description="Web-based interface for building AmberMeta simulation protocol manifests",
        version="1.0.0",
    )

    # CORS middleware for development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:8765",
            "http://127.0.0.1:8765",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routes
    app.include_router(router, prefix="/api")

    # Determine static files location
    gui_dir = Path(__file__).parent
    static_dir = gui_dir / "static"
    frontend_dist = gui_dir / "frontend" / "dist"

    # Check for built frontend
    if static_dir.exists() and (static_dir / "index.html").exists():
        # Serve from static directory (default build output / packaged distribution)
        static_path = static_dir
    elif frontend_dist.exists() and (frontend_dist / "index.html").exists():
        # Legacy fallback: serve from frontend/dist
        static_path = frontend_dist
    else:
        # No frontend built, serve a placeholder
        static_path = None

    if static_path:
        # Serve static files
        app.mount("/assets", StaticFiles(directory=static_path / "assets"), name="assets")

        @app.get("/")
        async def serve_root():
            """Serve the main HTML file."""
            return FileResponse(static_path / "index.html")

        @app.get("/{path:path}")
        async def serve_spa(path: str):
            """Serve the SPA for any unmatched routes."""
            file_path = static_path / path
            if file_path.exists() and file_path.is_file():
                return FileResponse(file_path)
            # Fallback to index.html for SPA routing
            return FileResponse(static_path / "index.html")
    else:
        # Serve a development placeholder
        @app.get("/")
        async def serve_placeholder():
            """Serve a placeholder when frontend is not built."""
            return HTMLResponse(content=_get_placeholder_html())

    return app


def _get_placeholder_html() -> str:
    """Return placeholder HTML when frontend is not built."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AmberMeta GUI</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: #e0e0e0;
            padding: 20px;
        }
        .container {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            padding: 40px;
            max-width: 800px;
            width: 100%;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        h1 {
            font-size: 2.5rem;
            margin-bottom: 1rem;
            background: linear-gradient(90deg, #3b82f6, #10b981);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .subtitle {
            color: #888;
            font-size: 1.1rem;
            margin-bottom: 2rem;
        }
        .status {
            background: rgba(59, 130, 246, 0.1);
            border: 1px solid rgba(59, 130, 246, 0.3);
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 2rem;
        }
        .status h2 {
            color: #3b82f6;
            font-size: 1.2rem;
            margin-bottom: 0.5rem;
        }
        .status p {
            color: #aaa;
        }
        .api-section {
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid rgba(16, 185, 129, 0.3);
            border-radius: 8px;
            padding: 20px;
        }
        .api-section h2 {
            color: #10b981;
            font-size: 1.2rem;
            margin-bottom: 1rem;
        }
        .endpoint {
            background: rgba(0, 0, 0, 0.2);
            padding: 12px 16px;
            border-radius: 6px;
            margin-bottom: 8px;
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 0.9rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .method {
            background: #3b82f6;
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        .method.post { background: #10b981; }
        .method.put { background: #f59e0b; }
        .method.delete { background: #ef4444; }
        a {
            color: #3b82f6;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        .footer {
            margin-top: 2rem;
            color: #666;
            font-size: 0.9rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>AmberMeta GUI</h1>
        <p class="subtitle">Protocol Builder for Molecular Dynamics Simulations</p>

        <div class="status">
            <h2>Backend Active</h2>
            <p>The API server is running. The frontend has not been built yet.</p>
            <p style="margin-top: 10px;">To build the frontend, run:</p>
            <div class="endpoint" style="margin-top: 10px;">
                cd ambermeta/gui/frontend && npm install && npm run build
            </div>
        </div>

        <div class="api-section">
            <h2>Available API Endpoints</h2>
            <div class="endpoint">
                <span><span class="method">GET</span> /api/files</span>
                <span>List simulation files</span>
            </div>
            <div class="endpoint">
                <span><span class="method">GET</span> /api/stages</span>
                <span>Get all stages</span>
            </div>
            <div class="endpoint">
                <span><span class="method post">POST</span> /api/stages</span>
                <span>Create a stage</span>
            </div>
            <div class="endpoint">
                <span><span class="method put">PUT</span> /api/stages/{id}</span>
                <span>Update a stage</span>
            </div>
            <div class="endpoint">
                <span><span class="method delete">DELETE</span> /api/stages/{id}</span>
                <span>Delete a stage</span>
            </div>
            <div class="endpoint">
                <span><span class="method">GET</span> /api/protocol</span>
                <span>Get full protocol</span>
            </div>
            <div class="endpoint">
                <span><span class="method post">POST</span> /api/export</span>
                <span>Export manifest</span>
            </div>
            <p style="margin-top: 1rem;">
                View the full API documentation at:
                <a href="/docs">/docs</a> or <a href="/redoc">/redoc</a>
            </p>
        </div>

        <p class="footer">
            AmberMeta v1.0 | <a href="https://github.com/ambermeta/ambermeta">GitHub</a>
        </p>
    </div>
</body>
</html>
"""


def run_gui(
    directory: str = ".",
    port: int = 8765,
    host: str = "127.0.0.1",
    open_browser: bool = True,
    reload: bool = False,
) -> None:
    """
    Launch the AmberMeta GUI server.

    Args:
        directory: Base directory for file operations (default: current directory)
        port: Server port (default: 8765)
        host: Server host (default: 127.0.0.1 for localhost only)
        open_browser: Whether to automatically open the browser (default: True)
        reload: Enable auto-reload for development (default: False)
    """
    check_dependencies()

    import uvicorn

    # Resolve the directory to absolute path
    directory = os.path.abspath(directory)

    if not os.path.isdir(directory):
        print(f"Error: Directory not found: {directory}")
        sys.exit(1)

    print(f"Starting AmberMeta GUI...")
    print(f"Base directory: {directory}")
    print(f"Server: http://{host}:{port}")
    print(f"API docs: http://{host}:{port}/docs")
    print()

    # Open browser after a short delay
    if open_browser:
        def open_after_delay():
            time.sleep(1.5)
            url = f"http://{host}:{port}"
            print(f"Opening browser: {url}")
            webbrowser.open(url)

        browser_thread = threading.Thread(target=open_after_delay, daemon=True)
        browser_thread.start()

    # Create and run the app
    app = create_app(directory)

    # Configure uvicorn
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info" if reload else "warning",
        reload=reload,
    )

    server = uvicorn.Server(config)

    try:
        server.run()
    except KeyboardInterrupt:
        print("\nShutting down AmberMeta GUI...")
