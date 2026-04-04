from __future__ import annotations

from backend.md_quiz.services.support_deps import *
from backend.md_quiz.services.validation_helpers import *
from urllib.parse import urlsplit

_SYSTEM_STATUS_LEVEL_SEVERITY = {
    "ok": 0,
    "warn": 1,
    "danger": 2,
    "critical": 3,
}
_SYSTEM_STATUS_REQUIRED_ENV_FIELDS = {
    "llm": {
        "label": "LLM",
        "fields": ["OPENAI_API_KEY", "OPENAI_MODEL"],
    },
    "sms": {
        "label": "短信认证",
        "fields": [
            "ALIYUN_ACCESS_KEY_ID",
            "ALIYUN_ACCESS_KEY_SECRET",
            "ALIYUN_PNVS_SIGN_NAME",
            "ALIYUN_PNVS_TEMPLATE_CODE",
        ],
    },
}

_DEFAULT_OPENAI_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
_DEFAULT_ALIYUN_PNVS_ENDPOINT = "dypnsapi.aliyuncs.com"


# 系统状态：读取阈值配置（大模型 token / 短信调用）。
def _load_system_status_cfg() -> dict[str, int]:
    """
    Load daily thresholds for system status page.
    """
    obj = get_runtime_kv("system_status_config") or {}
    llm = _safe_int(obj.get("llm_tokens_limit"), 0)
    sms = _safe_int(obj.get("sms_calls_limit"), 0)
    return {"llm_tokens_limit": max(0, llm), "sms_calls_limit": max(0, sms)}


def _save_system_status_cfg(cfg: dict[str, object]) -> dict[str, int]:
    out = _load_system_status_cfg()
    if isinstance(cfg, dict):
        if "llm_tokens_limit" in cfg:
            out["llm_tokens_limit"] = max(0, _safe_int(cfg.get("llm_tokens_limit"), 0))
        if "sms_calls_limit" in cfg:
            out["sms_calls_limit"] = max(0, _safe_int(cfg.get("sms_calls_limit"), 0))
    try:
        set_runtime_kv("system_status_config", out)
    except Exception:
        pass
    return out


def _level_from_ratio(ratio: float) -> tuple[str, int]:
    r = float(ratio or 0.0)
    if r >= 1.0:
        return "critical", 3
    if r >= 0.9:
        return "danger", 2
    if r >= 0.7:
        return "warn", 1
    return "ok", 0


def _safe_ratio(used: int, limit: int) -> float:
    try:
        u = int(used or 0)
    except Exception:
        u = 0
    try:
        l = int(limit or 0)
    except Exception:
        l = 0
    if u <= 0:
        return 0.0
    if l <= 0:
        return 0.0
    return float(u) / float(l)


def _status_overall_level(items: list[tuple[str, int]]) -> str:
    """
    items: list of (level_key, severity_int)
    """
    best = ("ok", 0)
    for k, s in items or []:
        if int(s) > int(best[1]):
            best = (str(k), int(s))
    return str(best[0])


def _missing_required_env_fields(fields: list[str]) -> list[str]:
    return [field for field in fields if not str(os.getenv(field) or "").strip()]


def _display_summary_value(value: object, *, default: str = "未设置") -> str:
    text = str(value or "").strip()
    return text or default


def _extract_host_label(raw: object, *, default: str = "") -> str:
    text = str(raw or "").strip()
    if not text:
        return default
    try:
        parsed = urlsplit(text)
    except Exception:
        return text
    host = str(parsed.netloc or parsed.path or "").strip()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    return host or text


def _build_llm_integration_summary() -> dict[str, str]:
    model = str(os.getenv("OPENAI_MODEL") or "").strip()
    base_url = str(os.getenv("OPENAI_BASE_URL") or _DEFAULT_OPENAI_BASE_URL).strip()
    endpoint_host = _extract_host_label(base_url, default=_extract_host_label(_DEFAULT_OPENAI_BASE_URL))
    return {
        "title": "OpenAI 兼容 Responses API",
        "summary": f"模型 {_display_summary_value(model)} · 接口 {_display_summary_value(endpoint_host)}",
    }


def _build_sms_integration_summary() -> dict[str, str]:
    sign_name = str(os.getenv("ALIYUN_PNVS_SIGN_NAME") or "").strip()
    template_code = str(os.getenv("ALIYUN_PNVS_TEMPLATE_CODE") or "").strip()
    endpoint = str(os.getenv("ALIYUN_PNVS_ENDPOINT") or _DEFAULT_ALIYUN_PNVS_ENDPOINT).strip()
    region_id = str(os.getenv("ALIYUN_PNVS_REGION_ID") or "").strip()
    summary_parts = [
        f"签名 {_display_summary_value(sign_name)}",
        f"模板 {_display_summary_value(template_code)}",
        f"接口 {_display_summary_value(endpoint)}",
    ]
    if region_id:
        summary_parts.append(f"地域 {region_id}")
    return {
        "title": "阿里云 PNVS 短信认证",
        "summary": " · ".join(summary_parts),
    }


def _build_system_status_config_summary() -> dict[str, object]:
    modules: dict[str, dict[str, object]] = {}
    alerts: list[dict[str, object]] = []
    for key, meta in _SYSTEM_STATUS_REQUIRED_ENV_FIELDS.items():
        label = str(meta.get("label") or key)
        fields = list(meta.get("fields") or [])
        missing_fields = _missing_required_env_fields(fields)
        configured = not missing_fields
        item = {
            "configured": configured,
            "missing_fields": missing_fields,
        }
        modules[key] = item
        if configured:
            continue
        alerts.append(
            {
                "key": key,
                "label": label,
                "level": "danger",
                "missing_fields": missing_fields,
                "message": f"{label} 缺少 {'、'.join(missing_fields)}，请先在 .env 中完成配置并重启服务。",
            }
        )
    return {
        "llm": modules.get("llm") or {"configured": True, "missing_fields": []},
        "sms": modules.get("sms") or {"configured": True, "missing_fields": []},
        "config_alerts": alerts,
    }


def _compute_system_status_range(*, start_day: date, end_day: date) -> dict[str, object]:
    """
    Compute daily system status metrics for [start_day, end_day] inclusive (local).
    """
    now_local = datetime.now().astimezone()
    local_tz = now_local.tzinfo
    today_local = now_local.date()

    sday = start_day if isinstance(start_day, date) else today_local
    eday = end_day if isinstance(end_day, date) else today_local
    if eday > today_local:
        eday = today_local
    if sday > eday:
        sday = eday

    start_local_dt = datetime.combine(sday, dt_time.min, tzinfo=local_tz)
    end_local_dt = datetime.combine(eday, dt_time.max, tzinfo=local_tz)
    try:
        tz_offset_seconds = int((now_local.utcoffset() or timedelta(0)).total_seconds())
    except Exception:
        tz_offset_seconds = 0

    rows = list_system_status_daily_metrics(
        tz_offset_seconds=tz_offset_seconds,
        at_from=start_local_dt.astimezone(timezone.utc),
        at_to=end_local_dt.astimezone(timezone.utc),
    )
    try:
        sms_est_map = list_estimated_sms_calls_daily_counts(
            tz_offset_seconds=tz_offset_seconds,
            at_from=start_local_dt.astimezone(timezone.utc),
            at_to=end_local_dt.astimezone(timezone.utc),
        )
    except Exception:
        sms_est_map = {}
    m: dict[str, dict[str, int]] = {}
    for r in rows or []:
        k = str(r.get("day") or "")[:10]
        if not k:
            continue
        m[k] = {
            "exams_new": int(r.get("exams_new") or 0),
            "invites_new": int(r.get("invites_new") or 0),
            "candidates_new": int(r.get("candidates_new") or 0),
            "llm_tokens": int(r.get("llm_tokens") or 0),
            "sms_calls": int(r.get("sms_calls") or 0),
        }

    days: list[str] = []
    items: list[dict[str, int | str]] = []
    span = max(0, min(180, (eday - sday).days))
    for i in range(span + 1):
        d = sday + timedelta(days=i)
        ds = d.isoformat()
        days.append(ds)
        it = m.get(ds) or {}
        # Override llm/sms usage with file-based daily counters so we can avoid persisting per-call logs.
        try:
            llm_used2 = int(get_daily_metric(day=ds, key="llm_tokens") or 0)
        except Exception:
            llm_used2 = 0
        try:
            sms_used2 = int(get_daily_metric(day=ds, key="sms_calls") or 0)
        except Exception:
            sms_used2 = 0
        if sms_used2 <= 0:
            try:
                sms_used2 = int(sms_est_map.get(ds) or 0)
            except Exception:
                sms_used2 = 0
        items.append(
            {
                "day": ds,
                "exams_new": int(it.get("exams_new") or 0),
                "invites_new": int(it.get("invites_new") or 0),
                "candidates_new": int(it.get("candidates_new") or 0),
                "llm_tokens": int(llm_used2) if llm_used2 > 0 else int(it.get("llm_tokens") or 0),
                "sms_calls": int(sms_used2) if sms_used2 > 0 else int(it.get("sms_calls") or 0),
            }
        )

    return {"days": days, "items": items, "range_start": sday.isoformat(), "range_end": eday.isoformat()}


def _compute_system_status_summary() -> dict[str, object]:
    cfg = _load_system_status_cfg()
    config_summary = _build_system_status_config_summary()
    llm_integration = _build_llm_integration_summary()
    sms_integration = _build_sms_integration_summary()
    today = datetime.now().astimezone().date()
    data = _compute_system_status_range(start_day=today, end_day=today)
    it0 = (data.get("items") or [{}])[0] if isinstance(data.get("items"), list) else {}
    used_llm = int(it0.get("llm_tokens") or 0)
    used_sms = int(it0.get("sms_calls") or 0)

    llm_limit = int(cfg.get("llm_tokens_limit") or 0)
    sms_limit = int(cfg.get("sms_calls_limit") or 0)

    llm_ratio = _safe_ratio(used_llm, llm_limit)
    sms_ratio = _safe_ratio(used_sms, sms_limit)

    llm_ratio_level, llm_ratio_sev = _level_from_ratio(llm_ratio)
    sms_ratio_level, sms_ratio_sev = _level_from_ratio(sms_ratio)

    llm_items = [(llm_ratio_level, llm_ratio_sev)]
    sms_items = [(sms_ratio_level, sms_ratio_sev)]
    if not bool((config_summary.get("llm") or {}).get("configured")):
        llm_items.append(("danger", _SYSTEM_STATUS_LEVEL_SEVERITY["danger"]))
    if not bool((config_summary.get("sms") or {}).get("configured")):
        sms_items.append(("danger", _SYSTEM_STATUS_LEVEL_SEVERITY["danger"]))

    llm_level = _status_overall_level(llm_items)
    sms_level = _status_overall_level(sms_items)
    overall = _status_overall_level(
        [
            (llm_level, _SYSTEM_STATUS_LEVEL_SEVERITY.get(llm_level, 0)),
            (sms_level, _SYSTEM_STATUS_LEVEL_SEVERITY.get(sms_level, 0)),
        ]
    )

    day = str(today.isoformat())
    llm_config = dict(config_summary.get("llm") or {})
    sms_config = dict(config_summary.get("sms") or {})

    return {
        "day": day,
        "config": cfg,
        "overall_level": overall,
        "config_alerts": list(config_summary.get("config_alerts") or []),
        "llm": {
            "used": used_llm,
            "limit": llm_limit,
            "ratio": llm_ratio,
            "level": llm_level,
            "configured": bool(llm_config.get("configured")),
            "missing_fields": list(llm_config.get("missing_fields") or []),
            "integration": llm_integration,
        },
        "sms": {
            "used": used_sms,
            "limit": sms_limit,
            "ratio": sms_ratio,
            "level": sms_level,
            "configured": bool(sms_config.get("configured")),
            "missing_fields": list(sms_config.get("missing_fields") or []),
            "integration": sms_integration,
        },
    }


_SYSTEM_STATUS_SUMMARY_CACHE_LOCK = threading.Lock()
_SYSTEM_STATUS_SUMMARY_CACHE: dict[str, object] = {"at": 0.0, "value": {}}
_SYSTEM_STATUS_SUMMARY_TTL_SECONDS = 15.0
_ADMIN_LOGS_CONTEXT_CACHE_LOCK = threading.Lock()
_ADMIN_LOGS_CONTEXT_CACHE: dict[tuple[str, ...], dict[str, object]] = {}
_ADMIN_LOGS_CONTEXT_TTL_SECONDS = 15.0
_ADMIN_ASSIGNMENTS_CONTEXT_CACHE_LOCK = threading.Lock()
_ADMIN_ASSIGNMENTS_CONTEXT_CACHE: dict[tuple[str, ...], dict[str, object]] = {}
_ADMIN_ASSIGNMENTS_CONTEXT_TTL_SECONDS = 8.0


def _peek_cached_system_status_summary() -> dict[str, object]:
    with _SYSTEM_STATUS_SUMMARY_CACHE_LOCK:
        cached_val = _SYSTEM_STATUS_SUMMARY_CACHE.get("value") or {}
        return dict(cached_val) if isinstance(cached_val, dict) else {}


def _get_cached_system_status_summary(*, force: bool = False) -> dict[str, object]:
    now_ts = time_module.time()
    with _SYSTEM_STATUS_SUMMARY_CACHE_LOCK:
        cached_at = float(_SYSTEM_STATUS_SUMMARY_CACHE.get("at") or 0.0)
        cached_val = _SYSTEM_STATUS_SUMMARY_CACHE.get("value") or {}
        if (not force) and cached_val and (now_ts - cached_at) < _SYSTEM_STATUS_SUMMARY_TTL_SECONDS:
            return dict(cached_val) if isinstance(cached_val, dict) else {}
    fresh = _compute_system_status_summary()
    with _SYSTEM_STATUS_SUMMARY_CACHE_LOCK:
        _SYSTEM_STATUS_SUMMARY_CACHE["at"] = now_ts
        _SYSTEM_STATUS_SUMMARY_CACHE["value"] = fresh if isinstance(fresh, dict) else {}
    return dict(fresh) if isinstance(fresh, dict) else {}


def _get_cached_logs_context(key: tuple[str, ...]) -> dict[str, Any] | None:
    now_ts = time_module.time()
    with _ADMIN_LOGS_CONTEXT_CACHE_LOCK:
        item = _ADMIN_LOGS_CONTEXT_CACHE.get(key)
        if not item:
            return None
        at = float(item.get("at") or 0.0)
        value = item.get("value") or {}
        if (now_ts - at) >= _ADMIN_LOGS_CONTEXT_TTL_SECONDS:
            return None
        return dict(value) if isinstance(value, dict) else None


def _set_cached_logs_context(key: tuple[str, ...], value: dict[str, Any]) -> None:
    with _ADMIN_LOGS_CONTEXT_CACHE_LOCK:
        _ADMIN_LOGS_CONTEXT_CACHE[key] = {"at": time_module.time(), "value": dict(value)}


def _get_cached_assignments_context(key: tuple[str, ...]) -> dict[str, Any] | None:
    now_ts = time_module.time()
    with _ADMIN_ASSIGNMENTS_CONTEXT_CACHE_LOCK:
        item = _ADMIN_ASSIGNMENTS_CONTEXT_CACHE.get(key)
        if not item:
            return None
        at = float(item.get("at") or 0.0)
        value = item.get("value") or {}
        if (now_ts - at) >= _ADMIN_ASSIGNMENTS_CONTEXT_TTL_SECONDS:
            return None
        return dict(value) if isinstance(value, dict) else None


def _set_cached_assignments_context(key: tuple[str, ...], value: dict[str, Any]) -> None:
    with _ADMIN_ASSIGNMENTS_CONTEXT_CACHE_LOCK:
        _ADMIN_ASSIGNMENTS_CONTEXT_CACHE[key] = {"at": time_module.time(), "value": dict(value)}


# 系统日志：将内部事件类型映射为页面展示标签。
def _oplog_type_label_v2(et: str) -> tuple[str, str]:
    et = str(et or "").strip()
    if et.startswith("candidate."):
        return "candidate", "候选人操作"
    if et in {"assignment.create", "assignment.verify", "exam.enter", "exam.finish"}:
        return "assignment", "答题邀约操作"
    if et == "exam.grade":
        return "grading", "判卷操作"
    if et == "system.alert" or et.startswith("sms."):
        return "system", "系统"
    if et.startswith("exam."):
        return "exam", "测验操作"
    return "system", "系统"


def _oplog_safe_int2(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except Exception:
        return None


def _oplog_join_plus2(*parts: str) -> str:
    items = [str(x or "").strip() for x in parts]
    items = [x for x in items if x]
    return "+".join(items)


def _oplog_phone_from_assignment(token: str) -> str:
    t = str(token or "").strip()
    if not t:
        return ""
    try:
        obj = load_assignment(t)
    except Exception:
        return ""
    if not isinstance(obj, dict):
        return ""
    sms = obj.get("sms_verify") if isinstance(obj.get("sms_verify"), dict) else {}
    pending = obj.get("pending_verify") if isinstance(obj.get("pending_verify"), dict) else {}
    raw = str((sms or {}).get("phone") or (pending or {}).get("phone") or "").strip()
    if not raw:
        return ""
    p2 = _normalize_phone(raw)
    if len(p2) == 11 and p2.startswith("1"):
        return p2
    return ""


def _oplog_is_deleted_marker(v: str) -> bool:
    s = str(v or "").strip().lower()
    if not s:
        return False
    if s in {"已删除", "deleted", "???", "????"}:
        return True
    if "?" in s and len(s) <= 12:
        return True
    return s.startswith("deleted_")


def _oplog_pick_name_phone2(it: dict[str, Any], meta: dict[str, Any]) -> tuple[str, str]:
    meta_name = str(meta.get("name") or "").strip()
    candidate_name = str(it.get("candidate_name") or "").strip()
    raw_name = meta_name if meta_name else candidate_name
    raw_phone = str(meta.get("phone") or it.get("candidate_phone") or "").strip()
    cid = _oplog_safe_int2(it.get("candidate_id")) or 0

    deleted_phone_placeholder = str(raw_phone or "").strip().upper().startswith("DELETED_")

    n = ""
    if not _oplog_is_deleted_marker(raw_name):
        n = raw_name
    elif candidate_name and not _oplog_is_deleted_marker(candidate_name):
        # Backward-compat for old rows where meta.name was overwritten by delete marker.
        n = candidate_name
    if not n and cid > 0:
        n = f"候选人#{cid}"

    p = ""
    if raw_phone and not deleted_phone_placeholder:
        p2 = _normalize_phone(raw_phone)
        # Guard against malformed placeholder leftovers; only keep mainland 11-digit number.
        if len(p2) == 11 and p2.startswith("1"):
            p = p2
    if not p:
        try:
            p = _oplog_phone_from_assignment(str(it.get("token") or ""))
        except Exception:
            p = p or ""
    return n, p


def _oplog_exam_id_text2(meta: dict[str, Any], quiz_key: str) -> str:
    # User requirement: "测验id" means quiz_key (not sort-id).
    return str(quiz_key or "").strip() or "未知测验"


def _oplog_detail_text_v2(it: dict[str, Any]) -> str:
    et = str(it.get("event_type") or "").strip()
    meta = it.get("meta") if isinstance(it.get("meta"), dict) else {}
    quiz_key = str(it.get("quiz_key") or "").strip()
    exam_id = _oplog_exam_id_text2(meta, quiz_key)
    name, phone = _oplog_pick_name_phone2(it, meta)
    who_plus = _oplog_join_plus2(name, phone, exam_id)
    public_invite = bool(meta.get("public_invite"))

    if et.startswith("candidate."):
        op = et.split(".", 1)[1] if "." in et else et
        if op == "read":
            return f"查看{name or '候选人'}详情".strip()
        if op == "create":
            return f"新增{_oplog_join_plus2(name, phone)}".strip("+")
        if op == "delete":
            return f"删除{_oplog_join_plus2(name, phone)}".strip("+")
        if op in {"resume.parse", "resume_parse"}:
            try:
                tt = int(it.get("llm_total_tokens") or 0)
            except Exception:
                tt = 0
            try:
                is_reparse = bool(meta.get("reparse"))
            except Exception:
                is_reparse = False
            if is_reparse:
                return f"重新上传并解析简历，消耗token：{tt}" if tt > 0 else "重新上传并解析简历"
            return f"解析简历，消耗token：{tt}" if tt > 0 else "解析简历"
        return f"候选人操作{op}".strip()

    if et == "assignment.verify":
        try:
            sms_cnt = int(meta.get("sms_send_count") or 0)
        except Exception:
            sms_cnt = 0
        prefix = "公开邀约+" if public_invite else ""
        return f"{prefix}{who_plus}，消耗短信认证{sms_cnt}次".strip()

    if et == "exam.enter":
        prefix = "公开邀约+" if public_invite else ""
        return f"{prefix}进入答题{who_plus}".strip()

    if et == "exam.finish":
        prefix = "公开邀约+" if public_invite else ""
        return f"{prefix}提交答题{who_plus}".strip()

    if et == "exam.grade":
        score = meta.get("score")
        try:
            s2 = int(score or 0)
        except Exception:
            s2 = _oplog_safe_int2(score) or 0
        try:
            tt = int(it.get("llm_total_tokens") or 0)
        except Exception:
            tt = 0
        tok_part = f"，消耗token：{tt}" if tt > 0 else ""
        return f"判卷完成{_oplog_join_plus2(name, phone, exam_id)}（得分：{s2}）{tok_part}".strip()

    if et == "system.alert":
        kind = str(meta.get("kind") or "").strip() or "unknown"
        kind_label = kind
        if kind == "sms_calls":
            kind_label = "短信认证"
        elif kind == "llm_tokens":
            kind_label = "大模型token"
        level = str(meta.get("level") or "").strip() or "warn"
        used_i = _oplog_safe_int2(meta.get("used")) or 0
        limit_i = _oplog_safe_int2(meta.get("limit")) or 0
        try:
            pct_i = int(round(float(meta.get("ratio") or 0.0) * 100))
        except Exception:
            pct_i = 0
        used_part = f"（{used_i}/{limit_i}）" if limit_i > 0 else ""
        return f"系统告警：{kind_label}达到阈值，{level} {pct_i}%{used_part}".strip()

    if et.startswith("exam."):
        op = et.split(".", 1)[1] if "." in et else et
        if op == "read":
            view = str(meta.get("view") or "").strip().lower()
            if view == "paper":
                return f"查看候选人视图详情{exam_id}".strip()
            if view == "edit":
                return f"编辑测验{exam_id}".strip()
            return f"查看测验详情{exam_id}".strip()
        if op == "result":
            return f"查看{_oplog_join_plus2(name, phone, exam_id)}的结果".strip("+")
        if op == "upload":
            return f"上传测验{exam_id}".strip()
        if op == "update":
            return f"修改测验{exam_id}".strip()
        if op == "delete":
            return f"删除测验{exam_id}".strip()
        if op == "public_invite.enable":
            return f"测验{exam_id}开启公开邀约".strip()
        if op == "public_invite.disable":
            return f"测验{exam_id}关闭公开邀约".strip()
        return f"测验操作{op}({exam_id})".strip()

    if et == "assignment.create":
        return f"答题邀约{_oplog_join_plus2(name, phone, exam_id)}".strip("+")

    return et


__all__ = [name for name in globals() if not name.startswith("__")]
