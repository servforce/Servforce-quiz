from __future__ import annotations

import pytest

from backend.md_quiz.parsers.qml import QmlParseError, parse_qml_markdown


def test_parse_qml_answer_time_seconds_variants() -> None:
    exam, public_exam = parse_qml_markdown(
        """
## Q1 [single] (5) {answer_time=45s}
题目一

- A*) 正确
- B) 错误

## Q2 [multiple] (6) {partial=true, answer_time=90}
题目二

- A*) 正确
- B*) 正确

## Q3 [short] {max=10, answer_time=1h}
题目三

[rubric]
给出关键点即可。
[/rubric]
""".strip()
    )

    assert [q["answer_time_seconds"] for q in exam["questions"]] == [45, 90, 3600]
    assert [q["answer_time_seconds"] for q in public_exam["questions"]] == [45, 90, 3600]


def test_parse_qml_intro_and_outro_blocks() -> None:
    exam, public_exam = parse_qml_markdown(
        """
![intro](./assets/welcome.png)

## Q1 [single] (5)
题目一

- A*) 正确
- B) 错误

![bye](./assets/thanks.png)
""".strip()
    )

    assert exam["welcome_image"] == "./assets/welcome.png"
    assert public_exam["welcome_image"] == exam["welcome_image"]
    assert len(exam["questions"]) == 1
    assert exam["questions"][0]["stem_md"] == "题目一"
    assert exam["end_image"] == "./assets/thanks.png"
    assert public_exam["end_image"] == exam["end_image"]


def test_parse_qml_frontmatter_metadata_and_tags_are_normalized() -> None:
    exam, public_exam = parse_qml_markdown(
        """
---
id: personality-demo
title: 人格测试
description: |
  描述文本
tags:
  - personality
  - traits
  - personality
  - "  self-assessment  "
  - ""
schema_version: 2
format: qml-v2
question_count: 99
question_counts:
  single: 80
estimated_duration_minutes: 27
trait:
  dimensions: [I, E]
---

## Q1 [single] (5)
题目一

- A*) 正确
- B) 错误
""".strip()
    )

    assert exam["tags"] == ["personality", "traits", "self-assessment"]
    assert public_exam["tags"] == exam["tags"]
    assert exam["schema_version"] == 2
    assert public_exam["schema_version"] == 2
    assert exam["question_count"] == 99
    assert public_exam["question_count"] == 99
    assert exam["question_counts"] == {"single": 80}
    assert public_exam["question_counts"] == {"single": 80}
    assert exam["estimated_duration_minutes"] == 27
    assert public_exam["estimated_duration_minutes"] == 27
    assert exam["trait"] == {"dimensions": ["I", "E"]}
    assert public_exam["trait"] == exam["trait"]


def test_parse_qml_trait_single_allows_explicit_zero_points_without_correct_option() -> None:
    exam, public_exam = parse_qml_markdown(
        """
## Q1 [single] (0) {scoring=traits, answer_time=20s}
我更愿意先独处整理思路，再决定是否表达出来。

- A) 非常同意 {traits=I:2}
- B) 比较同意 {traits=I:1}
- C) 中立
- D) 比较不同意 {traits=E:1}
- E) 非常不同意 {traits=E:2}
""".strip()
    )

    question = exam["questions"][0]
    public_question = public_exam["questions"][0]
    assert question["points"] == 0
    assert question["max_points"] == 0
    assert question["answer_time_seconds"] == 20
    assert [option["correct"] for option in question["options"]] == [False, False, False, False, False]
    assert question["options"][0]["traits"] == {"I": 2}
    assert public_question["points"] == 0
    assert public_question["max_points"] == 0


def test_parse_qml_trait_single_rejects_correct_marker() -> None:
    markdown = """
## Q1 [single] (0) {scoring=traits}
题目一

- A*) 非常同意 {traits=I:2}
- B) 非常不同意 {traits=E:2}
""".strip()

    with pytest.raises(QmlParseError, match="trait single must not use correct option"):
        parse_qml_markdown(markdown)


def test_parse_qml_rejects_non_string_tags() -> None:
    markdown = """
---
id: demo
tags:
  - ok
  - 1
---

## Q1 [single] (5)
题目一

- A*) 正确
- B) 错误
""".strip()

    with pytest.raises(QmlParseError, match="tags"):
        parse_qml_markdown(markdown)


@pytest.mark.parametrize("raw", ["0", "0s", "3601", "61m", "bad"])
def test_parse_qml_answer_time_invalid(raw: str) -> None:
    markdown = f"""
## Q1 [single] (5) {{answer_time={raw}}}
题目一

- A*) 正确
- B) 错误
""".strip()

    with pytest.raises(QmlParseError, match="answer_time"):
        parse_qml_markdown(markdown)
