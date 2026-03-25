from __future__ import annotations

from web.runtime_support import *
from services.exam_repo_sync_service import migrate_legacy_exam_data


class RuntimeBootstrapError(RuntimeError):
    """Raised when app bootstrap cannot prepare required runtime dependencies."""


def _ensure_exam_paper_for_token(token: str, assignment: dict) -> dict[str, Any] | None:
    """
    Ensure exam_paper exists for a token once candidate identity is available.
    """
    t = str(token or "").strip()
    if not t:
        return None
    try:
        ep = get_exam_paper_by_token(t)
    except Exception:
        ep = None
    if ep:
        return ep

    try:
        candidate_id = int(assignment.get("candidate_id") or 0)
    except Exception:
        candidate_id = 0
    if candidate_id <= 0:
        return None

    c = get_candidate(candidate_id) or {}
    exam_key = str(assignment.get("exam_key") or "").strip()
    try:
        exam_version_id = int(assignment.get("exam_version_id") or 0)
    except Exception:
        exam_version_id = 0
    phone = str(c.get("phone") or "").strip()
    if not exam_key or not phone:
        return None

    a_status = str(assignment.get("status") or "").strip()
    status_map = {
        "invited": "invited",
        "verified": "verified",
        "in_exam": "in_exam",
        "grading": "grading",
        "graded": "finished",
    }
    status = status_map.get(a_status, "invited")

    inv = assignment.get("invite_window") or {}
    if not isinstance(inv, dict):
        inv = {}
    invite_start_date = str(inv.get("start_date") or "").strip() or None
    invite_end_date = str(inv.get("end_date") or "").strip() or None

    try:
        create_exam_paper(
            candidate_id=candidate_id,
            phone=phone,
            exam_key=exam_key,
            exam_version_id=(exam_version_id or None),
            token=t,
            invite_start_date=invite_start_date,
            invite_end_date=invite_end_date,
            status=status,
        )
    except Exception:
        pass
    try:
        return get_exam_paper_by_token(t)
    except Exception:
        return None


def _start_auto_collect_thread(app: Flask) -> None:
    if os.getenv("ENABLE_AUTO_COLLECT", "1").strip().lower() not in {"0", "false", "no"}:
        if os.getenv("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
            threading.Thread(target=_auto_collect_loop, daemon=True).start()


def _start_inline_job_worker_thread(app: Flask) -> None:
    if os.getenv("ENABLE_INLINE_JOB_WORKER", "1").strip().lower() in {"0", "false", "no"}:
        return
    if not (os.getenv("WERKZEUG_RUN_MAIN") == "true" or not app.debug):
        return

    def _runner() -> None:
        try:
            from backend.md_quiz.services import JobService
            from backend.md_quiz.storage import JsonJobStore
        except Exception:
            logger.exception("Inline job worker bootstrap failed")
            return

        runtime_root = Path(STORAGE_DIR).resolve() / "runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        service = JobService(JsonJobStore(runtime_root / "jobs.json"))
        while True:
            try:
                job = service.claim_next("legacy-inline-worker")
                if job is None:
                    time_module.sleep(1.0)
                    continue
                service.process(job)
            except Exception:
                logger.exception("Inline job worker loop failed")
                time_module.sleep(1.0)

    threading.Thread(target=_runner, daemon=True, name="legacy-inline-job-worker").start()


def bootstrap_runtime(app: Flask) -> None:
    ensure_dirs()
    try:
        init_db()
    except RuntimeError as e:
        raise RuntimeBootstrapError(str(e)) from e
    try:
        migrate_legacy_exam_data()
    except Exception:
        logger.exception("Legacy exam version migration failed")
    _start_auto_collect_thread(app)
    _start_inline_job_worker_thread(app)


__all__ = ["RuntimeBootstrapError", "_ensure_exam_paper_for_token", "bootstrap_runtime"]
