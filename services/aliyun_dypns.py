from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from config import logger
from services.system_log import log_event


def _pct_encode(s: str) -> str:
    # Aliyun RPC percent-encoding rules.
    return quote(str(s or ""), safe="~")


def _sign(parameters: dict[str, Any], access_key_secret: str) -> str:
    items = sorted((str(k), str(v)) for k, v in parameters.items() if v is not None)
    canonicalized = "&".join(f"{_pct_encode(k)}={_pct_encode(v)}" for k, v in items)
    string_to_sign = "POST&%2F&" + _pct_encode(canonicalized)
    key = (access_key_secret or "").strip() + "&"
    digest = hmac.new(key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def _rpc_call(action: str, *, extra: dict[str, Any]) -> dict[str, Any]:
    access_key_id = (os.getenv("ALIYUN_ACCESS_KEY_ID") or "").strip()
    access_key_secret = (os.getenv("ALIYUN_ACCESS_KEY_SECRET") or "").strip()
    if not access_key_id or not access_key_secret:
        raise RuntimeError("Missing ALIYUN_ACCESS_KEY_ID/ALIYUN_ACCESS_KEY_SECRET")

    endpoint = (os.getenv("ALIYUN_DYPNS_ENDPOINT") or "dypnsapi.aliyuncs.com").strip()
    region_id = (os.getenv("ALIYUN_DYPNS_REGION_ID") or "").strip()

    params: dict[str, Any] = {
        "Action": action,
        "Version": "2017-05-25",
        "Format": "JSON",
        "AccessKeyId": access_key_id,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0",
        "SignatureNonce": str(uuid.uuid4()),
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if region_id:
        params["RegionId"] = region_id
    params.update(extra or {})

    params["Signature"] = _sign(params, access_key_secret)

    body = "&".join(f"{_pct_encode(k)}={_pct_encode(v)}" for k, v in sorted(params.items()))
    data = body.encode("utf-8")
    url = f"https://{endpoint}/"
    req = Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")

    start = time.time()
    raw = ""
    status = 0
    try:
        with urlopen(req, timeout=30) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            raw = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        status = int(getattr(e, "code", 0) or 0)
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
    dt = time.time() - start

    try:
        obj = json.loads(raw) if raw else {}
    except Exception as e:
        raise RuntimeError(f"Aliyun DYPNS returned non-JSON (HTTP {status}): {raw[:400]}") from e

    if isinstance(obj, dict):
        obj.setdefault("_http_status", status)
    if status and status >= 400:
        logger.warning("Aliyun DYPNS %s failed (HTTP %s) in %.2fs: %s", action, status, dt, str(obj)[:240])
    else:
        logger.debug("Aliyun DYPNS %s ok in %.2fs", action, dt)
    return obj if isinstance(obj, dict) else {"_http_status": status, "raw": obj}


def send_sms_verify_code(phone: str) -> dict[str, Any]:
    sign_name = (os.getenv("ALIYUN_SMS_SIGN_NAME") or "").strip()
    template_code = (os.getenv("ALIYUN_SMS_TEMPLATE_CODE") or "").strip()
    if not sign_name or not template_code:
        raise RuntimeError("Missing ALIYUN_SMS_SIGN_NAME/ALIYUN_SMS_TEMPLATE_CODE")

    template_param = (os.getenv("ALIYUN_SMS_TEMPLATE_PARAM") or "").strip()
    if not template_param:
        # Default matches the console example.
        template_param = json.dumps({"code": "##code##", "min": "5"}, ensure_ascii=False)

    scheme_name = (os.getenv("ALIYUN_SMS_SCHEME_NAME") or "").strip()
    country_code = (os.getenv("ALIYUN_SMS_COUNTRY_CODE") or "").strip()
    out_id = (os.getenv("ALIYUN_SMS_OUT_ID") or "").strip()
    sms_up_extend_code = (os.getenv("ALIYUN_SMS_UP_EXTEND_CODE") or "").strip()

    extra: dict[str, Any] = {
        "PhoneNumber": str(phone or "").strip(),
        "SignName": sign_name,
        "TemplateCode": template_code,
        "TemplateParam": template_param,
    }
    if scheme_name:
        extra["SchemeName"] = scheme_name
    if country_code:
        extra["CountryCode"] = country_code
    if out_id:
        extra["OutId"] = out_id
    if sms_up_extend_code:
        extra["SmsUpExtendCode"] = sms_up_extend_code

    # Optional knobs.
    code_len = (os.getenv("ALIYUN_SMS_CODE_LENGTH") or "").strip()
    valid_time = (os.getenv("ALIYUN_SMS_VALID_TIME") or "").strip()
    if code_len:
        extra["CodeLength"] = code_len
    if valid_time:
        extra["ValidTime"] = valid_time

    try:
        res = _rpc_call("SendSmsVerifyCode", extra=extra)
    except Exception as e:
        raise
    return res


def check_sms_verify_code(phone: str, code: str) -> dict[str, Any]:
    scheme_name = (os.getenv("ALIYUN_SMS_SCHEME_NAME") or "").strip()
    country_code = (os.getenv("ALIYUN_SMS_COUNTRY_CODE") or "").strip()
    out_id = (os.getenv("ALIYUN_SMS_OUT_ID") or "").strip()

    extra: dict[str, Any] = {
        "PhoneNumber": str(phone or "").strip(),
        "VerifyCode": str(code or "").strip(),
    }
    if scheme_name:
        extra["SchemeName"] = scheme_name
    if country_code:
        extra["CountryCode"] = country_code
    if out_id:
        extra["OutId"] = out_id

    case_auth_policy = (os.getenv("ALIYUN_SMS_CASE_AUTH_POLICY") or "").strip()
    if case_auth_policy:
        extra["CaseAuthPolicy"] = case_auth_policy

    try:
        res = _rpc_call("CheckSmsVerifyCode", extra=extra)
    except Exception as e:
        raise
    return res
