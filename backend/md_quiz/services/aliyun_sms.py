from __future__ import annotations

import json
import os
from typing import Any, Optional

from backend.md_quiz.config import logger


def _mask_phone(phone: str) -> str:
    p = str(phone or "").strip()
    if len(p) >= 7:
        return f"{p[:3]}****{p[-4:]}"
    if len(p) >= 3:
        return f"{p[:2]}***"
    return "***"


_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    access_key_id = (os.getenv("ALIYUN_ACCESS_KEY_ID") or "").strip()
    access_key_secret = (os.getenv("ALIYUN_ACCESS_KEY_SECRET") or "").strip()
    if not access_key_id or not access_key_secret:
        raise RuntimeError("Missing ALIYUN_ACCESS_KEY_ID/ALIYUN_ACCESS_KEY_SECRET")

    # Lazy import so the app can boot without SMS deps installed (e.g. in dev).
    from alibabacloud_dysmsapi20170525.client import Client as Dysmsapi20170525Client
    from alibabacloud_tea_openapi import models as open_api_models

    endpoint = (os.getenv("ALIYUN_SMS_ENDPOINT") or "dysmsapi.aliyuncs.com").strip()
    region_id = (os.getenv("ALIYUN_SMS_REGION_ID") or "").strip()

    cfg = open_api_models.Config(access_key_id=access_key_id, access_key_secret=access_key_secret)
    if region_id:
        cfg.region_id = region_id
    if endpoint:
        cfg.endpoint = endpoint

    _client = Dysmsapi20170525Client(cfg)
    return _client


def _build_template_param(code: str, ttl_seconds: int) -> str:
    raw = (os.getenv("ALIYUN_SMS_TEMPLATE_PARAM") or "").strip()
    if not raw:
        raw = json.dumps({"code": "##code##", "min": "##min##"}, ensure_ascii=False)

    minutes = max(1, int(round(max(1, ttl_seconds) / 60.0)))
    replaced = (
        raw.replace("##code##", str(code or "").strip())
        .replace("##min##", str(minutes))
        .replace("##minutes##", str(minutes))
    )

    try:
        obj = json.loads(replaced)
    except Exception:
        # If user provides a plain string (already JSON-like), just pass through.
        return replaced

    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return replaced


def send_sms_verify_code(phone: str, *, code: str, ttl_seconds: int = 300) -> dict[str, Any]:
    sign_name = (os.getenv("ALIYUN_SMS_SIGN_NAME") or "").strip()
    template_code = (os.getenv("ALIYUN_SMS_TEMPLATE_CODE") or "").strip()
    if not sign_name or not template_code:
        raise RuntimeError("Missing ALIYUN_SMS_SIGN_NAME/ALIYUN_SMS_TEMPLATE_CODE")

    client = _get_client()

    # Request model for Dysmsapi 2017-05-25.
    from alibabacloud_dysmsapi20170525 import models as dysms_models

    out_id = (os.getenv("ALIYUN_SMS_OUT_ID") or "").strip()
    sms_up_extend_code = (os.getenv("ALIYUN_SMS_UP_EXTEND_CODE") or "").strip()

    req = dysms_models.SendSmsRequest(
        phone_numbers=str(phone or "").strip(),
        sign_name=sign_name,
        template_code=template_code,
        template_param=_build_template_param(code=code, ttl_seconds=int(ttl_seconds or 0) or 300),
    )
    if out_id:
        req.out_id = out_id
    if sms_up_extend_code:
        req.sms_up_extend_code = sms_up_extend_code

    logger.info("Aliyun SMS SendSms request phone=%s template=%s", _mask_phone(phone), template_code)
    resp = client.send_sms(req)

    body = getattr(resp, "body", None)
    if body is None:
        # Be defensive; Tea SDK always has .body, but avoid breaking callers.
        return {"Success": False, "Code": "NO_BODY", "Message": "Aliyun SMS returned empty body", "Model": {}}

    body_map: Optional[dict[str, Any]] = None
    try:
        body_map = body.to_map()
    except Exception:
        body_map = None

    if isinstance(body_map, dict):
        code2 = str((body_map.get("Code") or body_map.get("code") or "")).strip()
        msg = str((body_map.get("Message") or body_map.get("message") or "")).strip()
        biz_id = str((body_map.get("BizId") or body_map.get("biz_id") or "")).strip()
    else:
        code2 = str(getattr(body, "code", "") or "").strip()
        msg = str(getattr(body, "message", "") or "").strip()
        biz_id = str(getattr(body, "biz_id", "") or "").strip()

    ok = str(code2 or "").upper() == "OK"
    logger.info("Aliyun SMS SendSms response ok=%s code=%s biz_id=%s", ok, code2, biz_id)

    # Keep a compatible shape with the old DYPNS RPC wrapper.
    return {
        "Success": bool(ok),
        "Code": code2 or "",
        "Message": msg or "",
        "Model": {"BizId": biz_id} if biz_id else {},
    }
