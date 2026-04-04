from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from backend.md_quiz.config import logger
from backend.md_quiz.services.llm_client import call_llm_json, call_llm_text


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


def grade_attempt(spec: dict[str, Any], assignment: dict[str, Any]) -> dict[str, Any]:
    answers = assignment.get("answers") or {}
    objective_details = []
    subjective_details = []
    subjective_details_by_qid: dict[str, dict[str, Any]] = {}
    trait_questions = []
    short_batch_candidates: list[dict[str, Any]] = []

    raw_total = 0
    raw_scored = 0
    exam_llm = spec.get("llm") or {}

    for q in spec.get("questions", []):
        qid = q["qid"]
        qtype = q["type"]

        if _is_traits_question(q):
            trait_questions.append(q)
            continue

        max_points = int(q.get("max_points") or q.get("points") or 0)
        raw_total += max_points

        if qtype in {"single", "multiple"}:
            scored = _grade_objective(q, answers.get(qid))
            raw_scored += scored
            objective_details.append({"qid": qid, "score": scored, "max": max_points})
            continue

        if qtype == "short":
            normalized_answer = _normalize_short_answer(answers.get(qid, ""))
            if _is_blank_short_answer(normalized_answer):
                subjective_details_by_qid[qid] = {
                    "qid": qid,
                    "score": 0,
                    "max": max_points,
                    "reason": "未作答、无意义内容或与题目无关，得 0 分",
                }
                continue
            if _short_prompt_template(q, exam_llm):
                scored, reason = _grade_short(q, normalized_answer, exam_llm)
                subjective_details_by_qid[qid] = {
                    "qid": qid,
                    "score": scored,
                    "max": max_points,
                    "reason": reason,
                }
                raw_scored += scored
                continue
            short_batch_candidates.append(
                {
                    "qid": qid,
                    "question": q,
                    "answer": normalized_answer,
                    "max_points": max_points,
                }
            )
            continue

    if len(short_batch_candidates) == 1:
        item = short_batch_candidates[0]
        scored, reason = _grade_short(item["question"], item["answer"], exam_llm)
        subjective_details_by_qid[item["qid"]] = {
            "qid": item["qid"],
            "score": scored,
            "max": int(item["max_points"] or 0),
            "reason": reason,
        }
        raw_scored += scored
    elif short_batch_candidates:
        for result in _grade_short_batches(short_batch_candidates):
            subjective_details_by_qid[str(result.get("qid") or "")] = result
            raw_scored += int(result.get("score") or 0)

    for q in spec.get("questions", []):
        qid = str(q.get("qid") or "")
        if qid and qid in subjective_details_by_qid:
            subjective_details.append(subjective_details_by_qid[qid])

    scored_result = {
        "objective": objective_details,
        "subjective": subjective_details,
        "total": int(raw_scored),
        "total_max": int(raw_total),
    }
    trait_result = _aggregate_traits(spec, assignment, trait_questions)

    scored_present = raw_total > 0
    traits_present = int(trait_result.get("question_count") or 0) > 0
    if scored_present and traits_present:
        result_mode = "mixed"
    elif scored_present:
        result_mode = "scored"
    else:
        result_mode = "traits"

    total = int(raw_scored if scored_present else 0)
    total_max = int(raw_total if scored_present else 0)
    overall_reason = f"score={total}/{total_max}" if scored_present else ""

    try:
        final_analysis = _generate_final_analysis(
            spec=spec,
            assignment=assignment,
            scored_result=scored_result,
            trait_result=trait_result,
            result_mode=result_mode,
        )
    except Exception as e:
        logger.warning("Grading final analysis failed: %s", e)
        final_analysis = _fallback_final_analysis(
            scored_result=scored_result,
            trait_result=trait_result,
            result_mode=result_mode,
        )

    out = {
        "objective": objective_details,
        "subjective": subjective_details,
        "scored_result": scored_result,
        "trait_result": trait_result,
        "traits": trait_result,
        "result_mode": result_mode,
        "raw_total": raw_total,
        "raw_scored": raw_scored,
        "total": total,
        "total_max": total_max,
        "overall_reason": overall_reason,
        "final_analysis": final_analysis,
        "analysis": final_analysis,
        "graded_at": datetime.now(timezone.utc).isoformat(),
    }
    return out


def _is_traits_question(q: dict[str, Any]) -> bool:
    if str(q.get("type") or "").strip() != "single":
        return False
    options = q.get("options") or []
    return any(isinstance((option or {}).get("traits"), dict) and (option or {}).get("traits") for option in options)


def _normalize_dimension_name(value: Any) -> str:
    return str(value or "").strip()


def _parse_guidance_pair_entry(item: Any) -> dict[str, str] | None:
    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        pair_text = re.split(r"[：:]", text, maxsplit=1)[0].strip()
        if "/" not in pair_text:
            return None
        left, right = [part.strip() for part in pair_text.split("/", 1)]
        if not left or not right:
            return None
        description = text[len(pair_text) :].lstrip("：:").strip()
        return {"left": left, "right": right, "description": description}
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        left = _normalize_dimension_name(item[0])
        right = _normalize_dimension_name(item[1])
        if left and right:
            return {"left": left, "right": right, "description": ""}
    if isinstance(item, dict):
        pair = item.get("pair") if isinstance(item.get("pair"), (list, tuple)) else None
        left = _normalize_dimension_name(item.get("left") or (pair[0] if pair and len(pair) >= 1 else ""))
        right = _normalize_dimension_name(item.get("right") or (pair[1] if pair and len(pair) >= 2 else ""))
        if not left or not right:
            return None
        default_winner = _normalize_dimension_name(
            item.get("default")
            or item.get("default_winner")
            or item.get("fallback")
        )
        description = str(item.get("description") or item.get("meaning") or "").strip()
        out = {"left": left, "right": right, "description": description}
        if default_winner:
            out["default_winner"] = default_winner
        return out
    return None


def _parse_default_winners_from_guidance(scoring_method: Any) -> list[str]:
    lines: list[str] = []
    if isinstance(scoring_method, str):
        lines = [scoring_method]
    elif isinstance(scoring_method, list):
        lines = [str(item or "").strip() for item in scoring_method if str(item or "").strip()]

    for line in lines:
        match = re.search(r"固定落位\s*([A-Za-z0-9_/、,，\s-]+)", line)
        if not match:
            continue
        raw = match.group(1).strip().rstrip("。；;，, ")
        tokens = [part.strip() for part in re.split(r"[、/,，\s]+", raw) if part.strip()]
        if tokens:
            return tokens
    return []


def _default_trait_pairs(dimensions: list[str]) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    cleaned = [dim for dim in dimensions if dim]
    for idx in range(0, len(cleaned), 2):
        if idx + 1 >= len(cleaned):
            break
        pairs.append(
            {
                "left": cleaned[idx],
                "right": cleaned[idx + 1],
                "description": "",
                "default_winner": cleaned[idx],
            }
        )
    return pairs


def _resolve_trait_pairs(
    *,
    dimensions: list[str],
    analysis_guidance: dict[str, Any],
) -> list[dict[str, str]]:
    raw_pairs = analysis_guidance.get("paired_dimensions")
    pairs: list[dict[str, str]] = []
    if isinstance(raw_pairs, list):
        for item in raw_pairs:
            parsed = _parse_guidance_pair_entry(item)
            if parsed:
                pairs.append(parsed)
    if not pairs:
        return _default_trait_pairs(dimensions)

    default_winners = _parse_default_winners_from_guidance(analysis_guidance.get("scoring_method"))
    for idx, pair in enumerate(pairs):
        default_winner = _normalize_dimension_name(pair.get("default_winner"))
        if not default_winner and idx < len(default_winners):
            default_winner = _normalize_dimension_name(default_winners[idx])
        if default_winner not in {pair["left"], pair["right"]}:
            default_winner = pair["left"]
        pair["default_winner"] = default_winner
    return pairs


def _dimension_stats_map(dimensions: list[str], dimension_meanings: dict[str, str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for dim in dimensions:
        name = _normalize_dimension_name(dim)
        if not name:
            continue
        out[name] = {
            "score": 0,
            "plus2": 0,
            "plus1": 0,
            "hits": 0,
            "meaning": str(dimension_meanings.get(name) or "").strip(),
        }
    return out


def _aggregate_traits(
    spec: dict[str, Any],
    assignment: dict[str, Any],
    trait_questions: list[dict[str, Any]],
) -> dict[str, Any]:
    trait_meta = spec.get("trait") if isinstance(spec.get("trait"), dict) else {}
    dimension_meanings_raw = (
        trait_meta.get("dimension_meanings") if isinstance(trait_meta.get("dimension_meanings"), dict) else {}
    )
    dimension_meanings = {
        _normalize_dimension_name(key): str(value or "").strip()
        for key, value in dimension_meanings_raw.items()
        if _normalize_dimension_name(key)
    }
    dimensions = [
        _normalize_dimension_name(item)
        for item in (trait_meta.get("dimensions") or [])
        if _normalize_dimension_name(item)
    ]
    analysis_guidance = (
        trait_meta.get("analysis_guidance") if isinstance(trait_meta.get("analysis_guidance"), dict) else {}
    )

    if trait_meta and not trait_questions:
        logger.warning("Trait metadata exists but no traits questions found (exam=%s)", spec.get("id") or spec.get("title"))

    answers = assignment.get("answers") or {}
    stats = _dimension_stats_map(dimensions, dimension_meanings)
    responses: list[dict[str, Any]] = []

    for question in trait_questions:
        qid = str(question.get("qid") or "").strip()
        answer_key = str(answers.get(qid) or "").strip()
        selected_option = next(
            (
                option
                for option in (question.get("options") or [])
                if str((option or {}).get("key") or "").strip() == answer_key
            ),
            None,
        )
        contributions = dict((selected_option or {}).get("traits") or {})
        for raw_dim, raw_weight in contributions.items():
            dim = _normalize_dimension_name(raw_dim)
            if not dim:
                continue
            if dim not in stats:
                stats[dim] = {
                    "score": 0,
                    "plus2": 0,
                    "plus1": 0,
                    "hits": 0,
                    "meaning": str(dimension_meanings.get(dim) or "").strip(),
                }
            try:
                weight = int(raw_weight)
            except Exception:
                continue
            stats[dim]["score"] += weight
            if weight == 2:
                stats[dim]["plus2"] += 1
            if weight == 1:
                stats[dim]["plus1"] += 1
            if weight > 0:
                stats[dim]["hits"] += 1
        responses.append(
            {
                "qid": qid,
                "answer": answer_key,
                "answer_text": str((selected_option or {}).get("text") or "").strip(),
                "contributions": contributions,
            }
        )

    pairs = _resolve_trait_pairs(dimensions=list(stats.keys()), analysis_guidance=analysis_guidance)
    paired_results: list[dict[str, Any]] = []
    primary_dimensions: list[str] = []
    for pair in pairs:
        left = pair["left"]
        right = pair["right"]
        left_stats = stats.get(left) or {"score": 0, "plus2": 0, "plus1": 0}
        right_stats = stats.get(right) or {"score": 0, "plus2": 0, "plus1": 0}
        left_score = int(left_stats.get("score") or 0)
        right_score = int(right_stats.get("score") or 0)
        left_plus2 = int(left_stats.get("plus2") or 0)
        right_plus2 = int(right_stats.get("plus2") or 0)
        left_plus1 = int(left_stats.get("plus1") or 0)
        right_plus1 = int(right_stats.get("plus1") or 0)

        if left_score != right_score:
            winner = left if left_score > right_score else right
            tie_break = "score"
        elif left_plus2 != right_plus2:
            winner = left if left_plus2 > right_plus2 else right
            tie_break = "plus2"
        elif left_plus1 != right_plus1:
            winner = left if left_plus1 > right_plus1 else right
            tie_break = "plus1"
        else:
            winner = str(pair.get("default_winner") or left).strip() or left
            if winner not in {left, right}:
                winner = left
            tie_break = "default"

        loser = right if winner == left else left
        primary_dimensions.append(winner)
        paired_results.append(
            {
                "left": left,
                "right": right,
                "description": str(pair.get("description") or "").strip(),
                "left_score": left_score,
                "right_score": right_score,
                "left_plus2": left_plus2,
                "right_plus2": right_plus2,
                "left_plus1": left_plus1,
                "right_plus1": right_plus1,
                "winner": winner,
                "loser": loser,
                "winner_score": left_score if winner == left else right_score,
                "loser_score": right_score if winner == left else left_score,
                "diff": abs(left_score - right_score),
                "tie_break": tie_break,
                "default_winner": str(pair.get("default_winner") or left).strip() or left,
            }
        )

    scoring_method = analysis_guidance.get("scoring_method")
    interpretation = analysis_guidance.get("interpretation")
    scoring_method_lines = (
        [str(item or "").strip() for item in scoring_method if str(item or "").strip()]
        if isinstance(scoring_method, list)
        else ([str(scoring_method).strip()] if str(scoring_method or "").strip() else [])
    )
    interpretation_lines = (
        [str(item or "").strip() for item in interpretation if str(item or "").strip()]
        if isinstance(interpretation, list)
        else ([str(interpretation).strip()] if str(interpretation or "").strip() else [])
    )
    dimension_list = [
        {
            "dimension": name,
            "score": int((stats.get(name) or {}).get("score") or 0),
            "plus2": int((stats.get(name) or {}).get("plus2") or 0),
            "plus1": int((stats.get(name) or {}).get("plus1") or 0),
            "hits": int((stats.get(name) or {}).get("hits") or 0),
            "meaning": str((stats.get(name) or {}).get("meaning") or "").strip(),
        }
        for name in stats.keys()
    ]
    return {
        "question_count": len(trait_questions),
        "responses": responses,
        "dimensions": stats,
        "dimension_list": dimension_list,
        "dimension_meanings": dimension_meanings,
        "paired_dimensions": paired_results,
        "primary_dimensions": primary_dimensions,
        "analysis_guidance": {
            "paired_dimensions": [dict(item) for item in pairs],
            "scoring_method": scoring_method_lines,
            "interpretation": interpretation_lines,
        },
    }


def _grade_objective(q: dict[str, Any], ans: Any) -> int:
    qtype = q["type"]
    points = int(q.get("points") or 0)

    if qtype == "single":
        correct_key = next(
            (o["key"] for o in q.get("options", []) if o.get("correct")), None
        )
        return points if (isinstance(ans, str) and ans == correct_key) else 0

    if qtype == "multiple":
        correct = {o["key"] for o in q.get("options", []) if o.get("correct")}
        given = set(ans) if isinstance(ans, list) else set()
        if not q.get("partial", False):
            return points if given == correct else 0
        if not correct:
            return 0
        correct_selected = len(given & correct)
        wrong_selected = len(given - correct)
        raw = (correct_selected - wrong_selected) / max(1, len(correct))
        score = round(points * raw)
        return max(0, min(points, int(score)))

    return 0


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
    # Treat pure digits as meaningless (e.g., "1414123") -> 0 points.
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
    items: list[dict[str, Any]], *, batch_size: int = 5
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


def _grade_short_batch(batch_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prompt = _short_batch_grading_prefix() + "\n" + _default_batch_prompt(batch_items)
    raw = call_llm_json(prompt)
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
        )
        results.append(
            {"qid": qid, "score": score, "max": max_points, "reason": reason}
        )
    return results


def _grade_short_batches(batch_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for batch_items in _chunk_short_batch_candidates(batch_candidates, batch_size=5):
        try:
            results.extend(_grade_short_batch(batch_items))
        except Exception as e:
            logger.warning("Batch short grading failed, fallback to per-question grading: %s", e)
            for item in batch_items:
                scored, reason = _grade_short(
                    item["question"],
                    item["answer"],
                    {},
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
    q: dict[str, Any], answer: str, exam_llm: dict[str, Any]
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

    raw = call_llm_json(prompt)
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
    )
    return score, reason


def _grade_short_reason(*, question: str, rubric: str, answer: str, score: int, max_points: int) -> str:
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
    text = (call_llm_text(prompt) or "").strip()
    if not text:
        return "模型未返回原因"
    if len(text) > 160:
        text = text[:160].rstrip()
    return text


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


def _build_traits_summary_lines(trait_result: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    dimension_list = trait_result.get("dimension_list") or []
    if dimension_list:
        lines.append("【维度累计】")
        for item in dimension_list:
            dim = str(item.get("dimension") or "").strip()
            if not dim:
                continue
            meaning = str(item.get("meaning") or "").strip()
            meaning_suffix = f"；含义={meaning}" if meaning else ""
            lines.append(
                f"- {dim}：score={int(item.get('score') or 0)}；+2={int(item.get('plus2') or 0)}；+1={int(item.get('plus1') or 0)}{meaning_suffix}"
            )

    paired_dimensions = trait_result.get("paired_dimensions") or []
    if paired_dimensions:
        lines.append("【对立维度结果】")
        for pair in paired_dimensions:
            desc = str(pair.get("description") or "").strip()
            desc_suffix = f"；说明={desc}" if desc else ""
            lines.append(
                f"- {pair.get('left')}/{pair.get('right')}：winner={pair.get('winner')}；"
                f"score={pair.get('left_score')}/{pair.get('right_score')}；"
                f"+2={pair.get('left_plus2')}/{pair.get('right_plus2')}；"
                f"+1={pair.get('left_plus1')}/{pair.get('right_plus1')}；"
                f"diff={pair.get('diff')}；tie_break={pair.get('tie_break')}{desc_suffix}"
            )

    guidance = trait_result.get("analysis_guidance") or {}
    scoring_method = guidance.get("scoring_method") or []
    interpretation = guidance.get("interpretation") or []
    if scoring_method:
        lines.append("【计分说明】")
        lines.extend(f"- {item}" for item in scoring_method if str(item or "").strip())
    if interpretation:
        lines.append("【解释指导】")
        lines.extend(f"- {item}" for item in interpretation if str(item or "").strip())
    return lines


def _traits_compact_summary(trait_result: dict[str, Any]) -> str:
    paired_dimensions = trait_result.get("paired_dimensions") or []
    if not paired_dimensions:
        return ""
    parts = []
    for pair in paired_dimensions:
        left = str(pair.get("left") or "").strip()
        right = str(pair.get("right") or "").strip()
        winner = str(pair.get("winner") or "").strip()
        diff = int(pair.get("diff") or 0)
        if left and right and winner:
            parts.append(f"{left}/{right} 偏向 {winner}（差值 {diff}）")
    return "；".join(parts)


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
    text = (call_llm_text(prompt) or "").strip()
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
    spec: dict[str, Any], assignment: dict[str, Any], grading: dict[str, Any]
) -> str:
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
