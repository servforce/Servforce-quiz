from __future__ import annotations

from web.runtime_support import *


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


def bootstrap_runtime(app: Flask) -> None:
    ensure_dirs()
    try:
        init_db()
    except RuntimeError as e:
        raise RuntimeBootstrapError(str(e)) from e
    _start_auto_collect_thread(app)


__all__ = ["RuntimeBootstrapError", "_ensure_exam_paper_for_token", "bootstrap_runtime"]
