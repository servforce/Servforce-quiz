from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Request, Response, status

from . import admin as shared

router = APIRouter()


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
    shared._require_admin(request)
    per_page = 20
    invite_start_from = str(start_from or "").strip() or None
    invite_start_to = str(start_to or "").strip() or None
    invite_end_from = str(end_from or "").strip() or None
    invite_end_to = str(end_to or "").strip() or None
    total = shared.deps.count_quiz_papers(
        query=q or None,
        invite_start_from=invite_start_from,
        invite_start_to=invite_start_to,
        invite_end_from=invite_end_from,
        invite_end_to=invite_end_to,
    )
    unhandled_finished_count = shared.deps.count_unhandled_finished_quiz_papers(
        query=q or None,
        invite_start_from=invite_start_from,
        invite_start_to=invite_start_to,
        invite_end_from=invite_end_from,
        invite_end_to=invite_end_to,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    current_page = max(1, min(int(page or 1), total_pages))
    offset = (current_page - 1) * per_page
    rows = shared.deps.list_quiz_papers(
        query=q or None,
        invite_start_from=invite_start_from,
        invite_start_to=invite_start_to,
        invite_end_from=invite_end_from,
        invite_end_to=invite_end_to,
        limit=per_page,
        offset=offset,
    )
    return {
        "items": [shared._serialize_assignment_row(row, request=request) for row in rows],
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
def create_assignment(payload: shared.AssignmentCreatePayload, request: Request):
    shared._require_admin(request)
    quiz_key = str(payload.quiz_key or "").strip()
    if not quiz_key:
        raise shared.HTTPException(status_code=400, detail="缺少 quiz_key")
    candidate = shared.deps.get_candidate(int(payload.candidate_id))
    if not candidate:
        raise shared.HTTPException(status_code=404, detail="候选人不存在")
    exam = shared.deps.get_quiz_definition(quiz_key)
    quiz_version_id = shared.exam_helpers.resolve_quiz_version_id_for_new_assignment(quiz_key)
    if not exam or not quiz_version_id:
        raise shared.HTTPException(status_code=400, detail="测验不可用")
    start_date = shared._parse_date_ymd(payload.invite_start_date)
    end_date = shared._parse_date_ymd(payload.invite_end_date)
    if start_date is None or end_date is None:
        raise shared.HTTPException(status_code=400, detail="答题日期无效")
    if end_date < start_date:
        raise shared.HTTPException(status_code=400, detail="答题结束日期不能早于开始日期")
    ignore_timing = bool(payload.ignore_timing)
    public_spec = exam.get("public_spec") if isinstance(exam.get("public_spec"), dict) else {}
    time_limit_seconds = 0 if ignore_timing else shared.exam_helpers.compute_quiz_time_limit_seconds(public_spec)
    if not ignore_timing and time_limit_seconds <= 0:
        raise shared.HTTPException(status_code=400, detail="测验缺少有效的题目答题时长配置")
    result = shared.deps.create_assignment(
        quiz_key=quiz_key,
        candidate_id=int(payload.candidate_id),
        quiz_version_id=quiz_version_id,
        base_url=shared._admin_base_url(request),
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
        shared.deps.create_quiz_paper(
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
        shared.deps.logger.exception("Create quiz_paper failed (candidate_id=%s, quiz_key=%s)", payload.candidate_id, quiz_key)
    try:
        shared.deps.log_event(
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
    shared._require_admin(request)
    try:
        return shared._serialize_attempt_detail(token, request=request)
    except FileNotFoundError as exc:
        raise shared.HTTPException(status_code=404, detail="答题记录不存在") from exc


@router.get("/attempts/{token}")
def get_attempt_detail(token: str, request: Request):
    return get_assignment_detail(token, request)


@router.get("/results/{token}")
def get_result_detail(token: str, request: Request):
    return get_assignment_detail(token, request)


@router.delete("/assignments/{token}")
def delete_assignment(token: str, request: Request):
    shared._require_admin(request)
    token_str = str(token or "").strip()
    if not token_str:
        raise shared.HTTPException(status_code=400, detail="缺少 token")
    quiz_paper = shared.deps.get_quiz_paper_by_token(token_str)
    try:
        assignment = shared.deps.load_assignment(token_str)
    except FileNotFoundError:
        assignment = {}
    if not quiz_paper and not assignment:
        raise shared.HTTPException(status_code=404, detail="邀约不存在")

    status_key = shared.validation_helpers._normalize_exam_status(
        str((quiz_paper or {}).get("status") or (assignment or {}).get("status") or "").strip()
    )

    deleted_quiz_archive = int(shared.deps.delete_quiz_archive_by_token(token_str) or 0)
    deleted_quiz_paper = int(shared.deps.delete_quiz_paper_by_token(token_str) or 0)
    deleted_assignment_record = int(shared.deps.delete_assignment_record(token_str) or 0)
    if deleted_quiz_archive <= 0 and deleted_quiz_paper <= 0 and deleted_assignment_record <= 0:
        raise shared.HTTPException(status_code=404, detail="邀约不存在")

    candidate_id = int((quiz_paper or {}).get("candidate_id") or (assignment or {}).get("candidate_id") or 0)
    quiz_key = str((quiz_paper or {}).get("quiz_key") or (assignment or {}).get("quiz_key") or "").strip()
    source_kind = str(
        (quiz_paper or {}).get("source_kind") or ("public" if (assignment or {}).get("public_invite") else "direct")
    ).strip() or "direct"
    try:
        shared.deps.log_event(
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
def set_assignment_handling(token: str, payload: shared.AssignmentHandlingPayload, request: Request):
    shared._require_admin(request)
    quiz_paper = shared.deps.get_quiz_paper_by_token(token)
    if not quiz_paper:
        raise shared.HTTPException(status_code=404, detail="答题记录不存在")
    status_key = shared.validation_helpers._normalize_exam_status(str(quiz_paper.get("status") or "").strip())
    if status_key != "finished":
        raise shared.HTTPException(status_code=409, detail="只有已判卷完成的记录才能标记处理状态")
    admin_username = str(request.session.get("admin_username") or "").strip() or "admin"
    shared.deps.set_quiz_paper_handling(
        token,
        handled=bool(payload.handled),
        handled_by=admin_username,
    )
    row = shared.deps.get_quiz_paper_admin_detail_by_token(token)
    if not row:
        raise shared.HTTPException(status_code=404, detail="答题记录不存在")
    return {
        "item": shared._serialize_assignment_row(row, request=request),
    }


@router.get("/assignments/{token}/qr.png")
def get_assignment_qr(token: str, request: Request):
    shared._require_admin(request)
    try:
        shared.deps.load_assignment(token)
    except Exception as exc:
        raise shared.HTTPException(status_code=404, detail="答题记录不存在") from exc
    try:
        import qrcode  # type: ignore
    except Exception as exc:
        raise shared.HTTPException(status_code=500, detail="二维码依赖不可用") from exc
    url = f"{shared._admin_base_url(request)}/t/{str(token or '').strip()}"
    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    try:
        image.save(buffer, format="PNG")
    except TypeError:
        image.save(buffer)
    return Response(content=buffer.getvalue(), media_type="image/png")


@router.get("/attempt-status")
def get_attempt_status(request: Request, tokens: str = ""):
    shared._require_admin(request)
    values = [item.strip() for item in str(tokens or "").split(",") if item.strip()][:50]
    items: list[dict[str, Any]] = []
    today_local = datetime.now().astimezone().date()
    for token in values:
        quiz_paper = shared.deps.get_quiz_paper_by_token(token) or {}
        if not quiz_paper:
            continue
        status_key = shared.validation_helpers._normalize_exam_status(quiz_paper.get("status"))
        invite_end_date = shared._iso_or_empty(quiz_paper.get("invite_end_date"))
        if status_key in {"invited", "verified"} and not quiz_paper.get("entered_at"):
            end_date = shared._parse_date_ymd(invite_end_date)
            if end_date is not None and today_local > end_date:
                status_key = "expired"
        items.append(
            {
                "token": token,
                "status": status_key,
                "status_label": shared._status_label(status_key),
                "score": quiz_paper.get("score"),
            }
        )
    return {"items": items}
