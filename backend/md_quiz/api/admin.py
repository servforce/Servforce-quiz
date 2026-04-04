from __future__ import annotations

import hmac
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, Field

from backend.md_quiz.services import exam_helpers, runtime_jobs, support_deps as deps
from backend.md_quiz.services import system_status_helpers, validation_helpers
from backend.md_quiz.services.exam_repo_sync_service import ExamRepoSyncError

from .deps import get_container

router = APIRouter(prefix="/api/admin", tags=["admin"])

_LOG_CATEGORY_KEYS = ("candidate", "quiz", "grading", "assignment", "system")


class AdminLoginPayload(BaseModel):
    username: str
    password: str


class RuntimeConfigPatch(BaseModel):
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


class RepoBindingPayload(BaseModel):
    repo_url: str = ""


class RepoRebindPayload(BaseModel):
    repo_url: str = ""
    confirmation_text: str = ""


class PublicInviteTogglePayload(BaseModel):
    enabled: bool


class CandidateCreatePayload(BaseModel):
    name: str
    phone: str


class CandidateEvaluationPayload(BaseModel):
    evaluation: str


class AssignmentCreatePayload(BaseModel):
    quiz_key: str
    candidate_id: int
    time_limit_seconds: int | str | None = None
    invite_start_date: str
    invite_end_date: str
    min_submit_seconds: int | None = None
    require_phone_verification: bool = False
    ignore_timing: bool = False
    verify_max_attempts: int = 3


class AssignmentHandlingPayload(BaseModel):
    handled: bool


def _require_admin(request: Request) -> None:
    if not request.session.get("admin_logged_in"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="需要先登录后台")


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


def _coerce_int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _normalize_answer_keys(value: Any) -> list[str]:
    if isinstance(value, list):
        items = value
    elif value is None:
        items = []
    else:
        items = [value]
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized


def _has_trait_options(options: list[dict[str, Any]]) -> bool:
    return any(isinstance((option or {}).get("traits"), dict) and (option or {}).get("traits") for option in options)


def _normalize_review_options(raw_options: Any, *, spec_question: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    current_options = [dict(option) for option in (raw_options or []) if isinstance(option, dict)]
    current_by_key = {str(option.get("key") or "").strip(): option for option in current_options if str(option.get("key") or "").strip()}
    spec_options = [dict(option) for option in ((spec_question or {}).get("options") or []) if isinstance(option, dict)]
    if spec_options:
        merged: list[dict[str, Any]] = []
        for spec_option in spec_options:
            key = str(spec_option.get("key") or "").strip()
            current_option = current_by_key.get(key) or {}
            item: dict[str, Any] = {
                "key": current_option.get("key") or spec_option.get("key"),
                "text": current_option.get("text") or spec_option.get("text") or "",
            }
            if "correct" in current_option or "correct" in spec_option:
                item["correct"] = bool(current_option.get("correct")) or bool(spec_option.get("correct"))
            traits = current_option.get("traits")
            if not isinstance(traits, dict) or not traits:
                traits = spec_option.get("traits")
            if isinstance(traits, dict) and traits:
                item["traits"] = dict(traits)
            merged.append(item)
        return merged

    normalized: list[dict[str, Any]] = []
    for option in current_options:
        item = {
            "key": option.get("key"),
            "text": option.get("text") or "",
        }
        if "correct" in option:
            item["correct"] = bool(option.get("correct"))
        traits = option.get("traits")
        if isinstance(traits, dict) and traits:
            item["traits"] = dict(traits)
        normalized.append(item)
    return normalized


def _review_question_kind(question_type: str, options: list[dict[str, Any]]) -> str:
    qtype = str(question_type or "").strip().lower()
    if qtype == "short":
        return "short"
    if qtype in {"single", "multiple"} and _has_trait_options(options):
        return "traits"
    if qtype in {"single", "multiple"}:
        return "objective"
    return "unknown"


def _build_review_answer_item(
    raw_question: dict[str, Any],
    *,
    spec_question: dict[str, Any] | None = None,
    public_question: dict[str, Any] | None = None,
) -> dict[str, Any]:
    qid = str(raw_question.get("qid") or (spec_question or {}).get("qid") or "").strip()
    qtype = str(raw_question.get("type") or (spec_question or {}).get("type") or (public_question or {}).get("type") or "").strip()
    options = _normalize_review_options(raw_question.get("options"), spec_question=spec_question)
    review_kind = _review_question_kind(qtype, options)
    score = _coerce_int_or_none(raw_question.get("score"))
    max_points = _coerce_int_or_none(
        raw_question.get("max_points")
        or (spec_question or {}).get("max_points")
        or (spec_question or {}).get("points")
        or (public_question or {}).get("max_points")
        or (public_question or {}).get("points")
    )
    score_max = _coerce_int_or_none(raw_question.get("score_max"))
    if score_max is None:
        score_max = max_points
    stem_md = str(
        raw_question.get("stem_md")
        or (public_question or {}).get("stem_md")
        or (spec_question or {}).get("stem_md")
        or ""
    )
    stem_html = str(raw_question.get("stem_html") or "").strip() or exam_helpers._render_markdown_html(stem_md)
    answer = raw_question.get("answer")
    selected_options = _normalize_answer_keys(answer) if qtype in {"single", "multiple"} else []
    correct_options = [
        str(option.get("key") or "").strip()
        for option in options
        if bool(option.get("correct")) and str(option.get("key") or "").strip()
    ]
    has_answer = bool(str(answer or "").strip()) if qtype == "short" else bool(selected_options)
    is_correct: bool | None = None
    is_partial = False
    if review_kind == "objective" and has_answer:
        is_correct = set(selected_options) == set(correct_options)
        is_partial = not bool(is_correct) and score is not None and int(score or 0) > 0 and int(score or 0) < int(score_max or 0)
    score_display = _score_display(score, score_max, result_mode="scored") if review_kind != "traits" and score is not None else ""
    return {
        "qid": qid,
        "label": raw_question.get("label") or (spec_question or {}).get("label") or (public_question or {}).get("label") or qid,
        "type": qtype,
        "review_kind": review_kind,
        "is_trait_question": review_kind == "traits",
        "max_points": max_points,
        "score": score,
        "score_max": score_max,
        "has_score": review_kind != "traits" and score is not None,
        "score_display": score_display,
        "stem_md": stem_md,
        "stem_html": stem_html,
        "answer": answer,
        "has_answer": has_answer,
        "options": options,
        "correct_options": correct_options,
        "selected_options": selected_options,
        "is_correct": is_correct,
        "is_partial": is_partial,
        "reason": str(raw_question.get("reason") or "").strip(),
        "rubric": str(raw_question.get("rubric") or (spec_question or {}).get("rubric") or "").strip(),
    }


def _build_grading_details_by_qid(grading: Any) -> dict[str, dict[str, Any]]:
    details: dict[str, dict[str, Any]] = {}
    current = grading if isinstance(grading, dict) else {}
    for item in (current.get("objective") or []):
        qid = str((item or {}).get("qid") or "").strip()
        if qid:
            details[qid] = dict(item)
    for item in (current.get("subjective") or []):
        qid = str((item or {}).get("qid") or "").strip()
        if qid:
            details[qid] = dict(item)
    return details


def _resolve_attempt_snapshot(
    assignment: dict[str, Any] | None,
    archive: dict[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(assignment, dict) and assignment:
        snapshot = exam_helpers.get_exam_snapshot_for_assignment(assignment)
        if isinstance(snapshot, dict) and snapshot:
            return snapshot
    exam = (archive or {}).get("exam") or {}
    try:
        quiz_version_id = int(exam.get("quiz_version_id") or 0)
    except Exception:
        quiz_version_id = 0
    if quiz_version_id > 0:
        snapshot = exam_helpers.get_quiz_version_snapshot(quiz_version_id)
        if isinstance(snapshot, dict) and snapshot:
            return snapshot
    quiz_key = str(exam.get("quiz_key") or "").strip()
    if quiz_key:
        snapshot = deps.get_quiz_definition(quiz_key) or {}
        if isinstance(snapshot, dict):
            return snapshot
    return {}


def _build_review_answers(
    *,
    archive: dict[str, Any] | None,
    assignment: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    snapshot = _resolve_attempt_snapshot(assignment, archive)
    spec_questions = [dict(question) for question in ((snapshot.get("spec") or {}).get("questions") or []) if isinstance(question, dict)]
    spec_by_qid = {str(question.get("qid") or "").strip(): question for question in spec_questions if str(question.get("qid") or "").strip()}
    public_by_qid = {
        str(question.get("qid") or "").strip(): question
        for question in (((snapshot.get("public_spec") or {}).get("questions") or []))
        if isinstance(question, dict) and str(question.get("qid") or "").strip()
    }
    if isinstance(archive, dict) and isinstance(archive.get("questions"), list) and archive.get("questions"):
        answers: list[dict[str, Any]] = []
        for raw_question in archive.get("questions") or []:
            if not isinstance(raw_question, dict):
                continue
            qid = str(raw_question.get("qid") or "").strip()
            answers.append(
                _build_review_answer_item(
                    dict(raw_question),
                    spec_question=spec_by_qid.get(qid),
                    public_question=public_by_qid.get(qid),
                )
            )
        return answers

    if not isinstance(assignment, dict) or not spec_questions:
        return []

    grading = assignment.get("grading") or {}
    scored_by_qid = _build_grading_details_by_qid(grading)
    assignment_answers = assignment.get("answers") or {}
    answers: list[dict[str, Any]] = []
    for spec_question in spec_questions:
        qid = str(spec_question.get("qid") or "").strip()
        score_detail = scored_by_qid.get(qid) or {}
        raw_question = {
            "qid": qid,
            "label": spec_question.get("label") or qid,
            "type": spec_question.get("type"),
            "max_points": spec_question.get("max_points") or spec_question.get("points"),
            "stem_md": (public_by_qid.get(qid) or {}).get("stem_md") or spec_question.get("stem_md"),
            "options": spec_question.get("options"),
            "rubric": spec_question.get("rubric"),
            "answer": assignment_answers.get(qid),
            "score": score_detail.get("score"),
            "score_max": score_detail.get("max") or spec_question.get("max_points") or spec_question.get("points"),
            "reason": score_detail.get("reason"),
        }
        answers.append(
            _build_review_answer_item(
                raw_question,
                spec_question=spec_question,
                public_question=public_by_qid.get(qid),
            )
        )
    return answers


def _result_mode_label(result_mode: str) -> str:
    mapping = {
        "scored": "计分题",
        "traits": "量表题",
        "mixed": "计分 + 量表",
    }
    key = str(result_mode or "").strip().lower()
    return mapping.get(key, "未定义")


def _build_review_evaluation(
    *,
    archive: dict[str, Any] | None,
    assignment: dict[str, Any] | None,
) -> dict[str, Any]:
    archive_data = archive if isinstance(archive, dict) else {}
    assignment_data = assignment if isinstance(assignment, dict) else {}
    grading = archive_data.get("grading") or assignment_data.get("grading") or {}
    raw_total = _coerce_int_or_none((grading or {}).get("raw_total")) if isinstance(grading, dict) else None
    result_mode = str(
        archive_data.get("result_mode")
        or (grading.get("result_mode") if isinstance(grading, dict) else "")
        or ("traits" if isinstance(grading, dict) and raw_total == 0 and grading else "")
    ).strip().lower()
    total_score = _coerce_int_or_none(archive_data.get("total_score"))
    if total_score is None and isinstance(grading, dict):
        total_score = _coerce_int_or_none(grading.get("total"))
    score_max = _coerce_int_or_none(archive_data.get("score_max"))
    if score_max is None and isinstance(grading, dict):
        score_max = _coerce_int_or_none(grading.get("total_max"))
    traits = archive_data.get("traits")
    if not isinstance(traits, dict) or not traits:
        traits = (grading.get("traits") or grading.get("trait_result") or {}) if isinstance(grading, dict) else {}
    traits = dict(traits or {})
    has_score = result_mode != "traits" and total_score is not None
    return {
        "result_mode": result_mode,
        "result_mode_label": _result_mode_label(result_mode),
        "total_score": total_score,
        "score_max": score_max,
        "has_score": has_score,
        "score_display": _score_display(total_score, score_max, result_mode=result_mode) if has_score else "",
        "final_analysis": str(
            archive_data.get("final_analysis")
            or (grading.get("final_analysis") if isinstance(grading, dict) else "")
            or (grading.get("analysis") if isinstance(grading, dict) else "")
            or ""
        ).strip(),
        "candidate_remark": str(archive_data.get("candidate_remark") or assignment_data.get("candidate_remark") or "").strip(),
        "traits": traits,
        "primary_dimensions": list(traits.get("primary_dimensions") or []),
        "paired_dimensions": list(traits.get("paired_dimensions") or []),
        "dimension_list": list(traits.get("dimension_list") or []),
    }


def _build_attempt_review(
    *,
    archive: dict[str, Any] | None,
    assignment: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "answers": _build_review_answers(archive=archive, assignment=assignment),
        "evaluation": _build_review_evaluation(archive=archive, assignment=assignment),
    }


def _looks_deleted_marker(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if text in {"已删除", "deleted", "????", "???", "null", "none", "历史测验"}:
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


def _repo_sync_http_status(exc: Exception) -> int:
    message = str(exc or "")
    if any(text in message for text in ("已绑定仓库", "尚未绑定仓库", "同步任务在执行")):
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


def _serialize_repo_binding(binding: dict[str, Any] | None) -> dict[str, Any]:
    current = binding if isinstance(binding, dict) else {}
    repo_url = str(current.get("repo_url") or "").strip()
    if not repo_url:
        return {}
    return {
        "repo_url": repo_url,
        "bound_at": str(current.get("bound_at") or "").strip(),
        "updated_at": str(current.get("updated_at") or "").strip(),
    }


def _serialize_exam_summary(exam: dict[str, Any], request: Request) -> dict[str, Any]:
    quiz_key = str(exam.get("quiz_key") or "").strip()
    cfg = exam_helpers.get_public_invite_config(quiz_key)
    public_token = str(cfg.get("token") or "").strip()
    question_count = int(exam.get("question_count") or exam.get("count") or 0)
    question_counts = exam.get("question_counts") if isinstance(exam.get("question_counts"), dict) else {}
    tags = exam.get("tags") if isinstance(exam.get("tags"), list) else []
    trait = exam.get("trait") if isinstance(exam.get("trait"), dict) else {}
    return {
        "id": int(exam.get("id") or 0),
        "quiz_key": quiz_key,
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
        "current_quiz_version_id": int(exam.get("current_version_id") or 0),
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
    quiz_key = str(exam.get("quiz_key") or "").strip()
    current_version_id = int(exam.get("current_version_id") or 0)
    selected = selected_version or {}
    selected_version_id = int(selected.get("id") or 0)
    raw_spec = selected.get("spec") if isinstance(selected.get("spec"), dict) else exam.get("spec") or {}
    spec = exam_helpers.build_render_ready_public_spec(raw_spec if isinstance(raw_spec, dict) else {})
    quiz_metadata = exam_helpers.build_quiz_metadata(spec)
    stats = _compute_exam_stats(spec if isinstance(spec, dict) else {})
    cfg = exam_helpers.get_public_invite_config(quiz_key)
    public_token = str(cfg.get("token") or "").strip()
    versions: list[dict[str, Any]] = []
    for item in deps.list_quiz_versions(quiz_key):
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
        "quiz": {
            "id": int(exam_helpers._sort_id_from_quiz_key(quiz_key) or 0),
            "quiz_key": quiz_key,
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
        "selected_quiz_version": {
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
        "quiz_version_history": versions,
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
                "quiz_name": str(item.get("quiz_name") or "").strip(),
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


def _serialize_assignment_row(row: dict[str, Any], *, request: Request) -> dict[str, Any]:
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
    quiz_key = str(row.get("quiz_key") or "").strip()
    if _looks_deleted_marker(quiz_key):
        quiz_key = "历史测验"
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
    handled_at = _iso_or_empty(row.get("handled_at"))
    handled_by = str(row.get("handled_by") or "").strip()
    needs_attention = bool(status_key == "finished" and not handled_at)
    return {
        "attempt_id": int(row.get("attempt_id") or 0),
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "candidate_deleted": candidate_deleted,
        "phone": str(row.get("phone") or "").strip(),
        "quiz_key": quiz_key,
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
        "handled_at": handled_at,
        "handled_by": handled_by,
        "needs_attention": needs_attention,
        "score": score,
        "score_max": score_max,
        "score_display": _score_display(score, score_max, result_mode=result_mode),
        "result_mode": result_mode,
        "created_at": _iso_or_empty(row.get("created_at")),
        "url": f"{_admin_base_url(request)}/t/{token}" if token else "",
        "qr_url": f"/api/admin/assignments/{token}/qr.png" if token else "",
    }


def _serialize_attempt_detail(token: str, *, request: Request) -> dict[str, Any]:
    quiz_paper_row = deps.get_quiz_paper_admin_detail_by_token(token)
    try:
        assignment = deps.load_assignment(token)
    except FileNotFoundError:
        assignment = {}
    if not assignment and not quiz_paper_row:
        raise FileNotFoundError(token)
    row = runtime_jobs._find_archive_by_token(token, assignment=assignment)
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
    return {
        "assignment": assignment,
        "quiz_paper": _serialize_assignment_row(quiz_paper_row, request=request) if quiz_paper_row else None,
        "archive": archive,
        "review": _build_attempt_review(archive=archive, assignment=assignment),
    }


def _serialize_log_row(row: dict[str, Any]) -> dict[str, Any]:
    event_type = str(row.get("event_type") or "").strip()
    type_key, type_label = system_status_helpers._oplog_type_label_v2(event_type)
    if type_key == "exam":
        type_key = "quiz"
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
        "quiz_key": str(row.get("quiz_key") or "").strip(),
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
                raw_key = "exam_cnt" if key == "quiz" else f"{key}_cnt"
                count = int(row.get(raw_key) or 0)
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


def _normalize_log_category_counts(counts: dict[str, Any]) -> dict[str, Any]:
    current = dict(counts or {})
    return {
        "candidate": int(current.get("candidate") or 0),
        "quiz": int(current.get("quiz", current.get("exam") or 0) or 0),
        "grading": int(current.get("grading") or 0),
        "assignment": int(current.get("assignment") or 0),
        "system": int(current.get("system") or 0),
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


def _log_resume_parse_stage(
    stage: str,
    *,
    flow: str,
    candidate_id: int | None = None,
    size_bytes: int | None = None,
    mime: str = "",
    elapsed_ms: float | None = None,
    text_chars: int | None = None,
    phone_valid: bool | None = None,
    name_valid: bool | None = None,
    details_status: str = "",
    llm_tokens: int | None = None,
    error: str = "",
) -> None:
    fields: list[str] = [f"stage={stage}", f"flow={flow}"]
    if candidate_id:
        fields.append(f"candidate_id={candidate_id}")
    if size_bytes is not None:
        fields.append(f"size_bytes={int(size_bytes)}")
    if mime:
        fields.append(f"mime={mime}")
    if elapsed_ms is not None:
        fields.append(f"elapsed_ms={elapsed_ms:.1f}")
    if text_chars is not None:
        fields.append(f"text_chars={int(text_chars)}")
    if phone_valid is not None:
        fields.append(f"phone_valid={str(bool(phone_valid)).lower()}")
    if name_valid is not None:
        fields.append(f"name_valid={str(bool(name_valid)).lower()}")
    if details_status:
        fields.append(f"details_status={details_status}")
    if llm_tokens is not None:
        fields.append(f"llm_tokens={int(llm_tokens)}")
    if error:
        fields.append(f"error={error[:240]}")
    deps.logger.info("resume_parse %s", " ".join(fields))


def _parse_resume_payload(
    *,
    data: bytes,
    filename: str,
    mime: str,
    current_phone: str | None = None,
    flow: str = "candidate_upload",
    candidate_id: int | None = None,
) -> dict[str, Any]:
    parse_started_at = time.perf_counter()
    size_bytes = len(data or b"")
    _log_resume_parse_stage(
        "start",
        flow=flow,
        candidate_id=candidate_id,
        size_bytes=size_bytes,
        mime=mime,
    )
    llm_started_at = time.perf_counter()
    llm_total_tokens = 0
    try:
        with deps.audit_context(meta={}):
            parsed = deps.parse_resume_all_llm(data=data, filename=filename, mime=mime) or {}
            ctx = deps.get_audit_context()
            meta = ctx.get("meta")
            if isinstance(meta, dict):
                llm_total_tokens = int(meta.get("llm_total_tokens_sum") or 0)
    except Exception as exc:
        _log_resume_parse_stage(
            "llm.parse.failed",
            flow=flow,
            candidate_id=candidate_id,
            size_bytes=size_bytes,
            mime=mime,
            elapsed_ms=(time.perf_counter() - llm_started_at) * 1000,
            llm_tokens=llm_total_tokens,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise HTTPException(status_code=400, detail=str(exc) or f"简历解析失败：{type(exc).__name__}") from exc

    parsed_name = str(parsed.get("name") or "").strip()
    parsed_phone = validation_helpers._normalize_phone(str(parsed.get("phone") or "").strip())
    confidence = parsed.get("confidence") or {}
    if not isinstance(confidence, dict):
        confidence = {}
    name_conf = validation_helpers._safe_int(confidence.get("name") or 0, 0)
    phone_conf = validation_helpers._safe_int(confidence.get("phone") or 0, 0)
    details = parsed.get("details") or {}
    if not isinstance(details, dict):
        details = {}
    details_status = str(parsed.get("details_status") or ("done" if details else "empty")).strip() or "empty"
    method = parsed.get("method") if isinstance(parsed.get("method"), dict) else {
        "identity": "llm_attachment",
        "name": "llm_attachment",
        "details": "llm_attachment",
    }
    phone_is_valid = validation_helpers._is_valid_phone(parsed_phone)
    name_is_valid = validation_helpers._is_valid_name(parsed_name)
    _log_resume_parse_stage(
        "llm.parse.done",
        flow=flow,
        candidate_id=candidate_id,
        size_bytes=size_bytes,
        mime=mime,
        elapsed_ms=(time.perf_counter() - llm_started_at) * 1000,
        phone_valid=phone_is_valid,
        name_valid=name_is_valid,
        details_status=details_status,
        llm_tokens=llm_total_tokens,
    )

    if current_phone:
        normalized_current_phone = validation_helpers._normalize_phone(current_phone)
        if validation_helpers._is_valid_phone(parsed_phone) and normalized_current_phone and parsed_phone != normalized_current_phone:
            _log_resume_parse_stage(
                "phone_mismatch",
                flow=flow,
                candidate_id=candidate_id,
                phone_valid=True,
                name_valid=name_is_valid,
            )
            raise HTTPException(status_code=400, detail="简历手机号与候选人手机号不一致")
    details_block: dict[str, Any] = {
        "status": details_status,
        "data": details,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }
    _log_resume_parse_stage(
        "done",
        flow=flow,
        candidate_id=candidate_id,
        size_bytes=size_bytes,
        mime=mime,
        elapsed_ms=(time.perf_counter() - parse_started_at) * 1000,
        phone_valid=phone_is_valid,
        name_valid=name_is_valid,
        details_status=str(details_block.get("status") or ""),
        llm_tokens=llm_total_tokens,
    )

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
            {"key": "quizzes", "label": "测验", "href": "/admin/quizzes"},
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


@router.get("/quizzes")
@router.get("/exams")
def list_exams(request: Request, q: str = "", page: int = 1):
    _require_admin(request)
    exams = exam_helpers._list_exams()
    query = str(q or "").strip().lower()
    if query:
        exams = [
            item
            for item in exams
            if query in str(item.get("quiz_key") or "").lower()
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
        "repo_binding": _serialize_repo_binding(deps.read_exam_repo_binding()),
        "sync_state": deps.read_exam_repo_sync_state(),
    }


@router.post("/quizzes/binding", status_code=status.HTTP_201_CREATED)
def bind_exam_repo(payload: RepoBindingPayload, request: Request):
    _require_admin(request)
    try:
        result = deps.bind_exam_repo(str(payload.repo_url or "").strip())
    except ExamRepoSyncError as exc:
        raise HTTPException(status_code=_repo_sync_http_status(exc), detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"绑定仓库失败：{exc}") from exc
    try:
        deps.log_event(
            "exam.repo.bind",
            actor="admin",
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


@router.post("/quizzes/binding/rebind")
def rebind_exam_repo(payload: RepoRebindPayload, request: Request):
    _require_admin(request)
    if str(payload.confirmation_text or "").strip() != "重新绑定":
        raise HTTPException(status_code=400, detail="确认词不正确")
    try:
        result = deps.rebind_exam_repo(str(payload.repo_url or "").strip())
    except ExamRepoSyncError as exc:
        raise HTTPException(status_code=_repo_sync_http_status(exc), detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"重新绑定失败：{exc}") from exc
    try:
        deps.log_event(
            "exam.repo.rebind",
            actor="admin",
            meta={
                "previous_repo_url": str(result.get("previous_repo_url") or ""),
                "repo_url": str((result.get("binding") or {}).get("repo_url") or ""),
                "cleanup": result.get("cleanup") if isinstance(result.get("cleanup"), dict) else {},
                "job_id": str((result.get("sync") or {}).get("job_id") or ""),
                "sync_created": bool((result.get("sync") or {}).get("created")),
                "sync_error": str((result.get("sync") or {}).get("error") or ""),
            },
        )
    except Exception:
        pass
    return result


@router.post("/quizzes/sync")
def sync_exams(payload: SyncExamPayload, request: Request):
    _require_admin(request)
    _ = payload
    binding = _serialize_repo_binding(deps.read_exam_repo_binding())
    try:
        result = deps.enqueue_exam_repo_sync()
    except ExamRepoSyncError as exc:
        raise HTTPException(status_code=_repo_sync_http_status(exc), detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"同步任务创建失败：{exc}") from exc
    try:
        deps.log_event(
            "exam.sync.enqueue",
            actor="admin",
            meta={
                "repo_url": str(binding.get("repo_url") or ""),
                "job_id": str(result.get("job_id") or ""),
                "created": bool(result.get("created")),
            },
        )
    except Exception:
        pass
    return result


@router.get("/quizzes/{quiz_key}")
@router.get("/exams/{quiz_key}")
def get_exam_detail(quiz_key: str, request: Request):
    _require_admin(request)
    exam = deps.get_quiz_definition(str(quiz_key or "").strip())
    if not exam:
        raise HTTPException(status_code=404, detail="测验不存在")
    selected_version = None
    current_version_id = int(exam.get("current_version_id") or 0)
    if current_version_id > 0:
        selected_version = exam_helpers.get_quiz_version_snapshot(current_version_id)
    return _serialize_exam_detail(exam, request=request, selected_version=selected_version)


@router.get("/quiz-versions/{version_id}")
@router.get("/exam-versions/{version_id}")
def get_quiz_version_detail(version_id: int, request: Request):
    _require_admin(request)
    version = exam_helpers.get_quiz_version_snapshot(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")
    exam = deps.get_quiz_definition(str(version.get("quiz_key") or "").strip())
    if not exam:
        raise HTTPException(status_code=404, detail="测验不存在")
    return _serialize_exam_detail(exam, request=request, selected_version=version)


@router.post("/quizzes/{quiz_key}/public-invite")
def toggle_exam_public_invite(quiz_key: str, payload: PublicInviteTogglePayload, request: Request):
    _require_admin(request)
    exam = deps.get_quiz_definition(str(quiz_key or "").strip())
    if not exam:
        raise HTTPException(status_code=404, detail="测验不存在")
    cfg = exam_helpers.set_public_invite_enabled(str(quiz_key or "").strip(), payload.enabled)
    public_token = str(cfg.get("token") or "").strip()
    try:
        deps.log_event(
            "exam.public_invite.enable" if payload.enabled else "exam.public_invite.disable",
            actor="admin",
            quiz_key=str(quiz_key or "").strip(),
            meta={"public_token": public_token},
        )
    except Exception:
        pass
    return {
        "ok": True,
        "enabled": bool(cfg.get("enabled")),
        "token": public_token,
        "public_url": (
            f"{_admin_base_url(request)}/p/{public_token}"
            if bool(cfg.get("enabled")) and public_token
            else ""
        ),
        "qr_url": (
            f"/api/public/invites/{public_token}/qr.png"
            if bool(cfg.get("enabled")) and public_token
            else ""
        ),
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
    _log_resume_parse_stage("request.accepted", flow="candidate_upload", size_bytes=len(data), mime=mime)
    payload = _parse_resume_payload(
        data=data,
        filename=filename,
        mime=mime,
        flow="candidate_upload",
    )
    parsed_phone = validation_helpers._normalize_phone(str(payload.get("parsed_phone") or ""))
    if not validation_helpers._is_valid_phone(parsed_phone):
        _log_resume_parse_stage(
            "request.rejected",
            flow="candidate_upload",
            size_bytes=len(data),
            mime=mime,
            error="invalid_phone",
        )
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
    _log_resume_parse_stage(
        "request.completed",
        flow="candidate_upload",
        candidate_id=candidate_id,
        size_bytes=len(data),
        mime=mime,
        details_status=str(((payload.get("resume_parsed") or {}).get("details") or {}).get("status") or ""),
        llm_tokens=int(payload.get("llm_total_tokens") or 0),
    )
    return {
        "created": created,
        **_serialize_candidate_detail(candidate_id, candidate),
    }


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
    _log_resume_parse_stage(
        "request.accepted",
        flow="candidate_reparse",
        candidate_id=candidate_id,
        size_bytes=len(data),
        mime=mime,
    )
    payload = _parse_resume_payload(
        data=data,
        filename=filename,
        mime=mime,
        current_phone=current_phone,
        flow="candidate_reparse",
        candidate_id=candidate_id,
    )
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
    _log_resume_parse_stage(
        "request.completed",
        flow="candidate_reparse",
        candidate_id=candidate_id,
        size_bytes=len(data),
        mime=mime,
        details_status=str(((payload.get("resume_parsed") or {}).get("details") or {}).get("status") or ""),
        llm_tokens=int(payload.get("llm_total_tokens") or 0),
    )
    return _serialize_candidate_detail(candidate_id, deps.get_candidate(candidate_id) or candidate)


@router.get("/assignments")
def get_assignments(
    request: Request,
    q: str = "",
    start_from: str = "",
    start_to: str = "",
    end_from: str = "",
    end_to: str = "",
    page: int = 1,
):
    _require_admin(request)
    per_page = 20
    invite_start_from = str(start_from or "").strip() or None
    invite_start_to = str(start_to or "").strip() or None
    invite_end_from = str(end_from or "").strip() or None
    invite_end_to = str(end_to or "").strip() or None
    total = deps.count_quiz_papers(
        query=q or None,
        invite_start_from=invite_start_from,
        invite_start_to=invite_start_to,
        invite_end_from=invite_end_from,
        invite_end_to=invite_end_to,
    )
    unhandled_finished_count = deps.count_unhandled_finished_quiz_papers(
        query=q or None,
        invite_start_from=invite_start_from,
        invite_start_to=invite_start_to,
        invite_end_from=invite_end_from,
        invite_end_to=invite_end_to,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    current_page = max(1, min(int(page or 1), total_pages))
    offset = (current_page - 1) * per_page
    rows = deps.list_quiz_papers(
        query=q or None,
        invite_start_from=invite_start_from,
        invite_start_to=invite_start_to,
        invite_end_from=invite_end_from,
        invite_end_to=invite_end_to,
        limit=per_page,
        offset=offset,
    )
    return {
        "items": [_serialize_assignment_row(row, request=request) for row in rows],
        "summary": {
            "unhandled_finished_count": int(unhandled_finished_count or 0),
        },
        "page": current_page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "filters": {
            "q": str(q or "").strip(),
            "start_from": start_from,
            "start_to": start_to,
            "end_from": end_from,
            "end_to": end_to,
        },
    }


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
def create_assignment(payload: AssignmentCreatePayload, request: Request):
    _require_admin(request)
    quiz_key = str(payload.quiz_key or "").strip()
    if not quiz_key:
        raise HTTPException(status_code=400, detail="缺少 quiz_key")
    candidate = deps.get_candidate(int(payload.candidate_id))
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人不存在")
    exam = deps.get_quiz_definition(quiz_key)
    quiz_version_id = exam_helpers.resolve_quiz_version_id_for_new_assignment(quiz_key)
    if not exam or not quiz_version_id:
        raise HTTPException(status_code=400, detail="测验不可用")
    start_date = _parse_date_ymd(payload.invite_start_date)
    end_date = _parse_date_ymd(payload.invite_end_date)
    if start_date is None or end_date is None:
        raise HTTPException(status_code=400, detail="答题日期无效")
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="答题结束日期不能早于开始日期")
    ignore_timing = bool(payload.ignore_timing)
    public_spec = exam.get("public_spec") if isinstance(exam.get("public_spec"), dict) else {}
    time_limit_seconds = 0 if ignore_timing else exam_helpers.compute_quiz_time_limit_seconds(public_spec)
    if not ignore_timing and time_limit_seconds <= 0:
        raise HTTPException(status_code=400, detail="测验缺少有效的题目答题时长配置")
    result = deps.create_assignment(
        quiz_key=quiz_key,
        candidate_id=int(payload.candidate_id),
        quiz_version_id=quiz_version_id,
        base_url=_admin_base_url(request),
        phone=str(candidate.get("phone") or ""),
        invite_start_date=start_date.isoformat(),
        invite_end_date=end_date.isoformat(),
        time_limit_seconds=time_limit_seconds,
        min_submit_seconds=0,
        require_phone_verification=bool(payload.require_phone_verification),
        ignore_timing=ignore_timing,
        verify_max_attempts=int(payload.verify_max_attempts or 3),
    )
    token = str(result.get("token") or "").strip()
    try:
        deps.create_quiz_paper(
            candidate_id=int(payload.candidate_id),
            phone=str(candidate.get("phone") or ""),
            quiz_key=quiz_key,
            quiz_version_id=quiz_version_id,
            token=token,
            source_kind="direct",
            invite_start_date=start_date.isoformat(),
            invite_end_date=end_date.isoformat(),
            status="invited",
        )
    except Exception:
        deps.logger.exception("Create quiz_paper failed (candidate_id=%s, quiz_key=%s)", payload.candidate_id, quiz_key)
    try:
        deps.log_event(
            "assignment.create",
            actor="admin",
            candidate_id=int(payload.candidate_id),
            quiz_key=quiz_key,
            token=token or None,
            meta={
                "invite_start_date": start_date.isoformat(),
                "invite_end_date": end_date.isoformat(),
                "require_phone_verification": bool(payload.require_phone_verification),
                "ignore_timing": ignore_timing,
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
        return _serialize_attempt_detail(token, request=request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="答题记录不存在") from exc


@router.get("/attempts/{token}")
def get_attempt_detail(token: str, request: Request):
    return get_assignment_detail(token, request)


@router.get("/results/{token}")
def get_result_detail(token: str, request: Request):
    return get_assignment_detail(token, request)


@router.delete("/assignments/{token}")
def delete_assignment(token: str, request: Request):
    _require_admin(request)
    token_str = str(token or "").strip()
    if not token_str:
        raise HTTPException(status_code=400, detail="缺少 token")
    quiz_paper = deps.get_quiz_paper_by_token(token_str)
    try:
        assignment = deps.load_assignment(token_str)
    except FileNotFoundError:
        assignment = {}
    if not quiz_paper and not assignment:
        raise HTTPException(status_code=404, detail="邀约不存在")

    status_key = validation_helpers._normalize_exam_status(
        str((quiz_paper or {}).get("status") or (assignment or {}).get("status") or "").strip()
    )

    deleted_quiz_archive = int(deps.delete_quiz_archive_by_token(token_str) or 0)
    deleted_quiz_paper = int(deps.delete_quiz_paper_by_token(token_str) or 0)
    deleted_assignment_record = int(deps.delete_assignment_record(token_str) or 0)
    if deleted_quiz_archive <= 0 and deleted_quiz_paper <= 0 and deleted_assignment_record <= 0:
        raise HTTPException(status_code=404, detail="邀约不存在")

    candidate_id = int((quiz_paper or {}).get("candidate_id") or (assignment or {}).get("candidate_id") or 0)
    quiz_key = str((quiz_paper or {}).get("quiz_key") or (assignment or {}).get("quiz_key") or "").strip()
    source_kind = str(
        (quiz_paper or {}).get("source_kind") or ("public" if (assignment or {}).get("public_invite") else "direct")
    ).strip() or "direct"
    try:
        deps.log_event(
            "assignment.delete",
            actor="admin",
            candidate_id=(candidate_id or None),
            quiz_key=(quiz_key or None),
            token=token_str,
            meta={
                "source_kind": source_kind,
                "status": status_key,
                "deleted_quiz_archive": deleted_quiz_archive,
                "deleted_assignment_record": deleted_assignment_record,
                "deleted_quiz_paper": deleted_quiz_paper,
            },
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


@router.post("/assignments/{token}/handling")
def set_assignment_handling(token: str, payload: AssignmentHandlingPayload, request: Request):
    _require_admin(request)
    quiz_paper = deps.get_quiz_paper_by_token(token)
    if not quiz_paper:
        raise HTTPException(status_code=404, detail="答题记录不存在")
    status_key = validation_helpers._normalize_exam_status(str(quiz_paper.get("status") or "").strip())
    if status_key != "finished":
        raise HTTPException(status_code=409, detail="只有已判卷完成的记录才能标记处理状态")
    admin_username = str(request.session.get("admin_username") or "").strip() or "admin"
    deps.set_quiz_paper_handling(
        token,
        handled=bool(payload.handled),
        handled_by=admin_username,
    )
    row = deps.get_quiz_paper_admin_detail_by_token(token)
    if not row:
        raise HTTPException(status_code=404, detail="答题记录不存在")
    return {
        "item": _serialize_assignment_row(row, request=request),
    }


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
        quiz_paper = deps.get_quiz_paper_by_token(token) or {}
        if not quiz_paper:
            continue
        status_key = validation_helpers._normalize_exam_status(quiz_paper.get("status"))
        invite_end_date = _iso_or_empty(quiz_paper.get("invite_end_date"))
        if status_key in {"invited", "verified"} and not quiz_paper.get("entered_at"):
            end_date = _parse_date_ymd(invite_end_date)
            if end_date is not None and today_local > end_date:
                status_key = "expired"
        items.append(
            {
                "token": token,
                "status": status_key,
                "status_label": _status_label(status_key),
                "score": quiz_paper.get("score"),
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
        "counts": _normalize_log_category_counts(deps.count_operation_logs_by_category()),
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
    return {
        "ok": True,
        "config": system_status_helpers._load_system_status_cfg(),
        "data": data,
        "summary": system_status_helpers._get_cached_system_status_summary(),
    }


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
