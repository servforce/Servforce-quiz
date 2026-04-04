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
            "questions": [{"qid": "Q1", "stem_md": "题干 **加粗**"}],
        }
    )

    assert spec["welcome_image"] == "/quizzes/demo/assets/assets/welcome.png"
    assert spec["end_image"] == "/quizzes/demo/assets/assets/thanks.png"
    assert "<strong>加粗</strong>" in spec["questions"][0]["stem_html"]
