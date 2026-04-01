from __future__ import annotations

import copy
from typing import Any

QUIZ_SCHEMA_VERSION = 2
QUIZ_FORMAT = "qml-v2"
QUIZ_QUESTION_TYPES = ("single", "multiple", "short")


def coerce_optional_int(raw: Any, *, strict: bool = False, field: str = "value") -> int | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        if strict:
            raise ValueError(f"{field} 必须是整数")
        return None
    if isinstance(raw, int):
        return raw
    try:
        return int(str(raw).strip())
    except Exception:
        if strict:
            raise ValueError(f"{field} 必须是整数")
        return None


def normalize_quiz_tags(raw: Any, *, strict: bool = False) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = list(raw)
    else:
        if strict:
            raise ValueError("tags 必须是字符串或字符串列表")
        return []

    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, str):
            if strict:
                raise ValueError("tags 只能包含字符串")
            continue
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def normalize_question_counts(raw: Any, *, strict: bool = False) -> dict[str, int]:
    if raw is None or raw == "":
        return {}
    if not isinstance(raw, dict):
        if strict:
            raise ValueError("question_counts 必须是 mapping")
        return {}
    out: dict[str, int] = {}
    for key in QUIZ_QUESTION_TYPES:
        if key not in raw:
            continue
        value = coerce_optional_int(raw.get(key), strict=strict, field=f"question_counts.{key}")
        if value is None:
            continue
        if value < 0:
            if strict:
                raise ValueError(f"question_counts.{key} 不能小于 0")
            continue
        out[key] = int(value)
    return out


def compute_question_counts(questions: list[Any]) -> dict[str, int]:
    counts = {key: 0 for key in QUIZ_QUESTION_TYPES}
    for item in questions or []:
        if not isinstance(item, dict):
            continue
        qtype = str(item.get("type") or "").strip().lower()
        if qtype in counts:
            counts[qtype] += 1
    return counts


def estimate_duration_minutes(question_counts: dict[str, int]) -> int:
    return (
        int(question_counts.get("single", 0)) * 2
        + int(question_counts.get("multiple", 0)) * 3
        + int(question_counts.get("short", 0)) * 10
    )


def compute_answer_time_total_seconds(questions: list[Any]) -> int:
    total_seconds = 0
    for item in questions or []:
        if not isinstance(item, dict):
            continue
        try:
            seconds = int(item.get("answer_time_seconds") or 0)
        except Exception:
            seconds = 0
        if seconds > 0:
            total_seconds += seconds
    return int(total_seconds)


def build_quiz_metadata(spec: dict[str, Any], *, default_schema_version: int | None = None) -> dict[str, Any]:
    doc = spec if isinstance(spec, dict) else {}
    format_value = str(doc.get("format") or "").strip()
    schema_version = coerce_optional_int(doc.get("schema_version"), field="schema_version")
    if schema_version is None:
        if default_schema_version is not None:
            schema_version = int(default_schema_version)
        elif format_value == QUIZ_FORMAT:
            schema_version = QUIZ_SCHEMA_VERSION

    question_counts = compute_question_counts(list(doc.get("questions") or []))
    question_count = sum(question_counts.values())
    answer_time_total_seconds = compute_answer_time_total_seconds(list(doc.get("questions") or []))
    if answer_time_total_seconds > 0:
        estimated_duration_minutes = (answer_time_total_seconds + 59) // 60
    else:
        estimated_duration_minutes = estimate_duration_minutes(question_counts)
    trait = doc.get("trait") if isinstance(doc.get("trait"), dict) else {}

    return {
        "tags": normalize_quiz_tags(doc.get("tags")),
        "schema_version": schema_version,
        "format": format_value,
        "question_count": int(question_count),
        "question_counts": question_counts,
        "estimated_duration_minutes": int(estimated_duration_minutes),
        "trait": dict(trait),
    }


def apply_quiz_metadata(spec: dict[str, Any], *, default_schema_version: int | None = None) -> dict[str, Any]:
    out = copy.deepcopy(spec or {})
    metadata = build_quiz_metadata(out, default_schema_version=default_schema_version)
    out["tags"] = metadata["tags"]
    if metadata["schema_version"] is not None:
        out["schema_version"] = metadata["schema_version"]
    out["question_count"] = metadata["question_count"]
    out["question_counts"] = metadata["question_counts"]
    out["estimated_duration_minutes"] = metadata["estimated_duration_minutes"]
    out["trait"] = metadata["trait"]
    return out
