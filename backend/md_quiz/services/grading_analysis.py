from __future__ import annotations

import re
from typing import Any, Callable

from backend.md_quiz.services.grading_traits import (
    _build_traits_summary_lines,
    _traits_compact_summary,
)
from backend.md_quiz.services.llm_client import call_llm_text as _default_call_llm_text


def _build_scored_summary_lines(spec: dict[str, Any], assignment: dict[str, Any], scored_result: dict[str, Any]) -> list[str]:
    answers = assignment.get("answers") or {}
    questions = spec.get("questions") or []
    scored_by_qid: dict[str, dict[str, Any]] = {}
    for item in (scored_result.get("objective") or []):
        scored_by_qid[str(item.get("qid") or "")] = item
    for item in (scored_result.get("subjective") or []):
        scored_by_qid[str(item.get("qid") or "")] = item

    lines: list[str] = []
    for question in questions[:80]:
        qid = str(question.get("qid") or "").strip()
        if not qid or qid not in scored_by_qid:
            continue
        detail = scored_by_qid[qid]
        qtype = str(question.get("type") or "").strip()
        stem = str(question.get("stem_md") or "").strip().replace("\n", " ")
        stem = stem[:120]
        score = int(detail.get("score") or 0)
        max_points = int(detail.get("max") or question.get("max_points") or question.get("points") or 0)
        answer = answers.get(qid)
        if isinstance(answer, list):
            answer_text = ",".join(str(item) for item in answer)
        else:
            answer_text = "" if answer is None else str(answer)
        answer_text = answer_text.strip().replace("\n", " ")
        answer_text = answer_text[:120]
        line = f"- {qid}（{qtype}）：{score}/{max_points}；题目={stem}"
        if answer_text:
            line += f"；作答={answer_text}"
        reason = str(detail.get("reason") or "").strip().replace("\n", " ")
        if reason:
            line += f"；判分依据={reason[:160]}"
        lines.append(line)
    return lines


def _fallback_final_analysis(
    *,
    scored_result: dict[str, Any],
    trait_result: dict[str, Any],
    result_mode: str,
) -> str:
    parts: list[str] = []
    total = int(scored_result.get("total") or 0)
    total_max = int(scored_result.get("total_max") or 0)
    if result_mode in {"scored", "mixed"} and total_max > 0:
        parts.append(f"本次测验的可计分题得分为 {total}/{total_max}。")
    if result_mode in {"traits", "mixed"}:
        compact = _traits_compact_summary(trait_result)
        if compact:
            parts.append(f"traits 结果显示：{compact}。")
    return "\n".join(parts).strip()


def _generate_final_analysis(
    *,
    spec: dict[str, Any],
    assignment: dict[str, Any],
    scored_result: dict[str, Any],
    trait_result: dict[str, Any],
    result_mode: str,
    llm_text: Callable[..., str] | None = None,
) -> str:
    scored_lines = _build_scored_summary_lines(spec, assignment, scored_result)
    trait_lines = _build_traits_summary_lines(trait_result)
    if not scored_lines and not trait_lines:
        return ""

    total = int(scored_result.get("total") or 0)
    total_max = int(scored_result.get("total_max") or 0)
    if result_mode == "scored":
        task_hint = "请只分析可计分题表现，输出总体表现、主要优势、主要短板和建议。"
    elif result_mode == "traits":
        task_hint = "请只解释 traits 量表结果，输出主倾向、差值强弱、行为风格特点和建议。"
    else:
        task_hint = "请输出一份综合分析，先解释可计分题表现，再解释 traits 倾向，最后给出建议。"

    prompt_parts = [
        "你是一名资深测评分析师，请根据测验结果生成一份综合分析。",
        "要求：",
        "1) 输出纯文本，不要 Markdown，不要 JSON。",
        "2) 220-420 字。",
        "3) 不要输出招聘结论、通过/淘汰判断或下一轮建议。",
        "4) 不要编造不存在的分数或 traits 维度。",
        task_hint,
        f"【测验】{spec.get('title', '')}",
    ]
    if total_max > 0:
        prompt_parts.append(f"【可计分题得分】{total}/{total_max}")
    if scored_lines:
        prompt_parts.append("【可计分题摘要】")
        prompt_parts.extend(scored_lines)
    if trait_lines:
        prompt_parts.append("【Traits 摘要】")
        prompt_parts.extend(trait_lines)
    prompt = "\n".join(prompt_parts) + "\n"
    call_text = llm_text or _default_call_llm_text
    text = (call_text(prompt) or "").strip()
    if not text:
        return _fallback_final_analysis(
            scored_result=scored_result,
            trait_result=trait_result,
            result_mode=result_mode,
        )
    if len(text) > 1600:
        text = text[:1600].rstrip()
    return text


def generate_candidate_remark(
    spec: dict[str, Any],
    assignment: dict[str, Any],
    grading: dict[str, Any],
) -> str:
    _ = spec
    _ = assignment
    result_mode = str(grading.get("result_mode") or "").strip().lower()
    final_analysis = str(grading.get("final_analysis") or grading.get("analysis") or "").strip()
    if final_analysis:
        sentences = [part.strip() for part in re.split(r"[。！？\n]+", final_analysis) if part.strip()]
        if sentences:
            remark = "。".join(sentences[:2]).strip()
            if remark and not remark.endswith(("。", "！", "？")):
                remark += "。"
            return remark[:160].rstrip()

    if result_mode in {"scored", "mixed"}:
        total = int(grading.get("total") or 0)
        total_max = int(grading.get("total_max") or grading.get("raw_total") or 0)
        if total_max > 0:
            return f"本次测验可计分题得分 {total}/{total_max}。"

    if result_mode in {"traits", "mixed"}:
        compact = _traits_compact_summary(grading.get("traits") or grading.get("trait_result") or {})
        if compact:
            return f"本次量表结果显示：{compact}。"

    return str(grading.get("overall_reason") or "").strip()


__all__ = [
    "_fallback_final_analysis",
    "_generate_final_analysis",
    "generate_candidate_remark",
]
