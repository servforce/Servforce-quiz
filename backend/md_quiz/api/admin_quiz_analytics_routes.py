from __future__ import annotations

from fastapi import APIRouter, Request

from . import admin as shared

router = APIRouter()


@router.get("/quiz-analytics")
def get_quiz_analytics_list(
    request: Request,
    q: str = "",
    page: int = 1,
):
    shared._require_admin(request)
    query = str(q or "").strip().lower()
    exams = shared.exam_helpers._list_exams()
    if query:
        exams = [
            item
            for item in exams
            if query in str(item.get("quiz_key") or "").lower()
            or query in str(item.get("title") or "").lower()
            or any(query in str(tag or "").lower() for tag in (item.get("tags") or []))
        ]
    exams.sort(key=lambda item: float(item.get("_mtime") or 0), reverse=True)
    per_page = 20
    total = len(exams)
    total_pages = max(1, (total + per_page - 1) // per_page)
    current_page = max(1, min(int(page or 1), total_pages))
    start = (current_page - 1) * per_page
    items = [shared._serialize_exam_summary(item, request) for item in exams[start : start + per_page]]
    return {
        "items": items,
        "page": current_page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "filters": {
            "q": str(q or "").strip(),
        },
    }


@router.get("/quiz-analytics/{quiz_key}")
def get_quiz_analytics_detail(
    quiz_key: str,
    request: Request,
    window: str = "month",
    version_scope: str = "all",
    version_id: int = 0,
    start_date: str = "",
    end_date: str = "",
):
    shared._require_admin(request)
    exam = shared.deps.get_quiz_definition(str(quiz_key or "").strip())
    if not exam:
        raise shared.HTTPException(status_code=404, detail="测验不存在")
    return shared._serialize_quiz_analytics_detail(
        exam,
        request=request,
        window=window,
        version_scope=version_scope,
        version_id=(int(version_id or 0) or None),
        start_date=start_date,
        end_date=end_date,
    )
