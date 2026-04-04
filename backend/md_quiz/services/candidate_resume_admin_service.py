from __future__ import annotations

from typing import Any

from fastapi import HTTPException, UploadFile

from backend.md_quiz.services import resume_ingest_service
from backend.md_quiz.services import support_deps as deps
from backend.md_quiz.services import validation_helpers


def upload_candidate_resume(file: UploadFile) -> dict[str, Any]:
    data = resume_ingest_service.read_resume_bytes(file, missing_file_detail="缺少简历文件")
    filename = str(file.filename or "")
    mime = str(file.content_type or "")
    resume_ingest_service.log_resume_parse_stage(
        "request.accepted",
        flow="candidate_upload",
        size_bytes=len(data),
        mime=mime,
    )
    payload = resume_ingest_service.parse_resume_payload(
        data=data,
        filename=filename,
        mime=mime,
        flow="candidate_upload",
        enable_stage_logs=True,
    )
    parsed_phone = validation_helpers._normalize_phone(str(payload.get("parsed_phone") or ""))
    if not validation_helpers._is_valid_phone(parsed_phone):
        resume_ingest_service.log_resume_parse_stage(
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

    candidate = deps.get_candidate(candidate_id) or {
        "id": candidate_id,
        "name": candidate_name,
        "phone": parsed_phone,
    }
    resume_ingest_service.log_resume_parse_stage(
        "request.completed",
        flow="candidate_upload",
        candidate_id=candidate_id,
        size_bytes=len(data),
        mime=mime,
        details_status=str(((payload.get("resume_parsed") or {}).get("details") or {}).get("status") or ""),
        llm_tokens=int(payload.get("llm_total_tokens") or 0),
    )
    return {"created": created, "candidate_id": candidate_id, "candidate": candidate}


def reparse_candidate_resume(candidate_id: int, file: UploadFile) -> dict[str, Any]:
    candidate = deps.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="候选人不存在")

    data = resume_ingest_service.read_resume_bytes(file, missing_file_detail="缺少简历文件")
    filename = str(file.filename or "")
    mime = str(file.content_type or "")
    current_phone = str(candidate.get("phone") or "").strip()
    resume_ingest_service.log_resume_parse_stage(
        "request.accepted",
        flow="candidate_reparse",
        candidate_id=candidate_id,
        size_bytes=len(data),
        mime=mime,
    )
    payload = resume_ingest_service.parse_resume_payload(
        data=data,
        filename=filename,
        mime=mime,
        current_phone=current_phone,
        flow="candidate_reparse",
        candidate_id=candidate_id,
        enable_stage_logs=True,
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
    resume_ingest_service.log_resume_parse_stage(
        "request.completed",
        flow="candidate_reparse",
        candidate_id=candidate_id,
        size_bytes=len(data),
        mime=mime,
        details_status=str(((payload.get("resume_parsed") or {}).get("details") or {}).get("status") or ""),
        llm_tokens=int(payload.get("llm_total_tokens") or 0),
    )
    return {"candidate_id": candidate_id, "candidate": deps.get_candidate(candidate_id) or candidate}
