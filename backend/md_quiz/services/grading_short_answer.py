from __future__ import annotations

import json
import re
from typing import Any, Callable

from backend.md_quiz.config import logger
from backend.md_quiz.services.llm_client import (
    call_llm_json as _default_call_llm_json,
    call_llm_text as _default_call_llm_text,
)


def _parse_boolish(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return float(v) != 0.0
    s = str(v).strip().lower()
    if s in {"true", "1", "yes", "y", "是", "对"}:
        return True
    if s in {"false", "0", "no", "n", "否", "不", ""}:
        return False
    return False


def _parse_intish(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"-?\d+", str(v).strip())
    if not m:
        return None
    try:
        return int(m.group(0))
    except Exception:
        return None


def _default_prompt(question: str, rubric: str, answer: str, max_points: int) -> str:
    return (
        "你是一名公正的阅卷老师，只能依据评分标准评分，但要允许部分得分。\n"
        "评分规则：\n"
        f"1) score 为 0..{max_points} 的整数（可取中间分，不要只给 0 或满分）。\n"
        "2) 不要求与标准答案完全一致：允许同义改写、不同表述方式、举例说明；只要与评分要点沾边就可给部分分。\n"
        "3) 若答案为空、纯数字/乱码/随意输入等无意义内容，或与题目/评分标准完全无关：score=0。\n"
        "4) 若答案与评分标准矛盾、把关键事实说反（核心因果/结论颠倒）：score=0。\n"
        "5) 若答案只命中部分要点，请按要点覆盖程度给分；rubric 未细分时请自行拆分为 3-5 个要点再评。\n"
        "6) reason 用 1-3 句说明得分点/失分点，不要泄露标准答案原文。\n"
        "输出格式：只输出 JSON，必须包含字段：score、reason、relevance、contradiction。\n"
        f"- score: 0..{max_points} 的整数\n"
        "- relevance: 0..3（0=完全无关/无意义；1=略相关；2=相关且部分正确；3=高度相关且基本正确）\n"
        "- contradiction: true/false（true=关键事实与评分标准矛盾/说反，必须 score=0）\n"
        f"示例：{{\"score\":3,\"reason\":\"...\",\"relevance\":2,\"contradiction\":false}}。\n"
        f"【题目】{question}\n"
        f"【评分标准】{rubric}\n"
        f"【考生回答】{answer}\n"
    )


def _short_grading_prefix(max_points: int) -> str:
    return (
        "评分补充要求：\n"
        f"- 必须使用 0..{max_points} 的整数分，允许部分得分（可取中间分）。\n"
        "- 若答案为空、纯数字/乱码/随意输入等无意义内容、与题目或评分标准完全无关：给 0 分。\n"
        "- 若答案与评分标准矛盾、把关键事实说反（核心因果/结论颠倒）：给 0 分。\n"
        "- 只要与评分要点沾边一点，就允许给部分分（1..满分任意整数），不要求逐字一致。\n"
        "- 若 rubric 未给出分点，请自行拆分要点并按覆盖程度给分。\n"
        "- 只依据考生回答作答，不要推测其“可能想表达什么”。\n"
        f"- 只输出 JSON，必须包含：score、reason、relevance、contradiction。\n"
    )


def _short_batch_grading_prefix() -> str:
    return (
        "评分补充要求：\n"
        "- 对每道题分别给出结果，不要遗漏题目。\n"
        "- 每道题的 score 都必须落在该题自己的 0..max_points 范围内，允许部分得分。\n"
        "- 若答案为空、纯数字/乱码/随意输入等无意义内容、与题目或评分标准完全无关：该题给 0 分。\n"
        "- 若答案与评分标准矛盾、把关键事实说反（核心因果/结论颠倒）：该题给 0 分。\n"
        "- 只要与评分要点沾边一点，就允许给部分分（1..满分任意整数），不要求逐字一致。\n"
        "- 若 rubric 未给出分点，请自行拆分要点并按覆盖程度给分。\n"
        "- 只依据考生回答作答，不要推测其“可能想表达什么”。\n"
        '- 只输出一个 JSON 对象，格式为 {"results":[...]}。\n'
    )


def _is_blank_short_answer(answer: Any) -> bool:
    s = "" if answer is None else str(answer)
    s = s.strip()
    if not s:
        return True
    s2 = re.sub(r"\s+", "", s).lower()
    if s2 in {"无", "暂无", "没有", "不知道", "不清楚", "不会", "不会做", "不懂", "n/a", "na", "null"}:
        return True
    if re.fullmatch(r"\d+", s2):
        return True
    return re.search(r"[A-Za-z0-9\u4e00-\u9fff]", s2) is None


def _normalize_short_answer(answer: Any) -> str:
    text = "" if answer is None else str(answer)
    return text.replace("\r\n", "\n").strip()


def _short_prompt_template(q: dict[str, Any], exam_llm: dict[str, Any]) -> str:
    q_llm = q.get("llm") or {}
    return (
        q_llm.get("prompt_template") or exam_llm.get("prompt_template") or ""
    ).strip()


def _extract_json_like_payload(raw: Any) -> Any:
    if raw is None:
        raise ValueError("empty llm response")
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw).strip()
    if not text:
        raise ValueError("empty llm response")
    if not ((text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))):
        first_obj = text.find("{")
        last_obj = text.rfind("}")
        first_arr = text.find("[")
        last_arr = text.rfind("]")
        candidates: list[tuple[int, int]] = []
        if first_obj != -1 and last_obj > first_obj:
            candidates.append((first_obj, last_obj))
        if first_arr != -1 and last_arr > first_arr:
            candidates.append((first_arr, last_arr))
        if candidates:
            start, end = min(candidates, key=lambda item: item[0])
            text = text[start : end + 1]
    return json.loads(text)


def _coerce_short_grade_payload(raw: Any, *, max_points: int) -> tuple[int, str, int | None, bool]:
    obj = _extract_json_like_payload(raw)
    if not isinstance(obj, dict):
        raise ValueError("short grading payload must be an object")
    raw_score = obj.get("score", 0)
    if isinstance(raw_score, (int, float)):
        score = int(round(float(raw_score)))
    else:
        m = re.search(r"-?\d+(?:\.\d+)?", str(raw_score))
        score = int(round(float(m.group(0)))) if m else 0
    contradiction = _parse_boolish(obj.get("contradiction", False))
    relevance = _parse_intish(obj.get("relevance", None))
    if relevance is not None:
        relevance = max(0, min(3, int(relevance)))
    reason = str(obj.get("reason", "")).strip() or "模型未返回原因"
    score = max(0, min(max_points, score))
    return score, reason, relevance, contradiction


def _grade_short_reason(
    *,
    question: str,
    rubric: str,
    answer: str,
    score: int,
    max_points: int,
    llm_text: Callable[..., str] | None = None,
) -> str:
    prompt = (
        "你是严格的阅卷老师。请根据评分标准解释该答案的得分依据。\n"
        "要求：\n"
        "1) 输出纯文本，不要 JSON，不要 Markdown。\n"
        "2) 1-2 句话，<= 100 字。\n"
        "3) 只描述得分点/失分点，不要泄露标准答案原文。\n"
        f"【题目】{question}\n"
        f"【评分标准】{rubric}\n"
        f"【考生回答】{answer}\n"
        f"【得分】{score}/{max_points}\n"
    )
    call_text = llm_text or _default_call_llm_text
    text = (call_text(prompt) or "").strip()
    if not text:
        return "模型未返回原因"
    if len(text) > 160:
        text = text[:160].rstrip()
    return text


def _finalize_short_grade(
    *,
    question: str,
    rubric: str,
    answer: str,
    score: int,
    reason: str,
    relevance: int | None,
    contradiction: bool,
    max_points: int,
    llm_text: Callable[..., str] | None = None,
) -> tuple[int, str]:
    forced_reason = None
    if contradiction:
        forced_reason = "检测到与评分标准关键事实矛盾/说反，按规则记 0 分"
    elif relevance == 0:
        forced_reason = "答案与题目/评分标准完全无关，按规则记 0 分"
    if forced_reason:
        score = 0
        if not reason:
            reason = forced_reason
        elif "0" not in reason:
            reason = f"{reason}（{forced_reason}）"
    if (not reason or reason in {"模型未返回原因", "模型仅返回分数"}) and rubric:
        reason = _grade_short_reason(
            question=question,
            rubric=rubric,
            answer=answer,
            score=score,
            max_points=max_points,
            llm_text=llm_text,
        )
    return score, reason


def _default_batch_prompt(batch_items: list[dict[str, Any]]) -> str:
    parts = [
        "请一次性判改多道简答题。",
        "输出格式：只输出一个 JSON 对象，不要输出额外文本。",
        'JSON 格式：{"results":[{"qid":"Q1","score":3,"reason":"...","relevance":2,"contradiction":false}]}',
        "要求：",
        "- results 必须覆盖输入中的每一道题，且 qid 必须原样返回。",
        "- score 必须是对应题目允许范围内的整数，可给部分分。",
        "- relevance 含义：0=完全无关/无意义；1=略相关；2=相关且部分正确；3=高度相关且基本正确。",
        "- contradiction=true 表示关键事实与评分标准矛盾/说反，此时该题必须记 0 分。",
        "",
        "【待判简答题】",
    ]
    for item in batch_items:
        q = item["question"]
        parts.extend(
            [
                f"### {item['qid']}",
                f"max_points={int(item['max_points'] or 0)}",
                f"题目：{str(q.get('stem_md') or '').strip()}",
                f"评分标准：{str(q.get('rubric') or '').strip()}",
                f"考生回答：{str(item.get('answer') or '').strip()}",
                "",
            ]
        )
    return "\n".join(parts).strip() + "\n"


def _chunk_short_batch_candidates(
    items: list[dict[str, Any]],
    *,
    batch_size: int = 5,
) -> list[list[dict[str, Any]]]:
    if len(items) <= batch_size:
        return [items]
    return [items[idx : idx + batch_size] for idx in range(0, len(items), batch_size)]


def _parse_short_batch_results(raw: Any) -> dict[str, dict[str, Any]]:
    payload = _extract_json_like_payload(raw)
    items: list[Any]
    if isinstance(payload, dict):
        raw_items = payload.get("results")
        if not isinstance(raw_items, list):
            raise ValueError("batch grading payload missing results array")
        items = raw_items
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValueError("batch grading payload must be object or array")

    parsed: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("qid") or "").strip()
        if not qid:
            continue
        parsed[qid] = item
    if not parsed:
        raise ValueError("batch grading payload contains no results")
    return parsed


def _grade_short_batch(
    batch_items: list[dict[str, Any]],
    *,
    llm_json: Callable[..., str] | None = None,
    llm_text: Callable[..., str] | None = None,
) -> list[dict[str, Any]]:
    prompt = _short_batch_grading_prefix() + "\n" + _default_batch_prompt(batch_items)
    call_json = llm_json or _default_call_llm_json
    raw = call_json(prompt)
    parsed = _parse_short_batch_results(raw)
    results: list[dict[str, Any]] = []
    for item in batch_items:
        qid = str(item["qid"])
        q = item["question"]
        max_points = int(item["max_points"] or 0)
        payload = parsed.get(qid)
        if payload is None:
            raise ValueError(f"batch grading payload missing qid={qid}")
        score, reason, relevance, contradiction = _coerce_short_grade_payload(
            payload,
            max_points=max_points,
        )
        score, reason = _finalize_short_grade(
            question=str(q.get("stem_md") or ""),
            rubric=str(q.get("rubric") or ""),
            answer=str(item.get("answer") or ""),
            score=score,
            reason=reason,
            relevance=relevance,
            contradiction=contradiction,
            max_points=max_points,
            llm_text=llm_text,
        )
        results.append(
            {"qid": qid, "score": score, "max": max_points, "reason": reason}
        )
    return results


def _grade_short_batches(
    batch_candidates: list[dict[str, Any]],
    *,
    llm_json: Callable[..., str] | None = None,
    llm_text: Callable[..., str] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for batch_items in _chunk_short_batch_candidates(batch_candidates, batch_size=5):
        try:
            results.extend(_grade_short_batch(batch_items, llm_json=llm_json, llm_text=llm_text))
        except Exception as e:
            logger.warning("Batch short grading failed, fallback to per-question grading: %s", e)
            for item in batch_items:
                scored, reason = _grade_short(
                    item["question"],
                    item["answer"],
                    {},
                    llm_json=llm_json,
                    llm_text=llm_text,
                )
                results.append(
                    {
                        "qid": str(item["qid"]),
                        "score": scored,
                        "max": int(item["max_points"] or 0),
                        "reason": reason,
                    }
                )
    return results


def _grade_short(
    q: dict[str, Any],
    answer: str,
    exam_llm: dict[str, Any],
    *,
    llm_json: Callable[..., str] | None = None,
    llm_text: Callable[..., str] | None = None,
) -> tuple[int, str]:
    max_points = int(q.get("max_points") or q.get("points") or 0)
    answer = _normalize_short_answer(answer)
    if _is_blank_short_answer(answer):
        return 0, "未作答、无意义内容或与题目无关，得 0 分"
    rubric = q.get("rubric") or ""
    question = q.get("stem_md") or ""
    prompt_template = _short_prompt_template(q, exam_llm)
    if prompt_template:
        prompt = (
            prompt_template.replace("{{max_points}}", str(max_points))
            .replace("{max_points}", str(max_points))
            .replace("{{question}}", question)
            .replace("{question}", question)
            .replace("{{rubric}}", rubric)
            .replace("{rubric}", rubric)
            .replace("{{answer}}", answer)
            .replace("{answer}", answer)
        )
    else:
        prompt = _default_prompt(question, rubric, answer, max_points)

    prompt = _short_grading_prefix(max_points) + "\n" + prompt

    call_json = llm_json or _default_call_llm_json
    raw = call_json(prompt)
    if not raw:
        return 0, "LLM 调用失败"
    try:
        score, reason, relevance, contradiction = _coerce_short_grade_payload(
            raw,
            max_points=max_points,
        )
    except Exception:
        try:
            m = re.search(r"-?\d+(?:\.\d+)?", str(raw).strip())
            score = int(round(float(m.group(0)))) if m else 0
            contradiction = False
            relevance = None
            reason = ""
        except Exception:
            logger.warning("LLM output parse failed: %r", raw)
            return 0, "模型返回无法解析"
    score, reason = _finalize_short_grade(
        question=question,
        rubric=rubric,
        answer=answer,
        score=score,
        reason=reason,
        relevance=relevance,
        contradiction=contradiction,
        max_points=max_points,
        llm_text=llm_text,
    )
    return score, reason


__all__ = [
    "_coerce_short_grade_payload",
    "_extract_json_like_payload",
    "_finalize_short_grade",
    "_grade_short",
    "_grade_short_batches",
    "_is_blank_short_answer",
    "_normalize_short_answer",
    "_parse_short_batch_results",
    "_short_prompt_template",
]
