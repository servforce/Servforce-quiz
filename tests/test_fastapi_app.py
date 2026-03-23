from __future__ import annotations

from fastapi.testclient import TestClient

from backend.md_quiz.app import create_app


def _build_client(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_LEGACY_BRIDGE", "0")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
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
