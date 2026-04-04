from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import psycopg2
from psycopg2 import errorcodes

from backend.md_quiz.models import JobRecord
from backend.md_quiz.storage.db import (
    claim_next_runtime_job,
    create_runtime_job,
    get_active_runtime_job_by_dedupe_key,
    get_runtime_job,
    list_runtime_jobs,
    update_runtime_job,
    upsert_runtime_job,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class JobStore:
    def list_jobs(self) -> list[JobRecord]:
        return [JobRecord.model_validate(item) for item in list_runtime_jobs()]

    def get_job(self, job_id: str) -> JobRecord | None:
        raw = get_runtime_job(str(job_id or "").strip())
        return JobRecord.model_validate(raw) if raw else None

    def get_active_job_by_dedupe_key(self, dedupe_key: str) -> JobRecord | None:
        raw = get_active_runtime_job_by_dedupe_key(str(dedupe_key or "").strip())
        return JobRecord.model_validate(raw) if raw else None

    def enqueue(
        self,
        kind: str,
        *,
        payload: dict | None = None,
        source: str = "manual",
        dedupe_key: str | None = None,
    ) -> JobRecord:
        now = _utc_now()
        job = JobRecord(
            id=str(uuid4()),
            kind=kind,
            payload=payload or {},
            source=source,
            dedupe_key=(str(dedupe_key or "").strip() or None),
            created_at=now,
            updated_at=now,
        )
        return JobRecord.model_validate(create_runtime_job(job.model_dump()))

    def enqueue_unique(
        self,
        kind: str,
        *,
        payload: dict | None = None,
        source: str = "manual",
        dedupe_key: str,
    ) -> JobRecord:
        normalized = str(dedupe_key or "").strip()
        if not normalized:
            raise ValueError("dedupe_key 不能为空")

        existing = self.get_active_job_by_dedupe_key(normalized)
        if existing is not None:
            return existing

        try:
            return self.enqueue(kind, payload=payload, source=source, dedupe_key=normalized)
        except psycopg2.Error as exc:
            if getattr(exc, "pgcode", "") != errorcodes.UNIQUE_VIOLATION:
                raise
            existing = self.get_active_job_by_dedupe_key(normalized)
            if existing is None:
                raise
            return existing

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
            lease_expires_at=None,
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
            lease_expires_at=None,
            finished_at=now,
            updated_at=now,
        )
        return JobRecord.model_validate(raw) if raw else None

    def import_record(self, record: dict) -> JobRecord:
        return JobRecord.model_validate(upsert_runtime_job(dict(record or {})))


__all__ = ["JobStore"]
