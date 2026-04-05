from __future__ import annotations

import re
from typing import Any

from backend.md_quiz.config import logger


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


__all__ = [
    "_aggregate_traits",
    "_build_traits_summary_lines",
    "_is_traits_question",
    "_traits_compact_summary",
]
