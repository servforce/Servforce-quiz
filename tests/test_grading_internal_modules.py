from __future__ import annotations

from backend.md_quiz.services import grading_analysis, grading_short_answer, grading_traits


def test_extract_json_like_payload_accepts_wrapped_json_text():
    payload = grading_short_answer._extract_json_like_payload(
        '模型输出如下：\n```json\n{"score": 3, "reason": "ok"}\n```'
    )

    assert payload == {"score": 3, "reason": "ok"}


def test_finalize_short_grade_uses_reason_fallback_callback():
    score, reason = grading_short_answer._finalize_short_grade(
        question="题目",
        rubric="评分标准",
        answer="回答",
        score=4,
        reason="模型未返回原因",
        relevance=2,
        contradiction=False,
        max_points=5,
        llm_text=lambda _prompt: "命中主要要点，但少一个例子。",
    )

    assert score == 4
    assert reason == "命中主要要点，但少一个例子。"


def test_traits_helpers_build_summary_and_compact_text():
    trait_result = {
        "dimension_list": [
            {"dimension": "I", "score": 3, "plus2": 1, "plus1": 1, "meaning": "独处内化"},
            {"dimension": "E", "score": 1, "plus2": 0, "plus1": 1, "meaning": "外向互动"},
        ],
        "paired_dimensions": [
            {
                "left": "I",
                "right": "E",
                "winner": "I",
                "left_score": 3,
                "right_score": 1,
                "left_plus2": 1,
                "right_plus2": 0,
                "left_plus1": 1,
                "right_plus1": 1,
                "diff": 2,
                "tie_break": "score",
                "description": "比较独处内化与外向互动",
            }
        ],
        "analysis_guidance": {
            "scoring_method": ["若同组平分，则依次比较 +2 次数。"],
            "interpretation": ["差值越大，偏好越稳定。"],
        },
    }

    lines = grading_traits._build_traits_summary_lines(trait_result)
    compact = grading_traits._traits_compact_summary(trait_result)

    assert "【维度累计】" in lines
    assert any("I/E：winner=I" in line for line in lines)
    assert compact == "I/E 偏向 I（差值 2）"


def test_generate_final_analysis_uses_fallback_when_llm_returns_empty():
    text = grading_analysis._generate_final_analysis(
        spec={"title": "demo", "questions": []},
        assignment={"answers": {}},
        scored_result={"objective": [], "subjective": [], "total": 3, "total_max": 5},
        trait_result={
            "dimension_list": [],
            "paired_dimensions": [{"left": "I", "right": "E", "winner": "I", "diff": 2}],
            "analysis_guidance": {},
        },
        result_mode="mixed",
        llm_text=lambda _prompt: "",
    )

    assert "3/5" in text
    assert "I/E 偏向 I" in text
