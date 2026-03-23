from __future__ import annotations

from time import sleep

from backend.md_quiz.models import JobRecord
from backend.md_quiz.storage import JsonJobStore


class JobService:
    def __init__(self, store: JsonJobStore):
        self.store = store

    def list_jobs(self) -> list[JobRecord]:
        return self.store.list_jobs()

    def enqueue(self, kind: str, *, payload: dict | None = None, source: str = "manual") -> JobRecord:
        return self.store.enqueue(kind, payload=payload, source=source)

    def claim_next(self, worker_name: str) -> JobRecord | None:
        return self.store.claim_next(worker_name)

    def process(self, job: JobRecord) -> JobRecord | None:
        # 第一阶段只实现可验证的演示处理器；
        # 后续迁移真实业务时，再把旧 services/ 逐步接进来。
        match job.kind:
            case "scan_exams":
                result = {"message": "试卷扫描任务已完成", "count": 0}
            case "resume_parse":
                result = {"message": "简历解析任务已完成", "status": "placeholder"}
            case "grade_attempt":
                result = {"message": "判卷任务已完成", "status": "placeholder"}
            case "archive_attempt":
                result = {"message": "归档任务已完成", "status": "placeholder"}
            case "sync_metrics":
                result = {"message": "指标同步完成", "status": "ok"}
            case _:
                return self.store.fail(job.id, f"不支持的任务类型: {job.kind}")
        sleep(0.05)
        return self.store.complete(job.id, result)
