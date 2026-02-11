from __future__ import annotations

import json
import os
import re
from io import BytesIO
from typing import Any

from config import logger
from services.llm_client import call_llm_structured


_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def _normalize_phone(value: str) -> str:
    v = (value or "").strip().translate(_FULLWIDTH_DIGITS)
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


def _guess_phone_from_text(text: str) -> str:
    raw = (text or "").translate(_FULLWIDTH_DIGITS)
    m = re.search(r"(?:\+?86[\s-]*)?(1[3-9]\d{9})", raw)
    if not m:
        return ""
    return _normalize_phone(m.group(1))


def extract_resume_text(data: bytes, filename: str) -> str:
    """
    Best-effort resume text extraction.
    Supported:
    - .txt/.md
    - .pdf (pypdf)
    - .docx (python-docx)
    """
    name = (filename or "").strip().lower()
    if name.endswith((".txt", ".md")):
        return (data or b"").decode("utf-8", errors="replace")

    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception as e:
            raise RuntimeError("Missing dependency: pypdf. Please install requirements.txt") from e
        reader = PdfReader(BytesIO(data))
        parts: list[str] = []
        # For identity extraction, scanning the first few pages is usually enough and much faster.
        try:
            max_pages = int(os.getenv("RESUME_PDF_MAX_PAGES", "6") or "6")
        except Exception:
            max_pages = 6
        max_pages = max(1, min(20, max_pages))
        for p in reader.pages[:max_pages]:
            try:
                parts.append(p.extract_text() or "")
            except Exception:
                parts.append("")
        text = "\n".join(parts)
        # pypdf sometimes inserts spaces/newlines between Chinese characters.
        text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
        return text

    if name.endswith(".docx"):
        try:
            import docx  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "Missing dependency: python-docx. Please install requirements.txt"
            ) from e
        d = docx.Document(BytesIO(data))
        parts = [p.text for p in (d.paragraphs or []) if (p.text or "").strip()]
        return "\n".join(parts)

    raise ValueError("unsupported_file_type")


def extract_resume_section(
    text: str,
    *,
    section_keywords: list[str],
    stop_keywords: list[str] | None = None,
    max_chars: int = 6500,
) -> str:
    """
    Extract a specific section (best-effort) from resume plain text.

    It finds the first line containing any of `section_keywords` as a start marker,
    then collects subsequent lines until reaching a line containing any of
    `stop_keywords` (if provided), or until `max_chars` is reached.
    """
    s = (text or "").strip()
    if not s:
        return ""

    stops = stop_keywords or []
    lines = s.splitlines()

    def _hit(line: str, keywords: list[str]) -> bool:
        l = (line or "").strip()
        if not l:
            return False
        for kw in keywords:
            k = (kw or "").strip()
            if not k:
                continue
            if k.lower() in l.lower():
                return True
        return False

    def _first_pos(line: str, keywords: list[str]) -> int:
        """
        Return the earliest occurrence index of any keyword inside `line` (case-insensitive).
        If none found, return -1.
        """
        l = (line or "")
        lo = l.lower()
        best = -1
        for kw in keywords:
            k = (kw or "").strip()
            if not k:
                continue
            p = lo.find(k.lower())
            if p == -1:
                continue
            if best == -1 or p < best:
                best = p
        return best

    start_idx = -1
    for i, line in enumerate(lines):
        if _hit(line, section_keywords):
            start_idx = i
            break
    if start_idx < 0:
        return ""

    # If the section keyword is embedded inside a long line (common in PDF extraction),
    # drop the prefix before the keyword so we don't accidentally carry previous section text.
    sp = _first_pos(lines[start_idx], section_keywords)
    if sp > 0:
        lines[start_idx] = lines[start_idx][sp:]

    end_idx = len(lines)
    if stops:
        for j in range(start_idx + 1, len(lines)):
            if _hit(lines[j], stops):
                end_idx = j
                break

    chunk = "\n".join(lines[start_idx:end_idx]).strip()
    if not chunk:
        return ""
    if max_chars and len(chunk) > max_chars:
        chunk = chunk[:max_chars].rstrip()
    return chunk


def parse_resume_identity_fast(text: str) -> dict[str, Any]:
    """
    Fast (non-LLM) identity extraction from resume text.
    Returns: {"name": str, "phone": str, "confidence": {"name":0..100,"phone":0..100}, "method":"fast"}
    """
    t = (text or "").strip()
    if not t:
        return {"name": "", "phone": "", "confidence": {"name": 0, "phone": 0}, "method": "fast"}

    raw = t.translate(_FULLWIDTH_DIGITS)
    phone = _guess_phone_from_text(raw)

    name = ""
    # 1) Prefer explicit labels.
    m = re.search(r"(?:^|[\n\r\t ])(?:姓名|Name)\s*[:：]?\s*([A-Za-z\u4e00-\u9fff·\\s]{2,20})", raw, flags=re.IGNORECASE)
    if m:
        name = (m.group(1) or "").strip()
        name = re.sub(r"\s+", " ", name)
    # 2) Fallback: first meaningful line (avoid common header words).
    if not name:
        for line in raw.splitlines()[:8]:
            s = (line or "").strip()
            if not s:
                continue
            if any(k in s for k in ("个人简历", "简历", "求职", "简历投递", "Resume", "Curriculum Vitae")):
                continue
            # likely a name-only line
            if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", s):
                name = s
                break
            if re.fullmatch(r"[A-Za-z][A-Za-z\\s·]{1,19}", s):
                name = re.sub(r"\s+", " ", s)
                break

    phone_conf = 85 if phone else 0
    name_conf = 70 if name else 0
    if m and name:
        name_conf = 80
    return {"name": name, "phone": phone, "confidence": {"name": name_conf, "phone": phone_conf}, "method": "fast"}


def parse_resume_name_llm(text: str) -> dict[str, Any]:
    """
    Use LLM to extract only the candidate name from resume text.
    Returns: {"name": str, "confidence": 0..100}
    """
    t = (text or "").strip()
    if not t:
        return {"name": "", "confidence": 0}

    use_llm = os.getenv("RESUME_USE_LLM", "").strip().lower()
    if use_llm in {"0", "false", "no"}:
        return {"name": "", "confidence": 0}

    system = (
        "你是一个简历信息抽取助手。只从简历文本中抽取候选人的姓名。\n"
        "要求：\n"
        "1) 只输出一个 JSON 对象，不要输出多余文本。\n"
        "2) 字段：name（字符串）、confidence（0-100 整数）。\n"
        "3) 如果无法确定，name 返回空字符串，并把 confidence 设低。\n"
        "示例：{\"name\":\"张三\",\"confidence\":85}\n"
    )
    # Keep prompt small for latency.
    focused = t[:5200]
    prompt = "【简历文本】\n" + focused + "\n"
    raw = (call_llm_structured(prompt, system=system) or "").strip()
    if not raw:
        return {"name": "", "confidence": 0}
    try:
        s = raw
        if not (s.startswith("{") and s.endswith("}")):
            l = s.find("{")
            r = s.rfind("}")
            if l != -1 and r != -1 and r > l:
                s = s[l : r + 1]
        obj = json.loads(s)
    except Exception:
        logger.warning("Resume name LLM output parse failed: %r", raw[:400])
        return {"name": "", "confidence": 0}

    name = str(obj.get("name") or "").strip()
    conf = obj.get("confidence")
    try:
        name_conf = int(conf or 0)
    except Exception:
        name_conf = 0
    name_conf = max(0, min(100, name_conf))
    return {"name": name, "confidence": name_conf}


def parse_resume_details_llm(text: str) -> dict[str, Any]:
    """
    Use LLM to extract additional resume details (non-identity fields).
    Returns a JSON-friendly dict (best-effort).
    """
    t = (text or "").strip()
    if not t:
        return {}

    use_llm = os.getenv("RESUME_USE_LLM", "").strip().lower()
    if use_llm in {"0", "false", "no"}:
        return {}

    def _focus_blocks(raw: str) -> str:
        """
        Keep prompt focused on sections that usually contain structured info.
        """
        s = (raw or "").strip()
        if not s:
            return ""
        head = s[:2600]

        # Capture windows around key sections (education/projects/etc.).
        keywords = [
            "教育", "教育背景", "教育经历", "学习经历",
            "项目", "项目经历", "项目经验", "科研项目", "课程设计", "毕业设计",
            "实习", "实习经历", "工作经历", "经历",
            "技能", "专业技能",
            "证书", "英语", "CET", "四六级",
        ]
        lines = s.splitlines()
        hits: list[int] = []
        for i, line in enumerate(lines):
            lo = (line or "").strip()
            if not lo:
                continue
            for kw in keywords:
                if kw in lo:
                    hits.append(i)
                    break
        # Build up to 4 windows (each ~16 lines before/after).
        windows: list[tuple[int, int]] = []
        for idx in hits[:30]:
            a = max(0, idx - 16)
            b = min(len(lines), idx + 28)
            if windows and a <= windows[-1][1]:
                windows[-1] = (windows[-1][0], max(windows[-1][1], b))
            else:
                windows.append((a, b))
            if len(windows) >= 4:
                break
        body_parts: list[str] = []
        for a, b in windows:
            chunk = "\n".join(lines[a:b]).strip()
            if chunk:
                body_parts.append(chunk)
        body = "\n\n".join(body_parts).strip()

        focused = (head + "\n\n" + body).strip()
        if len(focused) > 9000:
            focused = focused[:9000]
        return focused

    system = (
        "你是一个“简历结构化解析助手”。你的任务是：只根据给定的【简历文本】抽取信息，输出一个 JSON 对象。\n"
        "\n"
        "重要规则：\n"
        "1) 只能输出 JSON（不要 Markdown、不要解释）。\n"
        "2) 不要编造；找不到就用空字符串/空数组/null。\n"
        "3) 教育经历/项目经历务必尽量抽取：如果文本中存在“教育/项目/实习/科研”等段落，就从这些段落里抽。\n"
        "4) 允许从常见格式推断字段归属，但不能凭空生成学校/专业/项目名。\n"
        "5) summary：用中文写一段候选人概览，尽量控制在 100 字左右（约 80-120 字），不要换行。\n"
        "\n"
        "输出 JSON schema（字段名必须一致）：\n"
        "{\n"
        "  \"summary\": string,\n"
        "  \"gender\": \"男\"|\"女\"|\"未知\"|\"\",\n"
        "  \"emails\": string[],\n"
        "  \"skills\": string[],\n"
        "  \"highest_education\": \"本科\"|\"硕士\"|\"博士\"|\"大专\"|\"高中\"|\"未知\"|\"\",\n"
        "  \"educations\": [\n"
        "    {\"degree\": string, \"school\": string, \"major\": string, \"start\": string, \"end\": string}\n"
        "  ],\n"
        "  \"english\": {\"cet4\": {\"score\": number|null}|null, \"cet6\": {\"score\": number|null}|null},\n"
        "  \"projects\": [\n"
        "    {\"name\": string, \"role\": string, \"period\": string, \"description\": string[]}\n"
        "  ],\n"
        "  \"experience_years\": number|null\n"
        "}\n"
        "\n"
        "抽取要点：\n"
        "- educations：按时间从早到晚排序；degree 取“本科/硕士/博士”等；school/major 从行内抽取。\n"
        "- projects：从“项目经历/项目经验/科研项目/课程设计/毕业设计/比赛项目”等段落抽取，最多 6 个；description 是要点列表（每条不超过 30 字）。\n"
        "- english：识别四级/六级分数（如：CET-4 510 / 四级：560）。\n"
        "\n"
        "示例（仅示意格式，不要照抄内容）：\n"
        "{\"summary\":\"...\",\"gender\":\"男\",\"emails\":[\"a@b.com\"],\"skills\":[\"Python\"],\"highest_education\":\"硕士\",\"educations\":[{\"degree\":\"本科\",\"school\":\"XX大学\",\"major\":\"计算机\",\"start\":\"2019\",\"end\":\"2023\"},{\"degree\":\"硕士\",\"school\":\"YY大学\",\"major\":\"人工智能\",\"start\":\"2023\",\"end\":\"至今\"}],\"english\":{\"cet4\":{\"score\":530},\"cet6\":null},\"projects\":[{\"name\":\"XX系统\",\"role\":\"后端\",\"period\":\"2024-03~2024-06\",\"description\":[\"...\",\"...\"]}],\"experience_years\":1}\n"
    )
    focused = _focus_blocks(t)
    prompt = "[简历文本]\n" + focused + "\n"
    raw = (call_llm_structured(prompt, system=system) or "").strip()
    if not raw:
        return {}
    try:
        s = raw
        if not (s.startswith("{") and s.endswith("}")):
            l = s.find("{")
            r = s.rfind("}")
            if l != -1 and r != -1 and r > l:
                s = s[l : r + 1]
        obj = json.loads(s)
    except Exception:
        logger.warning("Resume details LLM output parse failed: %r", raw[:400])
        return {}

    def _s(v) -> str:
        return str(v or "").strip()

    def _uniq_str_list(v) -> list[str]:
        if not isinstance(v, list):
            if isinstance(v, str):
                # split by common bullet separators/newlines
                parts = re.split(r"[\\n\\r•·\\-–—\\u2022]+", v)
                parts = [p.strip() for p in parts if p.strip()]
                return parts[:30]
            return []
        items = [str(x or "").strip() for x in v]
        items = [x for x in items if x]
        # preserve some order but de-dupe
        out: list[str] = []
        seen: set[str] = set()
        for x in items:
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    def _num_or_none(v):
        if v is None or v == "":
            return None
        try:
            return float(v)
        except Exception:
            return None

    def _norm_degree(v: str) -> str:
        s = _s(v)
        if not s:
            return "未知"
        s = s.replace("学士", "本科").replace("研究生", "硕士")
        if s in {"本科", "硕士", "博士", "大专", "高中", "未知"}:
            return s
        if "博" in s:
            return "博士"
        if "硕" in s:
            return "硕士"
        if "本" in s:
            return "本科"
        if "专" in s:
            return "大专"
        if "高" in s:
            return "高中"
        return "未知"

    def _norm_gender(v: str) -> str:
        s = _s(v)
        if s in {"男", "女", "未知"}:
            return s
        if s in {"M", "Male", "male"}:
            return "男"
        if s in {"F", "Female", "female"}:
            return "女"
        return "未知" if s else ""

    # Normalize basic types.
    out: dict[str, Any] = {}
    def _norm_summary(v: str) -> str:
        s = _s(v)
        if not s:
            return ""
        s = re.sub(r"\\s+", " ", s).strip()
        if len(s) > 120:
            s = s[:120].rstrip(" ,，;；.。")
            if s:
                s += "…"
        return s

    out["summary"] = _norm_summary(obj.get("summary"))
    out["gender"] = _norm_gender(obj.get("gender"))
    out["emails"] = _uniq_str_list(obj.get("emails") or [])
    out["skills"] = _uniq_str_list(obj.get("skills") or [])
    out["highest_education"] = _norm_degree(obj.get("highest_education"))

    educations = obj.get("educations") or []
    norm_edu: list[dict[str, Any]] = []
    if isinstance(educations, list):
        for e in educations[:10]:
            if not isinstance(e, dict):
                continue
            degree = _norm_degree(e.get("degree"))
            school = _s(e.get("school"))
            major = _s(e.get("major"))
            start = _s(e.get("start"))
            end = _s(e.get("end"))
            if not any([school, major, start, end]) and degree == "未知":
                continue
            norm_edu.append(
                {"degree": degree, "school": school, "major": major, "start": start, "end": end}
            )
    out["educations"] = norm_edu

    english = obj.get("english") or {}
    en_out: dict[str, Any] = {}
    if isinstance(english, dict):
        cet4 = english.get("cet4")
        cet6 = english.get("cet6")
        if isinstance(cet4, dict) or cet4 is None:
            en_out["cet4"] = None if cet4 is None else {"score": _num_or_none((cet4 or {}).get("score"))}
        if isinstance(cet6, dict) or cet6 is None:
            en_out["cet6"] = None if cet6 is None else {"score": _num_or_none((cet6 or {}).get("score"))}
    out["english"] = en_out

    projects = obj.get("projects") or []
    norm_proj: list[dict[str, Any]] = []
    if isinstance(projects, list):
        for p in projects[:6]:
            if not isinstance(p, dict):
                continue
            desc = p.get("description")
            norm_proj.append(
                {
                    "name": _s(p.get("name")),
                    "role": _s(p.get("role")),
                    "period": _s(p.get("period")),
                    "description": _uniq_str_list(desc or [])[:8],
                }
            )
    out["projects"] = norm_proj

    out["experience_years"] = _num_or_none(obj.get("experience_years"))
    return out


def parse_resume_identity_llm(text: str) -> dict[str, Any]:
    """
    Use LLM to extract candidate identity from resume text.
    Returns: {"name": str, "phone": str, "confidence": {"name":0..100,"phone":0..100}}
    """
    t = (text or "").strip()
    if not t:
        return {"name": "", "phone": "", "confidence": {"name": 0, "phone": 0}}

    use_llm = os.getenv("RESUME_USE_LLM", "").strip().lower()
    if use_llm in {"0", "false", "no"}:
        phone = _guess_phone_from_text(t)
        return {"name": "", "phone": phone, "confidence": {"name": 0, "phone": 40 if phone else 0}}

    system = (
        "你是一个简历信息抽取助手。只从简历文本中抽取候选人的姓名与手机号。\n"
        "要求：\n"
        "1) 只输出一个 JSON 对象，不要输出多余文本。\n"
        "2) 字段：name（字符串）、phone（字符串，仅11位中国大陆手机号）、confidence（对象，name/phone 0-100 整数）。\n"
        "3) 如果无法确定，返回空字符串，并把置信度设低。\n"
        "示例：{\"name\":\"张三\",\"phone\":\"13800138000\",\"confidence\":{\"name\":85,\"phone\":95}}\n"
    )
    # Keep prompt small for latency: first chunk + a window around the phone number if present.
    head = t[:2400]
    around = ""
    m = re.search(r"(?:\\+?86[\\s-]*)?(1[3-9]\\d{9})", t.translate(_FULLWIDTH_DIGITS))
    if m:
        s = max(0, m.start() - 500)
        e = min(len(t), m.end() + 500)
        around = t[s:e]
    focused = (head + "\n" + around).strip()
    if len(focused) > 5200:
        focused = focused[:5200]
    prompt = "【简历文本】\n" + focused + "\n"
    raw = (call_llm_structured(prompt, system=system) or "").strip()
    if not raw:
        phone = _guess_phone_from_text(t)
        return {"name": "", "phone": phone, "confidence": {"name": 0, "phone": 40 if phone else 0}}
    try:
        s = raw
        if not (s.startswith("{") and s.endswith("}")):
            l = s.find("{")
            r = s.rfind("}")
            if l != -1 and r != -1 and r > l:
                s = s[l : r + 1]
        obj = json.loads(s)
    except Exception:
        logger.warning("Resume identity LLM output parse failed: %r", raw[:400])
        phone = _guess_phone_from_text(t)
        return {"name": "", "phone": phone, "confidence": {"name": 0, "phone": 40 if phone else 0}}

    name = str(obj.get("name") or "").strip()
    phone = _normalize_phone(str(obj.get("phone") or "").strip())
    if not _PHONE_RE.fullmatch(phone):
        # fallback to regex guess
        phone2 = _guess_phone_from_text(t)
        if _PHONE_RE.fullmatch(phone2):
            phone = phone2

    conf = obj.get("confidence") or {}
    try:
        name_conf = int(conf.get("name") or 0)
    except Exception:
        name_conf = 0
    try:
        phone_conf = int(conf.get("phone") or 0)
    except Exception:
        phone_conf = 0
    name_conf = max(0, min(100, name_conf))
    phone_conf = max(0, min(100, phone_conf))

    return {"name": name, "phone": phone, "confidence": {"name": name_conf, "phone": phone_conf}}
