import backend.md_quiz.services.exam_helpers as exams_module


def test_resolve_exam_asset_reads_from_db(monkeypatch) -> None:
    monkeypatch.setattr(
        exams_module,
        "get_exam_asset",
        lambda exam_key, relpath: (b"png-bytes", "image/png"),
    )

    asset = exams_module._resolve_exam_asset_payload("common-test-2025", "img/q15.png")

    assert asset == (b"png-bytes", "image/png")


def test_resolve_exam_asset_returns_none_for_invalid_or_missing_asset(monkeypatch) -> None:
    monkeypatch.setattr(exams_module, "get_exam_asset", lambda exam_key, relpath: None)

    assert exams_module._resolve_exam_asset_payload("common-test-2025", "../app.py") is None
    assert exams_module._resolve_exam_asset_payload("common-test-2025", "..\\app.py") is None
    assert exams_module._resolve_exam_asset_payload("common-test-2025", "img/../../app.py") is None
    assert exams_module._resolve_exam_asset_payload("common-test-2025", "img\\..\\..\\app.py") is None


def test_collect_md_assets_includes_html_img_src() -> None:
    assets = exams_module._collect_md_assets(
        '题干 ![](img/q15.png) <img src="img/q44.png" alt="图示" width="720" />'
    )

    assert assets == {"img/q15.png", "img/q44.png"}


def test_build_render_ready_public_spec_renders_intro_outro_and_questions() -> None:
    spec = exams_module.build_render_ready_public_spec(
        {
            "welcome_image": "/exams/demo/assets/img/welcome.png",
            "end_image": "/exams/demo/assets/img/thanks.png",
            "questions": [{"qid": "Q1", "stem_md": "题干 **加粗**"}],
        }
    )

    assert spec["welcome_image"] == "/exams/demo/assets/img/welcome.png"
    assert spec["end_image"] == "/exams/demo/assets/img/thanks.png"
    assert "<strong>加粗</strong>" in spec["questions"][0]["stem_html"]
