from __future__ import annotations

from typing import Any

from config import logger
from db import create_system_log
from services.audit_context import get_audit_context


def log_event(
    event_type: str,
    *,
    actor: str | None = None,
    candidate_id: int | None = None,
    exam_key: str | None = None,
    token: str | None = None,
    llm_prompt_tokens: int | None = None,
    llm_completion_tokens: int | None = None,
    llm_total_tokens: int | None = None,
    duration_seconds: int | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    meta: dict[str, Any] | None = None,
) -> int:
    ctx = get_audit_context()
    a = str(actor or ctx.get("actor") or "system")
    cid = candidate_id if candidate_id is not None else ctx.get("candidate_id")
    ek = exam_key if exam_key is not None else ctx.get("exam_key")
    t = token if token is not None else ctx.get("token")
    ip2 = str(ip or ctx.get("ip") or "").strip() or None
    ua2 = str(user_agent or ctx.get("user_agent") or "").strip() or None
    merged_meta: dict[str, Any] = {}
    try:
        cm = ctx.get("meta")
        if isinstance(cm, dict):
            merged_meta.update(cm)
    except Exception:
        pass
    if isinstance(meta, dict):
        merged_meta.update(meta)
    if not merged_meta:
        merged_meta = None  # type: ignore[assignment]

    # If the caller didn't pass token usage explicitly, try to fill it from audit meta accumulation.
    # This lets one business log row carry the total token cost of the operation.
    if llm_total_tokens is None and isinstance(merged_meta, dict):
        try:
            tt = int(merged_meta.get("llm_total_tokens_sum") or 0)
        except Exception:
            tt = 0
        if tt > 0:
            llm_total_tokens = tt

    try:
        return int(
            create_system_log(
                actor=a,
                event_type=str(event_type or "").strip(),
                candidate_id=(int(cid) if cid is not None else None),
                exam_key=(str(ek).strip() if ek else None),
                token=(str(t).strip() if t else None),
                llm_prompt_tokens=llm_prompt_tokens,
                llm_completion_tokens=llm_completion_tokens,
                llm_total_tokens=llm_total_tokens,
                duration_seconds=duration_seconds,
                ip=ip2,
                user_agent=ua2,
                meta=merged_meta,
            )
        )
    except Exception:
        logger.exception("Failed to write system log (event_type=%s)", event_type)
        return 0
