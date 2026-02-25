from __future__ import annotations

import json
import os
import re
from io import BytesIO
from typing import Any

from config import logger
from services.llm_client import call_llm_structured, call_llm_structured_ex


_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_NOISE_TOKEN_LINE_HEX_RE = re.compile(r"^[0-9a-fA-F]{24,}$")
_NOISE_TOKEN_LINE_SAFE_RE = re.compile(r"^[A-Za-z0-9_-]{28,}$")


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


def _is_noise_token_line(line: str) -> bool:
    s = str(line or "").strip()
    if len(s) < 24:
        return False
    if " " in s or "\t" in s:
        return False
    if _NOISE_TOKEN_LINE_HEX_RE.fullmatch(s):
        return True
    if _NOISE_TOKEN_LINE_SAFE_RE.fullmatch(s):
        return True
    return False


def _clean_text_for_llm(text: str) -> str:
    """
    Best-effort cleanup for LLM prompts.

    Goals:
    - Remove repeated watermark/noise token lines (very common in PDF extraction).
    - Keep as much signal as possible without over-aggressive normalization.
    """
    s = str(text or "").strip()
    if not s:
        return ""

    lines = [ln.rstrip() for ln in s.splitlines()]
    out_lines: list[str] = []
    for ln in lines:
        if _is_noise_token_line(ln):
            continue
        out_lines.append(ln)

    out = "\n".join(out_lines).strip()
    out = re.sub(r"\n{4,}", "\n\n\n", out).strip()
    return out


def _extract_pdf_text_ocr(data: bytes, *, max_pages: int, lang: str) -> str:
    """
    OCR fallback for scanned/image-only PDFs.

    Uses:
    - PyMuPDF (fitz) to render PDF pages into images
    - pytesseract to OCR rendered images

    Notes:
    - Requires system Tesseract installation (binary).
    - Controlled by env RESUME_PDF_OCR=1 (or truthy) in extract_resume_text().
    """
    try:
        import fitz  # type: ignore
    except Exception as e:
        raise RuntimeError("Missing dependency: pymupdf (fitz). Please install requirements.txt") from e

    try:
        import pytesseract  # type: ignore
    except Exception as e:
        raise RuntimeError("Missing dependency: pytesseract. Please install requirements.txt") from e

    try:
        from PIL import Image  # type: ignore
    except Exception as e:
        raise RuntimeError("Missing dependency: pillow. Please install requirements.txt") from e

    tesseract_cmd = str(os.getenv("TESSERACT_CMD", "") or "").strip()
    if tesseract_cmd:
        try:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        except Exception:
            pass

    try:
        _ = pytesseract.get_tesseract_version()
    except Exception as e:
        raise RuntimeError(
            "Tesseract OCR is not available. Install Tesseract and ensure it is on PATH, "
            "or set env TESSERACT_CMD to the tesseract executable path."
        ) from e

    parts: list[str] = []
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        max_pages = max(1, min(20, int(max_pages or 6)))
        zoom = float(os.getenv("RESUME_OCR_ZOOM", "2.0") or "2.0")
        mat = fitz.Matrix(zoom, zoom)
        for i in range(min(max_pages, doc.page_count)):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            txt = pytesseract.image_to_string(img, lang=lang) or ""
            parts.append(txt.strip())
    finally:
        try:
            doc.close()
        except Exception:
            pass

    out = "\n".join([p for p in parts if p]).strip()
    out = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", out)
    return out


def _extract_image_text_ocr(data: bytes, *, lang: str) -> str:
    """
    OCR for image resumes (jpg/png/webp/etc).

    Notes:
    - Requires system Tesseract installation (binary).
    - Uses env TESSERACT_CMD / RESUME_OCR_LANG / RESUME_OCR_ZOOM (same as PDF OCR).
    """
    try:
        import pytesseract  # type: ignore
    except Exception as e:
        raise RuntimeError("Missing dependency: pytesseract. Please install requirements.txt") from e

    try:
        from PIL import Image  # type: ignore
    except Exception as e:
        raise RuntimeError("Missing dependency: pillow. Please install requirements.txt") from e

    tesseract_cmd = str(os.getenv("TESSERACT_CMD", "") or "").strip()
    if tesseract_cmd:
        try:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        except Exception:
            pass

    try:
        _ = pytesseract.get_tesseract_version()
    except Exception as e:
        raise RuntimeError(
            "Tesseract OCR is not available. Install Tesseract and ensure it is on PATH, "
            "or set env TESSERACT_CMD to the tesseract executable path."
        ) from e

    try:
        img = Image.open(BytesIO(data))
    except Exception as e:
        raise RuntimeError(f"Image decode failed: {type(e).__name__}({e})") from e

    try:
        if img.mode not in {"RGB", "L"}:
            img = img.convert("RGB")
        zoom = float(os.getenv("RESUME_OCR_ZOOM", "2.0") or "2.0")
        if zoom and abs(zoom - 1.0) > 0.05:
            w, h = img.size
            nw = max(1, int(w * zoom))
            nh = max(1, int(h * zoom))
            img = img.resize((nw, nh))
        txt = pytesseract.image_to_string(img, lang=lang) or ""
    finally:
        try:
            img.close()
        except Exception:
            pass

    out = (txt or "").strip()
    out = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", out)
    return out


def extract_resume_text(data: bytes, filename: str) -> str:
    """
    Best-effort resume text extraction.
    Supported:
    - .txt/.md
    - .pdf (pypdf)
    - .docx (python-docx)
    - image files (.png/.jpg/.jpeg/.webp/.bmp/.tif/.tiff) via OCR
    """
    name = (filename or "").strip().lower()
    if name.endswith((".txt", ".md")):
        return (data or b"").decode("utf-8", errors="replace")

    if name.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")):
        lang = str(os.getenv("RESUME_OCR_LANG", "chi_sim+eng") or "chi_sim+eng").strip()
        return _extract_image_text_ocr(data, lang=lang)

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

        # OCR fallback for scanned PDFs (no text layer).
        # Default: enabled (to reduce operational friction).
        # You can disable via env RESUME_PDF_OCR=0/false/no/off.
        ocr_flag = str(os.getenv("RESUME_PDF_OCR", "") or "").strip().lower()
        want_ocr = ocr_flag not in {"0", "false", "no", "n", "off"}
        min_chars = int(os.getenv("RESUME_PDF_MIN_TEXT_CHARS", "160") or "160")
        too_short = len((text or "").strip()) < max(40, min_chars)
        if want_ocr and too_short:
            lang = str(os.getenv("RESUME_OCR_LANG", "chi_sim+eng") or "chi_sim+eng").strip()
            try:
                ocr_text = _extract_pdf_text_ocr(data, max_pages=max_pages, lang=lang)
                if ocr_text.strip():
                    return ocr_text
            except Exception as e:
                logger.warning("Resume OCR failed: %s", e)

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
            # Prefer heading-like matches to avoid false positives inside body text.
            # Still fallback to substring match for glued PDF extraction cases.
            if re.search(rf"(?i)^\s*{re.escape(k)}\s*[:：\-—]*\s*$", line or ""):
                return True
            if re.search(rf"(?i)^\s*{re.escape(k)}\s*[:：\-—]", line or ""):
                return True
            if k.lower() in l.lower():
                return True
        return False

    def _first_pos_and_kw(line: str, keywords: list[str]) -> tuple[int, str]:
        """
        Return the earliest occurrence index + matched keyword inside `line` (case-insensitive).
        If none found, return (-1, "").
        """
        l = (line or "")
        lo = l.lower()
        best = -1
        best_kw = ""
        for kw in keywords:
            k = (kw or "").strip()
            if not k:
                continue
            p = lo.find(k.lower())
            if p == -1:
                continue
            if best == -1 or p < best:
                best = p
                best_kw = k
        return best, best_kw

    start_idx = -1
    start_kw = ""
    for i, line in enumerate(lines):
        if _hit(line, section_keywords):
            start_idx = i
            _p, _kw = _first_pos_and_kw(line, section_keywords)
            start_kw = _kw
            break
    if start_idx < 0:
        return ""

    # If the section keyword is embedded inside a long line (common in PDF extraction),
    # drop the prefix before the keyword so we don't accidentally carry previous section text.
    sp, _kw2 = _first_pos_and_kw(lines[start_idx], section_keywords)
    if sp > 0:
        lines[start_idx] = lines[start_idx][sp:]
        if not start_kw:
            start_kw = _kw2

    end_idx = len(lines)
    if stops:
        # Handle "glued headings" where stop keyword appears on the same line after the start marker.
        # Example (PDF text extraction): "项目经历 ... 工作经历 ..."
        try:
            start_kw_len = len(str(start_kw or ""))
        except Exception:
            start_kw_len = 0
        line0 = lines[start_idx]
        line0_lo = (line0 or "").lower()
        best_stop: int | None = None
        for sk in stops:
            ssk = str(sk or "").strip()
            if not ssk:
                continue
            p = line0_lo.find(ssk.lower(), max(0, start_kw_len))
            if p == -1:
                continue
            if best_stop is None or p < best_stop:
                best_stop = p
        if best_stop is not None and best_stop > 0:
            lines[start_idx] = (line0[:best_stop]).rstrip()
            end_idx = min(end_idx, start_idx + 1)
        else:
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


# Common experience section keywords/stops.
EXPERIENCE_SECTION_KEYWORDS_PROJECTS = [
    "项目经历",
    "项目经验",
    "科研项目",
    "课程设计",
    "毕业设计",
    "比赛项目",
    "Projects",
    "PROJECTS",
    "Project Experience",
    "PROJECT EXPERIENCE",
]

EXPERIENCE_SECTION_KEYWORDS_WORK = [
    "工作经历",
    "工作经验",
    "任职经历",
    "职业经历",
    "Work Experience",
    "WORK EXPERIENCE",
    "Experience",
    "EXPERIENCE",
]

EXPERIENCE_STOP_KEYWORDS = [
    "教育",
    "教育经历",
    "教育背景",
    "学习经历",
    "实习",
    "实习经历",
    "技能",
    "专业技能",
    "技术栈",
    "证书",
    "资格",
    "获奖",
    "获奖经历",
    "获奖情况",
    "荣誉",
    "奖项",
    "论文",
    "发表",
    "出版",
    "专利",
    "基本信息",
    "个人信息",
    "联系方式",
    "自我评价",
    "个人总结",
    # English common headings
    "education",
    "skills",
    "certificates",
    "certifications",
    "awards",
    "honors",
    "publications",
    "papers",
    "patents",
    "contact",
    "profile",
    "summary",
]

_COMPANY_HINT_RE = re.compile(
    r"(?:有限公司|有限责任公司|集团|科技|信息|数据|银行|证券|保险|股份|研究院|研究所|中心|大学|学院)",
    flags=re.IGNORECASE,
)


def _extract_experience_head_fallback(text: str, *, max_chars: int = 7000) -> str:
    """
    Heuristic fallback for resumes where work/project content appears before an explicit heading.

    Common in PDF extraction: the resume may start directly with lines like:
      "XX公司 XX岗位 2022.11-至今 ..."
    and the first occurrence of "工作经历" appears later, causing section-based extraction to miss
    the most recent experiences.
    """
    s = str(text or "").strip()
    if not s:
        return ""

    head = s[: max(0, int(max_chars or 0))] if max_chars else s
    head = _clean_text_for_llm(head)
    if not head:
        return ""

    # Require at least one time-range and a company-ish hint to avoid pulling unrelated headers.
    if len(_PROJECT_PERIOD_RANGE_RE.findall(head)) < 1:
        return ""
    if not _COMPANY_HINT_RE.search(head):
        return ""

    # Take head lines until we hit a clear stop heading (education/skills/etc), but keep
    # a small amount of spillover to preserve context when headings are glued.
    lines = head.splitlines()
    out_lines: list[str] = []
    for ln in lines[:220]:
        if not ln.strip():
            # Keep a single blank line at most.
            if out_lines and out_lines[-1] != "":
                out_lines.append("")
            continue
        if any((kw.lower() in ln.lower()) for kw in EXPERIENCE_STOP_KEYWORDS):
            # stop only if we already captured some experience-like content
            if out_lines:
                break
        out_lines.append(ln.rstrip())

    out = "\n".join(out_lines).strip()
    if max_chars and len(out) > int(max_chars):
        out = out[: int(max_chars)].rstrip()
    return out


def extract_experience_raw(text: str, *, max_chars: int = 20000) -> str:
    """
    Best-effort extraction for "experience blocks" that can be rendered as:
    title | period | body (per block).

    Strategy:
    - Prefer explicit 项目经历/项目经验段落
    - Also include 工作经历段落 because many resumes embed project-like details under work experience
    - Merge the two sections with conservative de-duplication
    """

    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip())

    def _merge(a: str, b: str) -> str:
        a2 = (a or "").strip()
        b2 = (b or "").strip()
        if not a2:
            return b2
        if not b2:
            return a2
        na = _norm(a2)
        nb = _norm(b2)
        if nb in na:
            return a2
        if na in nb:
            return b2
        return (a2.rstrip() + "\n\n" + b2).strip()

    sec_max = 0 if (not max_chars) or int(max_chars) <= 0 else max(1000, int(max_chars))

    proj = ""
    try:
        proj = extract_resume_section(
            text or "",
            section_keywords=EXPERIENCE_SECTION_KEYWORDS_PROJECTS,
            stop_keywords=EXPERIENCE_STOP_KEYWORDS,
            max_chars=sec_max,
        )
    except Exception:
        proj = ""

    work = ""
    try:
        work = extract_resume_section(
            text or "",
            section_keywords=EXPERIENCE_SECTION_KEYWORDS_WORK,
            stop_keywords=EXPERIENCE_STOP_KEYWORDS,
            max_chars=sec_max,
        )
    except Exception:
        work = ""

    head_fallback = ""
    try:
        head_fallback = _extract_experience_head_fallback(text or "", max_chars=min(7000, int(max_chars or 7000)))
    except Exception:
        head_fallback = ""

    merged = _merge(
        _merge(clean_projects_raw_for_display(head_fallback), clean_projects_raw_for_display(proj)),
        clean_projects_raw_for_display(work),
    )
    if not merged:
        return ""
    if max_chars and len(merged) > int(max_chars):
        merged = merged[: int(max_chars)].rstrip()
    return merged


def clean_projects_raw_for_display(text: str) -> str:
    """
    Best-effort cleanup for displaying the raw "项目经历" section:
    - remove the leading section label ("项目经历/项目经验") if it is glued to content
    - add line breaks before common field labels for readability
    """
    s = str(text or "").strip()
    if not s:
        return ""

    # Remove leading section labels.
    s = re.sub(
        r"^\s*(项目经历|项目经验|工作经历|工作经验|WORK EXPERIENCE|Work Experience)\s*[:：\-—]*\s*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    # Sometimes PDF extraction glues the label to the next token without spaces/punctuation.
    for lab in ("项目经历", "项目经验", "工作经历", "工作经验"):
        if s.startswith(lab):
            s = s[len(lab) :].lstrip()
            break

    # Add line breaks before common labels when they appear inline.
    # Use a boundary check to avoid splitting longer labels (e.g. "项目成果：" should not become "项目\n成果：").
    labels = [
        "内容：",
        "工作：",
        "负责：",
        "职责：",
        "项目名称：",
        "项目时间：",
        "时间：",
        "技术栈：",
        "关键词：",
        "项目成果：",
        "项目结果：",
        "成果：",
        "结果：",
        "项目描述：",
        "描述：",
    ]
    for lab in labels:
        s = re.sub(
            rf"(?<!\n)(?<![\u4e00-\u9fffA-Za-z0-9]){re.escape(lab)}",
            "\n" + lab,
            s,
        )

    # Ensure each "项目：" starts on its own line (common PDF glue).
    s = re.sub(r"(?<!\n)\s*(项目)\s*[:：]\s*", r"\n项目：", s)
    s = re.sub(r"(?<!\n)\s*(Project)\s*[:：]\s*", r"\nProject:", s, flags=re.IGNORECASE)

    # If multiple experience entries are glued on a single line:
    # "... 2022.11-至今北京中体联合数据科技有限公司 ..." -> break after the period.
    try:
        s = re.sub(
            rf"({_PROJECT_PERIOD_RANGE_RE.pattern})(?=(?:\s*)[\u4e00-\u9fff]{{2,}}(?:有限责任公司|有限公司|公司|集团|科技|信息|数据))",
            r"\1\n",
            s,
            flags=re.IGNORECASE,
        )
    except Exception:
        pass

    # Normalize excessive blank lines.
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


_PROJECT_YM_RE_PART = (
    # IMPORTANT: month alternation must prefer 10/11/12; otherwise "11" may match as "1".
    r"(?:(?:19|20)\d{2}\s*年\s*(?:1[0-2]|0?[1-9])\s*月?"
    r"|(?:19|20)\d{2}\s*[.\-/]\s*(?:1[0-2]|0?[1-9]))"
)

_PROJECT_PERIOD_RANGE_RE = re.compile(
    r"(?P<period>"
    + _PROJECT_YM_RE_PART
    + r"\s*(?:-|—|–|~|～|至|到)\s*"
    + r"(?:至今|现在|今|present|Present|current|Current|"
    + _PROJECT_YM_RE_PART
    + r")"
    + r")"
)

_YEAR_RE = r"(?:19|20)\d{2}"
_EDU_PERIOD_RE = re.compile(
    rf"(?:{_YEAR_RE}(?:[.\-/]\d{{1,2}})?\s*(?:-|—|–|~|～|至|到)\s*{_YEAR_RE}(?:[.\-/]\d{{1,2}})?)"
)
_EDU_LINE_RE = re.compile(rf"(?:大学|学院|学校|中学|高中|职高|技校).{{0,40}}{_EDU_PERIOD_RE.pattern}")


def _looks_like_noise_token_line(line: str) -> bool:
    s = str(line or "").strip()
    if not s:
        return False
    # Drop repeated long hex/base64-ish garbage lines (common in OCR/PDF extraction artifacts).
    if len(s) < 24:
        return False
    if " " in s or "\t" in s:
        return False
    if re.fullmatch(r"[0-9a-fA-F]{24,}", s):
        return True
    if re.fullmatch(r"[A-Za-z0-9_-]{28,}", s):
        return True
    return False


def _looks_like_education_line(line: str) -> bool:
    s = str(line or "").strip()
    if not s:
        return False
    if len(s) > 80:
        return False
    if _EDU_LINE_RE.search(s) and _EDU_PERIOD_RE.search(s):
        return True
    # Degree keywords + year range.
    if re.search(r"(?:本科|硕士|博士|学士|研究生|大专|中专|MBA|EMBA)", s, flags=re.IGNORECASE) and _EDU_PERIOD_RE.search(s):
        return True
    return False


_PROJECT_ITEM_RE = re.compile(
    r"^\s*(?:项目|Project|PROJECTS?)\s*[:：]\s*(?P<title>.+?)\s*$",
    flags=re.IGNORECASE,
)


def _split_body_by_project_items(body: str) -> tuple[str, list[dict[str, str]]]:
    """
    Split a long experience body into:
    - preface text (before the first "项目：/Project:" item)
    - project items blocks extracted from lines starting with "项目：/Project:"
    """
    s = str(body or "").strip()
    if not s:
        return "", []

    lines = [ln.rstrip() for ln in s.splitlines()]
    hits: list[tuple[int, re.Match[str]]] = []
    for i, ln in enumerate(lines):
        m = _PROJECT_ITEM_RE.match(ln)
        if not m:
            continue
        title = str(m.group("title") or "").strip()
        if not title or _looks_like_education_line(title) or _looks_like_noise_token_line(title):
            continue
        hits.append((i, m))

    if len(hits) < 2:
        return s, []

    first_i = hits[0][0]
    preface = "\n".join(lines[:first_i]).strip()

    blocks: list[dict[str, str]] = []
    for idx, (i, m) in enumerate(hits):
        j = hits[idx + 1][0] if idx + 1 < len(hits) else len(lines)
        title_raw = str(m.group("title") or "").strip()

        # Try to separate "title + inline fields" glued in one line.
        # Example: "项目：XX系统 负责：.../职责：..."
        title = title_raw
        inline_body = ""
        split_m = re.search(r"(?:负责|职责|工作内容|内容|描述|技术栈|成果)\s*[:：]", title_raw)
        if split_m and split_m.start() > 2:
            title = title_raw[: split_m.start()].strip()
            inline_body = title_raw[split_m.start() :].strip()

        body_lines = []
        if inline_body:
            body_lines.append(inline_body)
        body_lines.extend(lines[i + 1 : j])
        item_body = "\n".join([x for x in body_lines if x.strip()]).strip()
        blocks.append({"title": title, "period": "", "body": item_body})

    return preface, blocks


def split_projects_raw_into_blocks(text: str) -> list[dict[str, str]]:
    """
    Split a raw "项目经历" section into blocks and render in a "title | period" layout.
    This parser is heuristic-based and aims to handle PDF-extraction glue across lines.
    Returns: [{"title":..., "period":..., "body":...}, ...]
    """
    s = clean_projects_raw_for_display(text or "")
    if not s:
        return []

    def _norm_title(raw_title: str) -> str:
        title = str(raw_title or "").strip()
        if not title:
            return ""
        title = re.sub(
            r"^\s*(项目经历|项目经验|工作经历|工作经验|WORK EXPERIENCE|Work Experience)\s*[:：\-—]*\s*",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()
        title = re.sub(r"^\s*[-•·\u2022]+\s*", "", title).strip()
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            return ""

        # If a field label leaks into the "title" (common in PDF glue), keep the tail.
        label_tail_re = re.compile(
            r"(?:内容|工作|职责|项目成果|项目结果|成果|结果|项目描述|描述|技术栈|关键词)\s*[:：]\s*",
            flags=re.IGNORECASE,
        )
        last_tail = None
        for m in label_tail_re.finditer(title):
            last_tail = m
        if last_tail:
            cand = title[last_tail.end() :].strip()
            if 2 <= len(cand) <= 90:
                title = cand

        # Another frequent glue pattern: "...发表《...》论文XXX项目名"
        if "论文" in title and len(title) > 40:
            cand = title.split("论文")[-1].strip()
            if 2 <= len(cand) <= 90:
                title = cand
        # Common glue: "...》论文基于占用网络..." -> keep "基于占用网络..." as project name.
        if "论文基于" in title:
            tail = title.split("论文基于")[-1].strip()
            if tail and not tail.startswith("基于"):
                tail = "基于" + tail
            title = tail or title
        elif title.startswith("论文") and "基于" in title:
            # Conservative fallback.
            title = title[2:].lstrip() or title

        if len(title) > 90:
            parts = re.split(r"[\n\r|丨】\]\)）;；。:：]", title)
            parts = [p.strip() for p in parts if 2 <= len((p or "").strip()) <= 90]
            if parts:
                title = parts[-1]
            else:
                title = title[-90:].strip()

        # Skip obviously-bad titles.
        if title in {"项目经历", "项目经验", "工作经历", "工作经验", "工作", "项目", "经历", "内容", "职责", "成果"}:
            return ""
        return title

    # Build line index for better header/body splitting.
    line_starts: list[int] = [0]
    for m in re.finditer(r"\n", s):
        line_starts.append(m.end())

    def _line_bounds(pos: int) -> tuple[int, int]:
        # Return [start, end) for the line containing pos.
        idx = 0
        for i, st in enumerate(line_starts):
            if st > pos:
                idx = max(0, i - 1)
                break
            idx = i
        start = line_starts[idx]
        end = s.find("\n", start)
        if end == -1:
            end = len(s)
        return start, end

    periods = list(_PROJECT_PERIOD_RANGE_RE.finditer(s))
    if not periods:
        return []

    headers: list[dict[str, int | str]] = []
    for m in periods:
        period_start = m.start()
        period_end = m.end()
        line_start, line_end = _line_bounds(period_start)
        line_text = s[line_start:line_end].strip()

        header_start = line_start
        title_source = s[line_start:period_start].strip()

        # If the period is on its own line (or title part is too short), pull title from previous non-empty line.
        if not title_source or len(title_source) <= 2:
            for st in reversed(line_starts):
                if st >= line_start:
                    continue
                prev_end = s.find("\n", st)
                if prev_end == -1:
                    prev_end = len(s)
                prev_line = s[st:prev_end].strip()
                if prev_line:
                    header_start = st
                    title_source = prev_line
                    break

        # If header/title looks like education, skip.
        if _looks_like_education_line(line_text) or _looks_like_education_line(title_source):
            continue

        full_title = title_source

        title = _norm_title(full_title)
        if not title:
            continue

        block_start = header_start
        try:
            rel = str(full_title or "").rfind(title)
        except Exception:
            rel = -1
        if rel and rel > 0:
            block_start = header_start + int(rel)
        body_start = line_end
        if period_end > line_end:
            _ps, pe_line_end = _line_bounds(period_end)
            body_start = pe_line_end

        headers.append(
            {
                "block_start": int(block_start),
                "body_start": int(body_start),
                "period_start": int(period_start),
                "period_end": int(period_end),
                "period": str(m.group("period") or "").strip(),
                "title": title,
            }
        )

    if not headers:
        return []

    # De-dupe/ensure monotonic order.
    headers.sort(key=lambda x: int(x["block_start"]))
    uniq: list[dict[str, int | str]] = []
    last_pos = -1
    for h in headers:
        pos = int(h["block_start"])
        if pos <= last_pos:
            continue
        last_pos = pos
        uniq.append(h)
    headers = uniq

    out: list[dict[str, str]] = []
    for i, h in enumerate(headers):
        block_start = int(h["block_start"])
        period_end = int(h["period_end"])
        body_start = int(h.get("body_start") or period_end)
        next_start = int(headers[i + 1]["block_start"]) if i + 1 < len(headers) else len(s)

        body = s[body_start:next_start].strip()
        body = body.lstrip("：: \t-—–~～")
        body = re.sub(r"\n{3,}", "\n\n", body).strip()

        # Remove obvious education/noise lines inside body.
        body_lines = [ln.rstrip() for ln in body.splitlines()]
        cleaned_lines: list[str] = []
        for ln in body_lines:
            if _looks_like_noise_token_line(ln):
                continue
            if _looks_like_education_line(ln):
                continue
            cleaned_lines.append(ln)
        body = "\n".join(cleaned_lines).strip()

        # Further split by explicit "项目：" items inside a work-experience block.
        preface, items = _split_body_by_project_items(body)
        if items:
            if preface:
                out.append(
                    {"title": str(h["title"]), "period": str(h["period"]), "body": preface, "kind": "work"}
                )
            for it in items:
                # For child "项目：" items, do NOT blindly inherit the work period.
                # If the item has no explicit time window, leave it empty. This prevents
                # showing the same company period for every project (common resume format).
                item_body = str(it.get("body") or "")
                item_title = str(it.get("title") or "")
                item_period = ""
                try:
                    m = _PROJECT_PERIOD_RANGE_RE.search(item_title) or _PROJECT_PERIOD_RANGE_RE.search(item_body)
                    if m:
                        item_period = str(m.group("period") or "").strip()
                except Exception:
                    item_period = ""
                out.append(
                    {
                        "title": item_title,
                        "period": item_period,
                        "body": item_body,
                        "kind": "project",
                    }
                )
        else:
            out.append({"title": str(h["title"]), "period": str(h["period"]), "body": body, "kind": "project"})

    return out[:20]


def focus_resume_text_for_details(
    raw: str,
    *,
    head_chars: int = 4000,
    tail_chars: int = 2500,
    max_chars: int = 12000,
    window_before_lines: int = 18,
    window_after_lines: int = 32,
    max_windows: int = 6,
) -> str:
    """
    Build a compact, information-dense subset of the resume text for LLM extraction.

    Goals:
    - Keep latency/cost stable by limiting prompt length.
    - Still capture key sections even when PDF extraction glues content.
    - Prefer including both header (identity/contact) and tail (awards/publications).
    """
    s = _clean_text_for_llm(raw)
    if not s:
        return ""

    head = s[: max(0, int(head_chars or 0))] if head_chars else ""
    tail = s[-max(0, int(tail_chars or 0)) :] if tail_chars and len(s) > tail_chars else ""

    keywords = [
        # Chinese headings (common)
        "基本信息",
        "个人信息",
        "联系方式",
        "教育",
        "教育背景",
        "教育经历",
        "学习经历",
        "项目",
        "项目经历",
        "项目经验",
        "科研项目",
        "课程设计",
        "毕业设计",
        "比赛项目",
        "实习",
        "实习经历",
        "工作经历",
        "经历",
        "技能",
        "专业技能",
        "技术栈",
        "证书",
        "资格",
        "英语",
        "CET",
        "四六级",
        "获奖",
        "获奖经历",
        "获奖情况",
        "荣誉",
        "奖项",
        "竞赛",
        "论文",
        "发表",
        "出版",
        "专利",
        "成果",
        # English headings (some resumes are bilingual)
        "education",
        "work experience",
        "experience",
        "internship",
        "projects",
        "project experience",
        "skills",
        "certificates",
        "certifications",
        "awards",
        "honors",
        "publications",
        "papers",
        "patents",
        "contact",
        "profile",
        "summary",
    ]

    lines = s.splitlines()
    hits: list[int] = []
    for i, line in enumerate(lines):
        lo = (line or "").strip()
        if not lo:
            continue
        llo = lo.lower()
        for kw in keywords:
            k = (kw or "").strip()
            if not k:
                continue
            if k.lower() in llo:
                hits.append(i)
                break

    windows: list[tuple[int, int]] = []
    for idx in hits[:80]:
        a = max(0, idx - int(window_before_lines))
        b = min(len(lines), idx + int(window_after_lines))
        if windows and a <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], b))
        else:
            windows.append((a, b))
        if len(windows) >= int(max_windows):
            break

    body_parts: list[str] = []
    for a, b in windows:
        chunk = "\n".join(lines[a:b]).strip()
        if chunk:
            body_parts.append(chunk)
    body = "\n\n".join(body_parts).strip()

    # Compose focused text. Keep both head and tail to improve robustness.
    parts = [p for p in [head.strip(), body, tail.strip()] if p]
    focused = "\n\n".join(parts).strip()

    if max_chars and len(focused) > int(max_chars):
        focused = focused[: int(max_chars)].rstrip()
    return focused


def _env_int(name: str, default: int) -> int:
    v = str(os.getenv(name, "") or "").strip()
    if not v:
        return int(default)
    try:
        return int(v)
    except Exception:
        return int(default)


def _truncate(s: str, max_chars: int) -> str:
    if not s:
        return ""
    if not max_chars or int(max_chars) <= 0:
        return s
    return s[: int(max_chars)].rstrip()


def _build_details_llm_prompt(text: str) -> str:
    """
    Build the LLM input for resume details extraction.

    The old default focus limit (12k chars) could cut long "work/project experience"
    sections. Now we prefer using the full extracted text when it is within a
    configurable size, and we also include an explicit "experience raw" chunk to
    help the model split experience blocks without summarizing.

    Env knobs (optional):
    - RESUME_DETAILS_TEXT_MAX_CHARS: prefer full text up to this size (default 60000)
    - RESUME_DETAILS_FOCUS_MAX_CHARS: focus to this size when full text is too long (default 45000)
    - RESUME_EXPERIENCE_RAW_MAX_CHARS: max chars for experience_raw in prompt (default 50000)
    - RESUME_DETAILS_PROMPT_MAX_CHARS: hard cap on total prompt chars (default 100000)

    Notes:
    - Set any of these to 0 to disable truncation for that piece (not recommended for `*_PROMPT_MAX_CHARS`).
    """
    s = _clean_text_for_llm(text or "")
    if not s:
        return ""

    text_max = _env_int("RESUME_DETAILS_TEXT_MAX_CHARS", 60000)
    focus_max = _env_int("RESUME_DETAILS_FOCUS_MAX_CHARS", 45000)
    exp_max = _env_int("RESUME_EXPERIENCE_RAW_MAX_CHARS", 50000)
    prompt_max = _env_int("RESUME_DETAILS_PROMPT_MAX_CHARS", 100000)

    if (not text_max) or (text_max > 0 and len(s) <= int(text_max)):
        main = s
    else:
        mm = 0 if (not focus_max) or int(focus_max) <= 0 else max(1000, int(focus_max))
        main = focus_resume_text_for_details(s, max_chars=mm)

    experience_raw = ""
    try:
        em = 0 if (not exp_max) or int(exp_max) <= 0 else max(1000, int(exp_max))
        experience_raw = extract_experience_raw(s, max_chars=em)
    except Exception:
        experience_raw = ""

    prefix = "[简历文本]\n"
    exp_prefix = "\n\n[工作/项目经历原文]\n"
    suffix = "\n"

    main = (main or "").strip()
    experience_raw = (experience_raw or "").strip()

    if not experience_raw:
        return _truncate(prefix + main + suffix, prompt_max).strip() + "\n"

    exp_section = exp_prefix + experience_raw + suffix
    if prompt_max and len(prefix) + len(main) + len("\n") + len(exp_section) > int(prompt_max):
        allow_main = int(prompt_max) - len(prefix) - len("\n") - len(exp_section)
        if allow_main < 0:
            allow_exp = int(prompt_max) - len(prefix) - len("\n") - len(exp_prefix) - len(suffix)
            allow_exp = max(0, allow_exp)
            experience_raw = _truncate(experience_raw, allow_exp)
            exp_section = exp_prefix + experience_raw + suffix
            allow_main = 0
        main = _truncate(main, max(0, allow_main))

    return (prefix + main + "\n" + exp_section).strip() + "\n"


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

    system = """
你是一个“简历信息抽取助手”。只从【简历文本】中抽取候选人姓名。

要求：
1) 只能输出 JSON（不要 Markdown、不要解释）。
2) 不要编造：找不到就输出空字符串。
3) 过滤明显的水印/噪声行（例如一整行只有 A-Za-z0-9_- 且很长的 token 串），不要把它当成姓名。

输出格式：
{"name": string, "confidence": number}

confidence 是 0-100 的整数，表示你对 name 的可信度。
""".strip()
    # Keep prompt small for latency.
    focused = _clean_text_for_llm(t)[:5200]
    prompt = "[简历文本]\n" + focused + "\n"
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

    system = """
你是一个“简历结构化解析助手”。你的任务是：只根据给定的【简历文本】抽取信息，输出一个 JSON 对象。

重要规则：
1) 只能输出 JSON（不要 Markdown、不要解释）。
2) 不要编造；找不到就用空字符串 "" / 空数组 [] / null。
3) 需要尽量泛化：适配中文/中英混排、PDF 抽取错行/粘连/缺换行的简历。
4) 对于“经历内容”，不要总结改写：尽量按简历原句/原要点搬运，只做归类与分段（允许少量清理无意义水印/乱码行）。

预处理标准（对 PDF 抽取文本的脏数据很关键）：
- 忽略“噪声行/水印行”：整行几乎只有 [A-Za-z0-9_-] 且长度≥28，或 24 位以上十六进制串；以及大量重复出现的同样字符串。
- 如果同一行里出现多个“公司/职位/时间段”片段（常见于 PDF 两列粘连），要拆分成多条经历。

分段与归类标准：
- 标题识别：工作经历/项目经历/教育经历/技能/证书/奖项/自我评价/个人优势/基本信息 等。
- 若标题缺失，用“时间段 + 公司/学校关键词 + 语义”推断归属。
- 教育经历不要混进工作/项目：像“学校/学院/大学 + 学历 + 年份范围(2012-2014)”的行应归到 educations。

时间字段标准：
- 识别 YYYY.MM / YYYY-MM / YYYY年MM月 / YYYY 等；支持“至今/Present/现在”。
- period 字段保留简历原样即可（不要凭空补齐月份）。

输出 JSON schema（字段名必须一致）：
{
  "summary": string,
  "gender": "男"|"女"|"未知"|"",
  "emails": string[],
  "skills": string[],
  "highest_education": "本科"|"硕士"|"博士"|"大专"|"高中"|"未知"|"",
  "educations": [
    {"degree": string, "school": string, "major": string, "start": string, "end": string}
  ],
  "english": {"cet4": {"score": number|null}|null, "cet6": {"score": number|null}|null},
  "work_experiences": [
    {"company": string, "title": string, "period": string, "description": string[]}
  ],
  "projects": [
    {"name": string, "role": string, "period": string, "description": string[]}
  ],
  "experience_blocks": [
    {"kind": "work"|"project", "title": string, "period": string, "body": string}
  ],
  "awards": string[],
  "certifications": string[],
  "publications": string[],
  "experience_years": number|null
}

抽取要点：
- summary：用中文写一段候选人概览，尽量控制在 80-120 字，不要换行。
- educations：按时间从早到晚排序；degree 取“本科/硕士/博士/大专”等；school/major/start/end 从行内抽取；不确定就留空。
- work_experiences：最多 6 条，按时间从近到远；description 是要点列表（尽量每条 ≤30 字，必要时可略长但不要换行）。
- projects：最多 6 条。
  * 从“项目经历/项目经验/科研项目/课程设计/毕业设计/比赛项目”等段落抽取。
  * 也要从工作经历中抽取以“项目：/项目名称/Project:”开头的项目条目（很多简历把项目写在工作经历里）。
  * 若项目本身没有独立时间：period 可以继承其所在工作经历的 period；无法确定则留空。
  * name 只能是项目名称，不要把“负责/职责/工作内容/成果”等字段标签当成 name。
- experience_blocks：用于网页展示“工作/项目经历”的原文段落，最多 20 块。
  * title：尽量是“公司 + 职位”或“项目名称”的原文。
  * period：时间范围（原样）。
  * body：把该经历下的原文内容按原有编号/项目符号/换行组织成多行文本（不要总结改写）。
- skills：只提取简历明确写出的技能/工具/技术栈/关键词，不要从经历内容过度推断。
- awards/certifications/publications：能从简历里直接抄到的条目再写，不要编造。
- english：识别四级/六级分数（如：CET-4 510 / 四级：560）。
""".strip()
    focused = _clean_text_for_llm(focus_resume_text_for_details(t))
    prompt = "[简历文本]\n" + focused + "\n"
    prompt = _build_details_llm_prompt(t)
    if not prompt.strip():
        return {}
    raw, err = call_llm_structured_ex(prompt, system=system)
    raw = (raw or "").strip()
    if not raw:
        hint = (err or "").strip() or "empty output"
        raise RuntimeError(
            "LLM call failed: "
            + hint
            + ". Check DOUBAO_API_KEY/DOUBAO_BASE_URL/DOUBAO_MODEL and confirm the API key has permission for this endpoint."
        )
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

    exp_blocks = obj.get("experience_blocks") or []
    norm_blocks: list[dict[str, Any]] = []
    if isinstance(exp_blocks, list):
        for b in exp_blocks[:20]:
            if not isinstance(b, dict):
                continue
            kind = _s(b.get("kind")).lower()
            if kind not in {"work", "project"}:
                kind = "work" if "work" in kind else ("project" if "proj" in kind else "")
            title = _s(b.get("title"))
            period = _s(b.get("period"))
            body = _s(b.get("body"))
            if not title and not body:
                continue
            # keep body multiline but avoid excessive blanks
            body = re.sub(r"\n{4,}", "\n\n\n", body).strip()
            norm_blocks.append({"kind": kind, "title": title, "period": period, "body": body})
    out["experience_blocks"] = norm_blocks

    work_exps = obj.get("work_experiences") or []
    norm_work: list[dict[str, Any]] = []
    if isinstance(work_exps, list):
        for w in work_exps[:6]:
            if not isinstance(w, dict):
                continue
            desc = w.get("description")
            norm_work.append(
                {
                    "company": _s(w.get("company")),
                    "title": _s(w.get("title")),
                    "period": _s(w.get("period")),
                    "description": _uniq_str_list(desc or [])[:8],
                }
            )
    out["work_experiences"] = norm_work

    out["awards"] = _uniq_str_list(obj.get("awards") or [])[:20]
    out["certifications"] = _uniq_str_list(obj.get("certifications") or [])[:20]
    out["publications"] = _uniq_str_list(obj.get("publications") or [])[:20]

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

    system = """
你是一个“简历信息抽取助手”。只从【简历文本】中抽取候选人的姓名与手机号。

要求：
1) 只能输出 JSON（不要 Markdown、不要解释）。
2) phone 必须是 11 位中国大陆手机号（只输出数字）；无法确定就输出空字符串。
3) 过滤明显的水印/噪声行（例如一整行只有 A-Za-z0-9_- 且很长的 token 串），不要把它当成姓名或手机号来源。

输出格式：
{"name": string, "phone": string, "confidence": {"name": number, "phone": number}}

confidence 为 0-100 的整数，表示可信度。
""".strip()
    # Keep prompt small for latency: first chunk + a window around the phone number if present.
    head = t[:2400]
    around = ""
    m = re.search(r"(?:\\+?86[\\s-]*)?(1[3-9]\\d{9})", t.translate(_FULLWIDTH_DIGITS))
    if m:
        s = max(0, m.start() - 500)
        e = min(len(t), m.end() + 500)
        around = t[s:e]
    focused = _clean_text_for_llm((head + "\n" + around).strip())
    if len(focused) > 5200:
        focused = focused[:5200]
    prompt = "[简历文本]\n" + focused + "\n"
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
