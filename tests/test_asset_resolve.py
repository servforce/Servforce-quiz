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
