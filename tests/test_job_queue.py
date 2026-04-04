from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.md_quiz.services.job_service import JobService
from backend.md_quiz.storage import JobStore
from backend.md_quiz.storage.db import (
    create_assignment_record,
    create_candidate,
    create_quiz_paper,
    create_quiz_version,
    get_assignment_record,
    get_quiz_archive_by_token,
    get_quiz_paper_by_token,
    save_quiz_definition,
)


def _seed_objective_exam(quiz_key: str) -> int:
    spec = {
        "id": quiz_key,
        "title": "单题判卷测试",
        "description": "用于后台任务链路测试。",
        "schema_version": 2,
        "format": "qml-v2",
        "trait": {},
        "questions": [
            {
                "qid": "Q1",
                "type": "single",
                "max_points": 5,
                "points": 5,
                "stem_md": "题目一",
                "options": [{"key": "A", "text": "选项A", "correct": True}],
            }
        ],
    }
    public_spec = {
        "id": quiz_key,
        "title": "单题判卷测试",
        "description": "用于后台任务链路测试。",
        "schema_version": 2,
        "format": "qml-v2",
        "trait": {},
        "questions": [
            {
                "qid": "Q1",
                "type": "single",
                "max_points": 5,
                "points": 5,
                "stem_md": "题目一",
                "options": [{"key": "A", "text": "选项A"}],
            }
        ],
    }
    version_id = create_quiz_version(
        quiz_key=quiz_key,
        version_no=1,
        title="单题判卷测试",
        source_path=f"quizzes/{quiz_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        git_commit="queue-job-001",
        content_hash=f"hash-{quiz_key}",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
    )
    save_quiz_definition(
        quiz_key=quiz_key,
        title="单题判卷测试",
        source_md="---\nid: test\n---\n",
        spec=spec,
        public_spec=public_spec,
        status="active",
        source_path=f"quizzes/{quiz_key}/quiz.md",
        git_repo_url="https://example.com/repo.git",
        current_version_id=version_id,
        current_version_no=1,
        last_synced_commit="queue-job-001",
        last_sync_error="",
        last_sync_at=datetime.now(timezone.utc),
    )
    return version_id


def _seed_grading_assignment(*, quiz_key: str, token: str, phone: str) -> None:
    version_id = _seed_objective_exam(quiz_key)
    candidate_id = create_candidate("任务判卷候选人", phone)
    now = datetime.now(timezone.utc).isoformat()
    create_assignment_record(
        token,
        {
            "token": token,
            "quiz_key": quiz_key,
            "quiz_version_id": version_id,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "grading",
            "status_updated_at": now,
            "invite_window": {"start_date": None, "end_date": None},
            "time_limit_seconds": 120,
            "min_submit_seconds": 0,
            "verify_max_attempts": 3,
            "verify": {"attempts": 0, "locked": False},
            "sms_verify": {"verified": True, "phone": phone},
            "question_flow": {
                "current_index": 0,
                "current_started_at": now,
                "reentry_count": 0,
                "active_session_id": "sess-job-1",
                "last_session_seen_at": now,
            },
            "timing": {"start_at": now, "end_at": now},
            "answers": {"Q1": "A"},
            "grading_started_at": now,
            "graded_at": None,
            "grading_error": None,
            "grading": {"status": "pending", "queued_at": now},
        },
    )
    create_quiz_paper(
        candidate_id=candidate_id,
        phone=phone,
        quiz_key=quiz_key,
        quiz_version_id=version_id,
        token=token,
        status="grading",
    )


def test_ensure_grade_attempt_reuses_same_active_job():
    service = JobService(JobStore())

    first = service.ensure_grade_attempt("dedupe-token-001", source="test")
    second = service.ensure_grade_attempt("dedupe-token-001", source="test")

    assert first.id == second.id
    assert first.dedupe_key == "grade_attempt:dedupe-token-001"

    claimed = service.claim_next("worker-a")
    assert claimed is not None
    assert claimed.id == first.id

    third = service.ensure_grade_attempt("dedupe-token-001", source="test")
    assert third.id == first.id
    assert len(JobStore().list_jobs()) == 1


def test_claim_next_prioritizes_pending_and_recovers_expired_running_job():
    store = JobStore()
    now = datetime.now(timezone.utc)
    earlier = (now - timedelta(minutes=20)).isoformat()
    past = (now - timedelta(minutes=5)).isoformat()
    future = (now + timedelta(minutes=5)).isoformat()

    store.import_record(
        {
            "id": "running-fresh",
            "kind": "sync_metrics",
            "source": "test",
            "status": "running",
            "payload": {},
            "attempts": 1,
            "worker_name": "old-worker",
            "created_at": earlier,
            "updated_at": earlier,
            "started_at": earlier,
            "lease_expires_at": future,
            "finished_at": None,
        }
    )
    assert store.claim_next("worker-a") is None

    store.import_record(
        {
            "id": "running-expired",
            "kind": "sync_metrics",
            "source": "test",
            "status": "running",
            "payload": {},
            "attempts": 1,
            "worker_name": "old-worker",
            "created_at": earlier,
            "updated_at": earlier,
            "started_at": earlier,
            "lease_expires_at": past,
            "finished_at": None,
        }
    )
    pending = store.enqueue("sync_metrics", source="test")

    claimed_pending = store.claim_next("worker-a")
    assert claimed_pending is not None
    assert claimed_pending.id == pending.id

    claimed_recovered = store.claim_next("worker-b")
    assert claimed_recovered is not None
    assert claimed_recovered.id == "running-expired"
    assert claimed_recovered.attempts == 2
    assert claimed_recovered.worker_name == "worker-b"
    assert claimed_recovered.lease_expires_at is not None
    assert datetime.fromisoformat(claimed_recovered.lease_expires_at) > now

    assert store.claim_next("worker-c") is None


def test_process_grade_attempt_job_persists_grading_archive_and_noops_when_replayed(monkeypatch):
    monkeypatch.setattr(
        "backend.md_quiz.services.grading_service.call_llm_text",
        lambda _prompt: "综合分析：表现稳定。建议继续保持。",
    )

    token = "grade-job-001"
    _seed_grading_assignment(quiz_key="job-grade-demo", token=token, phone="13900000111")
    service = JobService(JobStore())

    first = service.ensure_grade_attempt(token, source="test")
    claimed = service.claim_next("worker-grade-1")
    assert claimed is not None
    assert claimed.id == first.id

    processed = service.process(claimed)
    assert processed is not None
    assert processed.status == "done"
    assert processed.result == {
        "message": "判卷任务已完成",
        "status": "done",
        "token": token,
        "candidate_id": 1,
        "quiz_key": "job-grade-demo",
    }

    assignment = get_assignment_record(token)
    assert assignment is not None
    assert assignment["status"] == "graded"
    assert assignment["grading"]["status"] == "done"
    assert assignment["grading_error"] is None
    assert assignment["candidate_remark"] == "综合分析：表现稳定。建议继续保持。"

    paper = get_quiz_paper_by_token(token)
    assert paper is not None
    assert paper["status"] == "finished"
    assert int(paper["score"] or 0) == 5

    archive = get_quiz_archive_by_token(token)
    assert archive is not None
    assert archive["archive"]["grading"]["status"] == "done"
    assert archive["archive"]["candidate_remark"] == "综合分析：表现稳定。建议继续保持。"

    replay = service.enqueue("grade_attempt", payload={"token": token}, source="test-replay")
    claimed_replay = service.claim_next("worker-grade-2")
    assert claimed_replay is not None
    assert claimed_replay.id == replay.id

    replay_result = service.process(claimed_replay)
    assert replay_result is not None
    assert replay_result.status == "done"
    assert replay_result.result == {
        "message": "判卷任务跳过，结果已存在",
        "status": "noop",
        "token": token,
    }
