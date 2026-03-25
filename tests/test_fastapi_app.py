from __future__ import annotations

from fastapi.testclient import TestClient

from backend.md_quiz.app import create_app
from backend.md_quiz.storage.db import conn_scope, init_db


def _reset_runtime_tables():
    init_db()
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM process_heartbeat")
            cur.execute("DELETE FROM runtime_job")
            cur.execute(
                """
DELETE FROM runtime_kv
WHERE key IN ('runtime_config', 'runtime_json_store_migration')
"""
            )


def _build_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    _reset_runtime_tables()
    app = create_app()
    return TestClient(app)


def test_system_health_smoke(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/api/system/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_system_processes_include_api_heartbeat(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    health = client.get("/api/system/health")
    assert health.status_code == 200

    response = client.get("/api/system/processes")

    assert response.status_code == 200
    items = response.json()["items"]
    assert any(item["name"] == "api" and item["process"] == "api" for item in items)


def test_admin_session_jobs_and_config_flow(monkeypatch, tmp_path):
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
    assert jobs_response.json()["items"][0]["kind"] == "scan_exams"

    update_response = client.put(
        "/api/admin/config",
        json={"sms_enabled": True, "min_submit_seconds": 180},
    )
    assert update_response.status_code == 200
    assert update_response.json()["sms_enabled"] is True
    assert update_response.json()["min_submit_seconds"] == 180


def test_admin_routes_are_served_by_spa_shell(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/admin")

    assert response.status_code == 200
    assert "adminApp()" in response.text


def test_public_routes_are_served_by_spa_shell(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/t/demo-token")

    assert response.status_code == 200
    assert "publicApp()" in response.text


def test_root_redirects_by_admin_session(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    logged_out = client.get("/", follow_redirects=False)
    assert logged_out.status_code == 307
    assert logged_out.headers["location"] == "/admin/login"

    client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    logged_in = client.get("/", follow_redirects=False)
    assert logged_in.status_code == 307
    assert logged_in.headers["location"] == "/admin"


def test_admin_logs_include_trend_series(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    login_response = client.post(
        "/api/admin/session/login",
        json={"username": "admin", "password": "password"},
    )
    assert login_response.status_code == 200

    response = client.get("/api/admin/logs?days=14&tz_offset_minutes=480")

    assert response.status_code == 200
    payload = response.json()
    assert "counts" in payload
    assert "trend" in payload
    assert payload["trend"]["start_day"] <= payload["trend"]["end_day"]
    assert len(payload["trend"]["days"]) == 14
    assert set(payload["trend"]["series"].keys()) == {"candidate", "exam", "grading", "assignment", "system"}
    for key in payload["trend"]["series"]:
        assert len(payload["trend"]["series"][key]) == 14


def test_legacy_redirects_preserve_path_and_query(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/legacy/admin/exams?tab=detail", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/admin/exams?tab=detail"
