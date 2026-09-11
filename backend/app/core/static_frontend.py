from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount_static_frontend(app: FastAPI, dist_dir: Path) -> bool:
    """Serve the compiled Vite app from FastAPI when a production build exists.

    API routes must be registered before calling this function because the root
    mount is intentionally the final route in the application.
    """

    index_file = dist_dir / "index.html"
    if not index_file.is_file():
        return False

    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")
    return True
