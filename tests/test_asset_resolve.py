import backend.md_quiz.services.exam_helpers as exams_module


def test_resolve_quiz_asset_reads_from_db(monkeypatch) -> None:
    monkeypatch.setattr(
        exams_module,
        "get_quiz_asset",
        lambda quiz_key, relpath: (b"png-bytes", "image/png"),
    )

    asset = exams_module._resolve_quiz_asset_payload("common-test-2025", "assets/q15.png")

    assert asset == (b"png-bytes", "image/png")


def test_resolve_quiz_asset_returns_none_for_invalid_or_missing_asset(monkeypatch) -> None:
    monkeypatch.setattr(exams_module, "get_quiz_asset", lambda quiz_key, relpath: None)

    assert exams_module._resolve_quiz_asset_payload("common-test-2025", "../app.py") is None
    assert exams_module._resolve_quiz_asset_payload("common-test-2025", "..\\app.py") is None
    assert exams_module._resolve_quiz_asset_payload("common-test-2025", "assets/../../app.py") is None
    assert exams_module._resolve_quiz_asset_payload("common-test-2025", "assets\\..\\..\\app.py") is None


def test_collect_md_assets_includes_html_img_src() -> None:
    assets = exams_module._collect_md_assets(
        '题干 ![](assets/q15.png) <img src="assets/q44.png" alt="图示" width="720" />'
    )

    assert assets == {"assets/q15.png", "assets/q44.png"}


def test_build_render_ready_public_spec_renders_intro_outro_and_questions() -> None:
    spec = exams_module.build_render_ready_public_spec(
        {
            "welcome_image": "/quizzes/demo/assets/assets/welcome.png",
            "end_image": "/quizzes/demo/assets/assets/thanks.png",
            "questions": [
                {
                    "qid": "Q1",
                    "stem_md": r"题干 **加粗**，字段 `student\_id`，公式 $V=\{v0,v1\}$",
                    "options": [{"key": "A", "text": r"select student\_id from learn"}],
                }
            ],
        }
    )

    assert spec["welcome_image"] == "/quizzes/demo/assets/assets/welcome.png"
    assert spec["end_image"] == "/quizzes/demo/assets/assets/thanks.png"
    assert "<strong>加粗</strong>" in spec["questions"][0]["stem_html"]
    assert "student_id" in spec["questions"][0]["stem_html"]
    assert r"$V=\{v0,v1\}$" in spec["questions"][0]["stem_html"]
    assert "student_id" in spec["questions"][0]["options"][0]["text_html"]


def test_build_render_ready_question_renders_rubric_markdown_and_preserves_tex() -> None:
    question = exams_module.build_render_ready_question(
        {
            "qid": "Q2",
            "stem_md": r"图论中有 $E=\{\langle v0,v1 \rangle\}$",
            "rubric": "见示意图：\n\n![参考答案](./assets/a15.png)\n\n- 提到关键点",
        },
        include_rubric_html=True,
    )

    assert r"$E=\{\langle v0,v1 \rangle\}$" in question["stem_html"]
    assert '<img alt="参考答案" src="./assets/a15.png"' in question["rubric_html"]
    assert "<li>提到关键点</li>" in question["rubric_html"]


def test_render_markdown_html_merges_inline_math_only_paragraphs() -> None:
    html = exams_module._render_markdown_html("则\n\n$x = 0$\n\n是\n\n$f(x)$\n\n的（）")

    assert html == "<p>则 $x = 0$ 是 $f(x)$ 的（）</p>"


def test_render_markdown_html_promotes_list_after_paragraph() -> None:
    html = exams_module._render_markdown_html(
        "学习策略\n\n请结合以下方面简要作答：\n- 学习内容选择\n- 学习方式\n- 能力迭代策略"
    )

    assert "<p>请结合以下方面简要作答：</p>" in html
    assert "<ul>" in html
    assert "<li>学习内容选择</li>" in html


def test_render_markdown_html_collapses_inline_hard_breaks() -> None:
    html = exams_module._render_markdown_html("则  \n$x = 0$  \n是  \n$f(x)$  \n的（）")

    assert html == "<p>则 $x = 0$ 是 $f(x)$ 的（）</p>"


def test_render_markdown_html_collapses_simple_multiline_paragraph_after_block_math() -> None:
    html = exams_module._render_markdown_html(
        "设函数\n\n$$f(x)=\\begin{cases}|x|x, & x\\leq 0,\\\\x\\ln x, & x>0.\\end{cases}$$\n\n则\n$x = 0$\n是\n$f(x)$\n的（）"
    )

    assert "<p>则 $x = 0$ 是 $f(x)$ 的（）</p>" in html
