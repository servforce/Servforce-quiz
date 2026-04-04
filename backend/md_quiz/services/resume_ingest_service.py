from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, UploadFile

from backend.md_quiz.services import support_deps as deps
from backend.md_quiz.services import validation_helpers
from backend.md_quiz.services.resume_service import build_resume_parsed_payload


def log_resume_parse_stage(
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


def read_resume_bytes(file: UploadFile, *, missing_file_detail: str = "请选择简历文件") -> bytes:
    if not file or not getattr(file, "filename", ""):
        raise HTTPException(status_code=400, detail=missing_file_detail)
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


def parse_resume_payload(
    *,
    data: bytes,
    filename: str,
    mime: str,
    current_phone: str | None = None,
    flow: str = "",
    candidate_id: int | None = None,
    enable_stage_logs: bool = False,
) -> dict[str, Any]:
    parse_started_at = time.perf_counter()
    size_bytes = len(data or b"")
    if enable_stage_logs:
        log_resume_parse_stage(
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
        if enable_stage_logs:
            log_resume_parse_stage(
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

    parsed_at = datetime.now(timezone.utc).isoformat()
    built = build_resume_parsed_payload(
        parsed,
        filename=filename,
        mime=mime,
        current_phone=str(current_phone or ""),
        parsed_at=parsed_at,
    )
    built["llm_total_tokens"] = llm_total_tokens

    parsed_name = str(built.get("parsed_name") or "").strip()
    parsed_phone = validation_helpers._normalize_phone(str(built.get("parsed_phone") or "").strip())
    details_status = str((((built.get("resume_parsed") or {}).get("details") or {}).get("status") or "")).strip()
    phone_is_valid = validation_helpers._is_valid_phone(parsed_phone)
    name_is_valid = validation_helpers._is_valid_name(parsed_name)

    if enable_stage_logs:
        log_resume_parse_stage(
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

    normalized_current_phone = validation_helpers._normalize_phone(str(current_phone or ""))
    if (
        normalized_current_phone
        and phone_is_valid
        and parsed_phone
        and parsed_phone != normalized_current_phone
    ):
        if enable_stage_logs:
            log_resume_parse_stage(
                "phone_mismatch",
                flow=flow,
                candidate_id=candidate_id,
                phone_valid=True,
                name_valid=name_is_valid,
            )
        raise HTTPException(status_code=400, detail="简历手机号与候选人手机号不一致")

    if enable_stage_logs:
        log_resume_parse_stage(
            "done",
            flow=flow,
            candidate_id=candidate_id,
            size_bytes=size_bytes,
            mime=mime,
            elapsed_ms=(time.perf_counter() - parse_started_at) * 1000,
            phone_valid=phone_is_valid,
            name_valid=name_is_valid,
            details_status=details_status,
            llm_tokens=llm_total_tokens,
        )
    return built
