from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.md_quiz.api import admin as admin_api
from backend.md_quiz.app import create_app
from backend.md_quiz.storage.db import (
    conn_scope,
    create_assignment_record,
    create_candidate,
    create_exam_paper,
    create_exam_version,
    get_candidate,
    get_runtime_kv,
    init_db,
    replace_exam_assets,
    replace_exam_version_assets,
    save_exam_archive,
    save_exam_definition,
    set_runtime_kv,
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
            cur.execute("DELETE FROM runtime_kv")


def _build_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    _reset_runtime_tables()
    app = create_app()
    return TestClient(app)


def _count_rows(table: str) -> int:
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            row = cur.fetchone()
    return int((row[0] if row else 0) or 0)


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


def _seed_exam_with_answer_time(exam_key: str) -> int:
    spec = {
        "id": exam_key,
        "title": "答题时长演示",
        "description": "用于验证 answer_time 累计时长。",
        "tags": ["timing", "answer-time"],
        "schema_version": 2,
        "format": "qml-v2",
        "trait": {},
        "questions": [
            {
                "qid": "Q1",
                "type": "single",
                "max_points": 5,
                "stem_md": "题目一",
                "answer_time_seconds": 45,
                "options": [{"key": "A", "text": "选项A", "correct": True}],
            },
            {
                "qid": "Q2",
                "type": "multiple",
                "max_points": 6,
                "stem_md": "题目二",
                "answer_time_seconds": 90,
                "options": [{"key": "A", "text": "选项A", "correct": True}],
            },
            {
                "qid": "Q3",
                "type": "short",
                "max_points": 10,
                "stem_md": "题目三",
                "answer_time_seconds": 15,
                "rubric": "给出关键点即可。",
            },
        ],
    }
    public_spec = {
        "id": exam_key,
        "title": "答题时长演示",
        "description": "用于验证 answer_time 累计时长。",
        "tags": ["timing", "answer-time"],
        "schema_version": 2,
        "format": "qml-v2",
        "trait": {},
        "questions": [
            {
                "qid": "Q1",
                "type": "single",
                "max_points": 5,
                "stem_md": "题目一",
                "answer_time_seconds": 45,
                "options": [{"key": "A", "text": "选项A"}],
            },
            {
                "qid": "Q2",
                "type": "multiple",
                "max_points": 6,
                "stem_md": "题目二",
                "answer_time_seconds": 90,
                "options": [{"key": "A", "text": "选项A"}],
            },
            {
                "qid": "Q3",
                "type": "short",
                "max_points": 10,
                "stem_md": "题目三",
                "answer_time_seconds": 15,
                "rubric": "给出关键点即可。",
            },
        ],
    }
    version_id = create_exam_version(
        exam_key=exam_key,
        version_no=1,
        title="答题时长演示",
        source_path=f"quizzes/{exam_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        git_commit="answertime01",
        content_hash=f"hash-{exam_key}",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
    )
    save_exam_definition(
        exam_key=exam_key,
        title="答题时长演示",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
        status="active",
        source_path=f"quizzes/{exam_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        current_version_id=version_id,
        current_version_no=1,
        last_synced_commit="answertime01",
        last_sync_error="",
        last_sync_at=datetime.now(timezone.utc),
    )
    return version_id


def _set_repo_binding(repo_url: str) -> None:
    set_runtime_kv(
        "exam_repo_binding",
        {
            "repo_url": repo_url,
            "bound_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    set_runtime_kv(
        "exam_repo_sync",
        {
            "repo_url": repo_url,
            "status": "idle",
            "last_job_id": "",
            "last_error": "",
            "last_result": {},
            "last_commit": "",
            "queued_at": "",
            "started_at": "",
            "finished_at": "",
        },
    )


def _stub_admin_resume_parsing(monkeypatch, *, parsed_name: str, parsed_phone: str) -> None:
    monkeypatch.setattr(
        admin_api.deps,
        "parse_resume_all_llm",
        lambda data, filename, mime="": {
            "name": parsed_name,
            "phone": parsed_phone,
            "confidence": {"name": 96, "phone": 98},
            "details": {"skills": ["python"], "experience_blocks": [], "projects_raw": ""},
            "details_status": "done",
            "method": {
                "identity": "llm_attachment",
                "name": "llm_attachment",
                "details": "llm_attachment",
            },
        },
    )
    monkeypatch.setattr(
        admin_api.deps,
        "extract_resume_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call extract_resume_text")),
    )
    monkeypatch.setattr(
        admin_api.deps,
        "parse_resume_identity_fast",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call parse_resume_identity_fast")),
    )
    monkeypatch.setattr(
        admin_api.deps,
        "parse_resume_identity_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call parse_resume_identity_llm")),
    )
    monkeypatch.setattr(
        admin_api.deps,
        "parse_resume_name_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call parse_resume_name_llm")),
    )
    monkeypatch.setattr(
        admin_api.deps,
        "parse_resume_details_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call parse_resume_details_llm")),
    )


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
    detail_payload = detail_response.json()
    detail_exam = detail_payload["exam"]
    assert detail_exam["tags"] == ["personality", "traits", "self-assessment"]
    assert detail_exam["schema_version"] == 2
    assert detail_exam["format"] == "qml-v2"
    assert detail_exam["question_count"] == 1
    assert detail_exam["question_counts"] == {"single": 1, "multiple": 0, "short": 0}
    assert detail_exam["estimated_duration_minutes"] == 2
    assert detail_exam["trait"] == {"dimensions": ["I", "E"]}
    detail_question = detail_payload["selected_version"]["spec"]["questions"][0]
    assert detail_question["stem_html"].startswith("<p>")
    assert "题目一" in detail_question["stem_html"]

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
    assert selected_version["spec"]["questions"][0]["stem_html"].startswith("<p>")
    assert "题目一" in selected_version["spec"]["questions"][0]["stem_html"]


def test_admin_exam_estimated_duration_prefers_answer_time_total(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_answer_time("answer-time-demo")

    login_response = client.post(
        "/api/admin/session/login",
        json={"username": "admin", "password": "password"},
    )
    assert login_response.status_code == 200

    list_response = client.get("/api/admin/exams?q=answer-time")
    assert list_response.status_code == 200
    item = next(entry for entry in list_response.json()["items"] if entry["exam_key"] == "answer-time-demo")
    assert item["question_counts"] == {"single": 1, "multiple": 1, "short": 1}
    assert item["estimated_duration_minutes"] == 3

    detail_response = client.get("/api/admin/exams/answer-time-demo")
    assert detail_response.status_code == 200
    assert detail_response.json()["exam"]["estimated_duration_minutes"] == 3

    version_response = client.get(f"/api/admin/exam-versions/{version_id}")
    assert version_response.status_code == 200
    assert version_response.json()["selected_version"]["estimated_duration_minutes"] == 3


def test_admin_candidate_resume_upload_returns_created_flag_for_new_candidate(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    _stub_admin_resume_parsing(monkeypatch, parsed_name="新候选人", parsed_phone="13912345678")

    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    response = client.post(
        "/api/admin/candidates/resume/upload",
        files={"file": ("resume.pdf", b"%PDF-1.4 demo", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] is True
    assert payload["candidate"]["name"] == "新候选人"
    assert payload["candidate"]["phone"] == "13912345678"
    assert payload["candidate"]["resume_filename"] == "resume.pdf"
    assert _count_rows("candidate") == 1


def test_admin_candidate_resume_upload_marks_existing_candidate_as_updated(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    create_candidate("现有候选人", "13912345678")
    _stub_admin_resume_parsing(monkeypatch, parsed_name="简历里的名字", parsed_phone="13912345678")

    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    response = client.post(
        "/api/admin/candidates/resume/upload",
        files={"file": ("resume.pdf", b"%PDF-1.4 demo", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] is False
    assert payload["candidate"]["name"] == "现有候选人"
    assert payload["candidate"]["phone"] == "13912345678"
    assert payload["candidate"]["resume_filename"] == "resume.pdf"
    assert _count_rows("candidate") == 1


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


def test_exam_repo_binding_persists_and_auto_enqueues_sync(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    response = client.post("/api/admin/exams/binding", json={"repo_url": "https://github.com/example/repo.git"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["binding"]["repo_url"] == "https://github.com/example/repo.git"
    assert payload["sync"]["created"] is True
    assert payload["sync"]["error"] == ""
    assert get_runtime_kv("exam_repo_binding")["repo_url"] == "https://github.com/example/repo.git"

    list_response = client.get("/api/admin/exams")
    assert list_response.status_code == 200
    assert list_response.json()["repo_binding"]["repo_url"] == "https://github.com/example/repo.git"

    jobs_response = client.get("/api/admin/jobs")
    assert jobs_response.status_code == 200
    items = jobs_response.json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "git_sync_exams"
    assert items[0]["payload"]["repo_url"] == "https://github.com/example/repo.git"


def test_exam_sync_requires_bound_repo(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    response = client.post("/api/admin/exams/sync", json={"repo_url": "https://github.com/example/other.git"})

    assert response.status_code == 409
    assert "尚未绑定仓库" in response.json()["detail"]


def test_exam_repo_binding_rejects_second_bind(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    first = client.post("/api/admin/exams/binding", json={"repo_url": "https://github.com/example/repo.git"})
    assert first.status_code == 201

    second = client.post("/api/admin/exams/binding", json={"repo_url": "https://github.com/example/another.git"})

    assert second.status_code == 409
    assert "已绑定仓库" in second.json()["detail"]


def test_exam_repo_rebind_rejects_invalid_confirmation(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    _seed_exam_with_metadata("rebind-confirm-demo")
    _set_repo_binding("https://github.com/example/old.git")
    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    response = client.post(
        "/api/admin/exams/binding/rebind",
        json={"repo_url": "https://github.com/example/new.git", "confirmation_text": "错误确认"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "确认词不正确"
    assert get_runtime_kv("exam_repo_binding")["repo_url"] == "https://github.com/example/old.git"
    assert _count_rows("exam_definition") == 1


def test_exam_repo_rebind_rejects_while_sync_busy(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    bind_response = client.post("/api/admin/exams/binding", json={"repo_url": "https://github.com/example/repo.git"})
    assert bind_response.status_code == 201

    rebind_response = client.post(
        "/api/admin/exams/binding/rebind",
        json={"repo_url": "https://github.com/example/new.git", "confirmation_text": "重新绑定"},
    )

    assert rebind_response.status_code == 409
    assert "同步任务在执行" in rebind_response.json()["detail"]


def test_exam_repo_rebind_clears_exam_domain_and_keeps_candidates(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("rebind-demo")
    candidate_id = create_candidate("保留候选人", "13900000002")
    now = datetime.now(timezone.utc).isoformat()
    create_assignment_record(
        "assign-rebind-001",
        {
            "token": "assign-rebind-001",
            "exam_key": "rebind-demo",
            "exam_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "verified",
        },
    )
    create_exam_paper(
        candidate_id=candidate_id,
        phone="13900000002",
        exam_key="rebind-demo",
        exam_version_id=version_id,
        token="paper-rebind-001",
    )
    save_exam_archive(
        archive_name="archive-rebind-001",
        token="paper-rebind-001",
        candidate_id=candidate_id,
        exam_key="rebind-demo",
        exam_version_id=version_id,
        phone="13900000002",
        archive={"exam": {"exam_key": "rebind-demo"}},
    )
    replace_exam_assets("rebind-demo", {"assets/q1.png": (b"png", "image/png")})
    replace_exam_version_assets(version_id, {"assets/q1.png": (b"png", "image/png")})
    _set_repo_binding("https://github.com/example/old.git")
    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    response = client.post(
        "/api/admin/exams/binding/rebind",
        json={"repo_url": "https://github.com/example/new.git", "confirmation_text": "重新绑定"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["binding"]["repo_url"] == "https://github.com/example/new.git"
    assert payload["previous_repo_url"] == "https://github.com/example/old.git"
    assert payload["cleanup"]["exam_definition"] == 1
    assert payload["cleanup"]["exam_version"] == 1
    assert payload["cleanup"]["assignment_record"] == 1
    assert payload["cleanup"]["exam_paper"] == 1
    assert payload["cleanup"]["exam_archive"] == 1
    assert payload["cleanup"]["exam_asset"] == 1
    assert payload["cleanup"]["exam_version_asset"] == 1
    assert payload["sync"]["created"] is True

    assert _count_rows("exam_definition") == 0
    assert _count_rows("exam_version") == 0
    assert _count_rows("assignment_record") == 0
    assert _count_rows("exam_paper") == 0
    assert _count_rows("exam_archive") == 0
    assert _count_rows("exam_asset") == 0
    assert _count_rows("exam_version_asset") == 0
    assert get_candidate(candidate_id)["name"] == "保留候选人"
    assert get_runtime_kv("exam_repo_binding")["repo_url"] == "https://github.com/example/new.git"

    list_response = client.get("/api/admin/exams")
    assert list_response.status_code == 200
    assert list_response.json()["items"] == []
    assert list_response.json()["repo_binding"]["repo_url"] == "https://github.com/example/new.git"

    jobs_response = client.get("/api/admin/jobs")
    assert jobs_response.status_code == 200
    assert jobs_response.json()["items"][0]["payload"]["repo_url"] == "https://github.com/example/new.git"


def test_exam_sync_ignores_payload_repo_url_and_uses_bound_repo(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    _set_repo_binding("https://github.com/example/bound.git")
    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    response = client.post("/api/admin/exams/sync", json={"repo_url": "https://github.com/example/ignored.git"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] is True

    jobs_response = client.get("/api/admin/jobs")
    assert jobs_response.status_code == 200
    items = jobs_response.json()["items"]
    assert len(items) == 1
    assert items[0]["payload"]["repo_url"] == "https://github.com/example/bound.git"
