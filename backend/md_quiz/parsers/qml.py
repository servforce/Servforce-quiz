"""
    qml.parser 是 markdown 解析，把试卷转变成结构化json
"""
from __future__ import annotations

import re
import uuid
from typing import Any

import yaml


class QmlParseError(Exception):
    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.line = line


_HEADER_RE = re.compile(
    r"^##\s+(?P<label>.+?)\s+\[(?P<type>single|multiple|short)\]"
    r"(?:\s+\((?P<points>\d+)\))?"
    r"(?:\s+(?P<attrs>\{.*\}))?\s*$"
)

_OPTION_RE = re.compile(r"^\s*[-*]\s+(?P<key>[A-Z])(?P<correct>\*)?\)\s*(?P<body>.*)$")
_ATTR_KV_RE = re.compile(r"(?P<k>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<v>[^,}]+)")


def _parse_attrs(attrs: str | None) -> dict[str, Any]:
    if not attrs:
        return {}
    if not (attrs.startswith("{") and attrs.endswith("}")):
        return {}
    inner = attrs[1:-1].strip()
    if not inner:
        return {}
    out: dict[str, Any] = {}
    for part in inner.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            m = _ATTR_KV_RE.match(part)
            if not m:
                continue
            k = m.group("k")
            v_raw = m.group("v").strip().strip('"').strip("'")
            if v_raw.lower() in {"true", "false"}:
                out[k] = v_raw.lower() == "true"
            else:
                try:
                    out[k] = int(v_raw)
                except ValueError:
                    out[k] = v_raw
        else:
            out[part] = True
    return out


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise QmlParseError("Front matter started but not closed", line=1)
    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    fm = yaml.safe_load(fm_text) or {}
    if not isinstance(fm, dict):
        raise QmlParseError("Front matter must be a YAML mapping", line=1)
    return fm, body


# 解析mardown试卷
def parse_qml_markdown(markdown_text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    front_matter, body = _split_front_matter(markdown_text)

    exam_id = str(front_matter.get("id") or f"exam-{uuid.uuid4().hex[:8]}")
    exam: dict[str, Any] = {
        "id": exam_id,
        "title": front_matter.get("title", ""),
        "description": front_matter.get("description", ""),
        "format": front_matter.get("format", ""),
        "welcome_image": front_matter.get("welcome_image", ""),
        "end_image": front_matter.get("end_image", ""),
        "llm": front_matter.get("llm", {}) or {},
        "trait": front_matter.get("trait", {}) or {},
        "questions": [],
    }

    public_exam = {
        k: exam[k]
        for k in [
            "id",
            "title",
            "description",
            "format",
            "welcome_image",
            "end_image",
            "trait",
        ]
    }
    public_exam["questions"] = []

    lines = body.splitlines()
    i = 0
    seen_qids: set[str] = set()
    auto_q_counter = 0

    def _bump_counter_from_qid(qid: str) -> None:
        nonlocal auto_q_counter
        m2 = re.match(r"^Q(\d+)$", qid)
        if not m2:
            return
        try:
            n = int(m2.group(1))
        except Exception:
            return
        auto_q_counter = max(auto_q_counter, n)

    def _next_auto_qid() -> str:
        nonlocal auto_q_counter
        while True:
            auto_q_counter += 1
            qid = f"Q{auto_q_counter}"
            if qid not in seen_qids:
                return qid

    def line_no() -> int:
        return i + 1

    while i < len(lines):
        line = lines[i]
        m = _HEADER_RE.match(line.strip())
        if not m:
            i += 1
            continue

        label = m.group("label").strip()
        qid = label
        if not re.fullmatch(r"Q[0-9A-Za-z_-]+", qid):
            qid = _next_auto_qid()
        _bump_counter_from_qid(qid)
        if qid in seen_qids:
            raise QmlParseError(f"Duplicate QID: {qid}", line=line_no())
        seen_qids.add(qid)

        qtype = m.group("type")
        points = int(m.group("points") or 0)
        attrs = _parse_attrs(m.group("attrs"))
        partial = bool(attrs.get("partial", False))
        media = attrs.get("media", "")
        max_points = int(attrs.get("max", points if points else 0) or 0)

        if qtype != "short" and points <= 0:
            raise QmlParseError(
                f"{qid} missing points, expected (N) for {qtype}",
                line=line_no(),
            )
        if qtype == "short" and max_points <= 0:
            raise QmlParseError(
                f"{qid} missing max points, expected {{max=N}}",
                line=line_no(),
            )

        i += 1

        stem_lines: list[str] = []
        options: list[dict[str, Any]] = []
        rubric: str | None = None
        llm_block: str | None = None

        while i < len(lines):
            cur = lines[i]
            if _HEADER_RE.match(cur.strip()):
                break
            if cur.strip().startswith("## "):
                break

            if cur.strip() == "[rubric]":
                i += 1
                rb: list[str] = []
                while i < len(lines) and lines[i].strip() != "[/rubric]":
                    # Allow missing closing tag: end rubric when the next question header starts.
                    if _HEADER_RE.match(lines[i].strip()):
                        break
                    rb.append(lines[i])
                    i += 1
                if i < len(lines) and lines[i].strip() == "[/rubric]":
                    i += 1
                rubric = "\n".join(rb).strip()
                continue

            if cur.strip() == "[llm]":
                i += 1
                lb: list[str] = []
                while i < len(lines) and lines[i].strip() != "[/llm]":
                    if _HEADER_RE.match(lines[i].strip()):
                        break
                    lb.append(lines[i])
                    i += 1
                if i < len(lines) and lines[i].strip() == "[/llm]":
                    i += 1
                llm_block = "\n".join(lb).strip()
                continue

            opt_m = _OPTION_RE.match(cur)
            if opt_m:
                key = opt_m.group("key")
                body_text = opt_m.group("body").strip()
                correct = bool(opt_m.group("correct"))
                traits: dict[str, int] = {}
                opt_points: int | None = None
                if "{" in body_text and body_text.rstrip().endswith("}"):
                    left = body_text.rfind("{")
                    attr_text = body_text[left:]
                    body_text = body_text[:left].rstrip()
                    opt_attrs = _parse_option_attrs(attr_text)
                    traits = opt_attrs.get("traits") or {}
                    if "points" in opt_attrs:
                        opt_points = opt_attrs["points"]
                options.append(
                    {
                        "key": key,
                        "text": body_text,
                        "correct": correct,
                        "points": opt_points,
                        "traits": traits,
                    }
                )
                i += 1
                continue

            stem_lines.append(cur)
            i += 1

        stem_md = "\n".join(stem_lines).strip()

        if qtype in {"single", "multiple"} and not options:
            raise QmlParseError(f"{qid} missing options", line=line_no())
        if qtype in {"single", "multiple"}:
            correct_keys = [o["key"] for o in options if o["correct"]]
            if not correct_keys:
                raise QmlParseError(f"{qid} has no correct option (*)", line=line_no())
            if qtype == "single" and len(correct_keys) != 1:
                raise QmlParseError(
                    f"{qid} single must have exactly 1 correct option",
                    line=line_no(),
                )
        if qtype == "short" and not rubric:
            raise QmlParseError(f"{qid} short missing [rubric] block", line=line_no())

        q_llm = _parse_llm_block(llm_block) if llm_block else None

        q = {
            "qid": qid,
            "label": label,
            "type": qtype,
            "points": points if qtype != "short" else max_points,
            "max_points": max_points if qtype == "short" else points,
            "partial": partial,
            "media": media,
            "stem_md": stem_md,
            "options": options,
            "rubric": rubric,
            "llm": q_llm,
        }
        exam["questions"].append(q)

        public_q = {
            "qid": qid,
            "label": label,
            "type": qtype,
            "points": q["points"],
            "max_points": q["max_points"],
            "partial": partial,
            "media": media,
            "stem_md": stem_md,
            "options": [{"key": o["key"], "text": o["text"]} for o in options],
        }
        public_exam["questions"].append(public_q)

    return exam, public_exam


def _parse_llm_block(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return out
    has_kv = any("=" in l for l in lines)
    if not has_kv:
        out["prompt_template"] = "\n".join(lines).strip()
        return out
    for l in lines:
        if "=" not in l:
            continue
        k, v = l.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _parse_traits(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            out[k.strip()] = int(v.strip())
        except ValueError:
            continue
    return out


def _parse_option_attrs(attrs: str) -> dict[str, Any]:
    if not (attrs.startswith("{") and attrs.endswith("}")):
        return {}
    inner = attrs[1:-1].strip()
    if not inner:
        return {}
    out: dict[str, Any] = {"traits": {}}
    traits: dict[str, int] = {}
    for part in inner.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("traits:"):
            traits.update(_parse_traits(part[len("traits:") :].strip()))
            continue
        if "=" in part:
            m = _ATTR_KV_RE.match(part)
            if not m:
                continue
            k = m.group("k")
            v_raw = m.group("v").strip().strip('"').strip("'")
            if k == "points":
                try:
                    out["points"] = int(v_raw)
                except ValueError:
                    continue
            elif k == "traits":
                traits.update(_parse_traits(v_raw))
            else:
                out[k] = v_raw
    out["traits"] = traits
    return out
