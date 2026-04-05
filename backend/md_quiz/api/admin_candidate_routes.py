from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, File, Request, Response, UploadFile, status

from . import admin as shared

router = APIRouter()


@router.get("/candidates")
def get_candidates(
    request: Request,
    q: str = "",
    created_from: str = "",
    created_to: str = "",
    page: int = 1,
):
    shared._require_admin(request)
    created_from_raw = str(created_from or "").strip() or (datetime.now().date() - timedelta(days=29)).isoformat()
    created_to_raw = str(created_to or "").strip() or datetime.now().date().isoformat()
    parsed_from = shared._parse_candidate_query_dates(created_from_raw, end_of_day=False)
    parsed_to = shared._parse_candidate_query_dates(created_to_raw, end_of_day=True)
    per_page = 20
    total = shared.deps.count_candidates(query=q or None, created_from=parsed_from, created_to=parsed_to)
    total_pages = max(1, (total + per_page - 1) // per_page)
    current_page = max(1, min(int(page or 1), total_pages))
    offset = (current_page - 1) * per_page
    items = shared.deps.list_candidates(
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
                "created_at": shared._iso_or_empty(item.get("created_at")),
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
def create_candidate(payload: shared.CandidateCreatePayload, request: Request):
    shared._require_admin(request)
    name = str(payload.name or "").strip()
    phone = shared.validation_helpers._normalize_phone(payload.phone)
    if not shared.validation_helpers._is_valid_name(name):
        raise shared.HTTPException(status_code=400, detail="姓名格式不正确")
    if not shared.validation_helpers._is_valid_phone(phone):
        raise shared.HTTPException(status_code=400, detail="手机号格式不正确")
    if shared.deps.get_candidate_by_phone(phone):
        raise shared.HTTPException(status_code=409, detail="候选人已存在")
    try:
        candidate_id = int(shared.deps.create_candidate(name=name, phone=phone))
        shared.deps.log_event(
            "candidate.create",
            actor="admin",
            candidate_id=candidate_id,
            meta={"name": name, "phone": phone},
        )
    except shared.HTTPException:
        raise
    except Exception as exc:
        raise shared.HTTPException(status_code=500, detail="创建候选人失败") from exc
    return {"id": candidate_id, "name": name, "phone": phone}


@router.post("/candidates/resume/upload")
def upload_candidate_resume(request: Request, file: UploadFile = File(...)):
    shared._require_admin(request)
    result = shared.candidate_resume_admin_service.upload_candidate_resume(file)
    candidate_id = int(result.get("candidate_id") or 0)
    candidate = result.get("candidate") if isinstance(result.get("candidate"), dict) else {}
    return {
        "created": bool(result.get("created")),
        **shared._serialize_candidate_detail(candidate_id, candidate),
    }


@router.post("/candidates/resume/upload-job", status_code=status.HTTP_202_ACCEPTED)
def enqueue_candidate_resume_upload(request: Request, file: UploadFile = File(...)):
    shared._require_admin(request)
    return shared.candidate_resume_admin_service.enqueue_candidate_resume_upload(file)


@router.get("/candidates/{candidate_id}")
def get_candidate_detail(candidate_id: int, request: Request):
    shared._require_admin(request)
    candidate = shared.deps.get_candidate(candidate_id)
    if not candidate:
        raise shared.HTTPException(status_code=404, detail="候选人不存在")
    try:
        shared.deps.log_event(
            "candidate.read",
            actor="admin",
            candidate_id=int(candidate_id),
            meta={
                "name": str(candidate.get("name") or "").strip(),
                "phone": str(candidate.get("phone") or "").strip(),
            },
        )
    except Exception:
        pass
    return shared._serialize_candidate_detail(candidate_id, candidate)


@router.delete("/candidates/{candidate_id}")
def remove_candidate(candidate_id: int, request: Request):
    shared._require_admin(request)
    candidate = shared.deps.get_candidate(candidate_id)
    if not candidate:
        raise shared.HTTPException(status_code=404, detail="候选人不存在")
    try:
        shared.deps.delete_candidate(candidate_id)
        shared.deps.log_event(
            "candidate.delete",
            actor="admin",
            candidate_id=int(candidate_id),
            meta={
                "name": str(candidate.get("name") or "").strip(),
                "phone": str(candidate.get("phone") or "").strip(),
            },
        )
    except Exception as exc:
        raise shared.HTTPException(status_code=500, detail="删除失败") from exc
    return {"ok": True}


@router.post("/candidates/{candidate_id}/evaluation")
def update_candidate_evaluation(candidate_id: int, payload: shared.CandidateEvaluationPayload, request: Request):
    shared._require_admin(request)
    candidate = shared.deps.get_candidate(candidate_id)
    if not candidate:
        raise shared.HTTPException(status_code=404, detail="候选人不存在")
    evaluation = str(payload.evaluation or "").strip()
    if not evaluation:
        raise shared.HTTPException(status_code=400, detail="评价不能为空")
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
    shared.deps.update_candidate_resume_parsed(
        candidate_id,
        resume_parsed=parsed,
        touch_resume_parsed_at=False,
    )
    return shared._serialize_candidate_detail(candidate_id, shared.deps.get_candidate(candidate_id) or candidate)


@router.get("/candidates/{candidate_id}/resume")
def download_candidate_resume(candidate_id: int, request: Request):
    shared._require_admin(request)
    candidate = shared.deps.get_candidate(candidate_id)
    if not candidate:
        raise shared.HTTPException(status_code=404, detail="候选人不存在")
    resume = shared.deps.get_candidate_resume(candidate_id)
    if not resume:
        raise shared.HTTPException(status_code=404, detail="简历不存在")
    data = resume.get("resume_bytes") or b""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise shared.HTTPException(status_code=404, detail="简历不存在")
    filename = os.path.basename(str(resume.get("resume_filename") or "").strip()) or f"candidate_{candidate_id}_resume.bin"
    mime = str(resume.get("resume_mime") or "").strip() or "application/octet-stream"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=bytes(data), media_type=mime, headers=headers)


@router.post("/candidates/{candidate_id}/resume/reparse")
def reparse_candidate_resume(candidate_id: int, request: Request, file: UploadFile = File(...)):
    shared._require_admin(request)
    result = shared.candidate_resume_admin_service.reparse_candidate_resume(candidate_id, file)
    candidate = result.get("candidate") if isinstance(result.get("candidate"), dict) else {}
    return shared._serialize_candidate_detail(candidate_id, candidate)


@router.post("/candidates/{candidate_id}/resume/reparse-job", status_code=status.HTTP_202_ACCEPTED)
def enqueue_candidate_resume_reparse(candidate_id: int, request: Request, file: UploadFile = File(...)):
    shared._require_admin(request)
    return shared.candidate_resume_admin_service.enqueue_candidate_resume_reparse(candidate_id, file)
