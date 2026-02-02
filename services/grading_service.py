from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from config import logger
from services.llm_client import call_llm_json, call_llm_text


def grade_attempt(spec: dict[str, Any], assignment: dict[str, Any]) -> dict[str, Any]:
    answers = assignment.get("answers") or {}
    objective_details = []
    subjective_details = []

    raw_total = 0
    raw_scored = 0

    for q in spec.get("questions", []):
        qid = q["qid"]
        qtype = q["type"]
        max_points = int(q.get("max_points") or q.get("points") or 0)
        raw_total += max_points

        if qtype in {"single", "multiple"}:
            scored = _grade_objective(q, answers.get(qid))
            raw_scored += scored
            objective_details.append({"qid": qid, "score": scored, "max": max_points})
            continue

        if qtype == "short":
            scored, reason = _grade_short(q, answers.get(qid, ""), spec.get("llm") or {})
            raw_scored += scored
            subjective_details.append(
                {"qid": qid, "score": scored, "max": max_points, "reason": reason}
            )
            continue

    percentage = 0
    if raw_total > 0:
        percentage = round(100 * raw_scored / raw_total)
    percentage = max(0, min(100, int(percentage)))

    threshold = int(assignment.get("pass_threshold") or 70)
    interview = percentage >= threshold
    overall_reason = f"raw={raw_scored}/{raw_total} => score={percentage}/100"

    out = {
        "objective": objective_details,
        "subjective": subjective_details,
        "raw_total": raw_total,
        "raw_scored": raw_scored,
        "total": percentage,
        "pass_threshold": threshold,
        "interview": interview,
        "overall_reason": overall_reason,
        "graded_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        out["analysis"] = _analyze_grading(spec, assignment, out)
    except Exception as e:
        logger.warning("Grading analysis failed: %s", e)
        out["analysis"] = ""
    return out


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
        "2) 若答案只命中部分要点，请按要点覆盖程度给分；rubric 未细分时请自行拆分为 3-5 个要点再评。\n"
        "3) reason 用 1-3 句说明得分点/失分点，不要泄露标准答案原文。\n"
        f"只输出 JSON：{{\"score\":0..{max_points},\"reason\":\"...\"}}。\n"
        f"【题目】{question}\n"
        f"【评分标准】{rubric}\n"
        f"【考生回答】{answer}\n"
    )

def _short_grading_prefix(max_points: int) -> str:
    return (
        "评分补充要求：\n"
        f"- 必须使用 0..{max_points} 的整数分，允许部分得分（可取中间分）。\n"
        "- 若 rubric 未给出分点，请自行拆分要点并按覆盖程度给分。\n"
        "- 只依据考生回答作答，不要推测其“可能想表达什么”。\n"
        f"- 只输出 JSON：{{\"score\":0..{max_points},\"reason\":\"...\"}}。\n"
    )


def _grade_short(
    q: dict[str, Any], answer: str, exam_llm: dict[str, Any]
) -> tuple[int, str]:
    max_points = int(q.get("max_points") or q.get("points") or 0)
    rubric = q.get("rubric") or ""
    question = q.get("stem_md") or ""
    q_llm = q.get("llm") or {}
    prompt_template = (
        q_llm.get("prompt_template") or exam_llm.get("prompt_template") or ""
    ).strip()
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
        try_text = str(raw).strip()
        # Be tolerant: some providers wrap JSON with extra text.
        if not (try_text.startswith("{") and try_text.endswith("}")):
            l = try_text.find("{")
            r = try_text.rfind("}")
            if l != -1 and r != -1 and r > l:
                try_text = try_text[l : r + 1]
        obj = json.loads(try_text)
        raw_score = obj.get("score", 0)
        if isinstance(raw_score, (int, float)):
            score = int(round(float(raw_score)))
        else:
            m = re.search(r"-?\d+(?:\.\d+)?", str(raw_score))
            score = int(round(float(m.group(0)))) if m else 0
        reason = str(obj.get("reason", "")).strip() or "模型未返回原因"
    except Exception:
        try:
            m = re.search(r"-?\d+(?:\.\d+)?", str(raw).strip())
            score = int(round(float(m.group(0)))) if m else 0
            reason = ""
        except Exception:
            logger.warning("LLM output parse failed: %r", raw)
            return 0, "模型返回无法解析"
    score = max(0, min(max_points, score))
    if (not reason or reason in {"模型未返回原因", "模型仅返回分数"}) and rubric:
        reason = _grade_short_reason(question=question, rubric=rubric, answer=answer, score=score, max_points=max_points)
    return score, reason


def _grade_short_reason(*, question: str, rubric: str, answer: str, score: int, max_points: int) -> str:
    prompt = (
        "你是严格的阅卷老师。请根据评分标准解释该答案的得分依据。\n"
        "要求：\n"
        "1) 输出纯文本，不要 JSON，不要 Markdown。\n"
        "2) 1-2 句话，<= 80 字。\n"
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


def _analyze_grading(spec: dict[str, Any], assignment: dict[str, Any], grading: dict[str, Any]) -> str:
    """
    Analyze per-question scoring and return a short text for admin review.
    This is stored under grading["analysis"] and shown in admin JSON view / archives.
    """
    answers = assignment.get("answers") or {}
    questions = spec.get("questions") or []

    scored_by_qid: dict[str, dict[str, Any]] = {}
    for d in (grading.get("objective") or []):
        scored_by_qid[str(d.get("qid"))] = d
    for d in (grading.get("subjective") or []):
        scored_by_qid[str(d.get("qid"))] = d

    lines: list[str] = []
    for q in questions[:60]:
        qid = str(q.get("qid") or "")
        if not qid:
            continue
        sd = scored_by_qid.get(qid) or {}
        score = sd.get("score")
        max_points = sd.get("max") or q.get("max_points") or q.get("points")
        reason = str(sd.get("reason") or "").strip()
        if reason:
            reason = reason.replace("\n", " ")
        ans = answers.get(qid)
        if isinstance(ans, list):
            ans_text = ",".join(str(x) for x in ans)
        else:
            ans_text = "" if ans is None else str(ans)
        ans_text = ans_text.strip().replace("\n", " ")
        if len(ans_text) > 120:
            ans_text = ans_text[:120].rstrip()
        line = f"- {qid}：{score}/{max_points}"
        if reason:
            line += f"；{reason[:120]}"
        if ans_text:
            line += f"；答={ans_text}"
        lines.append(line)

    total = int(grading.get("total") or 0)
    interview = bool(grading.get("interview"))
    threshold = int(grading.get("pass_threshold") or assignment.get("pass_threshold") or 70)

    prompt = (
        "你是一名资深面试官与阅卷负责人。请对本次考试的各题得分情况做简短分析，用于内部复盘。\n"
        "要求：\n"
        "1) 输出纯文本，不要 Markdown。\n"
        "2) 150-320 字。\n"
        "3) 先给出总体结论（1-2句），再给出3条要点（每条<=40字）。\n"
        "4) 最后给出面试建议：建议/不建议 + 一句话理由。\n"
        f"【考试】{spec.get('title','')}\n"
        f"【总分】{total}/100（阈值{threshold}，是否面试：{'是' if interview else '否'}）\n"
        "【得分明细】\n"
        + "\n".join(lines)
        + "\n"
    )
    text = (call_llm_text(prompt) or "").strip()
    if not text:
        return ""
    if len(text) > 1200:
        text = text[:1200].rstrip()
    return text


def generate_candidate_remark(
    spec: dict[str, Any], assignment: dict[str, Any], grading: dict[str, Any]
) -> str:
    answers = assignment.get("answers") or {}
    questions = spec.get("questions") or []

    scored_by_qid: dict[str, dict[str, Any]] = {}
    for d in (grading.get("objective") or []):
        scored_by_qid[str(d.get("qid"))] = d
    for d in (grading.get("subjective") or []):
        scored_by_qid[str(d.get("qid"))] = d

    parts: list[str] = []
    for q in questions[:30]:
        qid = str(q.get("qid") or "")
        stem = str(q.get("stem_md") or "").strip().replace("\n", " ")
        stem = stem[:160]
        ans = answers.get(qid)
        if isinstance(ans, list):
            ans_text = ",".join(str(x) for x in ans)
        else:
            ans_text = "" if ans is None else str(ans)
        ans_text = ans_text.strip()
        ans_text = ans_text[:280]
        sd = scored_by_qid.get(qid) or {}
        score = sd.get("score")
        max_points = sd.get("max") or q.get("max_points") or q.get("points")
        reason = sd.get("reason")
        line = f"- {qid}（{score}/{max_points}）：题目={stem}；回答={ans_text}"
        if reason:
            line += f"；判分要点={str(reason)[:160]}"
        parts.append(line)

    total = int(grading.get("total") or 0)
    interview = bool(grading.get("interview"))
    threshold = int(grading.get("pass_threshold") or assignment.get("pass_threshold") or 70)

    prompt = (
        "你是一名资深面试官，请根据考试答题情况给出候选人能力评价。\n"
        "要求：\n"
        "1) 输出纯文本（不要 JSON，不要 Markdown）。\n"
        "2) 120-220 字左右。\n"
        "3) 包含：综合评价、优势、短板、建议（各一句即可）。\n"
        "4) 不要泄露标准答案或题库内容，只能基于考生回答表现描述。\n"
        "5) 末尾补充“面试建议：建议/不建议 + 一句话理由”。\n"
        f"【考试】{spec.get('title','')}\n"
        f"【总分】{total}/100（阈值{threshold}，是否面试：{'是' if interview else '否'}）\n"
        "【答题摘要】\n"
        + "\n".join(parts)
        + "\n"
    )

    try:
        text = call_llm_text(prompt) or ""
    except Exception as e:
        logger.warning("LLM remark generation failed: %s", e)
        text = ""

    text = str(text).strip()
    if not text:
        return str(grading.get("overall_reason") or "").strip()
    if len(text) > 600:
        text = text[:600].rstrip()
    return text
