from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from config import STORAGE_DIR, logger
from db import create_system_log, has_system_alert, touch_system_alert
from db import estimate_sms_calls_for_day
from storage.json_store import read_json, write_json

_LOCK = threading.Lock()


def _metrics_path():
    return STORAGE_DIR / "system_metrics_daily.json"


def _cfg_path():
    return STORAGE_DIR / "system_status.json"


def _today_local_day() -> str:
    return datetime.now().astimezone().date().isoformat()


def _load_cfg() -> dict[str, int]:
    try:
        obj = read_json(_cfg_path())
    except Exception:
        obj = {}
    if not isinstance(obj, dict):
        obj = {}
    try:
        llm = int(obj.get("llm_tokens_limit") or 0)
    except Exception:
        llm = 0
    try:
        sms = int(obj.get("sms_calls_limit") or 0)
    except Exception:
        sms = 0
    return {"llm_tokens_limit": max(0, llm), "sms_calls_limit": max(0, sms)}


def _load_metrics() -> dict[str, dict[str, int]]:
    try:
        obj = read_json(_metrics_path())
    except Exception:
        obj = {}
    if not isinstance(obj, dict):
        return {}
    out: dict[str, dict[str, int]] = {}
    for k, v in obj.items():
        day = str(k or "").strip()[:10]
        if not day:
            continue
        if not isinstance(v, dict):
            continue
        dd: dict[str, int] = {}
        for kk, vv in v.items():
            try:
                dd[str(kk)] = max(0, int(vv or 0))
            except Exception:
                continue
        out[day] = dd
    return out


def _save_metrics(data: dict[str, dict[str, int]]) -> None:
    try:
        write_json(_metrics_path(), data)
    except Exception:
        pass


def _load_metrics_raw() -> dict[str, Any]:
    try:
        obj = read_json(_metrics_path())
    except Exception:
        obj = {}
    if not isinstance(obj, dict):
        return {}
    return dict(obj)


def _save_metrics_raw(obj: dict[str, Any]) -> None:
    try:
        write_json(_metrics_path(), obj)
    except Exception:
        pass


def get_daily_metric(*, day: str, key: str) -> int:
    d = str(day or "").strip()[:10]
    k = str(key or "").strip()
    if not d or not k:
        return 0
    with _LOCK:
        m = _load_metrics()
        try:
            return int((m.get(d) or {}).get(k) or 0)
        except Exception:
            return 0


def incr_daily_metric(*, day: str, key: str, delta: int) -> int:
    d = str(day or "").strip()[:10]
    k = str(key or "").strip()
    try:
        dd = int(delta or 0)
    except Exception:
        dd = 0
    if not d or not k or dd == 0:
        return 0
    with _LOCK:
        m = _load_metrics()
        row = dict(m.get(d) or {})
        try:
            cur = int(row.get(k) or 0)
        except Exception:
            cur = 0
        row[k] = max(0, cur + dd)
        m[d] = row
        _save_metrics(m)
        return int(row[k] or 0)


def set_daily_last(*, day: str, key: str, value: dict[str, Any]) -> None:
    d = str(day or "").strip()[:10]
    k = str(key or "").strip()
    if not d or not k:
        return
    v = dict(value or {})
    with _LOCK:
        obj = _load_metrics_raw()
        row = obj.get(d)
        if not isinstance(row, dict):
            row = {}
        row[k] = v
        obj[d] = row
        _save_metrics_raw(obj)


def _level_from_ratio(ratio: float) -> str:
    r = float(ratio or 0.0)
    if r >= 1.0:
        return "critical"
    if r >= 0.9:
        return "danger"
    if r >= 0.7:
        return "warn"
    return "ok"


def _safe_ratio(used: int, limit: int) -> float:
    try:
        u = int(used or 0)
    except Exception:
        u = 0
    try:
        l = int(limit or 0)
    except Exception:
        l = 0
    if u <= 0 or l <= 0:
        return 0.0
    return float(u) / float(l)


def _maybe_emit_system_alert(*, day: str, kind: str, used: int, limit: int) -> None:
    ratio = _safe_ratio(used, limit)
    level = _level_from_ratio(ratio)
    if level not in {"warn", "danger", "critical"}:
        return
    try:
        if has_system_alert(day=day, kind=kind, level=level):
            try:
                touch_system_alert(day=day, kind=kind, level=level, used=int(used or 0), limit=int(limit or 0), ratio=float(ratio or 0.0))
            except Exception:
                pass
            return
    except Exception:
        # If dedupe check fails, still best-effort write once.
        pass
    try:
        create_system_log(
            actor="system",
            event_type="system.alert",
            meta={
                "day": day,
                "kind": kind,
                "level": level,
                "used": int(used or 0),
                "limit": int(limit or 0),
                "ratio": float(ratio or 0.0),
            },
        )
    except Exception:
        logger.exception("Failed to emit system.alert (kind=%s, level=%s)", kind, level)


def incr_sms_calls_and_alert(delta: int = 1) -> int:
    day = _today_local_day()
    used = incr_daily_metric(day=day, key="sms_calls", delta=int(delta or 0))
    cfg = _load_cfg()
    limit = int(cfg.get("sms_calls_limit") or 0)
    _maybe_emit_system_alert(day=day, kind="sms_calls", used=used, limit=limit)
    return used


def incr_llm_tokens_and_alert(total_tokens: int | None) -> int:
    try:
        dt = int(total_tokens or 0)
    except Exception:
        dt = 0
    if dt <= 0:
        return 0
    day = _today_local_day()
    used = incr_daily_metric(day=day, key="llm_tokens", delta=dt)
    cfg = _load_cfg()
    limit = int(cfg.get("llm_tokens_limit") or 0)
    _maybe_emit_system_alert(day=day, kind="llm_tokens", used=used, limit=limit)
    return used


def ensure_sms_calls_metric(*, day: str, tz_offset_seconds: int) -> int:
    """
    Backfill sms_calls daily metric when it's missing in the file store.

    This keeps the "系统状态" panel consistent for days where we previously relied on DB logs.
    """
    d = str(day or "").strip()[:10]
    if not d:
        return 0
    with _LOCK:
        m = _load_metrics()
        row = dict(m.get(d) or {})
        try:
            cur = int(row.get("sms_calls") or 0)
        except Exception:
            cur = 0
        if cur > 0:
            return cur
    # Query outside the lock to avoid holding it during DB I/O.
    try:
        est = int(estimate_sms_calls_for_day(day=d, tz_offset_seconds=int(tz_offset_seconds or 0)) or 0)
    except Exception:
        est = 0
    if est <= 0:
        return 0
    with _LOCK:
        m2 = _load_metrics()
        row2 = dict(m2.get(d) or {})
        try:
            cur2 = int(row2.get("sms_calls") or 0)
        except Exception:
            cur2 = 0
        if cur2 <= 0:
            row2["sms_calls"] = int(est)
            m2[d] = row2
            _save_metrics(m2)
            return int(est)
        return cur2


def record_llm_usage(*, total_tokens: int | None, ctx: dict[str, Any] | None = None, model: str | None = None) -> None:
    try:
        tt = int(total_tokens or 0)
    except Exception:
        tt = 0
    if tt <= 0:
        return
    c = dict(ctx or {})
    try:
        candidate_id = int(c.get("candidate_id") or 0)
    except Exception:
        candidate_id = 0
    exam_key = str(c.get("exam_key") or "").strip()
    token = str(c.get("token") or "").strip()
    actor = str(c.get("actor") or "").strip() or "system"
    day = _today_local_day()
    set_daily_last(
        day=day,
        key="llm_last",
        value={
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "total_tokens": tt,
            "model": (str(model or "").strip() or None),
            "actor": actor,
            "candidate_id": (candidate_id if candidate_id > 0 else None),
            "exam_key": (exam_key or None),
            "token": (token or None),
        },
    )
