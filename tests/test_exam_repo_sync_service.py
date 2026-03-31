from __future__ import annotations

from pathlib import Path

import pytest

from backend.md_quiz.services.exam_repo_sync_service import (
    ExamRepoSyncError,
    _build_exam_candidate,
    _load_assets,
    _load_quiz_repo_manifest,
    _rewrite_archive_asset_urls,
    _rewrite_asset_paths_for_version,
    perform_exam_repo_sync,
)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _write_manifest(repo_root: Path, *quiz_paths: str) -> None:
    _write_text(repo_root / "README.md", "# demo\n")
    lines = [
        "schema_version: 1",
        "kind: md-quiz-repo",
        "quizzes:",
    ]
    for path in quiz_paths:
        lines.append(f"  - path: {path}")
    _write_text(repo_root / "md-quiz-repo.yaml", "\n".join(lines) + "\n")


def test_rewrite_asset_paths_for_version_rewrites_local_and_legacy_urls():
    spec = {
        "welcome_image": "assets/welcome.png",
        "questions": [
            {
                "qid": "Q1",
                "media": "/exams/demo/assets/assets/q1.png",
                "stem_md": "题干 ![](assets/q1.png) 和 ![](/exams/demo/assets/assets/q2.png)",
            }
        ],
    }
    public_spec = {
        "end_image": "/exams/demo/assets/assets/end.png",
        "questions": [{"qid": "Q1", "stem_md": "![](assets/q1.png)"}],
    }

    out_spec, out_public = _rewrite_asset_paths_for_version(12, spec, public_spec)

    assert out_spec["welcome_image"] == "/exams/versions/12/assets/assets/welcome.png"
    assert out_spec["questions"][0]["media"] == "/exams/versions/12/assets/assets/q1.png"
    assert "/exams/versions/12/assets/assets/q1.png" in out_spec["questions"][0]["stem_md"]
    assert "/exams/versions/12/assets/assets/q2.png" in out_spec["questions"][0]["stem_md"]
    assert out_public["end_image"] == "/exams/versions/12/assets/assets/end.png"


def test_load_assets_rejects_large_image(tmp_path):
    quiz_root = tmp_path
    img_dir = quiz_root / "assets"
    img_dir.mkdir()
    (img_dir / "large.png").write_bytes(b"x" * (1024 * 1024 + 1))

    with pytest.raises(ExamRepoSyncError, match="超过 1MB"):
        _load_assets(quiz_root, ["assets/large.png"])


def test_rewrite_archive_asset_urls_rewrites_exam_and_question_assets():
    archive = {
        "exam": {
            "welcome_image": "/exams/demo/assets/assets/welcome.png",
            "end_image": "/exams/demo/assets/assets/end.png",
        },
        "questions": [
            {
                "media": "/exams/demo/assets/assets/q1.png",
                "stem_md": "题干 ![](/exams/demo/assets/assets/q2.png)",
            }
        ],
    }

    out = _rewrite_archive_asset_urls(archive, version_id=9)

    assert out["exam"]["exam_version_id"] == 9
    assert out["exam"]["welcome_image"] == "/exams/versions/9/assets/assets/welcome.png"
    assert out["exam"]["end_image"] == "/exams/versions/9/assets/assets/end.png"
    assert out["questions"][0]["media"] == "/exams/versions/9/assets/assets/q1.png"
    assert "/exams/versions/9/assets/assets/q2.png" in out["questions"][0]["stem_md"]


def test_load_quiz_repo_manifest_requires_manifest(tmp_path):
    _write_text(tmp_path / "demo.md", "# legacy\n")
    (tmp_path / "images").mkdir()

    with pytest.raises(ExamRepoSyncError, match="md-quiz-repo.yaml"):
        _load_quiz_repo_manifest(tmp_path)


def test_load_quiz_repo_manifest_rejects_invalid_quiz_path(tmp_path):
    _write_manifest(tmp_path, "quizzes/demo/demo.md")
    _write_text(tmp_path / "quizzes/demo/demo.md", "# demo\n")

    with pytest.raises(ExamRepoSyncError, match="quizzes/<quiz_id>/quiz.md"):
        _load_quiz_repo_manifest(tmp_path)


def test_build_exam_candidate_uses_repo_relative_source_path_and_assets(tmp_path):
    _write_manifest(tmp_path, "quizzes/demo/quiz.md")
    _write_bytes(tmp_path / "quizzes/demo/assets/welcome.png", b"png")
    _write_bytes(tmp_path / "quizzes/demo/assets/q1.png", b"png")
    _write_bytes(tmp_path / "quizzes/demo/assets/media.png", b"png")
    _write_text(
        tmp_path / "quizzes/demo/quiz.md",
        """
---
id: demo
title: Demo
format: qml-v2
---

![intro](./assets/welcome.png)

## Q1 [single] (5) {media=assets/media.png}
题干 ![](assets/q1.png)

- A*) 正确
- B) 错误
""".strip()
        + "\n",
    )

    candidate = _build_exam_candidate(tmp_path, "https://example.com/repo.git", "deadbeef", "quizzes/demo/quiz.md")

    assert candidate["source_path"] == "quizzes/demo/quiz.md"
    assert set(candidate["assets"].keys()) == {"assets/media.png", "assets/q1.png", "assets/welcome.png"}


def test_build_exam_candidate_rejects_cross_quiz_asset(tmp_path):
    _write_manifest(tmp_path, "quizzes/demo/quiz.md")
    _write_text(
        tmp_path / "quizzes/demo/quiz.md",
        """
---
id: demo
title: Demo
---

## Q1 [single] (5)
题干 ![](../other/assets/q1.png)

- A*) 正确
- B) 错误
""".strip()
        + "\n",
    )

    with pytest.raises(ExamRepoSyncError, match="资源路径非法"):
        _build_exam_candidate(tmp_path, "https://example.com/repo.git", "deadbeef", "quizzes/demo/quiz.md")


def test_build_exam_candidate_requires_frontmatter_id_match_directory(tmp_path):
    _write_manifest(tmp_path, "quizzes/demo/quiz.md")
    _write_text(
        tmp_path / "quizzes/demo/quiz.md",
        """
---
id: other
title: Demo
---

## Q1 [single] (5)
题目一

- A*) 正确
- B) 错误
""".strip()
        + "\n",
    )

    with pytest.raises(ExamRepoSyncError, match="目录名一致"):
        _build_exam_candidate(tmp_path, "https://example.com/repo.git", "deadbeef", "quizzes/demo/quiz.md")


def test_perform_exam_repo_sync_scans_manifest_source_path(monkeypatch):
    captured: list[dict[str, object]] = []

    def _fake_clone(repo_url, workdir):
        _write_manifest(workdir, "quizzes/demo/quiz.md")
        _write_bytes(workdir / "quizzes/demo/assets/q1.png", b"png")
        _write_text(
            workdir / "quizzes/demo/quiz.md",
            """
---
id: demo
title: Demo
---

## Q1 [single] (5)
题干 ![](./assets/q1.png)

- A*) 正确
- B) 错误
""".strip()
            + "\n",
        )
        return "deadbeef"

    def _fake_sync(candidate, *, synced_at):
        captured.append(candidate)
        return {"exam_key": "demo", "version_id": 1, "version_no": 1, "action": "created"}

    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service._clone_repo", _fake_clone)
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service._sync_exam_candidate", _fake_sync)
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service._write_git_sync_state", lambda **kwargs: kwargs)
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.list_exam_definitions", lambda: [])

    result = perform_exam_repo_sync("https://example.com/repo.git")

    assert result["scanned_md"] == 1
    assert result["created_versions"] == 1
    assert captured[0]["source_path"] == "quizzes/demo/quiz.md"


def test_perform_exam_repo_sync_marks_invalid_existing_source_as_sync_error(monkeypatch):
    saved_statuses: list[str] = []

    def _fake_clone(repo_url, workdir):
        _write_manifest(workdir, "quizzes/demo/quiz.md")
        _write_text(workdir / "quizzes/demo/quiz.md", "# broken quiz\n")
        return "deadbeef"

    existing_exam = {
        "exam_key": "demo",
        "title": "Demo",
        "source_md": "---\nid: demo\n---\n",
        "spec": {"title": "Demo", "questions": []},
        "public_spec": {"title": "Demo", "questions": []},
        "status": "active",
        "source_path": "quizzes/demo/quiz.md",
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
