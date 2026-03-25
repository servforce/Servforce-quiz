from __future__ import annotations

import pytest

from backend.md_quiz.services.exam_repo_sync_service import (
    ExamRepoSyncError,
    _load_assets,
    _rewrite_archive_asset_urls,
    _rewrite_asset_paths_for_version,
    perform_exam_repo_sync,
)


def test_rewrite_asset_paths_for_version_rewrites_local_and_legacy_urls():
    spec = {
        "welcome_image": "images/welcome.png",
        "questions": [
            {
                "qid": "Q1",
                "media": "/exams/demo/assets/images/q1.png",
                "stem_md": "题干 ![](images/q1.png) 和 ![](/exams/demo/assets/images/q2.png)",
            }
        ],
    }
    public_spec = {
        "end_image": "/exams/demo/assets/images/end.png",
        "questions": [{"qid": "Q1", "stem_md": "![](images/q1.png)"}],
    }

    out_spec, out_public = _rewrite_asset_paths_for_version(12, spec, public_spec)

    assert out_spec["welcome_image"] == "/exams/versions/12/assets/images/welcome.png"
    assert out_spec["questions"][0]["media"] == "/exams/versions/12/assets/images/q1.png"
    assert "/exams/versions/12/assets/images/q1.png" in out_spec["questions"][0]["stem_md"]
    assert "/exams/versions/12/assets/images/q2.png" in out_spec["questions"][0]["stem_md"]
    assert out_public["end_image"] == "/exams/versions/12/assets/images/end.png"


def test_load_assets_rejects_large_image(tmp_path):
    repo_root = tmp_path
    img_dir = repo_root / "images"
    img_dir.mkdir()
    (img_dir / "large.png").write_bytes(b"x" * (1024 * 1024 + 1))

    with pytest.raises(ExamRepoSyncError, match="超过 1MB"):
        _load_assets(repo_root, ["images/large.png"])


def test_rewrite_archive_asset_urls_rewrites_exam_and_question_assets():
    archive = {
        "exam": {
            "welcome_image": "/exams/demo/assets/images/welcome.png",
            "end_image": "/exams/demo/assets/images/end.png",
        },
        "questions": [
            {
                "media": "/exams/demo/assets/images/q1.png",
                "stem_md": "题干 ![](/exams/demo/assets/images/q2.png)",
            }
        ],
    }

    out = _rewrite_archive_asset_urls(archive, version_id=9)

    assert out["exam"]["exam_version_id"] == 9
    assert out["exam"]["welcome_image"] == "/exams/versions/9/assets/images/welcome.png"
    assert out["exam"]["end_image"] == "/exams/versions/9/assets/images/end.png"
    assert out["questions"][0]["media"] == "/exams/versions/9/assets/images/q1.png"
    assert "/exams/versions/9/assets/images/q2.png" in out["questions"][0]["stem_md"]


def test_perform_exam_repo_sync_marks_invalid_existing_source_as_sync_error(monkeypatch):
    saved_statuses: list[str] = []

    def _fake_clone(repo_url, workdir):
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "demo.md").write_text("# broken exam\n", encoding="utf-8")
        return "deadbeef"

    existing_exam = {
        "exam_key": "demo",
        "title": "Demo",
        "source_md": "---\nid: demo\n---\n",
        "spec": {"title": "Demo", "questions": []},
        "public_spec": {"title": "Demo", "questions": []},
        "status": "active",
        "source_path": "demo.md",
        "git_repo_url": "https://example.com/repo.git",
        "current_version_id": 3,
        "current_version_no": 2,
        "last_synced_commit": "old",
        "last_sync_error": "",
        "public_invite_enabled": False,
        "public_invite_token": "",
    }

    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service._clone_repo", _fake_clone)
    monkeypatch.setattr(
        "backend.md_quiz.services.exam_repo_sync_service._build_exam_candidate",
        lambda *args, **kwargs: (_ for _ in ()).throw(ExamRepoSyncError("Front matter 缺少 id")),
    )
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service._write_git_sync_state", lambda **kwargs: kwargs)
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.list_exam_definitions", lambda: [existing_exam])
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.get_exam_definition", lambda exam_key: dict(existing_exam) if exam_key == "demo" else None)
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.set_exam_public_invite", lambda *args, **kwargs: None)

    def _record_save(**kwargs):
        saved_statuses.append(str(kwargs.get("status") or ""))

    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.save_exam_definition", _record_save)

    result = perform_exam_repo_sync("https://example.com/repo.git")

    assert result["error_count"] == 1
    assert result["retired_exams"] == 0
    assert saved_statuses == ["sync_error"]
