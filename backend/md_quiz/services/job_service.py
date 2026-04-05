from __future__ import annotations

from time import sleep

from backend.md_quiz.config import logger
from backend.md_quiz.models import JobRecord
from backend.md_quiz.storage import JobStore


class JobService:
    def __init__(self, store: JobStore):
        self.store = store

    def list_jobs(self) -> list[JobRecord]:
        return self.store.list_jobs()

    def get_job(self, job_id: str) -> JobRecord | None:
        return self.store.get_job(job_id)

    def enqueue(
        self,
        kind: str,
        *,
        payload: dict | None = None,
        source: str = "manual",
        dedupe_key: str | None = None,
    ) -> JobRecord:
        return self.store.enqueue(kind, payload=payload, source=source, dedupe_key=dedupe_key)

    def ensure_grade_attempt(self, token: str, *, source: str = "runtime_jobs") -> JobRecord:
        normalized = str(token or "").strip()
        if not normalized:
            raise ValueError("缺少 token")
        return self.store.enqueue_unique(
            "grade_attempt",
            payload={"token": normalized},
            source=source,
            dedupe_key=f"grade_attempt:{normalized}",
        )

    def claim_next(self, worker_name: str) -> JobRecord | None:
        return self.store.claim_next(worker_name)

    def process(self, job: JobRecord) -> JobRecord | None:
        # 第一阶段只实现可验证的演示处理器；
        # 后续迁移真实业务时，再把旧 services/ 逐步接进来。
        try:
            match job.kind:
                case "git_sync_exams":
                    from backend.md_quiz.services.exam_repo_sync_service import perform_exam_repo_sync

                    repo_url = str((job.payload or {}).get("repo_url") or "").strip()
                    if not repo_url:
                        return self.store.fail(job.id, "缺少 repo_url")
                    result = perform_exam_repo_sync(repo_url, job_id=job.id)
                case "scan_exams":
                    result = {"message": "测验扫描任务已完成", "count": 0}
                case "admin_candidate_resume_upload":
                    from backend.md_quiz.services import candidate_resume_admin_service

                    result = candidate_resume_admin_service.process_candidate_resume_upload_job(job.payload or {})
                case "admin_candidate_resume_reparse":
                    from backend.md_quiz.services import candidate_resume_admin_service

                    result = candidate_resume_admin_service.process_candidate_resume_reparse_job(job.payload or {})
                case "resume_parse":
                    from backend.md_quiz.services.audit_context import audit_context, get_audit_context
                    from backend.md_quiz.services.resume_service import (
                        build_resume_parsed_payload,
                        parse_resume_all_llm,
                    )
                    from backend.md_quiz.services.system_log import log_event
                    from backend.md_quiz.storage.db import (
                        get_candidate,
                        get_candidate_resume,
                        update_candidate,
                        update_candidate_resume_parsed,
                    )

                    payload = job.payload or {}
                    candidate_id = int(payload.get("candidate_id") or 0)
                    expected_phone = str(payload.get("expected_phone") or "").strip()
                    token = str(payload.get("token") or "").strip()
                    quiz_key = str(payload.get("quiz_key") or "").strip()
                    if candidate_id <= 0:
                        return self.store.fail(job.id, "缺少 candidate_id")
                    resume = get_candidate_resume(candidate_id)
                    if not resume or not resume.get("resume_bytes"):
                        return self.store.fail(job.id, "候选人缺少简历文件")

                    with audit_context(meta={}):
                        parsed = parse_resume_all_llm(
                            data=resume.get("resume_bytes") or b"",
                            filename=str(resume.get("resume_filename") or ""),
                            mime=str(resume.get("resume_mime") or ""),
                        ) or {}
                        ctx = get_audit_context()
                        meta = ctx.get("meta") if isinstance(ctx, dict) else {}
                        llm_total_tokens = int(meta.get("llm_total_tokens_sum") or 0) if isinstance(meta, dict) else 0

                    built = build_resume_parsed_payload(
                        parsed,
                        filename=str(resume.get("resume_filename") or ""),
                        mime=str(resume.get("resume_mime") or ""),
                        current_phone=expected_phone,
                    )
                    parsed_phone = str(built.get("parsed_phone") or "").strip()
                    if expected_phone and parsed_phone and parsed_phone != expected_phone:
                        return self.store.fail(job.id, "简历手机号与验证手机号不一致")

                    update_candidate_resume_parsed(candidate_id, resume_parsed=built["resume_parsed"])

                    parsed_name = str(built.get("parsed_name") or "").strip()
                    if parsed_name:
                        current = get_candidate(candidate_id) or {}
                        current_name = str(current.get("name") or "").strip()
                        if current_name in {"", "未知"}:
                            update_candidate(candidate_id, name=parsed_name, phone=expected_phone or str(current.get("phone") or ""))

                    try:
                        log_event(
                            "candidate.resume.parse",
                            actor="system",
                            candidate_id=candidate_id,
                            quiz_key=(quiz_key or None),
                            token=(token or None),
                            llm_total_tokens=(llm_total_tokens or None),
                            meta={"public_invite": True},
                        )
                    except Exception:
                        logger.exception("Resume parse log failed: candidate_id=%s", candidate_id)

                    result = {
                        "message": "简历解析任务已完成",
                        "status": str(((built["resume_parsed"].get("details") or {}).get("status")) or "done"),
                        "candidate_id": candidate_id,
                    }
                case "grade_attempt":
                    from backend.md_quiz.services import runtime_jobs

                    token = str((job.payload or {}).get("token") or "").strip()
                    if not token:
                        return self.store.fail(job.id, "缺少 token")
                    result = runtime_jobs.process_grade_attempt_job(token)
                case "archive_attempt":
                    return self.store.fail(job.id, "archive_attempt 已并入 grade_attempt")
                case "sync_metrics":
                    result = {"message": "指标同步完成", "status": "ok"}
                case _:
                    return self.store.fail(job.id, f"不支持的任务类型: {job.kind}")
        except Exception as exc:
            logger.exception("Job failed: kind=%s id=%s", job.kind, job.id)
            return self.store.fail(job.id, str(exc) or type(exc).__name__)
        sleep(0.05)
        return self.store.complete(job.id, result)
