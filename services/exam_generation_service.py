from __future__ import annotations

import json
import os
import re
import hashlib
from datetime import datetime
from typing import Any

from services.llm_client import call_llm_structured_ex


def _env_int(name: str, default: int, *, min_v: int, max_v: int) -> int:
    v = str(os.getenv(name, "") or "").strip()
    if not v:
        return int(default)
    try:
        n = int(float(v))
    except Exception:
        return int(default)
    return max(min_v, min(max_v, n))


def _diagram_mode() -> str:
    """
    Diagram strategy:
    - dynamic: prefer model SVG content, fallback to local templates.
    - template: force local templates for speed/stability.
    """
    v = str(os.getenv("AI_EXAM_DIAGRAM_MODE", "dynamic") or "").strip().lower()
    if v in {"template", "fixed", "fast"}:
        return "template"
    return "dynamic"


def _extract_json_object(raw: str) -> dict[str, Any]:
    s = str(raw or "").strip()
    if not s:
        return {}
    if not (s.startswith("{") and s.endswith("}")):
        l = s.find("{")
        r = s.rfind("}")
        if l != -1 and r != -1 and r > l:
            s = s[l : r + 1]
    try:
        obj = json.loads(s)
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _repair_invalid_json(raw_text: str) -> dict[str, Any]:
    """
    Best-effort repair when model output is not valid JSON.
    This consumes fewer tokens than re-generating a whole paper.
    """
    text = str(raw_text or "").strip()
    if not text:
        return {}
    repair_system = (
        "你是 JSON 修复器。"
        "请把用户提供的文本修复成一个合法 JSON 对象，"
        "只输出 JSON，不要解释，不要 markdown 代码块。"
    )
    repair_prompt = (
        "将下面内容修复为合法 JSON 对象；"
        "若包含额外文字，请移除无关文本并保留原语义字段：\n\n"
        f"{text}"
    )
    fixed_raw, _err = call_llm_structured_ex(repair_prompt, system=repair_system)
    return _extract_json_object(fixed_raw)


def _slugify_ascii(text: str) -> str:
    s = str(text or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def _safe_exam_id(raw: str | None) -> str:
    s = _slugify_ascii(raw or "")
    if not s.startswith("exam-"):
        s = f"exam-{s}" if s else ""
    if not s:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"exam-ai-{ts}"
    return s[:64]


def _safe_qid(raw: Any, idx: int) -> str:
    s = str(raw or "").strip()
    if not s:
        return f"Q{idx}"
    if not s.upper().startswith("Q"):
        s = f"Q{s}"
    s = re.sub(r"[^A-Za-z0-9_-]+", "", s)
    if not s:
        return f"Q{idx}"
    return s


def _safe_svg_text(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    l = s.find("<svg")
    r = s.rfind("</svg>")
    if l != -1 and r != -1 and r > l:
        s = s[l : r + len("</svg>")]
    if "<svg" not in s or "</svg>" not in s:
        return ""
    return s


def _xml_escape_text(text: str) -> str:
    s = str(text or "")
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace('"', "&quot;").replace("'", "&apos;")
    return s


def _first_nonempty_line(text: str, max_len: int = 36) -> str:
    for ln in str(text or "").splitlines():
        t = ln.strip()
        if t:
            return t[:max_len]
    t = str(text or "").strip()
    return t[:max_len] if t else "题目示意图"


def _semantic_svg_fallback(*, stem: str, alt: str, requested_type: str) -> str:
    """
    Dynamic local fallback: generate a non-fixed semantic sketch from question text.
    This avoids reusing static templates when LLM SVG generation fails.
    """
    seed_src = f"{stem}|{alt}|{requested_type}".encode("utf-8", errors="ignore")
    h = hashlib.sha1(seed_src).hexdigest()
    vals = [int(h[i : i + 2], 16) for i in range(0, 12, 2)]

    title = _xml_escape_text(_first_nonempty_line(alt or stem, max_len=32))
    subtitle = _xml_escape_text(_first_nonempty_line(stem, max_len=56))

    x0 = 180
    y0 = 390
    points: list[str] = []
    for i in range(6):
        x = x0 + i * 150
        y = y0 - int(28 + (vals[i % len(vals)] / 255.0) * 240)
        points.append(f"{x},{y}")
    polyline = " ".join(points)

    k_words = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]{2,}", str(stem or ""))
    k_words = [w for w in k_words if w not in {"题目", "请问", "根据", "以下", "其中", "以及"}]
    k1 = _xml_escape_text(k_words[0] if len(k_words) > 0 else "语义")
    k2 = _xml_escape_text(k_words[1] if len(k_words) > 1 else "趋势")
    k3 = _xml_escape_text(k_words[2] if len(k_words) > 2 else "分析")

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="520" viewBox="0 0 1200 520">
  <style>
    text{{font-family:'Microsoft YaHei','PingFang SC','Segoe UI',Arial,sans-serif;fill:#0f172a}}
    .title{{font-size:30px;font-weight:700}}
    .sub{{font-size:18px;font-weight:600;fill:#334155}}
    .lab{{font-size:16px;font-weight:600;fill:#475569}}
  </style>
  <rect x="0" y="0" width="1200" height="520" fill="#ffffff"/>
  <text x="600" y="48" text-anchor="middle" class="title">{title}</text>
  <text x="600" y="80" text-anchor="middle" class="sub">{subtitle}</text>
  <rect x="120" y="110" width="960" height="320" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1.5"/>
  <line x1="170" y1="390" x2="1040" y2="390" stroke="#334155" stroke-width="2"/>
  <line x1="170" y1="150" x2="170" y2="390" stroke="#334155" stroke-width="2"/>
  <polyline points="{polyline}" fill="none" stroke="#2563eb" stroke-width="4"/>
  <circle cx="{x0 + 150}" cy="{y0 - int(28 + (vals[1] / 255.0) * 240)}" r="7" fill="#ef4444"/>
  <circle cx="{x0 + 450}" cy="{y0 - int(28 + (vals[3] / 255.0) * 240)}" r="7" fill="#ef4444"/>
  <circle cx="{x0 + 750}" cy="{y0 - int(28 + (vals[5] / 255.0) * 240)}" r="7" fill="#ef4444"/>
  <text x="860" y="156" class="lab">关键词: {k1} / {k2} / {k3}</text>
</svg>"""


def _generate_svg_with_llm(*, stem: str, alt: str, requested_type: str) -> str:
    hint = str(requested_type or "").strip().lower()
    system = (
        "你是技术笔试配图生成器。"
        "请只输出 JSON 对象，字段为 svg。"
        "svg 必须是完整、可渲染、无外链、中文可读、不裁切。"
        "图内容必须和题干语义一致，不得复用固定模板。"
    )
    prompt = (
        "根据题干生成一张示意图 SVG。\n"
        f"题干：{stem}\n"
        f"配图说明：{alt or '示意图'}\n"
        f"类型提示：{hint or 'auto'}\n\n"
        '输出格式：{"svg":"<svg ...>...</svg>"}'
    )
    raw, _err = call_llm_structured_ex(prompt, system=system)
    obj = _extract_json_object(raw)
    if not obj:
        obj = _repair_invalid_json(raw)
    s = _safe_svg_text(obj.get("svg") if isinstance(obj, dict) else "")
    if not s:
        return ""
    return normalize_svg_text(s)


def _question_needs_figure(*, stem: str, fig_type: str, alt: str) -> bool:
    text = f"{stem} {fig_type} {alt}".lower()
    keys = [
        "如下图",
        "根据图",
        "图示",
        "示意图",
        "曲线",
        "趋势",
        "热力图",
        "混淆矩阵",
        "决策边界",
        "架构图",
        "流程图",
        "时序图",
        "拓扑",
        "表格",
        "指标对比",
        "柱状图",
        "折线图",
        "监控图",
        "p99",
        "gc",
    ]
    return any(k in text for k in keys)


def _extract_svg_bounds(svg: str) -> tuple[float, float]:
    max_x = 0.0
    max_y = 0.0
    for key in ("x", "x1", "x2", "cx"):
        for m in re.finditer(rf"\b{key}\s*=\s*['\"]\s*([0-9]+(?:\.[0-9]+)?)", svg):
            try:
                max_x = max(max_x, float(m.group(1)))
            except Exception:
                pass
    for m in re.finditer(r"\bx\s*=\s*['\"]\s*([0-9]+(?:\.[0-9]+)?)['\"][^>]*\bwidth\s*=\s*['\"]\s*([0-9]+(?:\.[0-9]+)?)", svg):
        try:
            max_x = max(max_x, float(m.group(1)) + float(m.group(2)))
        except Exception:
            pass
    for key in ("y", "y1", "y2", "cy"):
        for m in re.finditer(rf"\b{key}\s*=\s*['\"]\s*([0-9]+(?:\.[0-9]+)?)", svg):
            try:
                max_y = max(max_y, float(m.group(1)))
            except Exception:
                pass
    for m in re.finditer(r"\by\s*=\s*['\"]\s*([0-9]+(?:\.[0-9]+)?)['\"][^>]*\bheight\s*=\s*['\"]\s*([0-9]+(?:\.[0-9]+)?)", svg):
        try:
            max_y = max(max_y, float(m.group(1)) + float(m.group(2)))
        except Exception:
            pass
    return max_x, max_y


def normalize_svg_text(svg: str) -> str:
    s = _safe_svg_text(svg)
    if not s:
        return ""

    width = 1200.0
    height = 420.0
    m_w = re.search(r"\bwidth\s*=\s*['\"]\s*([0-9]+(?:\.[0-9]+)?)", s)
    m_h = re.search(r"\bheight\s*=\s*['\"]\s*([0-9]+(?:\.[0-9]+)?)", s)
    if m_w:
        try:
            width = max(width, float(m_w.group(1)))
        except Exception:
            pass
    if m_h:
        try:
            height = max(height, float(m_h.group(1)))
        except Exception:
            pass
    m_vb = re.search(r"\bviewBox\s*=\s*['\"]\s*([\-0-9.]+)\s+([\-0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*['\"]", s)
    if m_vb:
        try:
            width = max(width, float(m_vb.group(3)))
            height = max(height, float(m_vb.group(4)))
        except Exception:
            pass

    max_x, max_y = _extract_svg_bounds(s)
    width = max(width, max_x + 120.0)
    height = max(height, max_y + 80.0)
    w_i = int(round(width))
    h_i = int(round(height))

    # Rewrite only the opening <svg ...> tag. Do not globally strip width/height,
    # otherwise attributes like `stroke-width` on inner elements get corrupted.
    m_svg = re.search(r"<svg\b[^>]*>", s)
    if m_svg:
        opening = m_svg.group(0)
        opening2 = re.sub(r"\s+width\s*=\s*['\"][^'\"]*['\"]", "", opening, flags=re.IGNORECASE)
        opening2 = re.sub(r"\s+height\s*=\s*['\"][^'\"]*['\"]", "", opening2, flags=re.IGNORECASE)
        opening2 = re.sub(r"\s+viewBox\s*=\s*['\"][^'\"]*['\"]", "", opening2, flags=re.IGNORECASE)
        opening2 = re.sub(r"\s+preserveAspectRatio\s*=\s*['\"][^'\"]*['\"]", "", opening2, flags=re.IGNORECASE)
        opening2 = opening2[:-1] + (
            f" width=\"{w_i}\" height=\"{h_i}\" viewBox=\"0 0 {w_i} {h_i}\""
            " preserveAspectRatio=\"xMidYMid meet\">"
        )
        s = s[: m_svg.start()] + opening2 + s[m_svg.end() :]
    else:
        s = re.sub(
            r"<svg\b",
            f"<svg width=\"{w_i}\" height=\"{h_i}\" viewBox=\"0 0 {w_i} {h_i}\" preserveAspectRatio=\"xMidYMid meet\"",
            s,
            count=1,
        )

    # Repair common malformed rect tags from model output / legacy sanitizer:
    # if rect misses width/height, browsers render nothing.
    def _patch_rect(m: re.Match[str]) -> str:
        tag = m.group(0)
        low = tag.lower()
        has_w = re.search(r"\bwidth\s*=\s*['\"]", tag, flags=re.IGNORECASE) is not None
        has_h = re.search(r"\bheight\s*=\s*['\"]", tag, flags=re.IGNORECASE) is not None
        if has_w and has_h:
            return tag
        x = 0.0
        y = 0.0
        try:
            mx = re.search(r"\bx\s*=\s*['\"]\s*([0-9]+(?:\.[0-9]+)?)", tag, flags=re.IGNORECASE)
            my = re.search(r"\by\s*=\s*['\"]\s*([0-9]+(?:\.[0-9]+)?)", tag, flags=re.IGNORECASE)
            if mx:
                x = float(mx.group(1))
            if my:
                y = float(my.group(1))
        except Exception:
            pass
        # Heuristic: top-left light background rect should span almost full canvas.
        is_bg_like = (x <= 40 and y <= 40) and ("fill='#fff'" in low or "fill=\"#fff\"" in low or "#ffffff" in low)
        width_default = max(200, (w_i - 60) if is_bg_like else 280)
        height_default = max(120, (h_i - 60) if is_bg_like else 110)
        closing = "/>" if tag.rstrip().endswith("/>") else ">"
        body = tag.rstrip()
        body = body[:-2] if closing == "/>" else body[:-1]
        if not has_w:
            body += f" width='{int(width_default)}'"
        if not has_h:
            body += f" height='{int(height_default)}'"
        return body + closing

    s = re.sub(r"<rect\b[^>]*\/?>", _patch_rect, s, flags=re.IGNORECASE)

    if "<style" not in s:
        style_block = (
            "<style>"
            "text{font-family:'Microsoft YaHei','PingFang SC','Segoe UI',Arial,sans-serif;"
            "font-size:22px;font-weight:600;fill:#0f172a;}"
            "line,path,rect,polyline,polygon,circle,ellipse{stroke:#475569;stroke-width:2;}"
            "</style>"
        )
        s = re.sub(r"(<svg[^>]*>)", r"\1" + style_block, s, count=1)
    if "<rect" not in s:
        bg = f"<rect x=\"0\" y=\"0\" width=\"{w_i}\" height=\"{h_i}\" fill=\"#ffffff\"/>"
        s = re.sub(r"(<svg[^>]*>)", r"\1" + bg, s, count=1)
    return s


def normalize_svg_bytes_for_serving(data: bytes) -> bytes:
    if not data:
        return data
    try:
        raw = data.decode("utf-8", errors="ignore")
    except Exception:
        return data
    fixed = normalize_svg_text(raw)
    if not fixed:
        return data
    try:
        return fixed.encode("utf-8")
    except Exception:
        return data


def _safe_asset_name(raw: Any, fallback_qid: str) -> str:
    s = str(raw or "").strip().replace("\\", "/")
    if not s:
        s = f"img/{fallback_qid.lower()}-diagram.svg"
    if not s.lower().endswith(".svg"):
        s = f"{s}.svg"
    if "/" not in s:
        s = f"img/{s}"
    s = s.lstrip("/")
    parts = [p for p in s.split("/") if p and p not in {".", ".."}]
    if not parts:
        return f"img/{fallback_qid.lower()}-diagram.svg"
    return "/".join(parts)


def _template_svg_by_type(chart_type: str) -> str:
    t = str(chart_type or "").strip().lower()
    if t == "latency_curve":
        return """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="520" viewBox="0 0 1200 520">
  <style>
    text{font-family:'Microsoft YaHei','PingFang SC','Segoe UI',Arial,sans-serif;fill:#0f172a}
    .title{font-size:30px;font-weight:700}
    .axis{font-size:18px;font-weight:600}
    .tick{font-size:15px;font-weight:600}
  </style>
  <rect x="0" y="0" width="1200" height="520" fill="#ffffff"/>
  <text x="600" y="48" text-anchor="middle" class="title">并发数与 P99 延迟趋势</text>
  <line x1="110" y1="430" x2="1080" y2="430" stroke="#334155" stroke-width="2"/>
  <line x1="110" y1="90" x2="110" y2="430" stroke="#334155" stroke-width="2"/>
  <line x1="110" y1="430" x2="1080" y2="430" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="110" y1="362" x2="1080" y2="362" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="110" y1="294" x2="1080" y2="294" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="110" y1="226" x2="1080" y2="226" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="110" y1="158" x2="1080" y2="158" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="110" y1="90" x2="1080" y2="90" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="110" y1="430" x2="110" y2="90" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="303" y1="430" x2="303" y2="90" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="497" y1="430" x2="497" y2="90" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="691" y1="430" x2="691" y2="90" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="885" y1="430" x2="885" y2="90" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="1080" y1="430" x2="1080" y2="90" stroke="#e2e8f0" stroke-width="1"/>
  <text x="96" y="435" text-anchor="end" class="tick">10</text>
  <text x="96" y="367" text-anchor="end" class="tick">20</text>
  <text x="96" y="299" text-anchor="end" class="tick">40</text>
  <text x="96" y="231" text-anchor="end" class="tick">80</text>
  <text x="96" y="163" text-anchor="end" class="tick">160</text>
  <text x="96" y="95" text-anchor="end" class="tick">320</text>
  <text x="110" y="452" text-anchor="middle" class="tick">50</text>
  <text x="303" y="452" text-anchor="middle" class="tick">100</text>
  <text x="497" y="452" text-anchor="middle" class="tick">150</text>
  <text x="691" y="452" text-anchor="middle" class="tick">200</text>
  <text x="885" y="452" text-anchor="middle" class="tick">250</text>
  <text x="1080" y="452" text-anchor="middle" class="tick">300</text>
  <text x="595" y="486" text-anchor="middle" class="axis">并发数</text>
  <text x="32" y="260" transform="rotate(-90,32,260)" class="axis">P99 延迟(ms)</text>
  <polyline points="110,414 303,405 497,392 691,345 885,250 1080,140"
            fill="none" stroke="#1d4ed8" stroke-width="4"/>
  <line x1="691" y1="95" x2="691" y2="430" stroke="#dc2626" stroke-dasharray="8 8" stroke-width="2"/>
  <text x="700" y="118" class="tick" fill="#dc2626">拐点（并发约 200）</text>
  <rect x="850" y="98" width="18" height="18" fill="#1d4ed8"/><text x="876" y="113" class="tick">P99</text>
</svg>"""
    if t == "service_heatmap":
        return """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="520" viewBox="0 0 1200 520">
  <style>
    text{font-family:'Microsoft YaHei','PingFang SC','Segoe UI',Arial,sans-serif;fill:#0f172a}
    .title{font-size:30px;font-weight:700}
    .lab{font-size:20px;font-weight:600}
    .v{font-size:22px;font-weight:700}
  </style>
  <rect x="0" y="0" width="1200" height="520" fill="#ffffff"/>
  <text x="600" y="48" text-anchor="middle" class="title">微服务调用错误率热力图</text>
  <text x="290" y="120" text-anchor="middle" class="lab">订单接口</text>
  <text x="500" y="120" text-anchor="middle" class="lab">支付接口</text>
  <text x="710" y="120" text-anchor="middle" class="lab">库存接口</text>
  <text x="920" y="120" text-anchor="middle" class="lab">用户接口</text>
  <text x="120" y="205" text-anchor="middle" class="lab">网关</text>
  <text x="120" y="290" text-anchor="middle" class="lab">订单服务</text>
  <text x="120" y="375" text-anchor="middle" class="lab">支付服务</text>
  <rect x="180" y="150" width="220" height="70" fill="#fecaca" stroke="#ef4444"/><text x="290" y="193" text-anchor="middle" class="v">8.1%</text>
  <rect x="390" y="150" width="220" height="70" fill="#991b1b" stroke="#7f1d1d"/><text x="500" y="193" text-anchor="middle" class="v" fill="#fff">12.4%</text>
  <rect x="600" y="150" width="220" height="70" fill="#fee2e2" stroke="#ef4444"/><text x="710" y="193" text-anchor="middle" class="v">4.0%</text>
  <rect x="810" y="150" width="220" height="70" fill="#fee2e2" stroke="#ef4444"/><text x="920" y="193" text-anchor="middle" class="v">3.6%</text>
  <rect x="180" y="235" width="220" height="70" fill="#fee2e2" stroke="#ef4444"/><text x="290" y="278" text-anchor="middle" class="v">3.2%</text>
  <rect x="390" y="235" width="220" height="70" fill="#fecaca" stroke="#ef4444"/><text x="500" y="278" text-anchor="middle" class="v">7.3%</text>
  <rect x="600" y="235" width="220" height="70" fill="#fee2e2" stroke="#ef4444"/><text x="710" y="278" text-anchor="middle" class="v">2.8%</text>
  <rect x="810" y="235" width="220" height="70" fill="#fee2e2" stroke="#ef4444"/><text x="920" y="278" text-anchor="middle" class="v">2.1%</text>
  <rect x="180" y="320" width="220" height="70" fill="#fee2e2" stroke="#ef4444"/><text x="290" y="363" text-anchor="middle" class="v">2.4%</text>
  <rect x="390" y="320" width="220" height="70" fill="#fecaca" stroke="#ef4444"/><text x="500" y="363" text-anchor="middle" class="v">6.8%</text>
  <rect x="600" y="320" width="220" height="70" fill="#fee2e2" stroke="#ef4444"/><text x="710" y="363" text-anchor="middle" class="v">1.9%</text>
  <rect x="810" y="320" width="220" height="70" fill="#fee2e2" stroke="#ef4444"/><text x="920" y="363" text-anchor="middle" class="v">1.5%</text>
  <text x="180" y="440" class="lab">颜色越深代表错误率越高，优先排查网关 -> 支付接口链路</text>
</svg>"""
    if t == "loss_curve":
        return """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="520" viewBox="0 0 1200 520">
  <style>
    text{font-family:'Microsoft YaHei','PingFang SC','Segoe UI',Arial,sans-serif;fill:#0f172a}
    .title{font-size:30px;font-weight:700}
    .axis{font-size:18px;font-weight:600}
    .tick{font-size:15px;font-weight:600}
  </style>
  <rect x="0" y="0" width="1200" height="520" fill="#ffffff"/>
  <text x="600" y="48" text-anchor="middle" class="title">训练/测试损失曲线</text>
  <line x1="110" y1="430" x2="1080" y2="430" stroke="#334155" stroke-width="2"/>
  <line x1="110" y1="90" x2="110" y2="430" stroke="#334155" stroke-width="2"/>
  <line x1="110" y1="430" x2="1080" y2="430" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="110" y1="362" x2="1080" y2="362" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="110" y1="294" x2="1080" y2="294" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="110" y1="226" x2="1080" y2="226" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="110" y1="158" x2="1080" y2="158" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="110" y1="90" x2="1080" y2="90" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="110" y1="430" x2="110" y2="90" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="303" y1="430" x2="303" y2="90" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="497" y1="430" x2="497" y2="90" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="691" y1="430" x2="691" y2="90" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="885" y1="430" x2="885" y2="90" stroke="#e2e8f0" stroke-width="1"/>
  <line x1="1080" y1="430" x2="1080" y2="90" stroke="#e2e8f0" stroke-width="1"/>
  <text x="96" y="435" text-anchor="end" class="tick">0.35</text>
  <text x="96" y="367" text-anchor="end" class="tick">0.40</text>
  <text x="96" y="299" text-anchor="end" class="tick">0.45</text>
  <text x="96" y="231" text-anchor="end" class="tick">0.50</text>
  <text x="96" y="163" text-anchor="end" class="tick">0.55</text>
  <text x="96" y="95"  text-anchor="end" class="tick">0.60</text>
  <text x="110" y="452" text-anchor="middle" class="tick">0</text>
  <text x="303" y="452" text-anchor="middle" class="tick">10</text>
  <text x="497" y="452" text-anchor="middle" class="tick">20</text>
  <text x="691" y="452" text-anchor="middle" class="tick">30</text>
  <text x="885" y="452" text-anchor="middle" class="tick">40</text>
  <text x="1080" y="452" text-anchor="middle" class="tick">50</text>
  <text x="595" y="486" text-anchor="middle" class="axis">epoch</text>
  <text x="32" y="260" transform="rotate(-90,32,260)" class="axis">loss</text>
  <polyline points="110,130 190,190 270,228 350,252 430,273 510,290 590,305 670,322 750,338 830,353 910,366 990,379 1080,390"
            fill="none" stroke="#1d4ed8" stroke-width="4"/>
  <polyline points="110,140 190,215 270,262 350,281 430,284 510,286 590,292 670,304 750,318 830,336 910,348 990,360 1080,372"
            fill="none" stroke="#f59e0b" stroke-width="4"/>
  <line x1="470" y1="100" x2="470" y2="430" stroke="#dc2626" stroke-dasharray="8 8" stroke-width="2"/>
  <text x="480" y="118" class="tick" fill="#dc2626">过拟合开始（约 epoch=20）</text>
  <rect x="860" y="98" width="18" height="18" fill="#1d4ed8"/><text x="886" y="113" class="tick">train</text>
  <rect x="860" y="126" width="18" height="18" fill="#f59e0b"/><text x="886" y="141" class="tick">test</text>
</svg>"""
    if t == "model_compare":
        return """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="520" viewBox="0 0 1200 520">
  <style>
    text{font-family:'Microsoft YaHei','PingFang SC','Segoe UI',Arial,sans-serif;fill:#0f172a}
    .title{font-size:30px;font-weight:700}
    .axis{font-size:18px;font-weight:600}
    .tick{font-size:18px;font-weight:600}
    .v{font-size:16px;font-weight:700}
  </style>
  <rect x="0" y="0" width="1200" height="520" fill="#ffffff"/>
  <text x="600" y="48" text-anchor="middle" class="title">候选模型对比（AUC 与推理延迟）</text>
  <line x1="120" y1="440" x2="1080" y2="440" stroke="#334155" stroke-width="2"/>
  <line x1="120" y1="90" x2="120" y2="440" stroke="#334155" stroke-width="2"/>
  <text x="34" y="260" transform="rotate(-90,34,260)" class="axis">归一化分数（0-100）</text>
  <text x="600" y="490" text-anchor="middle" class="axis">模型</text>

  <rect x="920" y="96" width="20" height="20" fill="#2563eb"/><text x="948" y="112" class="tick">AUC（越高越好）</text>
  <rect x="920" y="126" width="20" height="20" fill="#f59e0b"/><text x="948" y="142" class="tick">延迟得分（越高越快）</text>

  <g>
    <rect x="220" y="114" width="70" height="326" fill="#2563eb"/><text x="255" y="106" text-anchor="middle" class="v">93</text>
    <rect x="300" y="212" width="70" height="228" fill="#f59e0b"/><text x="335" y="204" text-anchor="middle" class="v">65</text>
    <text x="295" y="470" text-anchor="middle" class="tick">模型A</text>
  </g>
  <g>
    <rect x="500" y="118" width="70" height="322" fill="#2563eb"/><text x="535" y="110" text-anchor="middle" class="v">92</text>
    <rect x="580" y="142" width="70" height="298" fill="#f59e0b"/><text x="615" y="134" text-anchor="middle" class="v">85</text>
    <text x="575" y="470" text-anchor="middle" class="tick">模型B</text>
  </g>
  <g>
    <rect x="780" y="104" width="70" height="336" fill="#2563eb"/><text x="815" y="96" text-anchor="middle" class="v">96</text>
    <rect x="860" y="254" width="70" height="186" fill="#f59e0b"/><text x="895" y="246" text-anchor="middle" class="v">53</text>
    <text x="855" y="470" text-anchor="middle" class="tick">模型C</text>
  </g>
</svg>"""
    if t == "confusion_matrix":
        return """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="520" viewBox="0 0 1200 520">
  <style>
    text{font-family:'Microsoft YaHei','PingFang SC','Segoe UI',Arial,sans-serif;fill:#0f172a}
    .title{font-size:30px;font-weight:700}
    .lab{font-size:20px;font-weight:600}
    .v{font-size:42px;font-weight:700}
  </style>
  <rect x="0" y="0" width="1200" height="520" fill="#ffffff"/>
  <text x="600" y="48" text-anchor="middle" class="title">二分类混淆矩阵（实际×预测）</text>
  <text x="420" y="104" text-anchor="middle" class="lab">预测：负类</text>
  <text x="760" y="104" text-anchor="middle" class="lab">预测：正类</text>
  <text x="170" y="220" text-anchor="middle" class="lab" transform="rotate(-90,170,220)">实际：负类</text>
  <text x="170" y="360" text-anchor="middle" class="lab" transform="rotate(-90,170,360)">实际：正类</text>
  <rect x="260" y="140" width="300" height="140" fill="#dcfce7" stroke="#16a34a" stroke-width="2"/>
  <rect x="600" y="140" width="300" height="140" fill="#fee2e2" stroke="#dc2626" stroke-width="2"/>
  <rect x="260" y="300" width="300" height="140" fill="#fee2e2" stroke="#dc2626" stroke-width="2"/>
  <rect x="600" y="300" width="300" height="140" fill="#dcfce7" stroke="#16a34a" stroke-width="2"/>
  <text x="410" y="228" text-anchor="middle" class="v">85</text>
  <text x="750" y="228" text-anchor="middle" class="v">15</text>
  <text x="410" y="388" text-anchor="middle" class="v">20</text>
  <text x="750" y="388" text-anchor="middle" class="v">70</text>
</svg>"""
    if t == "feature_distribution":
        return """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="520" viewBox="0 0 1200 520">
  <style>
    text{font-family:'Microsoft YaHei','PingFang SC','Segoe UI',Arial,sans-serif;fill:#0f172a}
    .title{font-size:30px;font-weight:700}
    .axis{font-size:18px;font-weight:600}
    .tick{font-size:16px;font-weight:600}
  </style>
  <rect x="0" y="0" width="1200" height="520" fill="#ffffff"/>
  <text x="600" y="48" text-anchor="middle" class="title">特征分布对比（训练 vs 线上）</text>
  <line x1="110" y1="430" x2="1080" y2="430" stroke="#334155" stroke-width="2"/>
  <line x1="110" y1="90" x2="110" y2="430" stroke="#334155" stroke-width="2"/>
  <text x="595" y="486" text-anchor="middle" class="axis">feature value</text>
  <text x="32" y="260" transform="rotate(-90,32,260)" class="axis">density</text>
  <polyline points="110,360 180,300 250,220 320,170 390,150 460,180 530,240 600,310 670,360"
            fill="none" stroke="#1d4ed8" stroke-width="4"/>
  <polyline points="350,360 420,330 490,290 560,230 630,180 700,150 770,170 840,220 910,300 980,360"
            fill="none" stroke="#ef4444" stroke-width="4"/>
  <rect x="850" y="98" width="18" height="18" fill="#1d4ed8"/><text x="876" y="113" class="tick">train</text>
  <rect x="850" y="126" width="18" height="18" fill="#ef4444"/><text x="876" y="141" class="tick">online</text>
  <text x="700" y="76" class="tick" fill="#dc2626">线上分布右移，存在漂移风险</text>
</svg>"""
    if t == "decision_boundary":
        return """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="520" viewBox="0 0 1200 520">
  <style>
    text{font-family:'Microsoft YaHei','PingFang SC','Segoe UI',Arial,sans-serif;fill:#0f172a}
    .title{font-size:30px;font-weight:700}
    .axis{font-size:18px;font-weight:600}
    .tick{font-size:16px;font-weight:600}
  </style>
  <rect x="0" y="0" width="1200" height="520" fill="#ffffff"/>
  <text x="600" y="48" text-anchor="middle" class="title">决策边界与样本分布</text>
  <rect x="130" y="90" width="940" height="340" fill="#f8fafc" stroke="#cbd5e1"/>
  <line x1="130" y1="430" x2="1070" y2="430" stroke="#334155" stroke-width="2"/>
  <line x1="130" y1="90" x2="130" y2="430" stroke="#334155" stroke-width="2"/>
  <text x="602" y="486" text-anchor="middle" class="axis">x1</text>
  <text x="52" y="260" transform="rotate(-90,52,260)" class="axis">x2</text>
  <polyline points="210,400 280,340 360,280 460,220 600,170 760,150 930,160" fill="none" stroke="#8b5cf6" stroke-width="3" stroke-dasharray="8 6"/>
  <circle cx="250" cy="330" r="8" fill="#2563eb"/><circle cx="290" cy="300" r="8" fill="#2563eb"/><circle cx="330" cy="278" r="8" fill="#2563eb"/>
  <circle cx="620" cy="230" r="8" fill="#2563eb"/><circle cx="680" cy="205" r="8" fill="#2563eb"/>
  <circle cx="770" cy="210" r="8" fill="#ef4444"/><circle cx="820" cy="240" r="8" fill="#ef4444"/><circle cx="860" cy="268" r="8" fill="#ef4444"/>
  <circle cx="910" cy="290" r="8" fill="#ef4444"/><circle cx="960" cy="320" r="8" fill="#ef4444"/>
  <rect x="840" y="96" width="18" height="18" fill="#2563eb"/><text x="866" y="111" class="tick">class 0</text>
  <rect x="840" y="124" width="18" height="18" fill="#ef4444"/><text x="866" y="139" class="tick">class 1</text>
  <line x1="840" y1="152" x2="858" y2="152" stroke="#8b5cf6" stroke-width="3" stroke-dasharray="8 6"/><text x="866" y="157" class="tick">decision boundary</text>
</svg>"""
    if t == "architecture":
        return """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="420" viewBox="0 0 1200 420">
  <style>
    text{font-family:'Microsoft YaHei','PingFang SC','Segoe UI',Arial,sans-serif;fill:#0f172a}
    .title{font-size:28px;font-weight:700}
    .node{font-size:18px;font-weight:600}
  </style>
  <rect x="0" y="0" width="1200" height="420" fill="#ffffff"/>
  <text x="600" y="46" text-anchor="middle" class="title">在线推理系统架构</text>
  <defs><marker id="a" markerWidth="12" markerHeight="12" refX="8" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#334155"/></marker></defs>
  <rect x="80" y="160" width="180" height="70" rx="10" fill="#e2e8f0" stroke="#64748b"/><text x="170" y="202" text-anchor="middle" class="node">客户端</text>
  <rect x="320" y="160" width="180" height="70" rx="10" fill="#dbeafe" stroke="#3b82f6"/><text x="410" y="202" text-anchor="middle" class="node">API 网关</text>
  <rect x="560" y="160" width="180" height="70" rx="10" fill="#dcfce7" stroke="#16a34a"/><text x="650" y="202" text-anchor="middle" class="node">推理服务</text>
  <rect x="800" y="90" width="180" height="70" rx="10" fill="#fef3c7" stroke="#d97706"/><text x="890" y="132" text-anchor="middle" class="node">特征存储</text>
  <rect x="800" y="230" width="180" height="70" rx="10" fill="#fee2e2" stroke="#dc2626"/><text x="890" y="272" text-anchor="middle" class="node">模型仓库</text>
  <line x1="260" y1="195" x2="320" y2="195" stroke="#334155" stroke-width="2.4" marker-end="url(#a)"/>
  <line x1="500" y1="195" x2="560" y2="195" stroke="#334155" stroke-width="2.4" marker-end="url(#a)"/>
  <line x1="740" y1="182" x2="800" y2="135" stroke="#334155" stroke-width="2.4" marker-end="url(#a)"/>
  <line x1="740" y1="208" x2="800" y2="255" stroke="#334155" stroke-width="2.4" marker-end="url(#a)"/>
</svg>"""
    if t == "metric_table":
        return """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="460" viewBox="0 0 1200 460">
  <style>
    text{font-family:'Microsoft YaHei','PingFang SC','Segoe UI',Arial,sans-serif;fill:#0f172a}
    .title{font-size:28px;font-weight:700}
    .h{font-size:20px;font-weight:700}
    .c{font-size:18px;font-weight:600}
  </style>
  <rect x="0" y="0" width="1200" height="460" fill="#ffffff"/>
  <text x="600" y="44" text-anchor="middle" class="title">候选模型指标对比表</text>
  <rect x="120" y="90" width="960" height="300" fill="#ffffff" stroke="#64748b" stroke-width="2"/>
  <line x1="120" y1="145" x2="1080" y2="145" stroke="#64748b"/><line x1="360" y1="90" x2="360" y2="390" stroke="#64748b"/>
  <line x1="580" y1="90" x2="580" y2="390" stroke="#64748b"/><line x1="800" y1="90" x2="800" y2="390" stroke="#64748b"/>
  <line x1="120" y1="205" x2="1080" y2="205" stroke="#cbd5e1"/><line x1="120" y1="265" x2="1080" y2="265" stroke="#cbd5e1"/><line x1="120" y1="325" x2="1080" y2="325" stroke="#cbd5e1"/>
  <text x="240" y="126" text-anchor="middle" class="h">模型</text><text x="470" y="126" text-anchor="middle" class="h">AUC</text><text x="690" y="126" text-anchor="middle" class="h">F1</text><text x="940" y="126" text-anchor="middle" class="h">延迟(ms)</text>
  <text x="240" y="186" text-anchor="middle" class="c">A</text><text x="470" y="186" text-anchor="middle" class="c">0.93</text><text x="690" y="186" text-anchor="middle" class="c">0.88</text><text x="940" y="186" text-anchor="middle" class="c">42</text>
  <text x="240" y="246" text-anchor="middle" class="c">B</text><text x="470" y="246" text-anchor="middle" class="c">0.92</text><text x="690" y="246" text-anchor="middle" class="c">0.90</text><text x="940" y="246" text-anchor="middle" class="c">31</text>
  <text x="240" y="306" text-anchor="middle" class="c">C</text><text x="470" y="306" text-anchor="middle" class="c">0.96</text><text x="690" y="306" text-anchor="middle" class="c">0.86</text><text x="940" y="306" text-anchor="middle" class="c">58</text>
</svg>"""
    return ""


def _infer_chart_type(*, relpath: str, alt: str, stem: str) -> str:
    text = f"{relpath} {alt} {stem}".lower()
    if any(k in text for k in ["热力图", "错误率", "service-heatmap", "服务调用", "微服务"]):
        return "service_heatmap"
    if any(k in text for k in ["p99", "延迟趋势", "响应时间", "full gc", "young gc", "gc暂停", "并发数"]):
        return "latency_curve"
    if any(k in text for k in ["loss", "训练/测试损失", "损失曲线", "train/test"]):
        return "loss_curve"
    if any(k in text for k in ["confusion", "混淆矩阵", "heatmap", "热力图", "matrix"]):
        return "confusion_matrix"
    if any(k in text for k in ["decision-boundary", "边界", "scatter", "散点", "决策边界"]):
        return "decision_boundary"
    if any(k in text for k in ["feature-dist", "distribution", "直方图", "分布", "漂移"]):
        return "feature_distribution"
    if any(k in text for k in ["model-compare", "models-comparison", "模型对比", "延迟", "auc"]):
        return "model_compare"
    if any(k in text for k in ["架构", "flow", "pipeline", "拓扑", "系统图"]):
        return "architecture"
    if any(k in text for k in ["table", "指标表", "对比表"]):
        return "metric_table"
    return ""


def _choose_final_svg(
    relpath: str,
    raw_svg: Any,
    *,
    alt: str,
    stem: str,
    requested_type: str,
    prefer_model_svg: bool,
) -> str:
    # Dynamic mode: prioritize model-provided SVG so figure content varies with prompt.
    if prefer_model_svg:
        s = _safe_svg_text(raw_svg)
        if s:
            return normalize_svg_text(s)
        s2 = _generate_svg_with_llm(stem=stem, alt=alt, requested_type=requested_type)
        if s2:
            return s2
        # Last-resort dynamic fallback: still semantic and variable, not a fixed template.
        s3 = _semantic_svg_fallback(stem=stem, alt=alt, requested_type=requested_type)
        return normalize_svg_text(s3)
    # Fallback to local templates for stability.
    # Do not blindly trust requested figure.type from model: content semantics in stem/alt
    # should win to avoid mismatch (e.g. Java GC question paired with loss curve).
    requested = str(requested_type or "").strip().lower()
    inferred = _infer_chart_type(relpath=relpath, alt=alt, stem=stem)
    chart_type = inferred or requested
    templ = _template_svg_by_type(chart_type)
    if templ:
        return normalize_svg_text(templ)
    s = _safe_svg_text(raw_svg)
    if not s:
        return ""
    return normalize_svg_text(s)


def check_exam_prompt_completeness(prompt: str) -> dict[str, Any]:
    text = str(prompt or "").strip()
    if not text:
        return {
            "complete": False,
            "score": 0,
            "missing": [
                "请先输入出题需求。",
                "建议至少包含：岗位/主题、目标人群、题型与题量、难度、评分要求。",
            ],
        }

    checks = {
        "岗位/主题": r"(岗位|主题|场景|方向|学科|科目|能力|考试)",
        "目标人群": r"(候选人|人群|级别|经验|年限|校招|社招|应届|资深)",
        "题型与题量": r"(单选|多选|简答|题型|题量|题数|题目)",
        "难度": r"(难度|简单|中等|困难|进阶|基础)",
        "评分要求": r"(分值|总分|评分|打分|rubric|判分|得分)",
    }
    missing: list[str] = []
    hit = 0
    for k, pattern in checks.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            hit += 1
        else:
            missing.append(f"缺少“{k}”信息")

    score = int(round(hit * 100 / max(1, len(checks))))
    if len(text) < 60:
        missing.append("提示词较短，建议补充约束条件（例如覆盖知识点、题目风格、是否需要示意图）。")
        score = min(score, 70)
    return {"complete": len(missing) == 0, "score": score, "missing": missing}


def _extract_target_question_count(prompt: str) -> int | None:
    text = str(prompt or "")
    if not text.strip():
        return None

    for pat in (
        r"(?:总题量|总题数|题目数|题量|题数)\s*[:：]?\s*(\d{1,3})\s*题",
        r"(?:总题量|总题数|题目数|题量|题数)\s*[:：]?\s*(\d{1,3})\b",
    ):
        m = re.search(pat, text, flags=re.IGNORECASE)
        if not m:
            continue
        try:
            n = int(m.group(1))
        except Exception:
            continue
        if 1 <= n <= 200:
            return n

    dist: dict[str, int] = {}
    dist_patterns = {
        "single": (r"(?:单选|单选题)\s*(\d{1,3})\s*题?", r"(\d{1,3})\s*题?\s*(?:单选|单选题)"),
        "multiple": (r"(?:多选|多选题)\s*(\d{1,3})\s*题?", r"(\d{1,3})\s*题?\s*(?:多选|多选题)"),
        "short": (r"(?:简答|简答题)\s*(\d{1,3})\s*题?", r"(\d{1,3})\s*题?\s*(?:简答|简答题)"),
    }
    for k, pats in dist_patterns.items():
        for pat in pats:
            m = re.search(pat, text, flags=re.IGNORECASE)
            if not m:
                continue
            try:
                n = int(m.group(1))
            except Exception:
                continue
            if 0 <= n <= 200:
                dist[k] = n
                break
    if dist:
        s = int(dist.get("single", 0)) + int(dist.get("multiple", 0)) + int(dist.get("short", 0))
        if 1 <= s <= 200:
            return s
    return None


def _build_generation_prompt_body(user_prompt: str, include_diagrams: bool, target_count: int | None, *, retry: bool) -> str:
    if target_count:
        count_rule = (
            f"请生成一份完整试卷，必须恰好 {target_count} 题；"
            "题数必须与要求完全一致，不能少、不能多；并尽量覆盖 single/multiple/short 三类题型。"
        )
    else:
        count_rule = "请生成一份完整试卷，至少 5 题，并尽量覆盖 single/multiple/short 三类题型。"

    retry_rule = ""
    if retry and target_count:
        retry_rule = (
            f"\n重要纠错：上一版题量不合规。你这次输出必须是恰好 {target_count} 题，"
            "否则视为无效。"
        )

    mode = _diagram_mode()
    if include_diagrams and mode == "dynamic":
        diagram_rule = (
            "示意图要求：仅在题干确实需要图示时返回 figure.svg（合法SVG，不能外链）；"
            "图数据与标题必须跟随题干变化，不能复用固定图内容。"
        )
    elif include_diagrams:
        diagram_rule = "示意图要求：仅返回 figure.type/filename/alt，图由系统模板生成。"
    else:
        diagram_rule = "本次无需示意图。"

    return (
        "优先级规则：用户提示词 > 其他默认规则；若冲突，以用户提示词为准。\n\n"
        f"用户提示词：\n{user_prompt}\n\n"
        f"{diagram_rule}\n"
        f"include_diagrams={'true' if include_diagrams else 'false'}\n"
        f"{count_rule}{retry_rule}"
    )


def generate_exam_from_prompt(prompt: str, *, include_diagrams: bool) -> tuple[str, dict[str, bytes], dict[str, Any]]:
    user_prompt = str(prompt or "").strip()
    if not user_prompt:
        raise ValueError("提示词不能为空")

    diagram_mode = _diagram_mode()
    system = """
你是“试卷生成助手”。请严格输出 JSON（不要 Markdown、不要解释）。目标：根据用户提示词生成可被 QML 解析器解析的试卷草案。
输出 JSON schema:
{
  "exam": {"id": "exam-xxx", "title": "...", "description": "..."},
  "questions": [
    {
      "qid": "Q1",
      "type": "single|multiple|short",
      "points": 5,
      "max_points": 10,
      "partial": false,
      "stem": "题干",
      "options": [{"key":"A","text":"...","correct":false}],
      "rubric": ["评分点1","评分点2"],
      "figure": {"filename":"img/q1-diagram.svg","type":"latency_curve|service_heatmap|loss_curve|confusion_matrix|model_compare|feature_distribution|decision_boundary|architecture|metric_table","alt":"示意图"}
    }
  ]
}

规则:
0) 用户提示词优先级最高；若与默认示例或习惯冲突，一律以用户提示词为准，不得擅自缩减题量或改题型分布。
1) single/multiple 必须提供 options，且有正确答案；single 只能一个正确答案。
2) short 必须提供 rubric 数组（至少 3 条）。
3) points/max_points 必须是正整数。
4) 若 include_diagrams=false，请不要输出 figure。
5) 若 include_diagrams=true，请输出与题干强相关的图信息。
6) 若需要，figure 可以包含 svg 字段；若没有 svg，至少给出 figure.type/filename/alt。
7) 图示必须跟随题目变化，不得整卷复用同一图内容；保证文字可读、元素不裁切。
""".strip()
    if diagram_mode == "template":
        system += "\n8) 当前为模板图模式：请不要返回 figure.svg，仅返回 figure.type/filename/alt。"

    target_count = _extract_target_question_count(user_prompt)
    obj: dict[str, Any] = {}
    last_err = ""
    max_attempts = _env_int("AI_EXAM_GEN_MAX_ATTEMPTS", 2, min_v=1, max_v=3)
    for attempt in range(max_attempts):
        prompt_body = _build_generation_prompt_body(
            user_prompt,
            include_diagrams,
            target_count,
            retry=(attempt > 0),
        )
        raw, err = call_llm_structured_ex(prompt_body, system=system)
        if not raw:
            last_err = (err or "LLM 无返回").strip()
            continue
        obj = _extract_json_object(raw)
        if not obj:
            obj = _repair_invalid_json(raw)
        if not obj:
            last_err = "LLM 输出不是合法 JSON"
            continue
        raw_questions_try = obj.get("questions")
        if not isinstance(raw_questions_try, list):
            raw_questions_try = []
        if target_count and len(raw_questions_try) != target_count:
            last_err = f"题量不符合要求：需要 {target_count} 题，模型返回 {len(raw_questions_try)} 题"
            obj = {}
            continue
        break
    if not obj:
        raise RuntimeError(last_err or "生成失败")

    exam = obj.get("exam") if isinstance(obj.get("exam"), dict) else {}
    title = str(exam.get("title") or "自动生成试卷").strip()
    description = str(exam.get("description") or "").strip()
    exam_id = _safe_exam_id(str(exam.get("id") or ""))

    raw_questions = obj.get("questions")
    if not isinstance(raw_questions, list):
        raw_questions = []
    if not raw_questions:
        raise RuntimeError("未生成题目，请补充提示词后重试")
    if target_count:
        if len(raw_questions) < target_count:
            raise RuntimeError(f"题量不符合要求：需要 {target_count} 题，模型仅返回 {len(raw_questions)} 题")
        if len(raw_questions) > target_count:
            raw_questions = raw_questions[:target_count]

    assets: dict[str, bytes] = {}
    seen_qid: set[str] = set()
    lines: list[str] = [
        "---",
        f"id: {exam_id}",
        f"title: {title}",
        "description: |",
    ]
    if description:
        for ln in description.splitlines():
            lines.append(f"  {ln}".rstrip())
    else:
        lines.append("  由大模型自动生成")
    lines.append("format: qml-v2")
    lines.extend(["---", ""])

    q_idx = 0
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        q_idx += 1
        qtype = str(item.get("type") or "").strip().lower()
        if qtype not in {"single", "multiple", "short"}:
            qtype = "single"

        qid = _safe_qid(item.get("qid"), q_idx)
        while qid in seen_qid:
            q_idx += 1
            qid = _safe_qid("", q_idx)
        seen_qid.add(qid)

        stem = str(item.get("stem") or "").strip() or "请根据题意作答。"
        partial = bool(item.get("partial")) if qtype == "multiple" else False

        if qtype == "short":
            try:
                max_points = int(item.get("max_points") or item.get("points") or 10)
            except Exception:
                max_points = 10
            max_points = max(1, min(100, max_points))
            lines.append(f"## {qid} [short] {{max={max_points}}}")
        else:
            try:
                points = int(item.get("points") or item.get("max_points") or 5)
            except Exception:
                points = 5
            points = max(1, min(100, points))
            attrs = " {partial=true}" if partial else ""
            lines.append(f"## {qid} [{qtype}] ({points}){attrs}")
        lines.append(stem)

        fig = item.get("figure") if isinstance(item.get("figure"), dict) else {}
        if include_diagrams:
            alt = str(fig.get("alt") or "示意图").strip() or "示意图"
            fig_type = str(fig.get("type") or "").strip().lower()
            need_fig = _question_needs_figure(stem=stem, fig_type=fig_type, alt=alt)
            if need_fig:
                if not fig:
                    fig = {"filename": f"img/{qid.lower()}-diagram.svg", "alt": "题目示意图", "type": ""}
                rel = _safe_asset_name(fig.get("filename"), qid)
                # Dynamic mode: prioritize semantic SVG generation.
                # Template mode: use local deterministic templates.
                svg_text = _choose_final_svg(
                    rel,
                    fig.get("svg"),
                    alt=alt,
                    stem=stem,
                    requested_type=fig_type,
                    prefer_model_svg=(diagram_mode == "dynamic"),
                )
                if svg_text:
                    assets[rel] = svg_text.encode("utf-8", errors="ignore")
                    lines.append(f"![{alt}]({rel})")

        if qtype in {"single", "multiple"}:
            opts = item.get("options") if isinstance(item.get("options"), list) else []
            out_opts: list[dict[str, Any]] = []
            for idx2, op in enumerate(opts):
                if not isinstance(op, dict):
                    continue
                key = str(op.get("key") or "").strip().upper()
                if not re.fullmatch(r"[A-Z]", key or ""):
                    key = chr(ord("A") + min(25, idx2))
                text2 = str(op.get("text") or "").strip() or f"选项{key}"
                out_opts.append({"key": key, "text": text2, "correct": bool(op.get("correct"))})
            if len(out_opts) < 2:
                out_opts = [
                    {"key": "A", "text": "选项A", "correct": True},
                    {"key": "B", "text": "选项B", "correct": False},
                ]
            if qtype == "single":
                correct_ix = [i for i, x in enumerate(out_opts) if x["correct"]]
                if len(correct_ix) != 1:
                    for x in out_opts:
                        x["correct"] = False
                    out_opts[0]["correct"] = True
            else:
                if not any(x["correct"] for x in out_opts):
                    out_opts[0]["correct"] = True
                    if len(out_opts) > 1:
                        out_opts[1]["correct"] = True
            for op in out_opts:
                star = "*" if op["correct"] else ""
                lines.append(f"- {op['key']}{star}) {op['text']}")
        else:
            rb = item.get("rubric")
            rb_lines: list[str] = []
            if isinstance(rb, list):
                rb_lines = [str(x or "").strip() for x in rb if str(x or "").strip()]
            elif isinstance(rb, str):
                rb_lines = [x.strip() for x in rb.splitlines() if x.strip()]
            if len(rb_lines) < 3:
                rb_lines = [
                    "观点准确、切题",
                    "论证过程清晰，有关键依据",
                    "表达完整、结构清楚",
                ]
            lines.append("[rubric]")
            for i2, rline in enumerate(rb_lines, start=1):
                lines.append(f"{i2}) {rline}")
            lines.append("[/rubric]")

        lines.append("")

    markdown_text = "\n".join(lines).strip() + "\n"
    meta = {"question_count": len(seen_qid), "asset_count": len(assets), "exam_id": exam_id}
    return markdown_text, assets, meta
