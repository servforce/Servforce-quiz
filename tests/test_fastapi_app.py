from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.md_quiz.api import admin as admin_api
from backend.md_quiz.api import public as public_api
from backend.md_quiz.app import create_app
from backend.md_quiz.services import system_status_helpers
from backend.md_quiz.storage.db import (
    conn_scope,
    create_assignment_record,
    create_candidate,
    create_quiz_paper,
    create_quiz_version,
    delete_exam_domain_data_by_quiz_key,
    get_candidate,
    get_assignment_record,
    get_quiz_archive_by_token,
    get_quiz_paper_by_token,
    get_runtime_kv,
    incr_runtime_daily_metric_int,
    init_db,
    replace_quiz_assets,
    replace_quiz_version_assets,
    save_quiz_archive,
    save_assignment_record,
    save_quiz_definition,
    set_exam_public_invite,
    set_runtime_kv,
)


def _reset_runtime_tables():
    init_db()
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM quiz_version_asset")
            cur.execute("DELETE FROM quiz_archive")
            cur.execute("DELETE FROM quiz_paper")
            cur.execute("DELETE FROM assignment_record")
            cur.execute("DELETE FROM quiz_version")
            cur.execute("DELETE FROM quiz_asset")
            cur.execute("DELETE FROM quiz_definition")
            cur.execute("DELETE FROM candidate")
            cur.execute("DELETE FROM process_heartbeat")
            cur.execute("DELETE FROM runtime_job")
            cur.execute("DELETE FROM runtime_daily_metric")
            cur.execute("DELETE FROM runtime_kv")


def _build_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    _reset_runtime_tables()
    with system_status_helpers._SYSTEM_STATUS_SUMMARY_CACHE_LOCK:
        system_status_helpers._SYSTEM_STATUS_SUMMARY_CACHE["at"] = 0.0
        system_status_helpers._SYSTEM_STATUS_SUMMARY_CACHE["value"] = {}
    app = create_app()
    return TestClient(app)


def _admin_login(client: TestClient) -> None:
    response = client.post(
        "/api/admin/session/login",
        json={"username": "admin", "password": "password"},
    )
    assert response.status_code == 200


def _count_rows(table: str) -> int:
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            row = cur.fetchone()
    return int((row[0] if row else 0) or 0)


def _seed_exam_with_metadata(quiz_key: str) -> int:
    spec = {
        "id": quiz_key,
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
                "answer_time_seconds": 120,
                "options": [{"key": "A", "text": "选项A", "correct": True}],
            }
        ],
    }
    public_spec = {
        "id": quiz_key,
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
                "answer_time_seconds": 120,
                "options": [{"key": "A", "text": "选项A"}],
            }
        ],
    }
    version_id = create_quiz_version(
        quiz_key=quiz_key,
        version_no=1,
        title="人格类型测试",
        source_path=f"quizzes/{quiz_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        git_commit="deadbeef",
        content_hash=f"hash-{quiz_key}",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
    )
    save_quiz_definition(
        quiz_key=quiz_key,
        title="人格类型测试",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
        status="active",
        source_path=f"quizzes/{quiz_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        current_version_id=version_id,
        current_version_no=1,
        last_synced_commit="deadbeef",
        last_sync_error="",
        last_sync_at=datetime.now(timezone.utc),
    )
    return version_id


def test_delete_exam_domain_data_by_quiz_key_removes_exam_related_rows(monkeypatch, tmp_path):
    _build_client(monkeypatch, tmp_path)
    quiz_key = "cleanup-demo"
    version_id = _seed_exam_with_metadata(quiz_key)
    replace_quiz_version_assets(version_id, {"assets/q1.png": (b"png", "image/png")})
    replace_quiz_assets(quiz_key, {"assets/welcome.png": (b"png", "image/png")})
    candidate_id = create_candidate(name="清理候选人", phone="13900000001")
    create_assignment_record(
        "cleanup-token",
        {
            "token": "cleanup-token",
            "quiz_key": quiz_key,
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "status": "invited",
        },
    )
    create_quiz_paper(
        candidate_id=candidate_id,
        phone="13900000001",
        quiz_key=quiz_key,
        quiz_version_id=version_id,
        token="cleanup-token",
        source_kind="direct",
        invite_start_date="2026-04-01",
        invite_end_date="2026-04-02",
        status="invited",
    )
    save_quiz_archive(
        archive_name="cleanup-demo-cleanup-token",
        token="cleanup-token",
        candidate_id=candidate_id,
        quiz_key=quiz_key,
        quiz_version_id=version_id,
        phone="13900000001",
        archive={"exam": {"quiz_key": quiz_key, "quiz_version_id": version_id}, "questions": []},
    )

    counts = delete_exam_domain_data_by_quiz_key(quiz_key)

    assert counts["quiz_definition"] == 1
    assert counts["quiz_version"] == 1
    assert counts["quiz_version_asset"] == 1
    assert counts["quiz_asset"] == 1
    assert counts["assignment_record"] == 1
    assert counts["quiz_paper"] == 1
    assert counts["quiz_archive"] == 1
    assert get_assignment_record("cleanup-token") is None
    assert get_quiz_paper_by_token("cleanup-token") is None
    assert get_quiz_archive_by_token("cleanup-token") is None


def _seed_exam_with_answer_time(quiz_key: str) -> int:
    spec = {
        "id": quiz_key,
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
        "id": quiz_key,
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
    version_id = create_quiz_version(
        quiz_key=quiz_key,
        version_no=1,
        title="答题时长演示",
        source_path=f"quizzes/{quiz_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        git_commit="answertime01",
        content_hash=f"hash-{quiz_key}",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
    )
    save_quiz_definition(
        quiz_key=quiz_key,
        title="答题时长演示",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
        status="active",
        source_path=f"quizzes/{quiz_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        current_version_id=version_id,
        current_version_no=1,
        last_synced_commit="answertime01",
        last_sync_error="",
        last_sync_at=datetime.now(timezone.utc),
    )
    return version_id


def _seed_exam_without_answer_time(quiz_key: str) -> int:
    spec = {
        "id": quiz_key,
        "title": "不限时演示",
        "description": "用于验证忽略计时时允许 0 时长测验。",
        "tags": ["timing", "ignore-timing"],
        "schema_version": 2,
        "format": "qml-v2",
        "trait": {},
        "questions": [
            {
                "qid": "Q1",
                "type": "single",
                "max_points": 5,
                "stem_md": "题目一",
                "answer_time_seconds": 0,
                "options": [{"key": "A", "text": "选项A", "correct": True}],
            }
        ],
    }
    public_spec = {
        "id": quiz_key,
        "title": "不限时演示",
        "description": "用于验证忽略计时时允许 0 时长测验。",
        "tags": ["timing", "ignore-timing"],
        "schema_version": 2,
        "format": "qml-v2",
        "trait": {},
        "questions": [
            {
                "qid": "Q1",
                "type": "single",
                "max_points": 5,
                "stem_md": "题目一",
                "answer_time_seconds": 0,
                "options": [{"key": "A", "text": "选项A"}],
            }
        ],
    }
    version_id = create_quiz_version(
        quiz_key=quiz_key,
        version_no=1,
        title="不限时演示",
        source_path=f"quizzes/{quiz_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        git_commit="ignoretiming01",
        content_hash=f"hash-{quiz_key}",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
    )
    save_quiz_definition(
        quiz_key=quiz_key,
        title="不限时演示",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
        status="active",
        source_path=f"quizzes/{quiz_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        current_version_id=version_id,
        current_version_no=1,
        last_synced_commit="ignoretiming01",
        last_sync_error="",
        last_sync_at=datetime.now(timezone.utc),
    )
    return version_id


def _seed_exam_with_review_content(quiz_key: str) -> int:
    spec = {
        "id": quiz_key,
        "title": "答题回放演示",
        "description": "用于验证答题详情页回放和评价结构。",
        "tags": ["review", "attempt-detail"],
        "schema_version": 2,
        "format": "qml-v2",
        "question_count": 4,
        "question_counts": {"single": 2, "multiple": 1, "short": 1},
        "estimated_duration_minutes": 6,
        "trait": {
            "dimensions": ["I", "E"],
            "analysis_guidance": {
                "paired_dimensions": [
                    {
                        "left": "I",
                        "right": "E",
                        "default_winner": "I",
                        "description": "观察更偏向独立推进还是外向协作。",
                    }
                ]
            },
        },
        "questions": [
            {
                "qid": "Q1",
                "label": "Q1 单选",
                "type": "single",
                "max_points": 5,
                "stem_md": "**选择正确答案**",
                "options": [
                    {"key": "A", "text": "错误答案", "correct": False},
                    {"key": "B", "text": "正确答案", "correct": True},
                ],
            },
            {
                "qid": "Q2",
                "label": "Q2 多选",
                "type": "multiple",
                "max_points": 6,
                "stem_md": "选择所有正确选项",
                "options": [
                    {"key": "A", "text": "选项 A", "correct": True},
                    {"key": "B", "text": "选项 B", "correct": True},
                    {"key": "C", "text": "选项 C", "correct": False},
                ],
            },
            {
                "qid": "Q3",
                "label": "Q3 简答",
                "type": "short",
                "max_points": 10,
                "stem_md": "请说明你会如何拆解问题。",
                "rubric": "提到分析现状和制定计划。",
            },
            {
                "qid": "Q4",
                "label": "Q4 倾向",
                "type": "single",
                "max_points": 0,
                "stem_md": "你更偏好哪种工作方式？",
                "options": [
                    {"key": "A", "text": "独立推进", "traits": {"I": 2}},
                    {"key": "B", "text": "频繁讨论", "traits": {"E": 2}},
                ],
            },
        ],
    }
    public_spec = {
        "id": quiz_key,
        "title": "答题回放演示",
        "description": "用于验证答题详情页回放和评价结构。",
        "tags": ["review", "attempt-detail"],
        "schema_version": 2,
        "format": "qml-v2",
        "question_count": 4,
        "question_counts": {"single": 2, "multiple": 1, "short": 1},
        "estimated_duration_minutes": 6,
        "trait": {"dimensions": ["I", "E"]},
        "questions": [
            {
                "qid": "Q1",
                "label": "Q1 单选",
                "type": "single",
                "max_points": 5,
                "stem_md": "**选择正确答案**",
                "options": [
                    {"key": "A", "text": "错误答案"},
                    {"key": "B", "text": "正确答案"},
                ],
            },
            {
                "qid": "Q2",
                "label": "Q2 多选",
                "type": "multiple",
                "max_points": 6,
                "stem_md": "选择所有正确选项",
                "options": [
                    {"key": "A", "text": "选项 A"},
                    {"key": "B", "text": "选项 B"},
                    {"key": "C", "text": "选项 C"},
                ],
            },
            {
                "qid": "Q3",
                "label": "Q3 简答",
                "type": "short",
                "max_points": 10,
                "stem_md": "请说明你会如何拆解问题。",
            },
            {
                "qid": "Q4",
                "label": "Q4 倾向",
                "type": "single",
                "max_points": 0,
                "stem_md": "你更偏好哪种工作方式？",
                "options": [
                    {"key": "A", "text": "独立推进"},
                    {"key": "B", "text": "频繁讨论"},
                ],
            },
        ],
    }
    version_id = create_quiz_version(
        quiz_key=quiz_key,
        version_no=1,
        title="答题回放演示",
        source_path=f"quizzes/{quiz_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        git_commit="reviewdemo01",
        content_hash=f"hash-{quiz_key}",
        source_md="---\nid: review\n---\n",
        spec=spec,
        public_spec=public_spec,
    )
    save_quiz_definition(
        quiz_key=quiz_key,
        title="答题回放演示",
        source_md="---\nid: review\n---\n",
        spec=spec,
        public_spec=public_spec,
        status="active",
        source_path=f"quizzes/{quiz_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        current_version_id=version_id,
        current_version_no=1,
        last_synced_commit="reviewdemo01",
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


def _stub_public_resume_parsing(monkeypatch, *, parsed_name: str, parsed_phone: str) -> None:
    monkeypatch.setattr(
        public_api.deps,
        "parse_resume_all_llm",
        lambda **_kwargs: {
            "name": parsed_name,
            "phone": parsed_phone,
            "confidence": {"name": 91, "phone": 96},
            "details_status": "done",
            "details": {
                "summary": "公开邀约候选人简历",
                "skills": ["Python", "沟通"],
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
        json={"sms_daily_threshold": 12, "min_submit_seconds": 180},
    )
    assert update_response.status_code == 200
    assert update_response.json()["sms_daily_threshold"] == 12
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
    _admin_login(client)

    response = client.get("/api/admin/logs?days=14&tz_offset_minutes=480")

    assert response.status_code == 200
    payload = response.json()
    assert "counts" in payload
    assert "trend" in payload
    assert payload["trend"]["start_day"] <= payload["trend"]["end_day"]
    assert len(payload["trend"]["days"]) == 14
    assert set(payload["trend"]["series"].keys()) == {"candidate", "quiz", "grading", "assignment", "system"}
    for key in payload["trend"]["series"]:
        assert len(payload["trend"]["series"][key]) == 14


def test_system_status_summary_marks_llm_as_unconfigured_when_required_env_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "sk")
    monkeypatch.setenv("ALIYUN_PNVS_SIGN_NAME", "sign")
    monkeypatch.setenv("ALIYUN_PNVS_TEMPLATE_CODE", "100001")
    client = _build_client(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_MODEL", "")
    _admin_login(client)

    response = client.get("/api/admin/system-status/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_level"] == "danger"
    assert payload["llm"]["configured"] is False
    assert payload["llm"]["missing_fields"] == ["OPENAI_API_KEY", "OPENAI_MODEL"]
    assert payload["sms"]["configured"] is True
    assert payload["config_alerts"][0]["key"] == "llm"


def test_system_status_summary_marks_sms_as_unconfigured_when_required_env_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("ALIYUN_PNVS_SIGN_NAME", "sign")
    monkeypatch.setenv("ALIYUN_PNVS_TEMPLATE_CODE", "100001")
    client = _build_client(monkeypatch, tmp_path)
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "")
    _admin_login(client)

    response = client.get("/api/admin/system-status/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_level"] == "danger"
    assert payload["sms"]["configured"] is False
    assert payload["sms"]["missing_fields"] == ["ALIYUN_ACCESS_KEY_SECRET"]
    assert payload["llm"]["configured"] is True


def test_system_status_summary_stays_ok_when_required_env_present_and_usage_is_low(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "sk")
    monkeypatch.setenv("ALIYUN_PNVS_SIGN_NAME", "sign")
    monkeypatch.setenv("ALIYUN_PNVS_TEMPLATE_CODE", "100001")
    client = _build_client(monkeypatch, tmp_path)
    _admin_login(client)

    update = client.put(
        "/api/admin/system-status/config",
        json={"llm_tokens_limit": 1000, "sms_calls_limit": 100},
    )

    assert update.status_code == 200
    payload = update.json()["summary"]
    assert payload["overall_level"] == "ok"
    assert payload["llm"]["configured"] is True
    assert payload["sms"]["configured"] is True
    assert payload["config_alerts"] == []


def test_system_status_summary_exposes_integration_summaries(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example-llm.internal/v1")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "sk")
    monkeypatch.setenv("ALIYUN_PNVS_SIGN_NAME", "验证码服务")
    monkeypatch.setenv("ALIYUN_PNVS_TEMPLATE_CODE", "100001")
    monkeypatch.setenv("ALIYUN_PNVS_ENDPOINT", "dypnsapi.aliyuncs.com")
    monkeypatch.setenv("ALIYUN_PNVS_REGION_ID", "cn-hangzhou")
    client = _build_client(monkeypatch, tmp_path)
    _admin_login(client)

    response = client.get("/api/admin/system-status/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["llm"]["integration"] == {
        "title": "OpenAI 兼容 Responses API",
        "summary": "模型 gpt-4.1-mini · 接口 example-llm.internal",
    }
    assert payload["sms"]["integration"] == {
        "title": "阿里云 PNVS 短信认证",
        "summary": "签名 验证码服务 · 模板 100001 · 接口 dypnsapi.aliyuncs.com · 地域 cn-hangzhou",
    }


def test_system_status_summary_keeps_critical_when_usage_over_threshold_and_config_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "sk")
    monkeypatch.setenv("ALIYUN_PNVS_SIGN_NAME", "sign")
    monkeypatch.setenv("ALIYUN_PNVS_TEMPLATE_CODE", "100001")
    client = _build_client(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_MODEL", "")
    _admin_login(client)
    today = datetime.now().astimezone().date().isoformat()
    incr_runtime_daily_metric_int(day=today, key="llm_tokens", delta=120)

    update = client.put(
        "/api/admin/system-status/config",
        json={"llm_tokens_limit": 100, "sms_calls_limit": 100},
    )

    assert update.status_code == 200
    payload = update.json()["summary"]
    assert payload["llm"]["level"] == "critical"
    assert payload["llm"]["configured"] is False
    assert payload["overall_level"] == "critical"


def test_system_status_range_returns_same_config_summary_as_summary_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "sk")
    monkeypatch.setenv("ALIYUN_PNVS_SIGN_NAME", "sign")
    monkeypatch.setenv("ALIYUN_PNVS_TEMPLATE_CODE", "100001")
    client = _build_client(monkeypatch, tmp_path)
    _admin_login(client)

    range_response = client.get("/api/admin/system-status")
    summary_response = client.get("/api/admin/system-status/summary")

    assert range_response.status_code == 200
    assert summary_response.status_code == 200
    assert range_response.json()["summary"] == summary_response.json()


def test_public_invite_toggle_clears_link_when_disabled_and_exposes_qr(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    _seed_exam_with_metadata("public-toggle-demo")
    _admin_login(client)

    enable_response = client.post(
        "/api/admin/quizzes/public-toggle-demo/public-invite",
        json={"enabled": True},
    )

    assert enable_response.status_code == 200
    enabled_payload = enable_response.json()
    public_token = str(enabled_payload["token"])
    assert enabled_payload["enabled"] is True
    assert enabled_payload["public_url"].endswith(f"/p/{public_token}")
    assert enabled_payload["qr_url"] == f"/api/public/invites/{public_token}/qr.png"

    detail_enabled = client.get("/api/admin/quizzes/public-toggle-demo")
    assert detail_enabled.status_code == 200
    enabled_quiz = detail_enabled.json()["quiz"]
    assert enabled_quiz["public_invite_enabled"] is True
    assert enabled_quiz["public_invite_url"].endswith(f"/p/{public_token}")
    assert enabled_quiz["public_invite_qr_url"] == f"/api/public/invites/{public_token}/qr.png"

    disable_response = client.post(
        "/api/admin/quizzes/public-toggle-demo/public-invite",
        json={"enabled": False},
    )

    assert disable_response.status_code == 200
    disabled_payload = disable_response.json()
    assert disabled_payload["enabled"] is False
    assert disabled_payload["public_url"] == ""
    assert disabled_payload["qr_url"] == ""

    detail_disabled = client.get("/api/admin/quizzes/public-toggle-demo")
    assert detail_disabled.status_code == 200
    disabled_quiz = detail_disabled.json()["quiz"]
    assert disabled_quiz["public_invite_enabled"] is False
    assert disabled_quiz["public_invite_url"] == ""
    assert disabled_quiz["public_invite_qr_url"] == ""


def test_legacy_redirects_preserve_path_and_query(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/legacy/admin/quizzes?tab=detail", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/admin/quizzes?tab=detail"


def test_admin_quiz_endpoints_expose_metadata_and_match_tags_query(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("personality-meta-demo")

    login_response = client.post(
        "/api/admin/session/login",
        json={"username": "admin", "password": "password"},
    )
    assert login_response.status_code == 200

    list_response = client.get("/api/admin/quizzes?q=traits")
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    item = next(entry for entry in items if entry["quiz_key"] == "personality-meta-demo")
    assert item["tags"] == ["personality", "traits", "self-assessment"]
    assert item["schema_version"] == 2
    assert item["format"] == "qml-v2"
    assert item["question_count"] == 1
    assert item["question_counts"] == {"single": 1, "multiple": 0, "short": 0}
    assert item["estimated_duration_minutes"] == 2
    assert item["trait"] == {"dimensions": ["I", "E"]}

    detail_response = client.get("/api/admin/quizzes/personality-meta-demo")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    detail_quiz = detail_payload["quiz"]
    assert detail_quiz["tags"] == ["personality", "traits", "self-assessment"]
    assert detail_quiz["schema_version"] == 2
    assert detail_quiz["format"] == "qml-v2"
    assert detail_quiz["question_count"] == 1
    assert detail_quiz["question_counts"] == {"single": 1, "multiple": 0, "short": 0}
    assert detail_quiz["estimated_duration_minutes"] == 2
    assert detail_quiz["trait"] == {"dimensions": ["I", "E"]}
    detail_question = detail_payload["selected_quiz_version"]["spec"]["questions"][0]
    assert detail_question["stem_html"].startswith("<p>")
    assert "题目一" in detail_question["stem_html"]
    assert detail_question["options"][0]["text_html"].startswith("<p>")
    assert "选项A" in detail_question["options"][0]["text_html"]

    version_response = client.get(f"/api/admin/quiz-versions/{version_id}")
    assert version_response.status_code == 200
    selected_version = version_response.json()["selected_quiz_version"]
    assert selected_version["tags"] == ["personality", "traits", "self-assessment"]
    assert selected_version["schema_version"] == 2
    assert selected_version["format"] == "qml-v2"
    assert selected_version["question_count"] == 1
    assert selected_version["question_counts"] == {"single": 1, "multiple": 0, "short": 0}
    assert selected_version["estimated_duration_minutes"] == 2
    assert selected_version["trait"] == {"dimensions": ["I", "E"]}
    assert selected_version["spec"]["questions"][0]["stem_html"].startswith("<p>")
    assert "题目一" in selected_version["spec"]["questions"][0]["stem_html"]
    assert selected_version["spec"]["questions"][0]["options"][0]["text_html"].startswith("<p>")


def test_admin_quiz_estimated_duration_prefers_answer_time_total(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_answer_time("answer-time-demo")

    login_response = client.post(
        "/api/admin/session/login",
        json={"username": "admin", "password": "password"},
    )
    assert login_response.status_code == 200

    list_response = client.get("/api/admin/quizzes?q=answer-time")
    assert list_response.status_code == 200
    item = next(entry for entry in list_response.json()["items"] if entry["quiz_key"] == "answer-time-demo")
    assert item["question_counts"] == {"single": 1, "multiple": 1, "short": 1}
    assert item["estimated_duration_minutes"] == 3

    detail_response = client.get("/api/admin/quizzes/answer-time-demo")
    assert detail_response.status_code == 200
    assert detail_response.json()["quiz"]["estimated_duration_minutes"] == 3

    version_response = client.get(f"/api/admin/quiz-versions/{version_id}")
    assert version_response.status_code == 200
    assert version_response.json()["selected_quiz_version"]["estimated_duration_minutes"] == 3


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
            "quiz_key": "public-meta-demo",
            "quiz_version_id": version_id,
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
    assert payload["step"] == "quiz"
    assert payload["quiz"]["tags"] == ["personality", "traits", "self-assessment"]
    assert payload["quiz"]["schema_version"] == 2
    assert payload["quiz"]["format"] == "qml-v2"
    assert payload["quiz"]["question_count"] == 1
    assert payload["quiz"]["question_counts"] == {"single": 1, "multiple": 0, "short": 0}
    assert payload["quiz"]["estimated_duration_minutes"] == 2
    assert payload["quiz"]["trait"] == {"dimensions": ["I", "E"]}
    assert payload["quiz"]["spec"]["questions"][0]["options"][0]["text_html"].startswith("<p>")
    assert "选项A" in payload["quiz"]["spec"]["questions"][0]["options"][0]["text_html"]


def test_public_attempt_bootstrap_normalizes_option_markdown_and_keeps_tex(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    quiz_key = "public-rich-text-demo"
    spec = {
        "id": quiz_key,
        "title": "富文本题目",
        "description": "用于验证公开端富文本字段。",
        "tags": ["markdown"],
        "schema_version": 2,
        "format": "qml-v2",
        "question_count": 1,
        "question_counts": {"single": 1, "multiple": 0, "short": 0},
        "estimated_duration_minutes": 1,
        "trait": {},
        "questions": [
            {
                "qid": "Q1",
                "type": "single",
                "max_points": 5,
                "stem_md": r"设有向图 $E=\{\langle v0,v1 \rangle\}$",
                "answer_time_seconds": 60,
                "options": [{"key": "A", "text": r"select student\_id from learn", "correct": True}],
            }
        ],
    }
    public_spec = {
        "id": quiz_key,
        "title": "富文本题目",
        "description": "用于验证公开端富文本字段。",
        "tags": ["markdown"],
        "schema_version": 2,
        "format": "qml-v2",
        "question_count": 1,
        "question_counts": {"single": 1, "multiple": 0, "short": 0},
        "estimated_duration_minutes": 1,
        "trait": {},
        "questions": [
            {
                "qid": "Q1",
                "type": "single",
                "max_points": 5,
                "stem_md": r"设有向图 $E=\{\langle v0,v1 \rangle\}$",
                "answer_time_seconds": 60,
                "options": [{"key": "A", "text": r"select student\_id from learn"}],
            }
        ],
    }
    version_id = create_quiz_version(
        quiz_key=quiz_key,
        version_no=1,
        title="富文本题目",
        source_path=f"quizzes/{quiz_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        git_commit="deadbeef",
        content_hash=f"hash-{quiz_key}",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
    )
    save_quiz_definition(
        quiz_key=quiz_key,
        title="富文本题目",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
        status="active",
        source_path=f"quizzes/{quiz_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        current_version_id=version_id,
        current_version_no=1,
        last_synced_commit="deadbeef",
        last_sync_error="",
        last_sync_at=datetime.now(timezone.utc),
    )
    candidate_id = create_candidate("富文本候选人", "13900000041")
    token = "pubrich001"
    now = datetime.now(timezone.utc).isoformat()
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": quiz_key,
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "verified",
            "status_updated_at": now,
            "invite_window": {"start_date": None, "end_date": None},
            "time_limit_seconds": 60,
            "min_submit_seconds": 0,
            "verify_max_attempts": 3,
            "pass_threshold": 60,
            "verify": {"attempts": 0, "locked": False},
            "sms_verify": {"verified": True, "phone": "13900000041"},
            "pending_profile": {"name": "富文本候选人", "phone": "13900000041"},
            "timing": {"start_at": None, "end_at": None},
            "answers": {},
            "grading": None,
        },
    )

    response = client.get(f"/api/public/attempt/{token}")

    assert response.status_code == 200
    question = response.json()["quiz"]["spec"]["questions"][0]
    assert "student_id" in question["options"][0]["text_html"]
    assert r"$E=\{\langle v0,v1 \rangle\}$" in question["stem_html"]


def test_public_done_payload_exposes_final_analysis_and_traits(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("public-done-result-demo")
    candidate_id = create_candidate("结果候选人", "13900000029")
    token = "publicdone01"
    now = datetime.now(timezone.utc).isoformat()
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": "public-done-result-demo",
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "graded",
            "status_updated_at": now,
            "invite_window": {"start_date": None, "end_date": None},
            "time_limit_seconds": 120,
            "min_submit_seconds": 0,
            "verify_max_attempts": 3,
            "verify": {"attempts": 0, "locked": False},
            "pending_profile": {"name": "结果候选人", "phone": "13900000029"},
            "timing": {"start_at": now, "end_at": now},
            "answers": {"Q1": "A"},
            "grading_started_at": now,
            "graded_at": now,
            "grading_error": None,
            "candidate_remark": "更偏向独处内化。",
            "grading": {
                "status": "done",
                "result_mode": "mixed",
                "total": 3,
                "total_max": 5,
                "final_analysis": "综合分析文本",
                "traits": {
                    "primary_dimensions": ["I"],
                    "paired_dimensions": [{"left": "I", "right": "E", "winner": "I", "diff": 2}],
                },
            },
        },
    )

    response = client.get(f"/api/public/attempt/{token}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["step"] == "done"
    assert payload["result"]["result_mode"] == "mixed"
    assert payload["result"]["score_max"] == 5
    assert payload["result"]["final_analysis"] == "综合分析文本"
    assert payload["result"]["candidate_remark"] == "更偏向独处内化。"
    assert payload["result"]["traits"]["primary_dimensions"] == ["I"]


def test_direct_assignment_without_phone_verification_enters_quiz(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("direct-no-phone-verify-demo")
    candidate_id = create_candidate("直邀候选人", "13900000009")
    token = "directquiz01"
    now = datetime.now(timezone.utc).isoformat()
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": "direct-no-phone-verify-demo",
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "invited",
            "status_updated_at": now,
            "invite_window": {"start_date": None, "end_date": None},
            "time_limit_seconds": 7200,
            "min_submit_seconds": 3600,
            "verify_max_attempts": 3,
            "pass_threshold": 60,
            "verify": {"attempts": 0, "locked": False},
            "pending_profile": {"name": "直邀候选人", "phone": "13900000009"},
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
    assert response.json()["step"] == "quiz"
    assert response.json()["assignment"]["require_phone_verification"] is False


def test_admin_create_assignment_defaults_phone_verification_false(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    _seed_exam_with_metadata("assign-default-phone-verify-demo")
    candidate_id = create_candidate("默认关闭候选人", "13900000013")

    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    create_response = client.post(
        "/api/admin/assignments",
        json={
            "quiz_key": "assign-default-phone-verify-demo",
            "candidate_id": candidate_id,
            "time_limit_seconds": 7200,
            "invite_start_date": "2026-04-01",
            "invite_end_date": "2026-04-02",
            "pass_threshold": 60,
        },
    )

    assert create_response.status_code == 201
    token = create_response.json()["token"]
    assignment = get_assignment_record(token)
    assert assignment is not None
    assert assignment["require_phone_verification"] is False
    assert assignment["ignore_timing"] is False
    assert assignment["time_limit_seconds"] == 120
    assert assignment["min_submit_seconds"] == 0
    assert "pass_threshold" not in assignment

    list_response = client.get("/api/admin/assignments")
    assert list_response.status_code == 200
    item = next(it for it in list_response.json()["items"] if it["token"] == token)
    assert item["require_phone_verification"] is False
    assert item["ignore_timing"] is False


def test_admin_create_assignment_can_enable_phone_verification(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    _seed_exam_with_metadata("assign-enable-phone-verify-demo")
    candidate_id = create_candidate("显式开启候选人", "13900000014")

    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    create_response = client.post(
        "/api/admin/assignments",
        json={
            "quiz_key": "assign-enable-phone-verify-demo",
            "candidate_id": candidate_id,
            "time_limit_seconds": 7200,
            "invite_start_date": "2026-04-01",
            "invite_end_date": "2026-04-02",
            "require_phone_verification": True,
        },
    )

    assert create_response.status_code == 201
    token = create_response.json()["token"]
    assignment = get_assignment_record(token)
    assert assignment is not None
    assert assignment["require_phone_verification"] is True

    detail_response = client.get(f"/api/admin/attempts/{token}")
    assert detail_response.status_code == 200
    assert detail_response.json()["assignment"]["require_phone_verification"] is True


def test_admin_create_assignment_can_ignore_timing(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    _seed_exam_with_metadata("assign-ignore-timing-demo")
    candidate_id = create_candidate("不限时候选人", "13900000015")

    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    create_response = client.post(
        "/api/admin/assignments",
        json={
            "quiz_key": "assign-ignore-timing-demo",
            "candidate_id": candidate_id,
            "invite_start_date": "2026-04-01",
            "invite_end_date": "2026-04-02",
            "ignore_timing": True,
        },
    )

    assert create_response.status_code == 201
    token = create_response.json()["token"]
    assignment = get_assignment_record(token)
    assert assignment is not None
    assert assignment["ignore_timing"] is True
    assert assignment["time_limit_seconds"] == 0
    assert assignment["min_submit_seconds"] == 0

    list_response = client.get("/api/admin/assignments")
    assert list_response.status_code == 200
    item = next(it for it in list_response.json()["items"] if it["token"] == token)
    assert item["ignore_timing"] is True

    detail_response = client.get(f"/api/admin/attempts/{token}")
    assert detail_response.status_code == 200
    assert detail_response.json()["assignment"]["ignore_timing"] is True
    assert detail_response.json()["quiz_paper"]["ignore_timing"] is True


def test_admin_create_assignment_can_ignore_timing_for_zero_time_quiz(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    _seed_exam_without_answer_time("assign-zero-time-ignore-demo")
    candidate_id = create_candidate("零时长候选人", "13900000016")

    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    response = client.post(
        "/api/admin/assignments",
        json={
            "quiz_key": "assign-zero-time-ignore-demo",
            "candidate_id": candidate_id,
            "invite_start_date": "2026-04-01",
            "invite_end_date": "2026-04-02",
            "ignore_timing": True,
        },
    )

    assert response.status_code == 201
    assignment = get_assignment_record(response.json()["token"])
    assert assignment is not None
    assert assignment["ignore_timing"] is True
    assert assignment["time_limit_seconds"] == 0


def test_admin_create_assignment_rejects_zero_time_quiz_without_ignore_timing(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    _seed_exam_without_answer_time("assign-zero-time-reject-demo")
    candidate_id = create_candidate("零时长拒绝候选人", "13900000017")

    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    response = client.post(
        "/api/admin/assignments",
        json={
            "quiz_key": "assign-zero-time-reject-demo",
            "candidate_id": candidate_id,
            "invite_start_date": "2026-04-01",
            "invite_end_date": "2026-04-02",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "测验缺少有效的题目答题时长配置"


def test_admin_attempt_detail_exposes_review_answers_and_evaluation(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_review_content("attempt-review-demo")
    candidate_id = create_candidate("答题回放候选人", "13900000024")
    token = "attemptreview01"
    now = datetime.now(timezone.utc).isoformat()
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": "attempt-review-demo",
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "finished",
            "status_updated_at": now,
            "invite_window": {"start_date": "2026-04-01", "end_date": "2026-04-03"},
            "timing": {"start_at": now, "end_at": now},
            "answers": {
                "Q1": "A",
                "Q2": ["A"],
                "Q3": "我会先确认目标，再拆分步骤并验证结果。",
                "Q4": "A",
            },
            "candidate_remark": "表达清晰，建议补充结构化细节。",
            "grading": {
                "status": "done",
                "result_mode": "mixed",
                "total": 9,
                "total_max": 21,
                "final_analysis": "综合分析：客观题基础扎实，开放题有一定思路。",
                "traits": {
                    "question_count": 1,
                    "primary_dimensions": ["I"],
                    "paired_dimensions": [
                        {
                            "left": "I",
                            "right": "E",
                            "winner": "I",
                            "left_score": 2,
                            "right_score": 0,
                            "diff": 2,
                            "description": "观察更偏向独立推进还是外向协作。",
                        }
                    ],
                    "dimension_list": [
                        {"dimension": "I", "score": 2, "meaning": "偏独立推进"},
                        {"dimension": "E", "score": 0, "meaning": "偏外向协作"},
                    ],
                },
            },
        },
    )
    create_quiz_paper(
        candidate_id=candidate_id,
        phone="13900000024",
        quiz_key="attempt-review-demo",
        quiz_version_id=version_id,
        token=token,
        source_kind="direct",
        invite_start_date="2026-04-01",
        invite_end_date="2026-04-03",
        status="finished",
    )
    save_quiz_archive(
        archive_name="archive-attemptreview01",
        token=token,
        candidate_id=candidate_id,
        quiz_key="attempt-review-demo",
        quiz_version_id=version_id,
        phone="13900000024",
        archive={
            "token": token,
            "exam": {
                "quiz_key": "attempt-review-demo",
                "quiz_version_id": version_id,
                "title": "答题回放演示",
            },
            "timing": {"start_at": now, "end_at": now},
            "total_score": 9,
            "score_max": 21,
            "result_mode": "mixed",
            "traits": {
                "question_count": 1,
                "primary_dimensions": ["I"],
                "paired_dimensions": [
                    {
                        "left": "I",
                        "right": "E",
                        "winner": "I",
                        "left_score": 2,
                        "right_score": 0,
                        "diff": 2,
                        "description": "观察更偏向独立推进还是外向协作。",
                    }
                ],
                "dimension_list": [
                    {"dimension": "I", "score": 2, "meaning": "偏独立推进"},
                    {"dimension": "E", "score": 0, "meaning": "偏外向协作"},
                ],
            },
            "final_analysis": "综合分析：客观题基础扎实，开放题有一定思路。",
            "candidate_remark": "表达清晰，建议补充结构化细节。",
            "questions": [
                {
                    "qid": "Q1",
                    "type": "single",
                    "max_points": 5,
                    "stem_md": "**选择正确答案**",
                    "options": [
                        {"key": "A", "text": "错误答案", "correct": False},
                        {"key": "B", "text": "正确答案", "correct": True},
                    ],
                    "answer": "A",
                    "score": 0,
                    "score_max": 5,
                },
                {
                    "qid": "Q2",
                    "type": "multiple",
                    "max_points": 6,
                    "stem_md": "选择所有正确选项",
                    "options": [
                        {"key": "A", "text": "选项 A", "correct": True},
                        {"key": "B", "text": "选项 B", "correct": True},
                        {"key": "C", "text": "选项 C", "correct": False},
                    ],
                    "answer": ["A"],
                    "score": 3,
                    "score_max": 6,
                },
                {
                    "qid": "Q3",
                    "type": "short",
                    "max_points": 10,
                    "stem_md": "请说明你会如何拆解问题。",
                    "rubric": "提到分析现状和制定计划。",
                    "answer": "我会先确认目标，再拆分步骤并验证结果。",
                    "score": 6,
                    "score_max": 10,
                    "reason": "覆盖了目标确认和执行步骤，但缺少风险控制。",
                },
                {
                    "qid": "Q4",
                    "type": "single",
                    "max_points": 0,
                    "stem_md": "你更偏好哪种工作方式？",
                    "options": [
                        {"key": "A", "text": "独立推进"},
                        {"key": "B", "text": "频繁讨论"},
                    ],
                    "answer": "A",
                    "score": None,
                    "score_max": 0,
                },
            ],
        },
    )
    _admin_login(client)

    response = client.get(f"/api/admin/attempts/{token}")

    assert response.status_code == 200
    payload = response.json()
    review = payload["review"]
    assert len(review["answers"]) == 4

    single = review["answers"][0]
    assert single["label"] == "Q1 单选"
    assert "<strong>选择正确答案</strong>" in single["stem_html"]
    assert single["correct_options"] == ["B"]
    assert single["selected_options"] == ["A"]
    assert single["is_correct"] is False
    assert single["is_partial"] is False

    multiple = review["answers"][1]
    assert multiple["correct_options"] == ["A", "B"]
    assert multiple["selected_options"] == ["A"]
    assert multiple["is_correct"] is False
    assert multiple["is_partial"] is True

    short = review["answers"][2]
    assert short["score"] == 6
    assert short["score_max"] == 10
    assert short["reason"] == "覆盖了目标确认和执行步骤，但缺少风险控制。"
    assert short["rubric"] == "提到分析现状和制定计划。"
    assert "<p>提到分析现状和制定计划。</p>" in short["rubric_html"]
    assert "<p>请说明你会如何拆解问题。</p>" in short["stem_html"]

    traits = review["answers"][3]
    assert traits["review_kind"] == "traits"
    assert traits["is_trait_question"] is True
    assert traits["selected_options"] == ["A"]
    assert traits["options"][0]["traits"] == {"I": 2}

    evaluation = review["evaluation"]
    assert evaluation["result_mode"] == "mixed"
    assert evaluation["result_mode_label"] == "计分 + 量表"
    assert evaluation["total_score"] == 9
    assert evaluation["score_max"] == 21
    assert evaluation["final_analysis"] == "综合分析：客观题基础扎实，开放题有一定思路。"
    assert evaluation["candidate_remark"] == "表达清晰，建议补充结构化细节。"
    assert evaluation["primary_dimensions"] == ["I"]


def test_admin_assignments_list_exposes_invite_urls_and_end_date_filters(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("assignment-list-demo")
    candidate_a = create_candidate("候选人甲", "13900000011")
    candidate_b = create_candidate("候选人乙", "13900000012")
    create_quiz_paper(
        candidate_id=candidate_a,
        phone="13900000011",
        quiz_key="assignment-list-demo",
        quiz_version_id=version_id,
        token="assignA001",
        invite_start_date="2026-04-01",
        invite_end_date="2026-04-03",
        status="invited",
    )
    create_quiz_paper(
        candidate_id=candidate_b,
        phone="13900000012",
        quiz_key="assignment-list-demo",
        quiz_version_id=version_id,
        token="assignB001",
        invite_start_date="2026-05-08",
        invite_end_date="2026-05-10",
        status="verified",
    )

    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    response = client.get("/api/admin/assignments?end_from=2026-05-01&end_to=2026-05-31")

    assert response.status_code == 200
    payload = response.json()
    assert payload["filters"]["end_from"] == "2026-05-01"
    assert payload["filters"]["end_to"] == "2026-05-31"
    assert payload["summary"]["unhandled_finished_count"] == 0
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["token"] == "assignB001"
    assert item["url"] == "http://testserver/t/assignB001"
    assert item["qr_url"] == "/api/admin/assignments/assignB001/qr.png"
    assert item["invite_end_date"] == "2026-05-10"
    assert item["source_kind"] == "direct"
    assert item["source_label"] == "主动邀约"
    assert item["needs_attention"] is False


def test_public_invite_only_enters_admin_list_after_verify_and_marks_public_source(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    _seed_exam_with_metadata("public-source-demo")
    set_exam_public_invite("public-source-demo", enabled=True, token="public-source-token")

    ensure_response = client.post("/api/public/invites/public-source-token/ensure")

    assert ensure_response.status_code == 200
    token = ensure_response.json()["token"]
    assignment = get_assignment_record(token)
    assert assignment is not None
    assert assignment["require_phone_verification"] is True
    assert get_quiz_paper_by_token(token) is None

    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    before_verify = client.get("/api/admin/assignments")
    assert before_verify.status_code == 200
    assert before_verify.json()["items"] == []

    create_candidate("公开候选人", "13900000021")
    assignment = get_assignment_record(token)
    assert assignment is not None
    assignment["sms_verify"] = {
        "verified": True,
        "phone": "13900000021",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    save_assignment_record(token, assignment)

    verify_response = client.post(
        "/api/public/verify",
        json={"token": token, "name": "公开候选人", "phone": "13900000021"},
    )

    assert verify_response.status_code == 200
    assert verify_response.json()["redirect"] == f"/quiz/{token}"
    quiz_paper = get_quiz_paper_by_token(token)
    assert quiz_paper is not None
    assert quiz_paper["source_kind"] == "public"
    assert quiz_paper["status"] == "verified"

    after_verify = client.get("/api/admin/assignments")
    assert after_verify.status_code == 200
    items = after_verify.json()["items"]
    assert len(items) == 1
    assert items[0]["token"] == token
    assert items[0]["source_kind"] == "public"
    assert items[0]["source_label"] == "公开邀约"
    assert items[0]["require_phone_verification"] is True


def test_phone_verification_send_and_verify_use_aliyun_pnvs(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("phone-verify-direct-demo")
    candidate_id = create_candidate("短信认证候选人", "13900000022")
    token = "smsverify01"
    now = datetime.now(timezone.utc).isoformat()
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": "phone-verify-direct-demo",
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "invited",
            "status_updated_at": now,
            "invite_window": {"start_date": None, "end_date": None},
            "time_limit_seconds": 7200,
            "min_submit_seconds": 3600,
            "require_phone_verification": True,
            "verify_max_attempts": 3,
            "pass_threshold": 60,
            "verify": {"attempts": 0, "locked": False},
            "timing": {"start_at": None, "end_at": None},
            "answers": {},
            "grading_started_at": None,
            "graded_at": None,
            "grading_error": None,
            "grading": None,
        },
    )
    monkeypatch.setattr(
        public_api.deps,
        "send_sms_verify_code",
        lambda phone: {"Success": True, "Code": "OK", "Message": "", "Model": {"BizId": "biz-001"}},
    )
    monkeypatch.setattr(
        public_api.deps,
        "check_sms_verify_code",
        lambda phone, code: {"Success": True, "Code": "OK", "Message": "", "Model": {}},
    )

    send_response = client.post(
        "/api/public/sms/send",
        json={"token": token, "name": "短信认证候选人", "phone": "13900000022"},
    )

    assert send_response.status_code == 200
    assignment = get_assignment_record(token)
    assert assignment is not None
    sms_verify = assignment["sms_verify"]
    assert sms_verify["phone"] == "13900000022"
    assert sms_verify["verified"] is False
    assert sms_verify["send_count"] == 1
    assert sms_verify["biz_id"] == "biz-001"
    assert "expires_at" not in sms_verify
    assert "code_salt" not in sms_verify
    assert "code_hash" not in sms_verify

    verify_response = client.post(
        "/api/public/verify",
        json={"token": token, "name": "短信认证候选人", "phone": "13900000022", "sms_code": "1234"},
    )

    assert verify_response.status_code == 200
    assert verify_response.json()["redirect"] == f"/quiz/{token}"
    assignment = get_assignment_record(token)
    assert assignment is not None
    assert assignment["sms_verify"]["verified"] is True
    assert assignment["sms_verify"]["verified_at"]
    quiz_paper = get_quiz_paper_by_token(token)
    assert quiz_paper is not None
    assert quiz_paper["source_kind"] == "direct"
    assert quiz_paper["status"] == "verified"


def test_phone_verification_send_rejects_repeat_within_cooldown(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("phone-verify-cooldown-demo")
    candidate_id = create_candidate("短信冷却候选人", "13900000026")
    token = "smscooldown01"
    now = datetime.now(timezone.utc).isoformat()
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": "phone-verify-cooldown-demo",
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "invited",
            "status_updated_at": now,
            "invite_window": {"start_date": None, "end_date": None},
            "time_limit_seconds": 120,
            "min_submit_seconds": 0,
            "require_phone_verification": True,
            "verify_max_attempts": 3,
            "pass_threshold": 60,
            "verify": {"attempts": 0, "locked": False},
            "timing": {"start_at": None, "end_at": None},
            "answers": {},
            "grading_started_at": None,
            "graded_at": None,
            "grading_error": None,
            "grading": None,
        },
    )
    send_calls: list[str] = []

    def _fake_send(phone: str) -> dict[str, object]:
        send_calls.append(phone)
        return {"Success": True, "Code": "OK", "Message": "", "Model": {"BizId": "biz-003"}}

    monkeypatch.setattr(public_api.deps, "send_sms_verify_code", _fake_send)

    first_response = client.post(
        "/api/public/sms/send",
        json={"token": token, "name": "短信冷却候选人", "phone": "13900000026"},
    )
    second_response = client.post(
        "/api/public/sms/send",
        json={"token": token, "name": "短信冷却候选人", "phone": "13900000026"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert re.fullmatch(r"请 \d+ 秒后再试", second_response.json()["detail"])
    assert send_calls == ["13900000026"]
    assignment = get_assignment_record(token)
    assert assignment is not None
    assert assignment["sms_verify"]["send_count"] == 1


def test_direct_phone_verification_accepts_code_only_payload(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("phone-verify-code-only-demo")
    candidate_id = create_candidate("验证码候选人", "13900000023")
    token = "smscodeonly01"
    now = datetime.now(timezone.utc).isoformat()
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": "phone-verify-code-only-demo",
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "invited",
            "status_updated_at": now,
            "invite_window": {"start_date": None, "end_date": None},
            "time_limit_seconds": 120,
            "min_submit_seconds": 0,
            "require_phone_verification": True,
            "verify_max_attempts": 3,
            "pass_threshold": 60,
            "verify": {"attempts": 0, "locked": False},
            "question_flow": {"current_index": 0, "current_started_at": None, "reentry_count": 0},
            "timing": {"start_at": None, "end_at": None},
            "answers": {},
            "grading_started_at": None,
            "graded_at": None,
            "grading_error": None,
            "grading": None,
        },
    )
    monkeypatch.setattr(
        public_api.deps,
        "send_sms_verify_code",
        lambda phone: {"Success": True, "Code": "OK", "Message": "", "Model": {"BizId": "biz-002"}},
    )
    monkeypatch.setattr(
        public_api.deps,
        "check_sms_verify_code",
        lambda phone, code: {"Success": True, "Code": "OK", "Message": "", "Model": {}},
    )

    send_response = client.post("/api/public/sms/send", json={"token": token})
    assert send_response.status_code == 200
    assert send_response.json()["masked_phone"] == "139****0023"

    verify_response = client.post("/api/public/verify", json={"token": token, "sms_code": "1234"})
    assert verify_response.status_code == 200
    assert verify_response.json()["redirect"] == f"/quiz/{token}"
    assignment = get_assignment_record(token)
    assert assignment is not None
    assert assignment["sms_verify"]["verified"] is True


def test_phone_verification_rejects_non_four_digit_code(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("phone-verify-invalid-code-demo")
    candidate_id = create_candidate("验证码长度候选人", "13900000027")
    token = "smscodeinvalid01"
    now = datetime.now(timezone.utc).isoformat()
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": "phone-verify-invalid-code-demo",
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "invited",
            "status_updated_at": now,
            "invite_window": {"start_date": None, "end_date": None},
            "time_limit_seconds": 120,
            "min_submit_seconds": 0,
            "require_phone_verification": True,
            "verify_max_attempts": 3,
            "pass_threshold": 60,
            "verify": {"attempts": 0, "locked": False},
            "question_flow": {"current_index": 0, "current_started_at": None, "reentry_count": 0},
            "timing": {"start_at": None, "end_at": None},
            "answers": {},
            "grading_started_at": None,
            "graded_at": None,
            "grading_error": None,
            "grading": None,
        },
    )
    monkeypatch.setattr(
        public_api.deps,
        "send_sms_verify_code",
        lambda phone: {"Success": True, "Code": "OK", "Message": "", "Model": {"BizId": "biz-004"}},
    )
    check_calls: list[tuple[str, str]] = []

    def _fake_check(phone: str, code: str) -> dict[str, object]:
        check_calls.append((phone, code))
        return {"Success": True, "Code": "OK", "Message": "", "Model": {}}

    monkeypatch.setattr(public_api.deps, "check_sms_verify_code", _fake_check)

    send_response = client.post("/api/public/sms/send", json={"token": token})
    assert send_response.status_code == 200

    verify_response = client.post("/api/public/verify", json={"token": token, "sms_code": "12345"})

    assert verify_response.status_code == 400
    assert verify_response.json()["detail"] == "请输入 4 位数字验证码"
    assert check_calls == []


def test_public_quiz_linear_flow_rejects_backtracking_and_submits_on_last_question(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_answer_time("linear-flow-demo")
    candidate_id = create_candidate("线性作答候选人", "13900000024")
    token = "linearflow01"
    now = datetime.now(timezone.utc).isoformat()
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": "linear-flow-demo",
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "verified",
            "status_updated_at": now,
            "invite_window": {"start_date": None, "end_date": None},
            "time_limit_seconds": 150,
            "min_submit_seconds": 0,
            "verify_max_attempts": 3,
            "pass_threshold": 60,
            "verify": {"attempts": 0, "locked": False},
            "sms_verify": {"verified": True, "phone": "13900000024"},
            "question_flow": {
                "current_index": 0,
                "current_started_at": None,
                "reentry_count": 0,
                "active_session_id": "",
                "last_session_seen_at": "",
            },
            "timing": {"start_at": None, "end_at": None},
            "answers": {},
            "grading_started_at": None,
            "graded_at": None,
            "grading_error": None,
            "grading": None,
        },
    )

    enter_response = client.post(
        f"/api/public/attempt/{token}/enter",
        headers={"X-Public-Session-Id": "sess-linear-1"},
    )
    assert enter_response.status_code == 200
    assert enter_response.json()["quiz"]["question_flow"]["current_index"] == 0

    q1_response = client.post(
        f"/api/public/answers/{token}",
        json={"question_id": "Q1", "answer": "A", "advance": True, "session_id": "sess-linear-1"},
    )
    assert q1_response.status_code == 200
    assert q1_response.json()["step"] == "quiz"
    assert q1_response.json()["quiz"]["question_flow"]["current_index"] == 1

    stale_response = client.post(
        f"/api/public/answers/{token}",
        json={"question_id": "Q1", "answer": "A", "advance": True, "session_id": "sess-linear-1"},
    )
    assert stale_response.status_code == 409
    assert stale_response.json()["detail"] == "question_locked"

    q2_response = client.post(
        f"/api/public/answers/{token}",
        json={"question_id": "Q2", "answer": ["A"], "advance": True, "session_id": "sess-linear-1"},
    )
    assert q2_response.status_code == 200
    assert q2_response.json()["quiz"]["question_flow"]["current_index"] == 2

    q3_response = client.post(
        f"/api/public/answers/{token}",
        json={"question_id": "Q3", "answer": "最后一题答案", "submit": True, "session_id": "sess-linear-1"},
    )
    assert q3_response.status_code == 200
    assert q3_response.json()["step"] == "done"
    assignment = get_assignment_record(token)
    assert assignment is not None
    assert assignment["grading"]["status"] in {"pending", "running", "done"}


def test_public_attempt_ignore_timing_zeroes_timer_fields_and_keeps_manual_flow(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_answer_time("ignore-timing-flow-demo")
    candidate_id = create_candidate("不限时作答候选人", "13900000026")
    old_time = datetime(2026, 4, 1, tzinfo=timezone.utc).isoformat()
    token = "ignoretimer01"
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": "ignore-timing-flow-demo",
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": old_time,
            "status": "in_quiz",
            "status_updated_at": old_time,
            "invite_window": {"start_date": None, "end_date": None},
            "time_limit_seconds": 150,
            "min_submit_seconds": 60,
            "ignore_timing": True,
            "verify_max_attempts": 3,
            "verify": {"attempts": 0, "locked": False},
            "sms_verify": {"verified": True, "phone": "13900000026"},
            "question_flow": {
                "current_index": 0,
                "current_started_at": old_time,
                "reentry_count": 0,
                "active_session_id": "",
                "last_session_seen_at": "",
            },
            "timing": {"start_at": old_time, "end_at": None},
            "answers": {},
            "grading_started_at": None,
            "graded_at": None,
            "grading_error": None,
            "grading": None,
        },
    )

    bootstrap = client.get(f"/api/public/attempt/{token}", headers={"X-Public-Session-Id": "sess-ignore-1"})

    assert bootstrap.status_code == 200
    payload = bootstrap.json()
    assert payload["step"] == "quiz"
    assert payload["assignment"]["ignore_timing"] is True
    assert payload["quiz"]["remaining_seconds"] == 0
    assert payload["quiz"]["time_limit_seconds"] == 0
    assert payload["quiz"]["question_flow"]["current_question_seconds"] == 0
    assert payload["quiz"]["question_flow"]["current_question_remaining_seconds"] == 0

    q1_response = client.post(
        f"/api/public/answers/{token}",
        json={"question_id": "Q1", "answer": "A", "advance": True, "session_id": "sess-ignore-1"},
    )

    assert q1_response.status_code == 200
    assert q1_response.json()["step"] == "quiz"
    assert q1_response.json()["quiz"]["question_flow"]["current_index"] == 1
    assignment = get_assignment_record(token)
    assert assignment is not None
    assert assignment["grading"] is None
    assert assignment["time_limit_seconds"] == 0
    assert assignment["min_submit_seconds"] == 0


def test_public_quiz_reentry_limit_counts_only_cross_session(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_answer_time("reentry-limit-demo")
    candidate_id = create_candidate("重进限制候选人", "13900000025")
    token = "reentry001"
    now = datetime.now(timezone.utc).isoformat()
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": "reentry-limit-demo",
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "verified",
            "status_updated_at": now,
            "invite_window": {"start_date": None, "end_date": None},
            "time_limit_seconds": 150,
            "min_submit_seconds": 0,
            "verify_max_attempts": 3,
            "pass_threshold": 60,
            "verify": {"attempts": 0, "locked": False},
            "sms_verify": {"verified": True, "phone": "13900000025"},
            "question_flow": {
                "current_index": 0,
                "current_started_at": None,
                "reentry_count": 0,
                "active_session_id": "",
                "last_session_seen_at": "",
            },
            "timing": {"start_at": None, "end_at": None},
            "answers": {},
            "grading_started_at": None,
            "graded_at": None,
            "grading_error": None,
            "grading": None,
        },
    )

    client.post(f"/api/public/attempt/{token}/enter", headers={"X-Public-Session-Id": "sess-r-1"})

    same_session = client.get(f"/api/public/attempt/{token}", headers={"X-Public-Session-Id": "sess-r-1"})
    assert same_session.status_code == 200
    assert same_session.json()["quiz"]["question_flow"]["reentry_count"] == 0

    final_payload = None
    for index in range(2, 8):
        response = client.get(f"/api/public/attempt/{token}", headers={"X-Public-Session-Id": f"sess-r-{index}"})
        assert response.status_code == 200
        final_payload = response.json()

    assert final_payload is not None
    assert final_payload["step"] == "done"


def test_public_resume_upload_creates_public_quiz_paper_when_candidate_missing(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("public-resume-demo")
    _stub_public_resume_parsing(monkeypatch, parsed_name="待建档候选人", parsed_phone="13900000031")
    token = "publicresume001"
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": "public-resume-demo",
            "quiz_version_id": version_id,
            "candidate_id": 0,
            "status": "resume_pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "invite_window": {"start_date": "", "end_date": ""},
            "public_invite": {
                "token": "public-resume-token",
                "quiz_key": "public-resume-demo",
                "quiz_version_id": version_id,
            },
            "sms_verify": {
                "verified": True,
                "phone": "13900000031",
                "verified_at": datetime.now(timezone.utc).isoformat(),
            },
            "pending_profile": {"name": "待建档候选人", "phone": "13900000031"},
        },
    )

    response = client.post(
        f"/api/public/resume/upload?token={token}",
        files={"file": ("resume.pdf", b"%PDF-1.4 test", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["redirect"] == f"/quiz/{token}"
    quiz_paper = get_quiz_paper_by_token(token)
    assert quiz_paper is not None
    assert quiz_paper["source_kind"] == "public"
    assert quiz_paper["status"] == "verified"


def test_admin_assignment_handling_summary_toggle_and_detail(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("handling-demo")
    candidate_a = create_candidate("待处理候选人", "13900000041")
    candidate_b = create_candidate("处理中候选人", "13900000042")
    create_quiz_paper(
        candidate_id=candidate_a,
        phone="13900000041",
        quiz_key="handling-demo",
        quiz_version_id=version_id,
        token="handleA001",
        source_kind="public",
        invite_start_date="2026-04-01",
        invite_end_date="2026-04-02",
        status="finished",
    )
    create_quiz_paper(
        candidate_id=candidate_b,
        phone="13900000042",
        quiz_key="handling-demo",
        quiz_version_id=version_id,
        token="handleB001",
        source_kind="direct",
        invite_start_date="2026-04-01",
        invite_end_date="2026-04-02",
        status="grading",
    )

    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    list_response = client.get("/api/admin/assignments")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["summary"]["unhandled_finished_count"] == 1
    by_token = {item["token"]: item for item in payload["items"]}
    assert by_token["handleA001"]["needs_attention"] is True
    assert by_token["handleA001"]["source_kind"] == "public"
    assert by_token["handleB001"]["needs_attention"] is False

    detail_before = client.get("/api/admin/attempts/handleA001")
    assert detail_before.status_code == 200
    assert detail_before.json()["quiz_paper"]["needs_attention"] is True
    assert detail_before.json()["quiz_paper"]["handled_at"] == ""

    handled_response = client.post("/api/admin/assignments/handleA001/handling", json={"handled": True})
    assert handled_response.status_code == 200
    handled_item = handled_response.json()["item"]
    assert handled_item["needs_attention"] is False
    assert handled_item["handled_by"] == "admin"
    assert handled_item["handled_at"] != ""

    list_after_handle = client.get("/api/admin/assignments")
    assert list_after_handle.status_code == 200
    assert list_after_handle.json()["summary"]["unhandled_finished_count"] == 0

    detail_after_handle = client.get("/api/admin/attempts/handleA001")
    assert detail_after_handle.status_code == 200
    assert detail_after_handle.json()["quiz_paper"]["needs_attention"] is False
    assert detail_after_handle.json()["quiz_paper"]["handled_by"] == "admin"

    unhandled_response = client.post("/api/admin/assignments/handleA001/handling", json={"handled": False})
    assert unhandled_response.status_code == 200
    unhandled_item = unhandled_response.json()["item"]
    assert unhandled_item["needs_attention"] is True
    assert unhandled_item["handled_at"] == ""
    assert unhandled_item["handled_by"] == ""

    list_after_unhandle = client.get("/api/admin/assignments")
    assert list_after_unhandle.status_code == 200
    assert list_after_unhandle.json()["summary"]["unhandled_finished_count"] == 1


def test_admin_can_delete_unstarted_assignment(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("assignment-delete-demo")
    candidate_id = create_candidate("待删除邀约", "13900000022")
    now = datetime.now(timezone.utc).isoformat()
    token = "deleteA001"
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": "assignment-delete-demo",
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "invited",
            "invite_window": {"start_date": "2026-04-01", "end_date": "2026-04-03"},
            "timing": {"start_at": None, "end_at": None},
        },
    )
    create_quiz_paper(
        candidate_id=candidate_id,
        phone="13900000022",
        quiz_key="assignment-delete-demo",
        quiz_version_id=version_id,
        token=token,
        source_kind="direct",
        invite_start_date="2026-04-01",
        invite_end_date="2026-04-03",
        status="invited",
    )
    _admin_login(client)

    response = client.delete(f"/api/admin/assignments/{token}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"]["quiz_archive"] == 0
    assert payload["deleted"]["assignment_record"] == 1
    assert payload["deleted"]["quiz_paper"] == 1
    assert get_assignment_record(token) is None
    assert get_quiz_archive_by_token(token) is None
    assert get_quiz_paper_by_token(token) is None


def test_admin_can_delete_finished_assignment_and_archive(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    version_id = _seed_exam_with_metadata("assignment-delete-guard-demo")
    candidate_id = create_candidate("已完成邀约", "13900000023")
    now = datetime.now(timezone.utc).isoformat()
    token = "deleteA002"
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": "assignment-delete-guard-demo",
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "finished",
            "timing": {"start_at": now, "end_at": now},
        },
    )
    create_quiz_paper(
        candidate_id=candidate_id,
        phone="13900000023",
        quiz_key="assignment-delete-guard-demo",
        quiz_version_id=version_id,
        token=token,
        source_kind="direct",
        invite_start_date="2026-04-01",
        invite_end_date="2026-04-03",
        status="finished",
    )
    save_quiz_archive(
        archive_name="archive-deleteA002",
        token=token,
        candidate_id=candidate_id,
        quiz_key="assignment-delete-guard-demo",
        quiz_version_id=version_id,
        phone="13900000023",
        archive={
            "token": token,
            "exam": {"quiz_key": "assignment-delete-guard-demo", "title": "人格类型测试"},
            "timing": {"start_at": now, "end_at": now},
            "total_score": 88,
        },
    )
    _admin_login(client)

    response = client.delete(f"/api/admin/assignments/{token}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"]["quiz_archive"] == 1
    assert payload["deleted"]["assignment_record"] == 1
    assert payload["deleted"]["quiz_paper"] == 1
    assert get_assignment_record(token) is None
    assert get_quiz_archive_by_token(token) is None
    assert get_quiz_paper_by_token(token) is None
    assert get_candidate(candidate_id) is not None

    candidate_detail = client.get(f"/api/admin/candidates/{candidate_id}")
    assert candidate_detail.status_code == 200
    assert candidate_detail.json()["profile"]["attempt_results"] == []


def test_exam_repo_binding_persists_and_auto_enqueues_sync(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    response = client.post("/api/admin/quizzes/binding", json={"repo_url": "https://github.com/example/repo.git"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["binding"]["repo_url"] == "https://github.com/example/repo.git"
    assert payload["sync"]["created"] is True
    assert payload["sync"]["error"] == ""
    assert get_runtime_kv("exam_repo_binding")["repo_url"] == "https://github.com/example/repo.git"

    list_response = client.get("/api/admin/quizzes")
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

    response = client.post("/api/admin/quizzes/sync", json={"repo_url": "https://github.com/example/other.git"})

    assert response.status_code == 409
    assert "尚未绑定仓库" in response.json()["detail"]


def test_exam_repo_binding_rejects_second_bind(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    first = client.post("/api/admin/quizzes/binding", json={"repo_url": "https://github.com/example/repo.git"})
    assert first.status_code == 201

    second = client.post("/api/admin/quizzes/binding", json={"repo_url": "https://github.com/example/another.git"})

    assert second.status_code == 409
    assert "已绑定仓库" in second.json()["detail"]


def test_exam_repo_rebind_rejects_invalid_confirmation(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    _seed_exam_with_metadata("rebind-confirm-demo")
    _set_repo_binding("https://github.com/example/old.git")
    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    response = client.post(
        "/api/admin/quizzes/binding/rebind",
        json={"repo_url": "https://github.com/example/new.git", "confirmation_text": "错误确认"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "确认词不正确"
    assert get_runtime_kv("exam_repo_binding")["repo_url"] == "https://github.com/example/old.git"
    assert _count_rows("quiz_definition") == 1


def test_exam_repo_rebind_rejects_while_sync_busy(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    bind_response = client.post("/api/admin/quizzes/binding", json={"repo_url": "https://github.com/example/repo.git"})
    assert bind_response.status_code == 201

    rebind_response = client.post(
        "/api/admin/quizzes/binding/rebind",
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
            "quiz_key": "rebind-demo",
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "verified",
        },
    )
    create_quiz_paper(
        candidate_id=candidate_id,
        phone="13900000002",
        quiz_key="rebind-demo",
        quiz_version_id=version_id,
        token="paper-rebind-001",
    )
    save_quiz_archive(
        archive_name="archive-rebind-001",
        token="paper-rebind-001",
        candidate_id=candidate_id,
        quiz_key="rebind-demo",
        quiz_version_id=version_id,
        phone="13900000002",
        archive={"exam": {"quiz_key": "rebind-demo"}},
    )
    replace_quiz_assets("rebind-demo", {"assets/q1.png": (b"png", "image/png")})
    replace_quiz_version_assets(version_id, {"assets/q1.png": (b"png", "image/png")})
    _set_repo_binding("https://github.com/example/old.git")
    login_response = client.post("/api/admin/session/login", json={"username": "admin", "password": "password"})
    assert login_response.status_code == 200

    response = client.post(
        "/api/admin/quizzes/binding/rebind",
        json={"repo_url": "https://github.com/example/new.git", "confirmation_text": "重新绑定"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["binding"]["repo_url"] == "https://github.com/example/new.git"
    assert payload["previous_repo_url"] == "https://github.com/example/old.git"
    assert payload["cleanup"]["quiz_definition"] == 1
    assert payload["cleanup"]["quiz_version"] == 1
    assert payload["cleanup"]["assignment_record"] == 1
    assert payload["cleanup"]["quiz_paper"] == 1
    assert payload["cleanup"]["quiz_archive"] == 1
    assert payload["cleanup"]["quiz_asset"] == 1
    assert payload["cleanup"]["quiz_version_asset"] == 1
    assert payload["sync"]["created"] is True

    assert _count_rows("quiz_definition") == 0
    assert _count_rows("quiz_version") == 0
    assert _count_rows("assignment_record") == 0
    assert _count_rows("quiz_paper") == 0
    assert _count_rows("quiz_archive") == 0
    assert _count_rows("quiz_asset") == 0
    assert _count_rows("quiz_version_asset") == 0
    assert get_candidate(candidate_id)["name"] == "保留候选人"
    assert get_runtime_kv("exam_repo_binding")["repo_url"] == "https://github.com/example/new.git"

    list_response = client.get("/api/admin/quizzes")
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

    response = client.post("/api/admin/quizzes/sync", json={"repo_url": "https://github.com/example/ignored.git"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] is True

    jobs_response = client.get("/api/admin/jobs")
    assert jobs_response.status_code == 200
    items = jobs_response.json()["items"]
    assert len(items) == 1
    assert items[0]["payload"]["repo_url"] == "https://github.com/example/bound.git"


def test_system_bootstrap_exposes_mcp_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_ENABLED", "1")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-mcp-token")
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/api/system/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mcp"] == {
        "enabled": True,
        "path": "/mcp",
        "transport": "streamable-http",
        "auth_scheme": "bearer",
        "docs_path": "/docs/reference/mcp.md",
    }


def test_admin_mcp_route_returns_admin_spa(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/admin/mcp")

    assert response.status_code == 200
    assert "MD Quiz Admin" in response.text
