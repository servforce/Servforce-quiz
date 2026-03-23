from __future__ import annotations

from web.support.deps import *

# 基础输入校验：姓名、手机号与全角数字归一化。
_NAME_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z·\s]{2,20}$")
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_ALLOWED_RESUME_EXTS = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def _sms_code_length() -> int:
    raw = str(os.getenv("ALIYUN_SMS_CODE_LENGTH") or "").strip()
    try:
        n = int(raw or 6)
    except Exception:
        n = 6
    return min(8, max(4, n))


def _sms_code_ttl_seconds() -> int:
    raw = str(os.getenv("ALIYUN_SMS_CODE_TTL_SECONDS") or "").strip()
    try:
        n = int(raw or 300)
    except Exception:
        n = 300
    return min(3600, max(60, n))


def _generate_sms_code(length: int) -> str:
    n = min(8, max(4, int(length or 6)))
    v = secrets.randbelow(10**n)
    return str(v).zfill(n)


def _hash_sms_code(code: str, salt: str) -> str:
    return hmac.new(str(salt or "").encode("utf-8"), str(code or "").encode("utf-8"), hashlib.sha256).hexdigest()


def _parse_iso_datetime(s: str) -> datetime | None:
    text = str(s or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


# 校验中文姓名（2-20字符，允许·与空格）。
def _is_valid_name(value: str) -> bool:
    v = (value or "").strip()
    return bool(_NAME_RE.fullmatch(v))

# 校验手机号（支持 +86/86 前缀及常见分隔符）。
def _is_valid_phone(value: str) -> bool:
    v = (value or "").strip()
    v = v.replace(" ", "").replace("-", "")
    if v.startswith("+86"):
        v = v[3:]
    if v.startswith("86") and len(v) == 13:
        v = v[2:]
    return bool(_PHONE_RE.fullmatch(v))

# 归一化手机号：统一去噪并提取 11 位中国大陆手机号。
def _normalize_phone(value: str) -> str:
    v = (value or "").strip()
    v = v.translate(_FULLWIDTH_DIGITS)
    digits = re.sub(r"\D+", "", v)
    if digits.startswith("0086"):
        digits = digits[4:]
    if digits.startswith("86") and len(digits) >= 13:
        cand = digits[2:]
        if _PHONE_RE.fullmatch(cand):
            digits = cand
    if len(digits) > 11:
        tail = digits[-11:]
        if _PHONE_RE.fullmatch(tail):
            digits = tail
    return digits


def _normalize_exam_status(value: str) -> str:
    """Normalize exam/assignment status values to canonical keys."""
    s = str(value or "").strip()
    if not s:
        return ""
    key = s.lower()
    mapping = {
        "verified": "verified",
        "验证通过": "verified",
        "invited": "invited",
        "已邀约": "invited",
        "in_exam": "in_exam",
        "正在答题": "in_exam",
        "grading": "grading",
        "正在判卷": "grading",
        "finished": "finished",
        "判卷结束": "finished",
        "expired": "expired",
        "失效": "expired",
    }
    return mapping.get(s, mapping.get(key, key))


def _clean_projects_raw(text: str) -> str:
    return clean_projects_raw_for_display(text)


def _split_projects_raw(text: str) -> list[dict[str, str]]:
    return split_projects_raw_into_blocks(text)


def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _parse_date_ymd(s: str) -> date | None:
    t = str(s or "").strip()
    if not t:
        return None
    try:
        return date.fromisoformat(t)
    except Exception:
        return None


__all__ = [name for name in globals() if not name.startswith("__")]
