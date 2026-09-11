from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.static_frontend import mount_static_frontend


def test_mount_static_frontend_serves_index_assets_and_preserves_api(tmp_path: Path):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html>frontend</html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")

    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    assert mount_static_frontend(app, dist) is True

    client = TestClient(app)
    assert client.get("/api/ping").json() == {"ok": True}
    assert "frontend" in client.get("/").text
    assert client.get("/assets/app.js").text == "console.log('ok')"


def test_mount_static_frontend_is_noop_when_build_is_absent(tmp_path: Path):
    app = FastAPI()
    assert mount_static_frontend(app, tmp_path / "missing") is False
