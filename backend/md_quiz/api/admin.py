from __future__ import annotations

import hmac
import os
import re
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, Field

from backend.md_quiz.services import exam_helpers, runtime_jobs, support_deps as deps
from backend.md_quiz.services import system_status_helpers, validation_helpers

from .deps import get_container

router = APIRouter(prefix="/api/admin", tags=["admin"])

_LOG_CATEGORY_KEYS = ("candidate", "exam", "grading", "assignment", "system")


class AdminLoginPayload(BaseModel):
    username: str
    password: str


class RuntimeConfigPatch(BaseModel):
    sms_enabled: bool | None = None
    token_daily_threshold: int | None = Field(default=None, ge=0)
    sms_daily_threshold: int | None = Field(default=None, ge=0)
    allow_public_assignments: bool | None = None
    min_submit_seconds: int | None = Field(default=None, ge=0)
    ui_theme_name: str | None = None


class EnqueueJobPayload(BaseModel):
    kind: str
    payload: dict = Field(default_factory=dict)


class SyncExamPayload(BaseModel):
    repo_url: str = ""


class PublicInviteTogglePayload(BaseModel):
    enabled: bool


class CandidateCreatePayload(BaseModel):
    name: str
    phone: str


class CandidateEvaluationPayload(BaseModel):
    evaluation: str


class AssignmentCreatePayload(BaseModel):
    exam_key: str
    candidate_id: int
    time_limit_seconds: int | str
    invite_start_date: str
    invite_end_date: str
    min_submit_seconds: int | None = None
    pass_threshold: int = 60
    verify_max_attempts: int = 3


def _require_admin(request: Request) -> None:
    if not request.session.get("admin_logged_in"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="需要先登录后台")


def _status_label(status_key: str) -> str:
    mapping = {
        "verified": "验证通过",
        "invited": "已邀约",
        "in_exam": "正在答题",
        "grading": "正在判卷",
        "finished": "判卷结束",
        "expired": "失效",
    }
    return mapping.get(str(status_key or "").strip(), "未知")


def _parse_date_ymd(value: str) -> date | None:
    return validation_helpers._parse_date_ymd(value)


def _iso_or_empty(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value or "").strip()


def _iso_to_local_display(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except Exception:
        return raw


def _looks_deleted_marker(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if text in {"已删除", "deleted", "????", "???", "null", "none", "历史试卷"}:
        return True
    if "?" in text and len(text) <= 12:
        return True
    return "删除" in text and len(text) <= 8


def _compute_exam_stats(spec: dict[str, Any]) -> dict[str, Any]:
    questions = list(spec.get("questions") or [])
    counts_by_type: dict[str, int] = {}
    points_by_type: dict[str, int] = {}
    total_points = 0
    for question in questions:
        qtype = str(question.get("type") or "").strip() or "unknown"
        counts_by_type[qtype] = int(counts_by_type.get(qtype, 0)) + 1
        try:
            points = int(question.get("max_points") or 0)
        except Exception:
            points = 0
        points_by_type[qtype] = int(points_by_type.get(qtype, 0)) + points
        total_points += points
    return {
        "total_questions": len(questions),
        "total_points": int(total_points),
        "counts_by_type": counts_by_type,
        "points_by_type": points_by_type,
    }


def _admin_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _serialize_exam_summary(exam: dict[str, Any], request: Request) -> dict[str, Any]:
    exam_key = str(exam.get("exam_key") or "").strip()
    cfg = exam_helpers.get_public_invite_config(exam_key)
    public_token = str(cfg.get("token") or "").strip()
    question_count = int(exam.get("question_count") or exam.get("count") or 0)
    question_counts = exam.get("question_counts") if isinstance(exam.get("question_counts"), dict) else {}
    tags = exam.get("tags") if isinstance(exam.get("tags"), list) else []
    trait = exam.get("trait") if isinstance(exam.get("trait"), dict) else {}
    return {
        "id": int(exam.get("id") or 0),
        "exam_key": exam_key,
        "title": str(exam.get("title") or "").strip(),
        "description": str(exam.get("description") or "").strip(),
        "status": str(exam.get("status") or "").strip() or "active",
        "question_count": question_count,
        "question_counts": question_counts,
        "estimated_duration_minutes": int(exam.get("estimated_duration_minutes") or 0),
        "tags": tags,
        "schema_version": exam.get("schema_version"),
        "format": str(exam.get("format") or "").strip(),
        "trait": trait,
        "current_version_id": int(exam.get("current_version_id") or 0),
        "current_version_no": int(exam.get("current_version_no") or 0),
        "source_path": str(exam.get("source_path") or "").strip(),
        "last_sync_error": str(exam.get("last_sync_error") or "").strip(),
        "updated_at": _iso_or_empty(exam.get("updated_at")),
        "public_invite_enabled": bool(cfg.get("enabled")),
        "public_invite_token": public_token,
        "public_invite_url": (
            f"{_admin_base_url(request)}/p/{public_token}"
            if bool(cfg.get("enabled")) and public_token
            else ""
        ),
        "public_invite_qr_url": (
            f"/api/public/invites/{public_token}/qr.png"
            if bool(cfg.get("enabled")) and public_token
            else ""
        ),
    }


def _serialize_exam_detail(
    exam: dict[str, Any],
    *,
    request: Request,
    selected_version: dict[str, Any] | None = None,
) -> dict[str, Any]:
    exam_key = str(exam.get("exam_key") or "").strip()
    current_version_id = int(exam.get("current_version_id") or 0)
    selected = selected_version or {}
    selected_version_id = int(selected.get("id") or 0)
    spec = selected.get("spec") if isinstance(selected.get("spec"), dict) else exam.get("spec") or {}
    quiz_metadata = exam_helpers.build_quiz_metadata(spec)
    stats = _compute_exam_stats(spec if isinstance(spec, dict) else {})
    cfg = exam_helpers.get_public_invite_config(exam_key)
    public_token = str(cfg.get("token") or "").strip()
    versions: list[dict[str, Any]] = []
    for item in deps.list_exam_versions(exam_key):
        version_id = int(item.get("id") or 0)
        versions.append(
            {
                "id": version_id,
                "version_no": int(item.get("version_no") or 0),
                "git_commit": str(item.get("git_commit") or "").strip(),
                "source_path": str(item.get("source_path") or "").strip(),
                "created_at": _iso_or_empty(item.get("created_at")),
                "is_current": bool(current_version_id and current_version_id == version_id),
                "is_selected": bool(selected_version_id and selected_version_id == version_id),
            }
        )
    return {
        "exam": {
            "id": int(exam_helpers._sort_id_from_exam_key(exam_key) or 0),
            "exam_key": exam_key,
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
            "current_version_id": current_version_id,
            "current_version_no": int(exam.get("current_version_no") or 0),
            "source_path": str(exam.get("source_path") or "").strip(),
            "last_synced_commit": str(exam.get("last_synced_commit") or "").strip(),
            "last_sync_error": str(exam.get("last_sync_error") or "").strip(),
            "public_invite_enabled": bool(cfg.get("enabled")),
            "public_invite_token": public_token,
            "public_invite_url": (
                f"{_admin_base_url(request)}/p/{public_token}"
                if bool(cfg.get("enabled")) and public_token
                else ""
            ),
            "public_invite_qr_url": (
                f"/api/public/invites/{public_token}/qr.png"
                if bool(cfg.get("enabled")) and public_token
                else ""
            ),
        },
        "selected_version": {
            "id": selected_version_id,
            "version_no": int(selected.get("version_no") or 0),
            "git_commit": str(selected.get("git_commit") or "").strip(),
            "source_path": str(selected.get("source_path") or "").strip(),
            "tags": list(quiz_metadata["tags"]),
            "schema_version": quiz_metadata["schema_version"],
            "format": str(quiz_metadata["format"] or "").strip(),
            "question_count": int(quiz_metadata["question_count"]),
            "question_counts": dict(quiz_metadata["question_counts"]),
            "estimated_duration_minutes": int(quiz_metadata["estimated_duration_minutes"]),
            "trait": dict(quiz_metadata["trait"]),
            "spec": spec if isinstance(spec, dict) else {},
        },
        "version_history": versions,
        "stats": stats,
        "sync_state": deps.read_exam_repo_sync_state(),
    }


def _parse_candidate_query_dates(raw: str, *, end_of_day: bool = False) -> datetime | None:
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
    rows = deps.list_exam_archives_for_phone(phone)
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
        if not end_at or score is None:
            continue
        exam = archive.get("exam") or {}
        if not isinstance(exam, dict):
            exam = {}
        exam_key = str(exam.get("exam_key") or "").strip()
        exam_name = str(exam.get("title") or "").strip() or exam_key or "未知试卷"
        sort_key = 0.0
        try:
            sort_key = datetime.fromisoformat(end_at.replace("Z", "+00:00")).timestamp()
        except Exception:
            updated_at = row.get("updated_at")
            try:
                sort_key = float(updated_at.timestamp()) if updated_at else 0.0
            except Exception:
                sort_key = 0.0
        dedupe_key = f"{token}::{exam_key}" if token else str(row.get("archive_name") or "")
        current = best_by_key.get(dedupe_key)
        if current is None or float(sort_key) >= float(current.get("_sort_key") or 0.0):
            best_by_key[dedupe_key] = {
                "token": token,
                "exam_name": exam_name,
                "score": score,
                "start_at": start_at,
                "end_at": end_at,
                "_sort_key": sort_key,
                "_archive_name": str(row.get("archive_name") or ""),
            }
    items = list(best_by_key.values())
    items.sort(key=lambda item: float(item.get("_sort_key") or 0.0))
    out: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        out.append(
            {
                "no": index,
                "token": str(item.get("token") or "").strip(),
                "exam_name": str(item.get("exam_name") or "").strip(),
                "score": item.get("score"),
                "start_at": _iso_to_local_display(str(item.get("start_at") or "")),
                "end_at": _iso_to_local_display(str(item.get("end_at") or "")),
                "archive_name": str(item.get("_archive_name") or "").strip(),
            }
        )
    return out


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

    def _degree_rank(value: str) -> int:
        return {"高中": 1, "大专": 2, "本科": 3, "硕士": 4, "博士": 5}.get(
            str(value or "").strip(),
            0,
        )

    educations = details_data.get("educations") or []
    if not isinstance(educations, list):
        educations = []
    education_rows = [item for item in educations if isinstance(item, dict)]
    highest = ""
    highest_rank = 0
    for item in education_rows:
        degree = str(item.get("degree") or "").strip()
        rank = _degree_rank(degree)
        if rank > highest_rank:
            highest_rank = rank
            highest = degree
    if not highest:
        highest = str(details_data.get("highest_education") or "").strip()
        highest_rank = _degree_rank(highest)
    education_view: list[dict[str, Any]] = []
    for item in education_rows:
        degree = str(item.get("degree") or "").strip()
        rank = _degree_rank(degree)
        if highest_rank <= 0 or (rank > 0 and rank <= highest_rank):
            education_view.append(dict(item))
    if not education_view:
        education_view = [dict(item) for item in education_rows]
    education_view.sort(
        key=lambda item: (
            _degree_rank(str(item.get("degree") or "")),
            str(item.get("start") or ""),
            str(item.get("end") or ""),
        )
    )
    for item in education_view:
        try:
            tag, label = deps.classify_university(str(item.get("school") or ""))
        except Exception:
            tag, label = "", ""
        item["school_tag"] = tag
        item["school_tag_label"] = label

    projects = details_data.get("projects") or []
    if not isinstance(projects, list):
        projects = []
    project_rows = [item for item in projects if isinstance(item, dict)]
    projects_raw = str(details_data.get("projects_raw") or "").strip()
    project_blocks = validation_helpers._split_projects_raw(projects_raw) if projects_raw else []
    llm_blocks = details_data.get("experience_blocks") or []
    if isinstance(llm_blocks, list) and any(isinstance(item, dict) for item in llm_blocks):
        experience_blocks = [item for item in llm_blocks if isinstance(item, dict)]
    else:
        experience_blocks = project_blocks
    uniq_blocks: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for block in experience_blocks:
        title = str(block.get("title") or "").strip()
        period = str(block.get("period") or "").strip()
        body = str(block.get("body") or "").strip()
        signature = (title, period, body[:120])
        if not title and not body:
            continue
        if signature in seen:
            continue
        seen.add(signature)
        uniq_blocks.append(block)

    evaluation_llm = str(details_data.get("evaluation") or "").strip() or str(
        details_data.get("summary") or ""
    ).strip()
    raw_admin_evaluations = details_data.get("admin_evaluations")
    admin_evaluations: list[dict[str, Any]] = []
    if isinstance(raw_admin_evaluations, list):
        for item in raw_admin_evaluations:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            at = str(item.get("at") or "").strip()
            if not text:
                continue
            at_display = _iso_to_local_display(at) if at else ""
            admin_evaluations.append({"text": text, "at": at, "at_display": at_display})
    else:
        blob = str(details_data.get("admin_evaluation") or "").strip()
        if blob:
            for block in [item.strip() for item in re.split(r"\n\s*\n", blob) if item.strip()]:
                lines = [line.rstrip() for line in block.splitlines()]
                at = ""
                if lines and re.match(r"^\[(.+?)\]\s*$", lines[0].strip()):
                    match = re.match(r"^\[(.+?)\]\s*$", lines[0].strip())
                    at = str(match.group(1) if match else "").strip()
                    lines = lines[1:]
                text = "\n".join(lines).strip()
                if not text:
                    continue
                admin_evaluations.append({"text": text, "at": at, "at_display": at})

    email = ""
    emails = details_data.get("emails") or []
    if isinstance(emails, list) and emails:
        email = str(emails[0] or "").strip()

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
            "educations": education_view,
            "english": details_data.get("english") or {},
            "experience_blocks": uniq_blocks,
            "projects": project_rows,
            "projects_raw": projects_raw,
            "projects_raw_blocks": project_blocks,
            "evaluation_llm": evaluation_llm,
            "admin_evaluations": admin_evaluations,
            "details_status": str(details.get("status") or "").strip(),
            "details_error": str(details.get("error") or "").strip(),
            "attempt_results": _candidate_attempt_results(candidate),
        },
        "resume_parsed": parsed,
    }


def _serialize_assignment_row(row: dict[str, Any]) -> dict[str, Any]:
    token = str(row.get("token") or "").strip()
    status_key = validation_helpers._normalize_exam_status(str(row.get("status") or "").strip())
    invite_end_date = _iso_or_empty(row.get("invite_end_date"))
    if status_key in {"invited", "verified"} and not row.get("entered_at"):
        end_date = _parse_date_ymd(invite_end_date)
        if end_date is not None and datetime.now().astimezone().date() > end_date:
            status_key = "expired"
    candidate_id = int(row.get("candidate_id") or 0)
    candidate_name = str(row.get("name") or "").strip()
    candidate_deleted = bool(row.get("candidate_deleted_at"))
    if _looks_deleted_marker(candidate_name) or not candidate_name:
        candidate_name = f"候选人#{candidate_id}" if candidate_id > 0 else "候选人"
    if candidate_id > 0 and (not candidate_deleted) and candidate_name.startswith("候选人#"):
        try:
            recovered = str(deps.get_candidate_name_from_logs(candidate_id) or "").strip()
        except Exception:
            recovered = ""
        if recovered:
            candidate_name = recovered
    exam_key = str(row.get("exam_key") or "").strip()
    if _looks_deleted_marker(exam_key):
        exam_key = "历史试卷"
    return {
        "attempt_id": int(row.get("attempt_id") or 0),
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "candidate_deleted": candidate_deleted,
        "phone": str(row.get("phone") or "").strip(),
        "exam_key": exam_key,
        "exam_version_id": int(row.get("exam_version_id") or 0),
        "token": token,
        "invite_start_date": _iso_or_empty(row.get("invite_start_date")),
        "invite_end_date": invite_end_date,
        "status": status_key,
        "status_label": _status_label(status_key),
        "entered_at": _iso_or_empty(row.get("entered_at")),
        "finished_at": _iso_or_empty(row.get("finished_at")),
        "score": row.get("score"),
        "created_at": _iso_or_empty(row.get("created_at")),
    }


def _serialize_attempt_detail(token: str) -> dict[str, Any]:
    assignment = deps.load_assignment(token)
    row = runtime_jobs._find_archive_by_token(token, assignment=assignment)
    archive = row.get("archive") if isinstance(row, dict) else None
    if isinstance(archive, dict):
        try:
            archive = runtime_jobs._augment_archive_with_spec(dict(archive))
        except Exception:
            archive = dict(archive)
    else:
        archive = None
    return {
        "assignment": assignment,
        "archive": archive,
    }


def _serialize_log_row(row: dict[str, Any]) -> dict[str, Any]:
    event_type = str(row.get("event_type") or "").strip()
    type_key, type_label = system_status_helpers._oplog_type_label_v2(event_type)
    detail_text = system_status_helpers._oplog_detail_text_v2(dict(row))
    return {
        "id": int(row.get("id") or 0),
        "at": _iso_or_empty(row.get("at")),
        "at_display": _iso_to_local_display(_iso_or_empty(row.get("at"))),
        "actor": str(row.get("actor") or "").strip(),
        "event_type": event_type,
        "candidate_id": row.get("candidate_id"),
        "candidate_name": str(row.get("candidate_name") or "").strip(),
        "candidate_phone": str(row.get("candidate_phone") or "").strip(),
        "exam_key": str(row.get("exam_key") or "").strip(),
        "token": str(row.get("token") or "").strip(),
        "llm_total_tokens": row.get("llm_total_tokens"),
        "duration_seconds": row.get("duration_seconds"),
        "meta": row.get("meta") or {},
        "type_key": type_key,
        "type_label": type_label,
        "detail_text": detail_text,
    }


def _resolve_log_trend_window(
    *,
    days: int,
    tz_offset_minutes: int,
) -> tuple[date, date, datetime, datetime, int]:
    clamped_days = max(7, min(120, int(days or 30)))
    tz_offset_seconds = int(tz_offset_minutes or 0) * 60
    local_now = datetime.now(timezone.utc) + timedelta(seconds=tz_offset_seconds)
    end_day = local_now.date()
    start_day = end_day - timedelta(days=clamped_days - 1)
    start_at = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc) - timedelta(
        seconds=tz_offset_seconds
    )
    end_at = (
        datetime.combine(end_day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        - timedelta(seconds=tz_offset_seconds)
        - timedelta(microseconds=1)
    )
    return start_day, end_day, start_at, end_at, tz_offset_seconds


def _serialize_log_trend(
    rows: list[dict[str, Any]],
    *,
    start_day: date,
    end_day: date,
) -> dict[str, Any]:
    by_day: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        day_text = str(row.get("day") or "")[:10]
        if day_text:
            by_day[day_text] = dict(row)
    days: list[str] = []
    series: dict[str, list[dict[str, Any]]] = {key: [] for key in _LOG_CATEGORY_KEYS}
    cursor = start_day
    while cursor <= end_day:
        day_text = cursor.isoformat()
        row = by_day.get(day_text) or {}
        days.append(day_text)
        for key in _LOG_CATEGORY_KEYS:
            try:
                count = int(row.get(f"{key}_cnt") or 0)
            except Exception:
                count = 0
            series[key].append({"day": day_text, "count": max(0, count)})
        cursor += timedelta(days=1)
    return {
        "start_day": start_day.isoformat(),
        "end_day": end_day.isoformat(),
        "days": days,
        "series": series,
    }


def _parse_assignment_duration(raw: int | str) -> int:
    if isinstance(raw, int):
        return max(0, raw)
    seconds = runtime_jobs._parse_duration_seconds(str(raw or ""))
    if seconds <= 0:
        raise HTTPException(status_code=400, detail="time_limit_seconds 无效")
    return seconds


def _read_resume_bytes(file: UploadFile) -> bytes:
    if not file or not getattr(file, "filename", ""):
        raise HTTPException(status_code=400, detail="缺少简历文件")
    try:
        data = file.file.read() or b""
    except Exception as exc:
        raise HTTPException(status_code=400, detail="简历文件读取失败") from exc
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="简历文件过大，需小于等于 10MB")
    ext = os.path.splitext(str(file.filename or ""))[1].lower()
    if ext not in validation_helpers._ALLOWED_RESUME_EXTS:
        raise HTTPException(status_code=400, detail="仅支持 PDF、DOCX 或图片简历")
    return data


def _parse_resume_payload(
    *,
    data: bytes,
    filename: str,
    mime: str,
    current_phone: str | None = None,
) -> dict[str, Any]:
    try:
        text = deps.extract_resume_text(data, filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"简历解析失败：{type(exc).__name__}") from exc

    parsed_name = ""
    parsed_phone = ""
    name_conf = 0
    phone_conf = 0
    method: dict[str, str] = {"identity": "fast", "name": "fast"}
    llm_total_tokens = 0
    try:
        fast = deps.parse_resume_identity_fast(text or "") or {}
        parsed_name = str(fast.get("name") or "").strip()
        parsed_phone = validation_helpers._normalize_phone(str(fast.get("phone") or "").strip())
        conf = fast.get("confidence") or {}
        if isinstance(conf, dict):
            name_conf = validation_helpers._safe_int(conf.get("name") or 0, 0)
            phone_conf = validation_helpers._safe_int(conf.get("phone") or 0, 0)
    except Exception:
        pass

    if not validation_helpers._is_valid_phone(parsed_phone):
        try:
            with deps.audit_context(meta={}):
                ident = deps.parse_resume_identity_llm(text or "") or {}
                parsed_name = str(ident.get("name") or "").strip()
                parsed_phone = validation_helpers._normalize_phone(str(ident.get("phone") or "").strip())
                conf = ident.get("confidence") or {}
                if isinstance(conf, dict):
                    name_conf = validation_helpers._safe_int(conf.get("name") or 0, 0)
                    phone_conf = validation_helpers._safe_int(conf.get("phone") or 0, 0)
                method["identity"] = "llm"
                method["name"] = "llm"
                ctx = deps.get_audit_context()
                meta = ctx.get("meta")
                if isinstance(meta, dict):
                    llm_total_tokens += int(meta.get("llm_total_tokens_sum") or 0)
        except Exception:
            pass

    if validation_helpers._is_valid_phone(parsed_phone) and not validation_helpers._is_valid_name(parsed_name):
        try:
            with deps.audit_context(meta={}):
                name_info = deps.parse_resume_name_llm(text or "") or {}
                candidate_name = str(name_info.get("name") or "").strip()
                confidence = validation_helpers._safe_int(name_info.get("confidence") or 0, 0)
                if validation_helpers._is_valid_name(candidate_name):
                    parsed_name = candidate_name
                    name_conf = max(name_conf, confidence)
                    method["name"] = "llm"
                ctx = deps.get_audit_context()
                meta = ctx.get("meta")
                if isinstance(meta, dict):
                    llm_total_tokens += int(meta.get("llm_total_tokens_sum") or 0)
        except Exception:
            pass

    if current_phone:
        normalized_current_phone = validation_helpers._normalize_phone(current_phone)
        if validation_helpers._is_valid_phone(parsed_phone) and normalized_current_phone and parsed_phone != normalized_current_phone:
            raise HTTPException(status_code=400, detail="简历手机号与候选人手机号不一致")

    details: dict[str, Any] = {}
    details_error = ""
    try:
        with deps.audit_context(meta={}):
            parsed_details = deps.parse_resume_details_llm(text or "")
            if isinstance(parsed_details, dict):
                details = parsed_details
            ctx = deps.get_audit_context()
            meta = ctx.get("meta")
            if isinstance(meta, dict):
                llm_total_tokens += int(meta.get("llm_total_tokens_sum") or 0)
    except Exception as exc:
        deps.logger.exception("Resume details parse failed")
        details_error = f"{type(exc).__name__}: {exc}"

    try:
        experience_raw = deps.extract_experience_raw(text or "", max_chars=20000)
        if experience_raw:
            details["projects_raw"] = deps.clean_projects_raw_for_display(experience_raw)
    except Exception:
        pass

    details_block: dict[str, Any] = {
        "status": "failed" if details_error else ("done" if details else "empty"),
        "data": details,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }
    if details_error:
        details_block["error"] = details_error

    return {
        "resume_parsed": {
            "extracted": {"name": parsed_name, "phone": parsed_phone},
            "confidence": {
                "name": max(0, min(100, validation_helpers._safe_int(name_conf, 0))),
                "phone": max(0, min(100, validation_helpers._safe_int(phone_conf, 0))),
            },
            "source_filename": filename,
            "source_mime": mime,
            "method": method,
            "details": details_block,
        },
        "parsed_name": parsed_name,
        "parsed_phone": parsed_phone,
        "llm_total_tokens": llm_total_tokens,
    }


@router.post("/session/login")
def login(payload: AdminLoginPayload, request: Request, container=Depends(get_container)):
    settings = container.settings
    if payload.username != settings.admin_username or payload.password != settings.admin_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    request.session["admin_logged_in"] = True
    request.session["admin_username"] = payload.username
    return {"ok": True, "username": payload.username}


@router.post("/session/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/session")
def session(request: Request):
    return {
        "authenticated": bool(request.session.get("admin_logged_in")),
        "username": request.session.get("admin_username"),
    }


@router.get("/bootstrap")
def bootstrap(request: Request, container=Depends(get_container)):
    _require_admin(request)
    runtime_config = container.runtime_service.get_runtime_config().model_dump()
    return {
        "brand": {"name": "MD Quiz", "theme": runtime_config.get("ui_theme_name") or "blue-green"},
        "navigation": [
            {"key": "exams", "label": "试卷", "href": "/admin/exams"},
            {"key": "candidates", "label": "候选人", "href": "/admin/candidates"},
            {"key": "assignments", "label": "邀约与答题", "href": "/admin/assignments"},
            {"key": "logs", "label": "系统日志", "href": "/admin/logs"},
            {"key": "status", "label": "系统状态", "href": "/admin/status"},
        ],
        "runtime_config": runtime_config,
        "cards": [
            {"label": "后端架构", "value": "FastAPI + Worker + Scheduler"},
            {"label": "后台入口", "value": "/admin"},
            {"label": "兼容跳转", "value": "/legacy/* -> /*"},
        ],
    }


@router.get("/config")
def get_runtime_config(request: Request, container=Depends(get_container)):
    _require_admin(request)
    return container.runtime_service.get_runtime_config().model_dump()


@router.put("/config")
def update_runtime_config(payload: RuntimeConfigPatch, request: Request, container=Depends(get_container)):
    _require_admin(request)
    updates = payload.model_dump(exclude_none=True)
    return container.runtime_service.update_runtime_config(updates).model_dump()


@router.get("/jobs")
def list_jobs(request: Request, container=Depends(get_container)):
    _require_admin(request)
    return {"items": [item.model_dump() for item in container.job_service.list_jobs()]}


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
def enqueue_job(payload: EnqueueJobPayload, request: Request, container=Depends(get_container)):
    _require_admin(request)
    job = container.job_service.enqueue(payload.kind, payload=payload.payload, source="admin-api")
    return job.model_dump()


@router.get("/exams")
def list_exams(request: Request, q: str = "", page: int = 1):
    _require_admin(request)
    exams = exam_helpers._list_exams()
    query = str(q or "").strip().lower()
    if query:
        exams = [
            item
            for item in exams
            if query in str(item.get("exam_key") or "").lower()
            or query in str(item.get("title") or "").lower()
            or query in str(item.get("id") or "")
            or any(query in str(tag or "").lower() for tag in (item.get("tags") or []))
        ]
    exams.sort(key=lambda item: float(item.get("_mtime") or 0), reverse=True)
    per_page = 20
    total = len(exams)
    total_pages = max(1, (total + per_page - 1) // per_page)
    current_page = max(1, min(int(page or 1), total_pages))
    start = (current_page - 1) * per_page
    items = [_serialize_exam_summary(item, request) for item in exams[start : start + per_page]]
    return {
        "items": items,
        "page": current_page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "sync_state": deps.read_exam_repo_sync_state(),
    }


@router.post("/exams/sync")
def sync_exams(payload: SyncExamPayload, request: Request):
    _require_admin(request)
    repo_url = str(payload.repo_url or "").strip()
    try:
        result = deps.enqueue_exam_repo_sync(repo_url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"同步任务创建失败：{exc}") from exc
    try:
        deps.log_event(
            "exam.sync.enqueue",
            actor="admin",
            meta={
                "repo_url": repo_url,
                "job_id": str(result.get("job_id") or ""),
                "created": bool(result.get("created")),
            },
        )
    except Exception:
        pass
    return result


@router.get("/exams/{exam_key}")
def get_exam_detail(exam_key: str, request: Request):
    _require_admin(request)
    exam = deps.get_exam_definition(str(exam_key or "").strip())
    if not exam:
        raise HTTPException(status_code=404, detail="试卷不存在")
    selected_version = None
    current_version_id = int(exam.get("current_version_id") or 0)
    if current_version_id > 0:
        selected_version = exam_helpers.get_exam_version_snapshot(current_version_id)
    return _serialize_exam_detail(exam, request=request, selected_version=selected_version)


@router.get("/exam-versions/{version_id}")
def get_exam_version_detail(version_id: int, request: Request):
    _require_admin(request)
    version = exam_helpers.get_exam_version_snapshot(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")
    exam = deps.get_exam_definition(str(version.get("exam_key") or "").strip())
    if not exam:
        raise HTTPException(status_code=404, detail="试卷不存在")
    return _serialize_exam_detail(exam, request=request, selected_version=version)


@router.post("/exams/{exam_key}/public-invite")
def toggle_exam_public_invite(exam_key: str, payload: PublicInviteTogglePayload, request: Request):
    _require_admin(request)
    exam = deps.get_exam_definition(str(exam_key or "").strip())
    if not exam:
        raise HTTPException(status_code=404, detail="试卷不存在")
    cfg = exam_helpers.set_public_invite_enabled(str(exam_key or "").strip(), payload.enabled)
    public_token = str(cfg.get("token") or "").strip()
    try:
        deps.log_event(
            "exam.public_invite.enable" if payload.enabled else "exam.public_invite.disable",
            actor="admin",
            exam_key=str(exam_key or "").strip(),
            meta={"public_token": public_token},
        )
    except Exception:
        pass
    return {
        "ok": True,
        "enabled": bool(cfg.get("enabled")),
        "token": public_token,
        "public_url": f"{_admin_base_url(request)}/p/{public_token}" if public_token else "",
        "qr_url": f"/api/public/invites/{public_token}/qr.png" if public_token else "",
    }


@router.get("/candidates")
def get_candidates(
    request: Request,
    q: str = "",
    created_from: str = "",
    created_to: str = "",
    page: int = 1,
):
    _require_admin(request)
    created_from_raw = str(created_from or "").strip() or (datetime.now().date() - timedelta(days=29)).isoformat()
    created_to_raw = str(created_to or "").strip() or datetime.now().date().isoformat()
    parsed_from = _parse_candidate_query_dates(created_from_raw, end_of_day=False)
    parsed_to = _parse_candidate_query_dates(created_to_raw, end_of_day=True)
    per_page = 20
    total = deps.count_candidates(query=q or None, created_from=parsed_from, created_to=parsed_to)
    total_pages = max(1, (total + per_page - 1) // per_page)
    current_page = max(1, min(int(page or 1), total_pages))
    offset = (current_page - 1) * per_page
    items = deps.list_candidates(
        limit=per_page,
        offset=offset,
        query=q or None,
        created_from=parsed_from,
        created_to=parsed_to,
    )
    return {
        "items": [
            {
                "id": int(item.get("id") or 0),
                "name": str(item.get("name") or "").strip(),
                "phone": str(item.get("phone") or "").strip(),
                "created_at": _iso_or_empty(item.get("created_at")),
                "has_resume": bool(item.get("has_resume")),
            }
            for item in items
        ],
        "page": current_page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "filters": {
            "q": str(q or "").strip(),
            "created_from": created_from_raw,
            "created_to": created_to_raw,
        },
    }


@router.post("/candidates", status_code=status.HTTP_201_CREATED)
def create_candidate(payload: CandidateCreatePayload, request: Request):
    _require_admin(request)
    name = str(payload.name or "").strip()
    phone = validation_helpers._normalize_phone(payload.phone)
    if not validation_helpers._is_valid_name(name):
        raise HTTPException(status_code=400, detail="姓名格式不正确")
    if not validation_helpers._is_valid_phone(phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")
    if deps.get_candidate_by_phone(phone):
        raise HTTPException(status_code=409, detail="候选人已存在")
    try:
        candidate_id = int(deps.create_candidate(name=name, phone=phone))
        deps.log_event("candidate.create", actor="admin", candidate_id=candidate_id, meta={"name": name, "phone": phone})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="创建候选人失败") from exc
    return {"id": candidate_id, "name": name, "phone": phone}


@router.post("/candidates/resume/upload")
def upload_candidate_resume(request: Request, file: UploadFile = File(...)):
    _require_admin(request)
    data = _read_resume_bytes(file)
    filename = str(file.filename or "")
    mime = str(file.content_type or "")
    payload = _parse_resume_payload(data=data, filename=filename, mime=mime)
    parsed_phone = validation_helpers._normalize_phone(str(payload.get("parsed_phone") or ""))
    if not validation_helpers._is_valid_phone(parsed_phone):
        raise HTTPException(status_code=400, detail="未能从简历中识别有效手机号")
    parsed_name = str(payload.get("parsed_name") or "").strip()
    candidate_name = parsed_name if validation_helpers._is_valid_name(parsed_name) else "未知"
    existed = deps.get_candidate_by_phone(parsed_phone)
    created = False
    if existed:
        candidate_id = int(existed.get("id") or 0)
        old_name = str(existed.get("name") or "").strip()
        if old_name in {"", "未知"} and candidate_name != "未知":
            deps.update_candidate(candidate_id, name=candidate_name, phone=parsed_phone)
    else:
        candidate_id = int(deps.create_candidate(name=candidate_name, phone=parsed_phone))
        created = True
    deps.update_candidate_resume(
        candidate_id,
        resume_bytes=data,
        resume_filename=filename,
        resume_mime=mime,
        resume_size=len(data),
        resume_parsed=payload["resume_parsed"],
    )
    try:
        deps.log_event(
            "candidate.resume.parse",
            actor="admin",
            candidate_id=candidate_id,
            llm_total_tokens=(int(payload.get("llm_total_tokens") or 0) or None),
        )
        if created:
            deps.log_event(
                "candidate.create",
                actor="admin",
                candidate_id=candidate_id,
                meta={"name": candidate_name, "phone": parsed_phone},
            )
    except Exception:
        pass
    candidate = deps.get_candidate(candidate_id) or {"id": candidate_id, "name": candidate_name, "phone": parsed_phone}
    return _serialize_candidate_detail(candidate_id, candidate)


@router.get("/candidates/{candidate_id}")
def get_candidate_detail(candidate_id: int, request: Request):
    _require_admin(request)
    candidate = deps.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人不存在")
    try:
        deps.log_event(
            "candidate.read",
            actor="admin",
            candidate_id=int(candidate_id),
            meta={"name": str(candidate.get("name") or "").strip(), "phone": str(candidate.get("phone") or "").strip()},
        )
    except Exception:
        pass
    return _serialize_candidate_detail(candidate_id, candidate)


@router.delete("/candidates/{candidate_id}")
def remove_candidate(candidate_id: int, request: Request):
    _require_admin(request)
    candidate = deps.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人不存在")
    try:
        deps.delete_candidate(candidate_id)
        deps.log_event(
            "candidate.delete",
            actor="admin",
            candidate_id=int(candidate_id),
            meta={"name": str(candidate.get("name") or "").strip(), "phone": str(candidate.get("phone") or "").strip()},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="删除失败") from exc
    return {"ok": True}


@router.post("/candidates/{candidate_id}/evaluation")
def update_candidate_evaluation(candidate_id: int, payload: CandidateEvaluationPayload, request: Request):
    _require_admin(request)
    candidate = deps.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人不存在")
    evaluation = str(payload.evaluation or "").strip()
    if not evaluation:
        raise HTTPException(status_code=400, detail="评价不能为空")
    parsed = candidate.get("resume_parsed") or {}
    if not isinstance(parsed, dict):
        parsed = {}
    details = parsed.get("details") or {}
    if not isinstance(details, dict):
        details = {}
    details_data = details.get("data") or {}
    if not isinstance(details_data, dict):
        details_data = {}
    existing = details_data.get("admin_evaluations")
    items: list[dict[str, str]] = []
    if isinstance(existing, list):
        for item in existing:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            at = str(item.get("at") or "").strip()
            if text:
                items.append({"text": text, "at": at})
    now_iso = datetime.now(timezone.utc).isoformat()
    items.append({"text": evaluation, "at": now_iso})
    details_data["admin_evaluations"] = items
    details_data["admin_evaluation"] = ""
    details["data"] = details_data
    parsed["details"] = details
    deps.update_candidate_resume_parsed(
        candidate_id,
        resume_parsed=parsed,
        touch_resume_parsed_at=False,
    )
    return _serialize_candidate_detail(candidate_id, deps.get_candidate(candidate_id) or candidate)


@router.get("/candidates/{candidate_id}/resume")
def download_candidate_resume(candidate_id: int, request: Request):
    _require_admin(request)
    candidate = deps.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人不存在")
    resume = deps.get_candidate_resume(candidate_id)
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    data = resume.get("resume_bytes") or b""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise HTTPException(status_code=404, detail="简历不存在")
    filename = os.path.basename(str(resume.get("resume_filename") or "").strip()) or f"candidate_{candidate_id}_resume.bin"
    mime = str(resume.get("resume_mime") or "").strip() or "application/octet-stream"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=bytes(data), media_type=mime, headers=headers)


@router.post("/candidates/{candidate_id}/resume/reparse")
def reparse_candidate_resume(candidate_id: int, request: Request, file: UploadFile = File(...)):
    _require_admin(request)
    candidate = deps.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人不存在")
    data = _read_resume_bytes(file)
    filename = str(file.filename or "")
    mime = str(file.content_type or "")
    current_phone = str(candidate.get("phone") or "").strip()
    payload = _parse_resume_payload(data=data, filename=filename, mime=mime, current_phone=current_phone)
    parsed_name = str(payload.get("parsed_name") or "").strip()
    if str(candidate.get("name") or "").strip() in {"", "未知"} and validation_helpers._is_valid_name(parsed_name):
        deps.update_candidate(candidate_id, name=parsed_name, phone=current_phone)
    deps.update_candidate_resume(
        candidate_id,
        resume_bytes=data,
        resume_filename=filename,
        resume_mime=mime,
        resume_size=len(data),
        resume_parsed=payload["resume_parsed"],
    )
    try:
        deps.log_event(
            "candidate.resume.parse",
            actor="admin",
            candidate_id=int(candidate_id),
            llm_total_tokens=(int(payload.get("llm_total_tokens") or 0) or None),
            meta={"reparse": True},
        )
    except Exception:
        pass
    return _serialize_candidate_detail(candidate_id, deps.get_candidate(candidate_id) or candidate)


@router.get("/assignments")
def get_assignments(
    request: Request,
    q: str = "",
    start_from: str = "",
    start_to: str = "",
    page: int = 1,
):
    _require_admin(request)
    per_page = 20
    total = deps.count_exam_papers(
        query=q or None,
        invite_start_from=str(start_from or "").strip() or None,
        invite_start_to=str(start_to or "").strip() or None,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    current_page = max(1, min(int(page or 1), total_pages))
    offset = (current_page - 1) * per_page
    rows = deps.list_exam_papers(
        query=q or None,
        invite_start_from=str(start_from or "").strip() or None,
        invite_start_to=str(start_to or "").strip() or None,
        limit=per_page,
        offset=offset,
    )
    return {
        "items": [_serialize_assignment_row(row) for row in rows],
        "page": current_page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "filters": {"q": str(q or "").strip(), "start_from": start_from, "start_to": start_to},
    }


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
def create_assignment(payload: AssignmentCreatePayload, request: Request):
    _require_admin(request)
    exam_key = str(payload.exam_key or "").strip()
    if not exam_key:
        raise HTTPException(status_code=400, detail="缺少 exam_key")
    candidate = deps.get_candidate(int(payload.candidate_id))
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人不存在")
    exam = deps.get_exam_definition(exam_key)
    exam_version_id = exam_helpers.resolve_exam_version_id_for_new_assignment(exam_key)
    if not exam or not exam_version_id:
        raise HTTPException(status_code=400, detail="试卷不可用")
    start_date = _parse_date_ymd(payload.invite_start_date)
    end_date = _parse_date_ymd(payload.invite_end_date)
    if start_date is None or end_date is None:
        raise HTTPException(status_code=400, detail="答题日期无效")
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="答题结束日期不能早于开始日期")
    time_limit_seconds = _parse_assignment_duration(payload.time_limit_seconds)
    result = deps.create_assignment(
        exam_key=exam_key,
        candidate_id=int(payload.candidate_id),
        exam_version_id=exam_version_id,
        base_url=_admin_base_url(request),
        phone=str(candidate.get("phone") or ""),
        invite_start_date=start_date.isoformat(),
        invite_end_date=end_date.isoformat(),
        time_limit_seconds=time_limit_seconds,
        min_submit_seconds=payload.min_submit_seconds,
        verify_max_attempts=int(payload.verify_max_attempts or 3),
        pass_threshold=int(payload.pass_threshold or 60),
    )
    token = str(result.get("token") or "").strip()
    try:
        deps.create_exam_paper(
            candidate_id=int(payload.candidate_id),
            phone=str(candidate.get("phone") or ""),
            exam_key=exam_key,
            exam_version_id=exam_version_id,
            token=token,
            invite_start_date=start_date.isoformat(),
            invite_end_date=end_date.isoformat(),
            status="invited",
        )
    except Exception:
        deps.logger.exception("Create exam_paper failed (candidate_id=%s, exam_key=%s)", payload.candidate_id, exam_key)
    try:
        deps.log_event(
            "assignment.create",
            actor="admin",
            candidate_id=int(payload.candidate_id),
            exam_key=exam_key,
            token=token or None,
            meta={
                "invite_start_date": start_date.isoformat(),
                "invite_end_date": end_date.isoformat(),
            },
        )
    except Exception:
        pass
    return {
        "token": token,
        "url": result.get("url"),
        "qr_url": f"/api/admin/assignments/{token}/qr.png" if token else "",
    }


@router.get("/assignments/{token}")
def get_assignment_detail(token: str, request: Request):
    _require_admin(request)
    try:
        return _serialize_attempt_detail(token)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="答题记录不存在") from exc


@router.get("/attempts/{token}")
def get_attempt_detail(token: str, request: Request):
    return get_assignment_detail(token, request)


@router.get("/results/{token}")
def get_result_detail(token: str, request: Request):
    return get_assignment_detail(token, request)


@router.get("/assignments/{token}/qr.png")
def get_assignment_qr(token: str, request: Request):
    _require_admin(request)
    try:
        deps.load_assignment(token)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="答题记录不存在") from exc
    try:
        import qrcode  # type: ignore
    except Exception as exc:
        raise HTTPException(status_code=500, detail="二维码依赖不可用") from exc
    url = f"{_admin_base_url(request)}/t/{str(token or '').strip()}"
    image = qrcode.make(url)
    buffer = BytesIO()
    try:
        image.save(buffer, format="PNG")
    except TypeError:
        image.save(buffer)
    return Response(content=buffer.getvalue(), media_type="image/png")


@router.get("/attempt-status")
def get_attempt_status(request: Request, tokens: str = ""):
    _require_admin(request)
    values = [item.strip() for item in str(tokens or "").split(",") if item.strip()][:50]
    items: list[dict[str, Any]] = []
    today_local = datetime.now().astimezone().date()
    for token in values:
        exam_paper = deps.get_exam_paper_by_token(token) or {}
        if not exam_paper:
            continue
        status_key = validation_helpers._normalize_exam_status(exam_paper.get("status"))
        invite_end_date = _iso_or_empty(exam_paper.get("invite_end_date"))
        if status_key in {"invited", "verified"} and not exam_paper.get("entered_at"):
            end_date = _parse_date_ymd(invite_end_date)
            if end_date is not None and today_local > end_date:
                status_key = "expired"
        items.append(
            {
                "token": token,
                "status": status_key,
                "status_label": _status_label(status_key),
                "score": exam_paper.get("score"),
            }
        )
    return {"items": items}


@router.get("/logs")
def get_logs(
    request: Request,
    page: int = 1,
    limit: int = 20,
    days: int = Query(default=30, ge=7, le=120),
    tz_offset_minutes: int = Query(default=0, ge=-720, le=840),
):
    _require_admin(request)
    page_size = max(1, min(100, int(limit or 20)))
    total = int(deps.count_operation_logs() or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    current_page = max(1, min(int(page or 1), total_pages))
    offset = (current_page - 1) * page_size
    rows = deps.list_operation_logs(limit=page_size, offset=offset)
    start_day, end_day, start_at, end_at, tz_offset_seconds = _resolve_log_trend_window(
        days=int(days or 30),
        tz_offset_minutes=int(tz_offset_minutes or 0),
    )
    trend_rows = deps.list_operation_daily_counts_by_category(
        tz_offset_seconds=tz_offset_seconds,
        at_from=start_at,
        at_to=end_at,
    )
    return {
        "items": [_serialize_log_row(row) for row in rows],
        "page": current_page,
        "per_page": page_size,
        "total": total,
        "total_pages": total_pages,
        "counts": deps.count_operation_logs_by_category(),
        "trend": _serialize_log_trend(trend_rows, start_day=start_day, end_day=end_day),
    }


@router.get("/logs/updates")
def get_log_updates(request: Request, after_id: int = 0, limit: int = 20):
    _require_admin(request)
    page_size = max(1, min(50, int(limit or 20)))
    rows = deps.list_operation_logs_after_id(after_id=int(after_id or 0), limit=page_size)
    items = [_serialize_log_row(row) for row in rows]
    items.sort(key=lambda item: int(item.get("id") or 0))
    return {"ok": True, "items": items}


@router.get("/system-status/summary")
def get_system_status_summary(request: Request):
    _require_admin(request)
    return system_status_helpers._get_cached_system_status_summary()


@router.get("/system-status")
def get_system_status_range(
    request: Request,
    start: str = "",
    end: str = "",
):
    _require_admin(request)
    today = datetime.now().astimezone().date()
    start_day = _parse_date_ymd(start) or (today - timedelta(days=29))
    end_day = _parse_date_ymd(end) or today
    data = system_status_helpers._compute_system_status_range(start_day=start_day, end_day=end_day)
    return {"ok": True, "config": system_status_helpers._load_system_status_cfg(), "data": data}


@router.put("/system-status/config")
def update_system_status_config(payload: dict[str, Any], request: Request):
    _require_admin(request)
    config = system_status_helpers._save_system_status_cfg(payload if isinstance(payload, dict) else {})
    try:
        deps.emit_alerts_for_current_snapshot()
    except Exception:
        pass
    return {
        "ok": True,
        "config": config,
        "summary": system_status_helpers._get_cached_system_status_summary(force=True),
    }


@router.post("/system-status/alerts/cleanup")
def cleanup_system_status_alerts(payload: dict[str, Any], request: Request):
    _require_admin(request)
    body = payload if isinstance(payload, dict) else {}
    day = str(body.get("day") or "").strip()
    kind = str(body.get("kind") or "").strip()
    try:
        deleted = int(deps.cleanup_duplicate_system_alert_logs(day=(day or None), kind=(kind or None)))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "deleted": deleted, "day": day, "kind": kind}


@router.post("/system-status/alerts/backfill")
def backfill_system_status_alerts(payload: dict[str, Any], request: Request):
    _require_admin(request)
    body = payload if isinstance(payload, dict) else {}
    day = str(body.get("day") or "").strip()
    kind = str(body.get("kind") or "").strip()
    if not day or kind not in {"llm_tokens", "sms_calls"}:
        raise HTTPException(status_code=400, detail="invalid day/kind")
    try:
        inserted = int(deps.backfill_missing_system_alert_levels(day=day, kind=kind))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "inserted": inserted, "day": day, "kind": kind}
