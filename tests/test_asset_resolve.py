from pathlib import Path

from app import _resolve_exam_asset_file


def test_resolve_exam_asset_falls_back_to_examples() -> None:
    p = _resolve_exam_asset_file("common-test-2025", "img/q15.png")
    assert p is not None
    assert p.exists()
    assert p.is_file()
    assert str(p).replace("\\", "/").endswith("examples/img/q15.png")


def test_resolve_exam_asset_blocks_traversal() -> None:
    assert _resolve_exam_asset_file("common-test-2025", "../app.py") is None
    assert _resolve_exam_asset_file("common-test-2025", "..\\app.py") is None
    assert _resolve_exam_asset_file("common-test-2025", "img/../../app.py") is None
    assert _resolve_exam_asset_file("common-test-2025", "img\\..\\..\\app.py") is None

