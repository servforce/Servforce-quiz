from __future__ import annotations

from backend.md_quiz.services.support_deps import *

# 基础输入校验：姓名、手机号与全角数字归一化。
_NAME_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z·\s]{2,20}$")
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_ALLOWED_RESUME_EXTS = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


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


def _require_phone_verification(assignment: dict[str, Any] | None) -> bool:
    current = assignment if isinstance(assignment, dict) else {}
    if "require_phone_verification" in current:
        return bool(current.get("require_phone_verification"))
    return bool(current.get("public_invite"))


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
        "in_quiz": "in_quiz",
        "正在答题": "in_quiz",
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
