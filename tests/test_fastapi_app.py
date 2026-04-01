from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.md_quiz.app import create_app
from backend.md_quiz.storage.db import (
    conn_scope,
    create_assignment_record,
    create_candidate,
    create_exam_version,
    init_db,
    save_exam_definition,
)


def _reset_runtime_tables():
    init_db()
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM exam_version_asset")
            cur.execute("DELETE FROM exam_archive")
            cur.execute("DELETE FROM exam_paper")
            cur.execute("DELETE FROM assignment_record")
            cur.execute("DELETE FROM exam_version")
            cur.execute("DELETE FROM exam_asset")
            cur.execute("DELETE FROM exam_definition")
            cur.execute("DELETE FROM candidate")
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


def _seed_exam_with_metadata(exam_key: str) -> int:
    spec = {
        "id": exam_key,
        "title": "人格类型测试",
        "description": "用于接口测试的问卷。",
        "tags": ["personality", "traits", "self-assessment"],
        "schema_version": 2,
        "format": "qml-v2",
        "question_count": 1,
        "question_counts": {"single": 1, "multiple": 0, "short": 0},
        "estimated_duration_minutes": 2,
        "trait": {"dimensions": ["I", "E"]},
        "questions": [
            {
                "qid": "Q1",
                "type": "single",
                "max_points": 5,
                "stem_md": "题目一",
                "options": [{"key": "A", "text": "选项A", "correct": True}],
            }
        ],
    }
    public_spec = {
        "id": exam_key,
        "title": "人格类型测试",
        "description": "用于接口测试的问卷。",
        "tags": ["personality", "traits", "self-assessment"],
        "schema_version": 2,
        "format": "qml-v2",
        "question_count": 1,
        "question_counts": {"single": 1, "multiple": 0, "short": 0},
        "estimated_duration_minutes": 2,
        "trait": {"dimensions": ["I", "E"]},
        "questions": [
            {
                "qid": "Q1",
                "type": "single",
                "max_points": 5,
                "stem_md": "题目一",
                "options": [{"key": "A", "text": "选项A"}],
            }
        ],
    }
    version_id = create_exam_version(
        exam_key=exam_key,
        version_no=1,
        title="人格类型测试",
        source_path=f"quizzes/{exam_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        git_commit="deadbeef",
        content_hash=f"hash-{exam_key}",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
    )
    save_exam_definition(
        exam_key=exam_key,
        title="人格类型测试",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
        status="active",
        source_path=f"quizzes/{exam_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        current_version_id=version_id,
        current_version_no=1,
        last_synced_commit="deadbeef",
        last_sync_error="",
        last_sync_at=datetime.now(timezone.utc),
    )
    return version_id


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


def test_admin_exam_endpoints_expose_metadata_and_match_tags_query(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("personality-meta-demo")

    login_response = client.post(
        "/api/admin/session/login",
        json={"username": "admin", "password": "password"},
    )
    assert login_response.status_code == 200

    list_response = client.get("/api/admin/exams?q=traits")
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    item = next(entry for entry in items if entry["exam_key"] == "personality-meta-demo")
    assert item["tags"] == ["personality", "traits", "self-assessment"]
    assert item["schema_version"] == 2
    assert item["format"] == "qml-v2"
    assert item["question_count"] == 1
    assert item["question_counts"] == {"single": 1, "multiple": 0, "short": 0}
    assert item["estimated_duration_minutes"] == 2
    assert item["trait"] == {"dimensions": ["I", "E"]}

    detail_response = client.get("/api/admin/exams/personality-meta-demo")
    assert detail_response.status_code == 200
    detail_exam = detail_response.json()["exam"]
    assert detail_exam["tags"] == ["personality", "traits", "self-assessment"]
    assert detail_exam["schema_version"] == 2
    assert detail_exam["format"] == "qml-v2"
    assert detail_exam["question_count"] == 1
    assert detail_exam["question_counts"] == {"single": 1, "multiple": 0, "short": 0}
    assert detail_exam["estimated_duration_minutes"] == 2
    assert detail_exam["trait"] == {"dimensions": ["I", "E"]}

    version_response = client.get(f"/api/admin/exam-versions/{version_id}")
    assert version_response.status_code == 200
    selected_version = version_response.json()["selected_version"]
    assert selected_version["tags"] == ["personality", "traits", "self-assessment"]
    assert selected_version["schema_version"] == 2
    assert selected_version["format"] == "qml-v2"
    assert selected_version["question_count"] == 1
    assert selected_version["question_counts"] == {"single": 1, "multiple": 0, "short": 0}
    assert selected_version["estimated_duration_minutes"] == 2
    assert selected_version["trait"] == {"dimensions": ["I", "E"]}


def test_public_attempt_bootstrap_exposes_quiz_metadata(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("public-meta-demo")
    candidate_id = create_candidate("测试候选人", "13900000001")
    token = "pubmeta001"
    now = datetime.now(timezone.utc).isoformat()
    create_assignment_record(
        token,
        {
            "token": token,
            "exam_key": "public-meta-demo",
            "exam_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "verified",
            "status_updated_at": now,
            "invite_window": {"start_date": None, "end_date": None},
            "time_limit_seconds": 7200,
            "min_submit_seconds": 3600,
            "verify_max_attempts": 3,
            "pass_threshold": 60,
            "verify": {"attempts": 1, "locked": False},
            "sms_verify": {"verified": True, "phone": "13900000001"},
            "pending_profile": {"name": "测试候选人", "phone": "13900000001"},
            "timing": {"start_at": None, "end_at": None},
            "answers": {},
            "grading_started_at": None,
            "graded_at": None,
            "grading_error": None,
            "grading": None,
        },
    )

    response = client.get(f"/api/public/attempt/{token}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["step"] == "exam"
    assert payload["exam"]["tags"] == ["personality", "traits", "self-assessment"]
    assert payload["exam"]["schema_version"] == 2
    assert payload["exam"]["format"] == "qml-v2"
    assert payload["exam"]["question_count"] == 1
    assert payload["exam"]["question_counts"] == {"single": 1, "multiple": 0, "short": 0}
    assert payload["exam"]["estimated_duration_minutes"] == 2
    assert payload["exam"]["trait"] == {"dimensions": ["I", "E"]}
