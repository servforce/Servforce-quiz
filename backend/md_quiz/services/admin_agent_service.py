from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from backend.md_quiz.services import exam_helpers, runtime_jobs, system_status_helpers, validation_helpers
from backend.md_quiz.services import support_deps as deps


def _iso_or_empty(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value or "").strip()


def _parse_date_ymd(value: str) -> date | None:
    return validation_helpers._parse_date_ymd(value)


def _mask_phone(phone: str) -> str:
    normalized = validation_helpers._normalize_phone(phone)
    if len(normalized) != 11:
        return ""
    return f"{normalized[:3]}****{normalized[-4:]}"


def _mask_email(email: str) -> str:
    text = str(email or "").strip()
    if not text or "@" not in text:
        return ""
    local, domain = text.split("@", 1)
    if len(local) <= 2:
        return f"{local[:1]}***@{domain}"
    return f"{local[:2]}***@{domain}"


def _score_display(score: Any, score_max: Any, *, result_mode: str = "") -> str:
    mode = str(result_mode or "").strip().lower()
    if mode == "traits":
        return "-"
    try:
        scored = int(score)
    except Exception:
        return "-"
    try:
        max_value = int(score_max)
    except Exception:
        max_value = 0
    if max_value > 0:
        return f"{scored} / {max_value}"
    return str(scored)


def _status_label(status_key: str) -> str:
    mapping = {
        "verified": "验证通过",
        "invited": "已邀约",
        "in_quiz": "正在答题",
        "grading": "正在判卷",
        "finished": "判卷结束",
        "expired": "失效",
    }
    return mapping.get(str(status_key or "").strip(), "未知")


def _source_label(source_kind: str) -> str:
    return "公开邀约" if str(source_kind or "").strip() == "public" else "主动邀约"


def _looks_deleted_marker(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if text in {"已删除", "deleted", "????", "???", "null", "none", "历史测验"}:
        return True
    if "?" in text and len(text) <= 12:
        return True
    return "删除" in text and len(text) <= 8


def _requires_confirmation(action: str, *, target: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "requires_confirmation": True,
        "action": action,
        "target": target,
        "message": message,
    }


def _parse_candidate_query_datetime(raw: str, *, end_of_day: bool = False) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if text.count("-") == 2 and "T" not in text and " " not in text:
        if end_of_day:
            return parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
        return parsed.replace(hour=0, minute=0, second=0, microsecond=0)
    return parsed


def _candidate_attempt_results(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    phone = str(candidate.get("phone") or "").strip()
    if not phone:
        return []
    best_by_key: dict[str, dict[str, Any]] = {}
    rows = deps.list_quiz_archives_for_phone(phone)
    for row in rows:
        archive = row.get("archive") if isinstance(row, dict) else None
        if not isinstance(archive, dict):
            continue
        token = str(archive.get("token") or "").strip()
        timing = archive.get("timing") or {}
        if not isinstance(timing, dict):
            timing = {}
        start_at = str(timing.get("start_at") or "").strip()
        end_at = str(timing.get("end_at") or "").strip()
        score = archive.get("total_score")
        score_max = archive.get("score_max")
        grading = archive.get("grading") if isinstance(archive.get("grading"), dict) else {}
        result_mode = str(
            archive.get("result_mode")
            or grading.get("result_mode")
            or ("traits" if int(archive.get("raw_total") or 0) <= 0 else "scored")
        ).strip()
        if not end_at or (score is None and result_mode != "traits"):
            continue
        exam = archive.get("exam") or {}
        if not isinstance(exam, dict):
            exam = {}
        quiz_key = str(exam.get("quiz_key") or "").strip()
        quiz_name = str(exam.get("title") or "").strip() or quiz_key or "未知测验"
        sort_key = 0.0
        try:
            sort_key = datetime.fromisoformat(end_at.replace("Z", "+00:00")).timestamp()
        except Exception:
            updated_at = row.get("updated_at")
            try:
                sort_key = float(updated_at.timestamp()) if updated_at else 0.0
            except Exception:
                sort_key = 0.0
        dedupe_key = f"{token}::{quiz_key}" if token else str(row.get("archive_name") or "")
        current = best_by_key.get(dedupe_key)
        if current is None or float(sort_key) >= float(current.get("_sort_key") or 0.0):
            best_by_key[dedupe_key] = {
                "token": token,
                "quiz_name": quiz_name,
                "score": score,
                "score_max": score_max,
                "score_display": _score_display(score, score_max, result_mode=result_mode),
                "result_mode": result_mode,
                "start_at": _iso_or_empty(start_at),
                "end_at": _iso_or_empty(end_at),
                "_sort_key": sort_key,
            }
    items = list(best_by_key.values())
    items.sort(key=lambda item: float(item.get("_sort_key") or 0.0), reverse=True)
    return [
        {
            "token": str(item.get("token") or "").strip(),
            "quiz_name": str(item.get("quiz_name") or "").strip(),
            "score": item.get("score"),
            "score_max": item.get("score_max"),
            "score_display": str(item.get("score_display") or "").strip(),
            "result_mode": str(item.get("result_mode") or "").strip(),
            "start_at": str(item.get("start_at") or "").strip(),
            "end_at": str(item.get("end_at") or "").strip(),
        }
        for item in items
    ]


def _serialize_candidate_detail(candidate_id: int, candidate: dict[str, Any]) -> dict[str, Any]:
    parsed = candidate.get("resume_parsed") or {}
    if not isinstance(parsed, dict):
        parsed = {}
    details = parsed.get("details") or {}
    if not isinstance(details, dict):
        details = {}
    details_data = details.get("data") or {}
    if not isinstance(details_data, dict):
        details_data = {}

    educations = details_data.get("educations") or []
    if not isinstance(educations, list):
        educations = []
    education_rows = [dict(item) for item in educations if isinstance(item, dict)]
    for item in education_rows:
        try:
            tag, label = deps.classify_university(str(item.get("school") or ""))
        except Exception:
            tag, label = "", ""
        item["school_tag"] = tag
        item["school_tag_label"] = label

    projects = details_data.get("projects") or []
    if not isinstance(projects, list):
        projects = []
    project_rows = [dict(item) for item in projects if isinstance(item, dict)]
    projects_raw = str(details_data.get("projects_raw") or "").strip()

    email = ""
    emails = details_data.get("emails") or []
    if isinstance(emails, list) and emails:
        email = str(emails[0] or "").strip()

    evaluation_llm = str(details_data.get("evaluation") or "").strip() or str(
        details_data.get("summary") or ""
    ).strip()
    raw_admin_evaluations = details_data.get("admin_evaluations") or []
    admin_evaluations = [dict(item) for item in raw_admin_evaluations if isinstance(item, dict)]

    return {
        "candidate": {
            "id": int(candidate.get("id") or candidate_id),
            "name": str(candidate.get("name") or "").strip(),
            "phone": str(candidate.get("phone") or "").strip(),
            "created_at": _iso_or_empty(candidate.get("created_at")),
            "deleted_at": _iso_or_empty(candidate.get("deleted_at")),
            "resume_filename": str(candidate.get("resume_filename") or "").strip(),
            "resume_mime": str(candidate.get("resume_mime") or "").strip(),
            "resume_size": candidate.get("resume_size"),
            "resume_parsed_at": _iso_or_empty(candidate.get("resume_parsed_at")),
        },
        "profile": {
            "gender": str(details_data.get("gender") or "").strip(),
            "email": email,
            "highest_education": str(details_data.get("highest_education") or "").strip(),
            "educations": education_rows,
            "english": details_data.get("english") or {},
            "projects": project_rows,
            "projects_raw": projects_raw,
            "evaluation_llm": evaluation_llm,
            "admin_evaluations": admin_evaluations,
            "details_status": str(details.get("status") or "").strip(),
            "details_error": str(details.get("error") or "").strip(),
            "attempt_results": _candidate_attempt_results(candidate),
        },
        "resume_parsed": parsed,
    }


def _sanitize_candidate_payload(payload: dict[str, Any], *, include_sensitive: bool) -> dict[str, Any]:
    out = {
        "candidate": dict(payload.get("candidate") or {}),
        "profile": dict(payload.get("profile") or {}),
    }
    if include_sensitive:
        out["resume_parsed"] = payload.get("resume_parsed") or {}
        return out

    candidate = out["candidate"]
    candidate["phone"] = _mask_phone(str(candidate.get("phone") or ""))
    profile = out["profile"]
    profile["email"] = _mask_email(str(profile.get("email") or ""))
    profile["projects_raw"] = ""
    out["resume_parsed"] = {
        "details": {
            "status": str(((payload.get("resume_parsed") or {}).get("details") or {}).get("status") or "").strip(),
            "error": str(((payload.get("resume_parsed") or {}).get("details") or {}).get("error") or "").strip(),
        }
    }
    return out


def _serialize_assignment_row(row: dict[str, Any], *, include_sensitive: bool) -> dict[str, Any]:
    token = str(row.get("token") or "").strip()
    status_key = validation_helpers._normalize_exam_status(str(row.get("status") or "").strip())
    invite_end_date = _iso_or_empty(row.get("invite_end_date"))
    if status_key in {"invited", "verified"} and not row.get("entered_at"):
        end_date = _parse_date_ymd(invite_end_date)
        if end_date is not None and datetime.now().astimezone().date() > end_date:
            status_key = "expired"
    source_kind = "public" if str(row.get("source_kind") or "").strip() == "public" else "direct"
    require_phone_verification = bool(source_kind == "public")
    ignore_timing = False
    score = row.get("score")
    score_max = None
    result_mode = ""
    if token:
        try:
            assignment = deps.load_assignment(token)
        except Exception:
            assignment = None
        grading = (assignment or {}).get("grading") if isinstance((assignment or {}).get("grading"), dict) else {}
        score_max = grading.get("total_max")
        result_mode = str(
            grading.get("result_mode")
            or ("traits" if int(grading.get("raw_total") or 0) <= 0 and grading else "")
        ).strip()
        require_phone_verification = validation_helpers._require_phone_verification(assignment or row)
        ignore_timing = bool((assignment or row).get("ignore_timing"))
    phone = str(row.get("phone") or "").strip()
    return {
        "attempt_id": int(row.get("attempt_id") or 0),
        "candidate_id": int(row.get("candidate_id") or 0),
        "candidate_name": str(row.get("name") or "").strip(),
        "candidate_deleted": bool(row.get("candidate_deleted_at")),
        "phone": phone if include_sensitive else _mask_phone(phone),
        "quiz_key": str(row.get("quiz_key") or "").strip(),
        "quiz_version_id": int(row.get("quiz_version_id") or 0),
        "token": token,
        "source_kind": source_kind,
        "source_label": _source_label(source_kind),
        "invite_start_date": _iso_or_empty(row.get("invite_start_date")),
        "invite_end_date": invite_end_date,
        "require_phone_verification": require_phone_verification,
        "ignore_timing": ignore_timing,
        "status": status_key,
        "status_label": _status_label(status_key),
        "entered_at": _iso_or_empty(row.get("entered_at")),
        "finished_at": _iso_or_empty(row.get("finished_at")),
        "handled_at": _iso_or_empty(row.get("handled_at")),
        "handled_by": str(row.get("handled_by") or "").strip(),
        "needs_attention": bool(status_key == "finished" and not row.get("handled_at")),
        "score": score,
        "score_max": score_max,
        "score_display": _score_display(score, score_max, result_mode=result_mode),
        "result_mode": result_mode,
        "created_at": _iso_or_empty(row.get("created_at")),
        "invite_path": f"/t/{token}" if token else "",
        "qr_path": f"/api/admin/assignments/{token}/qr.png" if token else "",
    }


def _build_assignment_result_summary(archive: dict[str, Any] | None, assignment: dict[str, Any] | None) -> dict[str, Any]:
    evaluation = {}
    try:
        evaluation = runtime_jobs._build_review_evaluation(archive=archive, assignment=assignment)
    except Exception:
        evaluation = {}
    answers_count = 0
    try:
        answers_count = len(runtime_jobs._build_review_answers(archive=archive, assignment=assignment))
    except Exception:
        answers_count = 0
    return {
        "answers_count": answers_count,
        "has_evaluation": bool(evaluation),
        "evaluation": evaluation,
    }


class AdminAgentService:
    def __init__(self, *, runtime_service, job_service, settings: Any):
        self.runtime_service = runtime_service
        self.job_service = job_service
        self.settings = settings

    def system_health(self) -> dict[str, Any]:
        self.runtime_service.heartbeat("api", name="api", message="mcp-health-check")
        return {
            "status": "ok",
            "service": "md-quiz",
            "mode": "fastapi",
            "admin_path": "/admin",
        }

    def system_processes(self) -> dict[str, Any]:
        return {"items": [item.model_dump() for item in self.runtime_service.list_processes()]}

    def runtime_config_get(self) -> dict[str, Any]:
        return self.runtime_service.get_runtime_config().model_dump()

    def runtime_config_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.runtime_service.update_runtime_config(dict(payload or {})).model_dump()

    def system_status_summary(self) -> dict[str, Any]:
        return system_status_helpers._get_cached_system_status_summary(force=True)

    def system_status_range(self, *, start: str = "", end: str = "") -> dict[str, Any]:
        today = datetime.now().astimezone().date()
        start_day = _parse_date_ymd(start) or (today - timedelta(days=29))
        end_day = _parse_date_ymd(end) or today
        data = system_status_helpers._compute_system_status_range(start_day=start_day, end_day=end_day)
        return {
            "config": system_status_helpers._load_system_status_cfg(),
            "data": data,
            "summary": system_status_helpers._get_cached_system_status_summary(force=True),
        }

    def system_status_update_thresholds(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = system_status_helpers._save_system_status_cfg(payload if isinstance(payload, dict) else {})
        try:
            deps.emit_alerts_for_current_snapshot()
        except Exception:
            pass
        return {
            "config": config,
            "summary": system_status_helpers._get_cached_system_status_summary(force=True),
        }

    def job_list(self) -> dict[str, Any]:
        return {"items": [item.model_dump() for item in self.job_service.list_jobs()]}

    def job_get(self, job_id: str) -> dict[str, Any] | None:
        job = self.job_service.get_job(job_id)
        return job.model_dump() if job else None

    def job_wait(self, job_id: str, *, timeout_seconds: int = 30, poll_seconds: float = 1.0) -> dict[str, Any]:
        deadline = time.monotonic() + max(1, int(timeout_seconds or 30))
        while True:
            current = self.job_get(job_id)
            if not current:
                return {"ok": False, "job_id": str(job_id or "").strip(), "message": "任务不存在"}
            if str(current.get("status") or "").strip() in {"done", "failed"}:
                return {"ok": True, "timed_out": False, "job": current}
            if time.monotonic() >= deadline:
                return {"ok": True, "timed_out": True, "job": current}
            time.sleep(max(0.2, float(poll_seconds or 1.0)))

    def quiz_repo_get_binding(self) -> dict[str, Any]:
        binding = deps.read_exam_repo_binding()
        return {
            "binding": binding if isinstance(binding, dict) else {},
            "sync_state": deps.read_exam_repo_sync_state(),
        }

    def quiz_repo_bind(self, repo_url: str) -> dict[str, Any]:
        result = deps.bind_exam_repo(str(repo_url or "").strip())
        try:
            deps.log_event(
                "exam.repo.bind",
                actor="mcp",
                meta={
                    "repo_url": str((result.get("binding") or {}).get("repo_url") or ""),
                    "job_id": str((result.get("sync") or {}).get("job_id") or ""),
                    "sync_created": bool((result.get("sync") or {}).get("created")),
                    "sync_error": str((result.get("sync") or {}).get("error") or ""),
                },
            )
        except Exception:
            pass
        return result

    def quiz_repo_rebind(self, repo_url: str, *, confirm: bool = False) -> dict[str, Any]:
        normalized = str(repo_url or "").strip()
        if not confirm:
            return _requires_confirmation(
                "quiz_repo_rebind",
                target={"repo_url": normalized},
                message="重新绑定会删除当前实例中的测验、版本、邀约与答题归档数据，但保留候选人与简历。",
            )
        result = deps.rebind_exam_repo(normalized)
        try:
            deps.log_event(
                "exam.repo.rebind",
                actor="mcp",
                meta={
                    "previous_repo_url": str(result.get("previous_repo_url") or ""),
                    "repo_url": str((result.get("binding") or {}).get("repo_url") or ""),
                    "cleanup": result.get("cleanup") if isinstance(result.get("cleanup"), dict) else {},
                    "job_id": str((result.get("sync") or {}).get("job_id") or ""),
                },
            )
        except Exception:
            pass
        return result

    def quiz_repo_sync(self) -> dict[str, Any]:
        result = deps.enqueue_exam_repo_sync()
        try:
            binding = deps.read_exam_repo_binding() or {}
            deps.log_event(
                "exam.sync.enqueue",
                actor="mcp",
                meta={
                    "repo_url": str(binding.get("repo_url") or ""),
                    "job_id": str(result.get("job_id") or ""),
                    "created": bool(result.get("created")),
                },
            )
        except Exception:
            pass
        return result

    def quiz_list(self, *, query: str = "") -> dict[str, Any]:
        items = exam_helpers._list_exams()
        needle = str(query or "").strip().lower()
        if needle:
            items = [
                item
                for item in items
                if needle in str(item.get("quiz_key") or "").lower()
                or needle in str(item.get("title") or "").lower()
                or any(needle in str(tag or "").lower() for tag in (item.get("tags") or []))
            ]
        items.sort(key=lambda item: float(item.get("_mtime") or 0), reverse=True)
        result = []
        for item in items:
            quiz_key = str(item.get("quiz_key") or "").strip()
            cfg = exam_helpers.get_public_invite_config(quiz_key)
            token = str(cfg.get("token") or "").strip()
            result.append(
                {
                    "id": int(item.get("id") or 0),
                    "quiz_key": quiz_key,
                    "title": str(item.get("title") or "").strip(),
                    "description": str(item.get("description") or "").strip(),
                    "status": str(item.get("status") or "").strip() or "active",
                    "question_count": int(item.get("question_count") or 0),
                    "question_counts": dict(item.get("question_counts") or {}),
                    "estimated_duration_minutes": int(item.get("estimated_duration_minutes") or 0),
                    "tags": list(item.get("tags") or []),
                    "schema_version": item.get("schema_version"),
                    "format": str(item.get("format") or "").strip(),
                    "trait": dict(item.get("trait") or {}),
                    "current_quiz_version_id": int(item.get("current_version_id") or 0),
                    "current_version_no": int(item.get("current_version_no") or 0),
                    "source_path": str(item.get("source_path") or "").strip(),
                    "last_sync_error": str(item.get("last_sync_error") or "").strip(),
                    "public_invite_enabled": bool(cfg.get("enabled")),
                    "public_invite_token": token,
                    "public_invite_path": f"/p/{token}" if token and bool(cfg.get("enabled")) else "",
                    "public_invite_qr_path": (
                        f"/api/public/invites/{token}/qr.png" if token and bool(cfg.get("enabled")) else ""
                    ),
                }
            )
        return {
            "items": result,
            "repo_binding": deps.read_exam_repo_binding() or {},
            "sync_state": deps.read_exam_repo_sync_state(),
        }

    def quiz_get(self, quiz_key: str) -> dict[str, Any]:
        key = str(quiz_key or "").strip()
        exam = deps.get_quiz_definition(key)
        if not exam:
            raise FileNotFoundError(key)
        current_version_id = int(exam.get("current_version_id") or 0)
        selected_version = exam_helpers.get_quiz_version_snapshot(current_version_id) if current_version_id > 0 else None
        raw_spec = selected_version.get("spec") if isinstance((selected_version or {}).get("spec"), dict) else exam.get("spec") or {}
        spec = exam_helpers.build_render_ready_public_spec(raw_spec if isinstance(raw_spec, dict) else {})
        quiz_metadata = exam_helpers.build_quiz_metadata(spec)
        cfg = exam_helpers.get_public_invite_config(key)
        token = str(cfg.get("token") or "").strip()
        versions = []
        for item in deps.list_quiz_versions(key):
            versions.append(
                {
                    "id": int(item.get("id") or 0),
                    "version_no": int(item.get("version_no") or 0),
                    "git_commit": str(item.get("git_commit") or "").strip(),
                    "source_path": str(item.get("source_path") or "").strip(),
                    "created_at": _iso_or_empty(item.get("created_at")),
                    "is_current": bool(current_version_id and current_version_id == int(item.get("id") or 0)),
                }
            )
        return {
            "quiz": {
                "id": int(exam_helpers._sort_id_from_quiz_key(key) or 0),
                "quiz_key": key,
                "title": str((spec or {}).get("title") or exam.get("title") or "").strip(),
                "description": str((spec or {}).get("description") or "").strip(),
                "status": str(exam.get("status") or "").strip() or "active",
                "tags": list(quiz_metadata["tags"]),
                "schema_version": quiz_metadata["schema_version"],
                "format": str(quiz_metadata["format"] or "").strip(),
                "question_count": int(quiz_metadata["question_count"]),
                "question_counts": dict(quiz_metadata["question_counts"]),
                "estimated_duration_minutes": int(quiz_metadata["estimated_duration_minutes"]),
                "trait": dict(quiz_metadata["trait"]),
                "current_quiz_version_id": current_version_id,
                "current_version_no": int(exam.get("current_version_no") or 0),
                "source_path": str(exam.get("source_path") or "").strip(),
                "last_synced_commit": str(exam.get("last_synced_commit") or "").strip(),
                "last_sync_error": str(exam.get("last_sync_error") or "").strip(),
                "public_invite_enabled": bool(cfg.get("enabled")),
                "public_invite_token": token,
                "public_invite_path": f"/p/{token}" if token and bool(cfg.get("enabled")) else "",
                "public_invite_qr_path": (
                    f"/api/public/invites/{token}/qr.png" if token and bool(cfg.get("enabled")) else ""
                ),
            },
            "selected_quiz_version": {
                "id": int((selected_version or {}).get("id") or 0),
                "version_no": int((selected_version or {}).get("version_no") or 0),
                "git_commit": str((selected_version or {}).get("git_commit") or "").strip(),
                "source_path": str((selected_version or {}).get("source_path") or "").strip(),
                "spec": spec if isinstance(spec, dict) else {},
            },
            "quiz_version_history": versions,
            "sync_state": deps.read_exam_repo_sync_state(),
        }

    def quiz_set_public_invite(self, quiz_key: str, *, enabled: bool) -> dict[str, Any]:
        key = str(quiz_key or "").strip()
        exam = deps.get_quiz_definition(key)
        if not exam:
            raise FileNotFoundError(key)
        cfg = exam_helpers.set_public_invite_enabled(key, enabled)
        token = str(cfg.get("token") or "").strip()
        try:
            deps.log_event(
                "exam.public_invite.enable" if enabled else "exam.public_invite.disable",
                actor="mcp",
                quiz_key=key,
                meta={"public_token": token},
            )
        except Exception:
            pass
        return {
            "ok": True,
            "enabled": bool(cfg.get("enabled")),
            "token": token,
            "public_path": f"/p/{token}" if bool(cfg.get("enabled")) and token else "",
            "qr_path": f"/api/public/invites/{token}/qr.png" if bool(cfg.get("enabled")) and token else "",
        }

    def candidate_list(
        self,
        *,
        query: str = "",
        created_from: str = "",
        created_to: str = "",
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        created_from_raw = str(created_from or "").strip() or (datetime.now().date() - timedelta(days=29)).isoformat()
        created_to_raw = str(created_to or "").strip() or datetime.now().date().isoformat()
        parsed_from = _parse_candidate_query_datetime(created_from_raw, end_of_day=False)
        parsed_to = _parse_candidate_query_datetime(created_to_raw, end_of_day=True)
        page_size = max(1, min(100, int(per_page or 20)))
        total = deps.count_candidates(query=query or None, created_from=parsed_from, created_to=parsed_to)
        total_pages = max(1, (total + page_size - 1) // page_size)
        current_page = max(1, min(int(page or 1), total_pages))
        offset = (current_page - 1) * page_size
        rows = deps.list_candidates(
            limit=page_size,
            offset=offset,
            query=query or None,
            created_from=parsed_from,
            created_to=parsed_to,
        )
        return {
            "items": [
                {
                    "id": int(item.get("id") or 0),
                    "name": str(item.get("name") or "").strip(),
                    "phone": _mask_phone(str(item.get("phone") or "").strip()),
                    "created_at": _iso_or_empty(item.get("created_at")),
                    "has_resume": bool(item.get("has_resume")),
                }
                for item in rows
            ],
            "page": current_page,
            "per_page": page_size,
            "total": total,
            "total_pages": total_pages,
        }

    def candidate_ensure(self, *, name: str, phone: str) -> dict[str, Any]:
        normalized_name = str(name or "").strip()
        normalized_phone = validation_helpers._normalize_phone(phone)
        if not validation_helpers._is_valid_name(normalized_name):
            raise ValueError("姓名格式不正确")
        if not validation_helpers._is_valid_phone(normalized_phone):
            raise ValueError("手机号格式不正确")
        existed = deps.get_candidate_by_phone(normalized_phone)
        created = False
        if existed:
            candidate_id = int(existed.get("id") or 0)
            current_name = str(existed.get("name") or "").strip()
            if current_name in {"", "未知"} and normalized_name:
                deps.update_candidate(candidate_id, name=normalized_name, phone=normalized_phone)
            candidate = deps.get_candidate(candidate_id) or existed
        else:
            candidate_id = int(deps.create_candidate(name=normalized_name, phone=normalized_phone))
            created = True
            candidate = deps.get_candidate(candidate_id) or {
                "id": candidate_id,
                "name": normalized_name,
                "phone": normalized_phone,
            }
            try:
                deps.log_event(
                    "candidate.create",
                    actor="mcp",
                    candidate_id=candidate_id,
                    meta={"name": normalized_name, "phone": normalized_phone},
                )
            except Exception:
                pass
        return {
            "created": created,
            "candidate": {
                "id": int(candidate.get("id") or candidate_id),
                "name": str(candidate.get("name") or normalized_name).strip(),
                "phone": _mask_phone(str(candidate.get("phone") or normalized_phone).strip()),
                "created_at": _iso_or_empty(candidate.get("created_at")),
            },
        }

    def candidate_get(self, candidate_id: int, *, include_sensitive: bool = False) -> dict[str, Any]:
        candidate = deps.get_candidate(int(candidate_id))
        if not candidate:
            raise FileNotFoundError(str(candidate_id))
        detail = _serialize_candidate_detail(int(candidate_id), candidate)
        return _sanitize_candidate_payload(detail, include_sensitive=include_sensitive)

    def candidate_add_evaluation(self, candidate_id: int, *, evaluation: str) -> dict[str, Any]:
        candidate = deps.get_candidate(int(candidate_id))
        if not candidate:
            raise FileNotFoundError(str(candidate_id))
        text = str(evaluation or "").strip()
        if not text:
            raise ValueError("评价不能为空")
        parsed = candidate.get("resume_parsed") or {}
        if not isinstance(parsed, dict):
            parsed = {}
        details = parsed.get("details") or {}
        if not isinstance(details, dict):
            details = {}
        details_data = details.get("data") or {}
        if not isinstance(details_data, dict):
            details_data = {}
        existing = details_data.get("admin_evaluations") or []
        items = [dict(item) for item in existing if isinstance(item, dict)]
        now_iso = datetime.now(timezone.utc).isoformat()
        items.append({"text": text, "at": now_iso})
        details_data["admin_evaluations"] = items
        details_data["admin_evaluation"] = ""
        details["data"] = details_data
        parsed["details"] = details
        deps.update_candidate_resume_parsed(
            int(candidate_id),
            resume_parsed=parsed,
            touch_resume_parsed_at=False,
        )
        try:
            deps.log_event(
                "candidate.evaluation.add",
                actor="mcp",
                candidate_id=int(candidate_id),
            )
        except Exception:
            pass
        return self.candidate_get(int(candidate_id), include_sensitive=False)

    def candidate_delete(self, candidate_id: int, *, confirm: bool = False) -> dict[str, Any]:
        candidate = deps.get_candidate(int(candidate_id))
        if not candidate:
            raise FileNotFoundError(str(candidate_id))
        if not confirm:
            return _requires_confirmation(
                "candidate_delete",
                target={
                    "candidate_id": int(candidate_id),
                    "name": str(candidate.get("name") or "").strip(),
                },
                message="若候选人已有答题记录，将执行软删除并脱敏保留历史；否则会直接删除。",
            )
        deps.delete_candidate(int(candidate_id))
        try:
            deps.log_event(
                "candidate.delete",
                actor="mcp",
                candidate_id=int(candidate_id),
                meta={"name": str(candidate.get("name") or "").strip()},
            )
        except Exception:
            pass
        return {"ok": True, "candidate_id": int(candidate_id)}

    def assignment_list(
        self,
        *,
        query: str = "",
        start_from: str = "",
        start_to: str = "",
        end_from: str = "",
        end_to: str = "",
        page: int = 1,
        per_page: int = 20,
        include_sensitive: bool = False,
    ) -> dict[str, Any]:
        page_size = max(1, min(100, int(per_page or 20)))
        total = deps.count_quiz_papers(
            query=query or None,
            invite_start_from=(str(start_from or "").strip() or None),
            invite_start_to=(str(start_to or "").strip() or None),
            invite_end_from=(str(end_from or "").strip() or None),
            invite_end_to=(str(end_to or "").strip() or None),
        )
        total_pages = max(1, (total + page_size - 1) // page_size)
        current_page = max(1, min(int(page or 1), total_pages))
        offset = (current_page - 1) * page_size
        rows = deps.list_quiz_papers(
            query=query or None,
            invite_start_from=(str(start_from or "").strip() or None),
            invite_start_to=(str(start_to or "").strip() or None),
            invite_end_from=(str(end_from or "").strip() or None),
            invite_end_to=(str(end_to or "").strip() or None),
            limit=page_size,
            offset=offset,
        )
        return {
            "items": [_serialize_assignment_row(row, include_sensitive=include_sensitive) for row in rows],
            "summary": {
                "unhandled_finished_count": int(
                    deps.count_unhandled_finished_quiz_papers(
                        query=query or None,
                        invite_start_from=(str(start_from or "").strip() or None),
                        invite_start_to=(str(start_to or "").strip() or None),
                        invite_end_from=(str(end_from or "").strip() or None),
                        invite_end_to=(str(end_to or "").strip() or None),
                    )
                    or 0
                ),
            },
            "page": current_page,
            "per_page": page_size,
            "total": total,
            "total_pages": total_pages,
        }

    def assignment_create(
        self,
        *,
        quiz_key: str,
        candidate_id: int,
        invite_start_date: str,
        invite_end_date: str,
        require_phone_verification: bool = False,
        ignore_timing: bool = False,
        verify_max_attempts: int = 3,
    ) -> dict[str, Any]:
        key = str(quiz_key or "").strip()
        if not key:
            raise ValueError("缺少 quiz_key")
        candidate = deps.get_candidate(int(candidate_id))
        if not candidate:
            raise FileNotFoundError(f"candidate:{candidate_id}")
        exam = deps.get_quiz_definition(key)
        quiz_version_id = exam_helpers.resolve_quiz_version_id_for_new_assignment(key)
        if not exam or not quiz_version_id:
            raise ValueError("测验不可用")
        start_date = _parse_date_ymd(invite_start_date)
        end_date = _parse_date_ymd(invite_end_date)
        if start_date is None or end_date is None:
            raise ValueError("答题日期无效")
        if end_date < start_date:
            raise ValueError("答题结束日期不能早于开始日期")
        ignore_timing = bool(ignore_timing)
        public_spec = exam.get("public_spec") if isinstance(exam.get("public_spec"), dict) else {}
        time_limit_seconds = 0 if ignore_timing else exam_helpers.compute_quiz_time_limit_seconds(public_spec)
        if not ignore_timing and time_limit_seconds <= 0:
            raise ValueError("测验缺少有效的题目答题时长配置")
        result = deps.create_assignment(
            quiz_key=key,
            candidate_id=int(candidate_id),
            quiz_version_id=quiz_version_id,
            base_url="",
            phone=str(candidate.get("phone") or ""),
            invite_start_date=start_date.isoformat(),
            invite_end_date=end_date.isoformat(),
            time_limit_seconds=time_limit_seconds,
            min_submit_seconds=0,
            require_phone_verification=bool(require_phone_verification),
            ignore_timing=ignore_timing,
            verify_max_attempts=int(verify_max_attempts or 3),
        )
        token = str(result.get("token") or "").strip()
        try:
            deps.create_quiz_paper(
                candidate_id=int(candidate_id),
                phone=str(candidate.get("phone") or ""),
                quiz_key=key,
                quiz_version_id=quiz_version_id,
                token=token,
                source_kind="direct",
                invite_start_date=start_date.isoformat(),
                invite_end_date=end_date.isoformat(),
                status="invited",
            )
        except Exception:
            deps.logger.exception("Create quiz_paper failed (candidate_id=%s, quiz_key=%s)", candidate_id, key)
        try:
            deps.log_event(
                "assignment.create",
                actor="mcp",
                candidate_id=int(candidate_id),
                quiz_key=key,
                token=token or None,
                meta={
                    "invite_start_date": start_date.isoformat(),
                    "invite_end_date": end_date.isoformat(),
                    "require_phone_verification": bool(require_phone_verification),
                    "ignore_timing": ignore_timing,
                },
            )
        except Exception:
            pass
        return {
            "token": token,
            "invite_path": f"/t/{token}" if token else "",
            "qr_path": f"/api/admin/assignments/{token}/qr.png" if token else "",
        }

    def assignment_get(self, token: str, *, include_sensitive: bool = False) -> dict[str, Any]:
        token_str = str(token or "").strip()
        quiz_paper_row = deps.get_quiz_paper_admin_detail_by_token(token_str)
        try:
            assignment = deps.load_assignment(token_str)
        except FileNotFoundError:
            assignment = {}
        if not assignment and not quiz_paper_row:
            raise FileNotFoundError(token_str)
        row = runtime_jobs._find_archive_by_token(token_str, assignment=assignment)
        archive = row.get("archive") if isinstance(row, dict) else None
        if isinstance(archive, dict):
            try:
                archive = runtime_jobs._augment_archive_with_spec(dict(archive))
            except Exception:
                archive = dict(archive)
        else:
            archive = None
        if isinstance(assignment, dict):
            assignment = dict(assignment)
            assignment["require_phone_verification"] = validation_helpers._require_phone_verification(assignment)
            assignment["ignore_timing"] = bool(assignment.get("ignore_timing"))
        quiz_paper = _serialize_assignment_row(quiz_paper_row, include_sensitive=include_sensitive) if quiz_paper_row else None
        if include_sensitive:
            return {
                "assignment": assignment,
                "quiz_paper": quiz_paper,
                "archive": archive,
                "review": {
                    "answers": runtime_jobs._build_review_answers(archive=archive, assignment=assignment),
                    "evaluation": runtime_jobs._build_review_evaluation(archive=archive, assignment=assignment),
                },
            }
        sanitized_assignment = {}
        if isinstance(assignment, dict):
            sanitized_assignment = {
                "token": token_str,
                "quiz_key": str(assignment.get("quiz_key") or "").strip(),
                "candidate_id": int(assignment.get("candidate_id") or 0),
                "status": str(assignment.get("status") or "").strip(),
                "status_updated_at": _iso_or_empty(assignment.get("status_updated_at")),
                "created_at": _iso_or_empty(assignment.get("created_at")),
                "ignore_timing": bool(assignment.get("ignore_timing")),
                "require_phone_verification": bool(assignment.get("require_phone_verification")),
            }
        return {
            "assignment": sanitized_assignment,
            "quiz_paper": quiz_paper,
            "archive_summary": {
                "token": token_str,
                "has_archive": bool(archive),
                "candidate_remark": str((archive or {}).get("candidate_remark") or (assignment or {}).get("candidate_remark") or "").strip(),
            },
            "review_summary": _build_assignment_result_summary(archive=archive, assignment=assignment),
        }

    def assignment_set_handling(self, token: str, *, handled: bool, handled_by: str = "mcp") -> dict[str, Any]:
        quiz_paper = deps.get_quiz_paper_by_token(str(token or "").strip())
        if not quiz_paper:
            raise FileNotFoundError(str(token or ""))
        status_key = validation_helpers._normalize_exam_status(str(quiz_paper.get("status") or "").strip())
        if status_key != "finished":
            raise ValueError("只有已判卷完成的记录才能标记处理状态")
        deps.set_quiz_paper_handling(
            str(token or "").strip(),
            handled=bool(handled),
            handled_by=str(handled_by or "mcp").strip() or "mcp",
        )
        row = deps.get_quiz_paper_admin_detail_by_token(str(token or "").strip())
        if not row:
            raise FileNotFoundError(str(token or ""))
        return {"item": _serialize_assignment_row(row, include_sensitive=False)}

    def assignment_delete(self, token: str, *, confirm: bool = False) -> dict[str, Any]:
        token_str = str(token or "").strip()
        if not token_str:
            raise ValueError("缺少 token")
        quiz_paper = deps.get_quiz_paper_by_token(token_str)
        try:
            assignment = deps.load_assignment(token_str)
        except FileNotFoundError:
            assignment = {}
        if not quiz_paper and not assignment:
            raise FileNotFoundError(token_str)
        if not confirm:
            return _requires_confirmation(
                "assignment_delete",
                target={"token": token_str, "quiz_key": str((quiz_paper or {}).get("quiz_key") or (assignment or {}).get("quiz_key") or "").strip()},
                message="删除邀约会同时删除 assignment、quiz_paper 以及已生成的答题归档。",
            )
        deleted_quiz_archive = int(deps.delete_quiz_archive_by_token(token_str) or 0)
        deleted_quiz_paper = int(deps.delete_quiz_paper_by_token(token_str) or 0)
        deleted_assignment_record = int(deps.delete_assignment_record(token_str) or 0)
        try:
            deps.log_event(
                "assignment.delete",
                actor="mcp",
                candidate_id=int((quiz_paper or {}).get("candidate_id") or (assignment or {}).get("candidate_id") or 0) or None,
                quiz_key=str((quiz_paper or {}).get("quiz_key") or (assignment or {}).get("quiz_key") or "").strip() or None,
                token=token_str,
            )
        except Exception:
            pass
        return {
            "ok": True,
            "deleted": {
                "quiz_archive": deleted_quiz_archive,
                "assignment_record": deleted_assignment_record,
                "quiz_paper": deleted_quiz_paper,
            },
        }
