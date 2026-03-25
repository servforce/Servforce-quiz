from __future__ import annotations

from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

import backend.md_quiz.app as fastapi_app
from backend.md_quiz.app import create_app


def _build_stub_legacy_app():
    async def _root(_request):
        return PlainTextResponse("legacy-root")

    async def _admin(_request):
        return PlainTextResponse("legacy-admin")

    async def _admin_login(_request):
        return PlainTextResponse("legacy-login")

    return Starlette(
        routes=[
            Route("/", _root),
            Route("/admin", _admin),
            Route("/admin/login", _admin_login, methods=["GET", "POST"]),
        ]
    )


def _build_client(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    monkeypatch.setattr(fastapi_app, "build_legacy_bridge", _build_stub_legacy_app)
    app = create_app()
    return TestClient(app)


def test_system_health_smoke(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/api/system/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_admin_session_and_jobs_flow(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    login_response = client.post(
        "/api/admin/session/login",
        json={"username": "admin", "password": "password"},
    )
    assert login_response.status_code == 200

    create_job = client.post("/api/admin/jobs", json={"kind": "scan_exams", "payload": {}})
    assert create_job.status_code == 201

    jobs_response = client.get("/api/admin/jobs")
    assert jobs_response.status_code == 200
    assert len(jobs_response.json()["items"]) == 1

    set_cookie = login_response.headers.get("set-cookie", "")
    assert "api_session=" in set_cookie


def test_runtime_config_roundtrip(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})

    update_response = client.put(
        "/api/admin/config",
        json={"sms_enabled": True, "min_submit_seconds": 180},
    )

    assert update_response.status_code == 200
    assert update_response.json()["sms_enabled"] is True
    assert update_response.json()["min_submit_seconds"] == 180


def test_admin_path_is_served_by_legacy_app(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/admin")

    assert response.status_code == 200
    assert response.text == "legacy-admin"


def test_root_is_served_by_legacy_app(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert response.text == "legacy-root"


def test_legacy_admin_redirects_to_admin(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    monkeypatch.setattr(fastapi_app, "build_legacy_bridge", _build_stub_legacy_app)
    client = TestClient(create_app())

    response = client.get("/legacy/admin", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/admin"


def test_legacy_login_post_redirect_preserves_target(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.post("/legacy/admin/login", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/admin/login"


def test_flask_login_keeps_flask_session_cookie(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    client = TestClient(create_app())

    # Simulate an old API-side session cookie already existing in the browser.
    client.cookies.set("api_session", "stale-api-cookie", domain="testserver.local", path="/")
    response = client.post(
        "/admin/login",
        data={"username": "admin", "password": "password"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/admin"
    set_cookie = response.headers.get("set-cookie", "")
    assert "session=" in set_cookie
    assert "api_session=" not in set_cookie
