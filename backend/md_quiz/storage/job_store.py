from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from backend.md_quiz.models import JobRecord
from backend.md_quiz.storage.db import (
    claim_next_runtime_job,
    create_runtime_job,
    list_runtime_jobs,
    update_runtime_job,
    upsert_runtime_job,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class JobStore:
    def list_jobs(self) -> list[JobRecord]:
        return [JobRecord.model_validate(item) for item in list_runtime_jobs()]

    def enqueue(self, kind: str, *, payload: dict | None = None, source: str = "manual") -> JobRecord:
        now = _utc_now()
        job = JobRecord(
            id=str(uuid4()),
            kind=kind,
            payload=payload or {},
            source=source,
            created_at=now,
            updated_at=now,
        )
        return JobRecord.model_validate(create_runtime_job(job.model_dump()))

    def claim_next(self, worker_name: str) -> JobRecord | None:
        raw = claim_next_runtime_job(str(worker_name or "").strip(), started_at=_utc_now())
        return JobRecord.model_validate(raw) if raw else None

    def complete(self, job_id: str, result: dict | None = None) -> JobRecord | None:
        now = _utc_now()
        raw = update_runtime_job(
            str(job_id or "").strip(),
            status="done",
            result=result or {},
            error=None,
            finished_at=now,
            updated_at=now,
        )
        return JobRecord.model_validate(raw) if raw else None

    def fail(self, job_id: str, error: str) -> JobRecord | None:
        now = _utc_now()
        raw = update_runtime_job(
            str(job_id or "").strip(),
            status="failed",
            result=None,
            error=str(error or "").strip(),
            finished_at=now,
            updated_at=now,
        )
        return JobRecord.model_validate(raw) if raw else None

    def import_record(self, record: dict) -> JobRecord:
        return JobRecord.model_validate(upsert_runtime_job(dict(record or {})))


__all__ = ["JobStore"]
