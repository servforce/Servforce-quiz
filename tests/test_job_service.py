from __future__ import annotations

from backend.md_quiz.models import JobRecord
from backend.md_quiz.services.exam_repo_sync_service import ExamRepoSyncError
from backend.md_quiz.services.job_service import JobService


class _FakeStore:
    def __init__(self) -> None:
        self.failed: list[tuple[str, str]] = []
        self.completed: list[tuple[str, dict | None]] = []

    def fail(self, job_id: str, error: str):
        self.failed.append((job_id, error))
        return {"id": job_id, "status": "failed", "error": error}

    def complete(self, job_id: str, result: dict | None = None):
        self.completed.append((job_id, result))
        return {"id": job_id, "status": "done", "result": result}


def test_process_marks_git_sync_job_failed_instead_of_raising(monkeypatch):
    def _boom(*args, **kwargs):
        raise ExamRepoSyncError("git clone 失败：Proxy CONNECT aborted")

    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.perform_exam_repo_sync", _boom)

    store = _FakeStore()
    service = JobService(store)  # type: ignore[arg-type]
    job = JobRecord(
        id="job-1",
        kind="git_sync_exams",
        payload={"repo_url": "https://example.com/repo.git"},
        created_at="2026-04-02T00:00:00+00:00",
        updated_at="2026-04-02T00:00:00+00:00",
    )

    result = service.process(job)

    assert result == {"id": "job-1", "status": "failed", "error": "git clone 失败：Proxy CONNECT aborted"}
    assert store.failed == [("job-1", "git clone 失败：Proxy CONNECT aborted")]
    assert store.completed == []
