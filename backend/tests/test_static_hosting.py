"""Single-container mode: the backend serves the built client and keeps the API honest."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import register_exception_handlers
from app.main import _mount_frontend


def _client(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>NYX shell</title>", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    _mount_frontend(app, SimpleNamespace(static_dir=str(tmp_path)))
    return TestClient(app)


def test_browser_routes_fall_back_to_the_app_shell(tmp_path):
    client = _client(tmp_path)
    response = client.get("/projects/some-id")
    assert response.status_code == 200
    assert "NYX shell" in response.text


def test_real_static_files_are_served_directly(tmp_path):
    client = _client(tmp_path)
    assert client.get("/favicon.svg").status_code == 200


def test_unknown_api_paths_are_json_errors_not_the_html_shell(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "HTTP_404"
    assert "<html" not in response.text.lower()


def test_real_api_routes_still_win(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/health").json() == {"status": "ok"}
