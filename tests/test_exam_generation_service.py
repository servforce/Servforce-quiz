from __future__ import annotations

import json

from backend.md_quiz.services import exam_generation_service as service


def test_safe_asset_name_defaults_to_assets_directory() -> None:
    assert service._safe_asset_name("", "Q1") == "assets/q1-diagram.svg"
    assert service._safe_asset_name("diagram", "Q1") == "assets/diagram.svg"


def test_generate_exam_from_prompt_uses_assets_path_for_generated_figures(monkeypatch) -> None:
    payload = {
        "exam": {"id": "demo", "title": "Demo Quiz", "description": "示例"},
        "questions": [
            {
                "qid": "Q1",
                "type": "single",
                "points": 5,
                "stem": "请根据如下图判断结果",
                "options": [
                    {"key": "A", "text": "选项A", "correct": True},
                    {"key": "B", "text": "选项B", "correct": False},
                ],
            }
        ],
    }

    monkeypatch.setattr(
        service,
        "call_llm_structured_ex",
        lambda prompt, system="": (json.dumps(payload, ensure_ascii=False), ""),
    )
    monkeypatch.setattr(
        service,
        "_choose_final_svg",
        lambda *args, **kwargs: "<svg xmlns='http://www.w3.org/2000/svg'></svg>",
    )

    markdown_text, assets, meta = service.generate_exam_from_prompt("请生成一份带图单选题", include_diagrams=True)

    assert "schema_version: 2" in markdown_text
    assert "format: qml-v2" in markdown_text
    assert "question_count: 1" in markdown_text
    assert "question_counts:" in markdown_text
    assert "  single: 1" in markdown_text
    assert "estimated_duration_minutes: 2" in markdown_text
    assert "![示意图](assets/q1-diagram.svg)" in markdown_text
    assert "assets/q1-diagram.svg" in assets
    assert meta["asset_count"] == 1
    assert meta["question_counts"] == {"single": 1, "multiple": 0, "short": 0}
    assert meta["estimated_duration_minutes"] == 2
