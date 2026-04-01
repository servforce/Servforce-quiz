"""
    qml.parser 是 markdown 解析，把试卷转变成结构化json
"""
from __future__ import annotations

import re
import uuid
from typing import Any

import yaml

from backend.md_quiz.services.quiz_metadata import (
    coerce_optional_int,
    normalize_question_counts,
    normalize_quiz_tags,
)


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
_DURATION_RE = re.compile(r"^(?P<num>\d+)\s*(?P<unit>s|m|h)?$", re.IGNORECASE)
_STANDALONE_MD_IMAGE_RE = re.compile(r"^\s*!\[[^\]]*]\((?P<path>[^)]+)\)\s*$")


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


def _parse_answer_time_seconds(raw: Any, *, qid: str, line: int) -> int | None:
    if raw in {None, ""}:
        return None

    seconds: int
    if isinstance(raw, bool):
        raise QmlParseError(f"{qid} invalid answer_time, expected 1s..1h", line=line)

    if isinstance(raw, int):
        seconds = raw
    else:
        text = str(raw).strip().lower()
        m = _DURATION_RE.fullmatch(text)
        if not m:
            raise QmlParseError(
                f"{qid} invalid answer_time, expected integer seconds or suffix s/m/h",
                line=line,
            )
        num = int(m.group("num"))
        unit = (m.group("unit") or "s").lower()
        factor = {"s": 1, "m": 60, "h": 3600}[unit]
        seconds = num * factor

    if seconds < 1 or seconds > 3600:
        raise QmlParseError(f"{qid} answer_time out of range, expected 1..3600 seconds", line=line)
    return seconds


def _extract_edge_image(lines: list[str]) -> str:
    non_empty = [line.strip() for line in lines if line.strip()]
    if len(non_empty) != 1:
        return ""
    match = _STANDALONE_MD_IMAGE_RE.fullmatch(non_empty[0])
    if not match:
        return ""
    return str(match.group("path") or "").strip()


# 解析mardown试卷
def parse_qml_markdown(markdown_text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    front_matter, body = _split_front_matter(markdown_text)
    try:
        tags = normalize_quiz_tags(front_matter.get("tags"), strict=True)
        schema_version = coerce_optional_int(
            front_matter.get("schema_version"),
            strict=True,
            field="schema_version",
        )
        question_count = coerce_optional_int(
            front_matter.get("question_count"),
            strict=True,
            field="question_count",
        )
        question_counts = normalize_question_counts(front_matter.get("question_counts"), strict=True)
        estimated_duration_minutes = coerce_optional_int(
            front_matter.get("estimated_duration_minutes"),
            strict=True,
            field="estimated_duration_minutes",
        )
    except ValueError as exc:
        raise QmlParseError(str(exc), line=1) from exc

    exam_id = str(front_matter.get("id") or f"exam-{uuid.uuid4().hex[:8]}")
    exam: dict[str, Any] = {
        "id": exam_id,
        "title": front_matter.get("title", ""),
        "description": front_matter.get("description", ""),
        "tags": tags,
        "schema_version": schema_version,
        "format": front_matter.get("format", ""),
        "question_count": question_count,
        "question_counts": question_counts,
        "estimated_duration_minutes": estimated_duration_minutes,
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
            "tags",
            "schema_version",
            "format",
            "question_count",
            "question_counts",
            "estimated_duration_minutes",
            "welcome_image",
            "end_image",
            "trait",
        ]
    }
    public_exam["questions"] = []

    lines = body.splitlines()
    parse_end = len(lines)
    j = len(lines) - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j >= 0:
        end_image = _extract_edge_image([lines[j]])
        if end_image:
            exam["end_image"] = end_image
            public_exam["end_image"] = end_image
            parse_end = j

    header_indices = [idx for idx, line in enumerate(lines[:parse_end]) if _HEADER_RE.match(line.strip())]
    if not header_indices:
        return exam, public_exam

    welcome_image = _extract_edge_image(lines[: header_indices[0]])
    if welcome_image:
        exam["welcome_image"] = welcome_image
        public_exam["welcome_image"] = welcome_image

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

    def line_no(idx: int) -> int:
        return idx + 1

    def _parse_question_segment(start_idx: int, end_idx: int) -> tuple[dict[str, Any], dict[str, Any]]:
        i = start_idx
        line = lines[i]
        m = _HEADER_RE.match(line.strip())

        label = m.group("label").strip()
        qid = label
        if not re.fullmatch(r"Q[0-9A-Za-z_-]+", qid):
            qid = _next_auto_qid()
        _bump_counter_from_qid(qid)
        if qid in seen_qids:
            raise QmlParseError(f"Duplicate QID: {qid}", line=line_no(i))
        seen_qids.add(qid)

        qtype = m.group("type")
        points = int(m.group("points") or 0)
        attrs = _parse_attrs(m.group("attrs"))
        partial = bool(attrs.get("partial", False))
        media = attrs.get("media", "")
        max_points = int(attrs.get("max", points if points else 0) or 0)
        answer_time_seconds = _parse_answer_time_seconds(
            attrs.get("answer_time"),
            qid=qid,
            line=line_no(i),
        )

        if qtype != "short" and points <= 0:
            raise QmlParseError(
                f"{qid} missing points, expected (N) for {qtype}",
                line=line_no(i),
            )
        if qtype == "short" and max_points <= 0:
            raise QmlParseError(
                f"{qid} missing max points, expected {{max=N}}",
                line=line_no(i),
            )

        i += 1

        stem_lines: list[str] = []
        options: list[dict[str, Any]] = []
        rubric: str | None = None
        llm_block: str | None = None

        while i < end_idx:
            cur = lines[i]

            if cur.strip() == "[rubric]":
                i += 1
                rb: list[str] = []
                while i < end_idx and lines[i].strip() != "[/rubric]":
                    # Allow missing closing tag: end rubric when the next question header starts.
                    if _HEADER_RE.match(lines[i].strip()):
                        break
                    rb.append(lines[i])
                    i += 1
                if i < end_idx and lines[i].strip() == "[/rubric]":
                    i += 1
                rubric = "\n".join(rb).strip()
                continue

            if cur.strip() == "[llm]":
                i += 1
                lb: list[str] = []
                while i < end_idx and lines[i].strip() != "[/llm]":
                    if _HEADER_RE.match(lines[i].strip()):
                        break
                    lb.append(lines[i])
                    i += 1
                if i < end_idx and lines[i].strip() == "[/llm]":
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
            raise QmlParseError(f"{qid} missing options", line=line_no(i))
        if qtype in {"single", "multiple"}:
            correct_keys = [o["key"] for o in options if o["correct"]]
            if not correct_keys:
                raise QmlParseError(f"{qid} has no correct option (*)", line=line_no(i))
            if qtype == "single" and len(correct_keys) != 1:
                raise QmlParseError(
                    f"{qid} single must have exactly 1 correct option",
                    line=line_no(i),
                )
        if qtype == "short" and not rubric:
            raise QmlParseError(f"{qid} short missing [rubric] block", line=line_no(i))

        q_llm = _parse_llm_block(llm_block) if llm_block else None

        q = {
            "qid": qid,
            "label": label,
            "type": qtype,
            "points": points if qtype != "short" else max_points,
            "max_points": max_points if qtype == "short" else points,
            "partial": partial,
            "media": media,
            "answer_time_seconds": int(answer_time_seconds or 0),
            "stem_md": stem_md,
            "options": options,
            "rubric": rubric,
            "llm": q_llm,
        }

        public_q = {
            "qid": qid,
            "label": label,
            "type": qtype,
            "points": q["points"],
            "max_points": q["max_points"],
            "partial": partial,
            "media": media,
            "answer_time_seconds": int(answer_time_seconds or 0),
            "stem_md": stem_md,
            "options": [{"key": o["key"], "text": o["text"]} for o in options],
        }
        return q, public_q

    for pos, start_idx in enumerate(header_indices):
        end_idx = header_indices[pos + 1] if pos + 1 < len(header_indices) else parse_end
        q, public_q = _parse_question_segment(start_idx, end_idx)
        exam["questions"].append(q)
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
