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
