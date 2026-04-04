from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.md_quiz.services.exam_repo_sync_service import (
    ExamRepoSyncError,
    _build_exam_candidate,
    _clone_repo,
    _load_assets,
    _load_quiz_repo_manifest,
    _rewrite_archive_asset_urls,
    _rewrite_asset_paths_for_version,
    _sync_exam_candidate,
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
        "schema_version: 2",
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
                "media": "/quizzes/demo/assets/assets/q1.png",
                "stem_md": "题干 ![](assets/q1.png) 和 ![](/quizzes/demo/assets/assets/q2.png)",
                "rubric": "评分图 ![](assets/rubric.png)",
            }
        ],
    }
    public_spec = {
        "end_image": "/quizzes/demo/assets/assets/end.png",
        "questions": [{"qid": "Q1", "stem_md": "![](assets/q1.png)"}],
    }

    out_spec, out_public = _rewrite_asset_paths_for_version(12, spec, public_spec)

    assert out_spec["welcome_image"] == "/quizzes/versions/12/assets/assets/welcome.png"
    assert out_spec["questions"][0]["media"] == "/quizzes/versions/12/assets/assets/q1.png"
    assert "/quizzes/versions/12/assets/assets/q1.png" in out_spec["questions"][0]["stem_md"]
    assert "/quizzes/versions/12/assets/assets/q2.png" in out_spec["questions"][0]["stem_md"]
    assert "/quizzes/versions/12/assets/assets/rubric.png" in out_spec["questions"][0]["rubric"]
    assert out_public["end_image"] == "/quizzes/versions/12/assets/assets/end.png"


def test_load_assets_rejects_large_image(tmp_path):
    quiz_root = tmp_path
    img_dir = quiz_root / "assets"
    img_dir.mkdir()
    (img_dir / "large.png").write_bytes(b"x" * (1024 * 1024 + 1))

    with pytest.raises(ExamRepoSyncError, match="超过 1MB"):
        _load_assets(quiz_root, ["assets/large.png"])


def test_clone_repo_surfaces_git_stderr(monkeypatch, tmp_path):
    def _boom(*args, **kwargs):
        raise subprocess.CalledProcessError(
            128,
            args[0],
            output="",
            stderr="fatal: unable to access 'https://example.com/repo.git/': Proxy CONNECT aborted",
        )

    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.subprocess.run", _boom)

    with pytest.raises(ExamRepoSyncError, match="Proxy CONNECT aborted"):
        _clone_repo("https://example.com/repo.git", tmp_path / "repo")


def test_clone_repo_passes_explicit_git_proxy_config(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def _ok(cmd, **kwargs):
        calls.append(list(cmd))
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="deadbeef\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.EXAM_REPO_SYNC_PROXY", "http://10.0.6.20:8888")
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.subprocess.run", _ok)

    commit = _clone_repo("https://example.com/repo.git", tmp_path / "repo")

    assert commit == "deadbeef"
    assert calls[0][:3] == ["git", "-c", "http.proxy=http://10.0.6.20:8888"]
    assert calls[0][3:] == ["clone", "--depth", "1", "https://example.com/repo.git", str(tmp_path / "repo")]
    assert calls[1][:4] == ["git", "-C", str(tmp_path / "repo"), "rev-parse"]


def test_rewrite_archive_asset_urls_rewrites_exam_and_question_assets():
    archive = {
        "exam": {
            "welcome_image": "/quizzes/demo/assets/assets/welcome.png",
            "end_image": "/quizzes/demo/assets/assets/end.png",
        },
        "questions": [
            {
                "media": "/quizzes/demo/assets/assets/q1.png",
                "stem_md": "题干 ![](/quizzes/demo/assets/assets/q2.png)",
                "rubric": "评分图 ![](/quizzes/demo/assets/assets/a15.png)",
            }
        ],
    }

    out = _rewrite_archive_asset_urls(archive, version_id=9)

    assert out["exam"]["quiz_version_id"] == 9
    assert out["exam"]["welcome_image"] == "/quizzes/versions/9/assets/assets/welcome.png"
    assert out["exam"]["end_image"] == "/quizzes/versions/9/assets/assets/end.png"
    assert out["questions"][0]["media"] == "/quizzes/versions/9/assets/assets/q1.png"
    assert "/quizzes/versions/9/assets/assets/q2.png" in out["questions"][0]["stem_md"]
    assert "/quizzes/versions/9/assets/assets/a15.png" in out["questions"][0]["rubric"]


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

## Q1 [single] (5) {media=assets/media.png, answer_time=60s}
题干 ![](assets/q1.png)

- A*) 正确
- B) 错误
""".strip()
        + "\n",
    )

    candidate = _build_exam_candidate(tmp_path, "https://example.com/repo.git", "deadbeef", "quizzes/demo/quiz.md")

    assert candidate["source_path"] == "quizzes/demo/quiz.md"
    assert set(candidate["assets"].keys()) == {"assets/media.png", "assets/q1.png", "assets/welcome.png"}


def test_build_exam_candidate_normalizes_tags_and_rebuilds_quiz_metadata(tmp_path):
    _write_manifest(tmp_path, "quizzes/demo/quiz.md")
    _write_text(
        tmp_path / "quizzes/demo/quiz.md",
        """
---
id: demo
title: Demo
tags:
  - personality
  - traits
  - personality
  - "  self-assessment  "
  - ""
question_count: 999
question_counts:
  single: 999
estimated_duration_minutes: 1
trait:
  dimensions: [I, E]
---

## Q1 [single] (5) {answer_time=120s}
题目一

- A*) 正确
- B) 错误

## Q2 [short] {max=10, answer_time=600s}
题目二

[rubric]
给出关键点即可。
[/rubric]
""".strip()
        + "\n",
    )

    candidate = _build_exam_candidate(tmp_path, "https://example.com/repo.git", "deadbeef", "quizzes/demo/quiz.md")

    assert candidate["spec"]["tags"] == ["personality", "traits", "self-assessment"]
    assert candidate["public_spec"]["tags"] == candidate["spec"]["tags"]
    assert candidate["spec"]["schema_version"] == 2
    assert candidate["public_spec"]["schema_version"] == 2
    assert candidate["spec"]["question_count"] == 2
    assert candidate["public_spec"]["question_count"] == 2
    assert candidate["spec"]["question_counts"] == {"single": 1, "multiple": 0, "short": 1}
    assert candidate["public_spec"]["question_counts"] == {"single": 1, "multiple": 0, "short": 1}
    assert candidate["spec"]["estimated_duration_minutes"] == 12
    assert candidate["public_spec"]["estimated_duration_minutes"] == 12
    assert candidate["spec"]["trait"] == {"dimensions": ["I", "E"]}


def test_build_exam_candidate_rejects_non_string_tags(tmp_path):
    _write_manifest(tmp_path, "quizzes/demo/quiz.md")
    _write_text(
        tmp_path / "quizzes/demo/quiz.md",
        """
---
id: demo
tags:
  - demo
  - 1
---

## Q1 [single] (5) {answer_time=60s}
题目一

- A*) 正确
- B) 错误
""".strip()
        + "\n",
    )

    with pytest.raises(ExamRepoSyncError, match="tags"):
        _build_exam_candidate(tmp_path, "https://example.com/repo.git", "deadbeef", "quizzes/demo/quiz.md")


def test_sync_exam_candidate_persists_quiz_metadata(monkeypatch):
    captured: dict[str, dict[str, object]] = {}
    candidate = {
        "quiz_key": "demo",
        "title": "Demo",
        "source_path": "quizzes/demo/quiz.md",
        "git_repo_url": "https://example.com/repo.git",
        "git_commit": "deadbeef",
        "markdown_text": "---\nid: demo\n---\n",
        "spec": {
            "id": "demo",
            "title": "Demo",
            "tags": ["traits", "personality"],
            "schema_version": 2,
            "format": "qml-v2",
            "question_count": 1,
            "question_counts": {"single": 1, "multiple": 0, "short": 0},
            "estimated_duration_minutes": 2,
            "trait": {"dimensions": ["I", "E"]},
            "questions": [{"qid": "Q1", "type": "single", "max_points": 5, "stem_md": "题目一", "answer_time_seconds": 120}],
        },
        "public_spec": {
            "id": "demo",
            "title": "Demo",
            "tags": ["traits", "personality"],
            "schema_version": 2,
            "format": "qml-v2",
            "question_count": 1,
            "question_counts": {"single": 1, "multiple": 0, "short": 0},
            "estimated_duration_minutes": 2,
            "trait": {"dimensions": ["I", "E"]},
            "questions": [{"qid": "Q1", "type": "single", "max_points": 5, "stem_md": "题目一", "answer_time_seconds": 120}],
        },
        "assets": {},
        "content_hash": "hash-demo",
    }

    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.find_quiz_version_by_hash", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.list_quiz_versions", lambda quiz_key: [])
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.create_quiz_version", lambda **kwargs: 9)
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.replace_quiz_version_assets", lambda *args, **kwargs: None)

    def _capture_payload(version_id, *, title, source_md, spec, public_spec):
        captured["payload"] = {"spec": spec, "public_spec": public_spec, "title": title, "source_md": source_md}
        return 1

    def _capture_definition(**kwargs):
        captured["definition"] = {"spec": kwargs["spec"], "public_spec": kwargs["public_spec"], "title": kwargs["title"]}

    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.update_quiz_version_payload", _capture_payload)
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.save_quiz_definition", _capture_definition)

    result = _sync_exam_candidate(candidate, synced_at="2026-04-01T00:00:00+00:00")

    assert result["action"] == "created"
    assert captured["payload"]["spec"]["tags"] == ["traits", "personality"]
    assert captured["payload"]["spec"]["question_counts"] == {"single": 1, "multiple": 0, "short": 0}
    assert captured["payload"]["spec"]["estimated_duration_minutes"] == 2
    assert captured["definition"]["public_spec"]["tags"] == ["traits", "personality"]
    assert captured["definition"]["public_spec"]["trait"] == {"dimensions": ["I", "E"]}


def test_build_exam_candidate_rejects_cross_quiz_asset(tmp_path):
    _write_manifest(tmp_path, "quizzes/demo/quiz.md")
    _write_text(
        tmp_path / "quizzes/demo/quiz.md",
        """
---
id: demo
title: Demo
---

## Q1 [single] (5) {answer_time=60s}
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

## Q1 [single] (5) {answer_time=60s}
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

## Q1 [single] (5) {answer_time=60s}
题干 ![](./assets/q1.png)

- A*) 正确
- B) 错误
""".strip()
            + "\n",
        )
        return "deadbeef"

    def _fake_sync(candidate, *, synced_at):
        captured.append(candidate)
        return {"quiz_key": "demo", "version_id": 1, "version_no": 1, "action": "created"}

    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service._clone_repo", _fake_clone)
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service._sync_exam_candidate", _fake_sync)
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service._write_git_sync_state", lambda **kwargs: kwargs)
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.list_quiz_definitions", lambda: [])

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
        "quiz_key": "demo",
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
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.list_quiz_definitions", lambda: [existing_exam])
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.get_quiz_definition", lambda quiz_key: dict(existing_exam) if quiz_key == "demo" else None)
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.set_exam_public_invite", lambda *args, **kwargs: None)

    def _record_save(**kwargs):
        saved_statuses.append(str(kwargs.get("status") or ""))

    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service.save_quiz_definition", _record_save)

    result = perform_exam_repo_sync("https://example.com/repo.git")

    assert result["error_count"] == 1
    assert result["retired_exams"] == 0
    assert saved_statuses == ["sync_error"]


def test_perform_exam_repo_sync_deletes_missing_quiz_not_in_current_manifest(monkeypatch):
    deleted_quiz_keys: list[str] = []

    def _fake_clone(repo_url, workdir):
        _write_manifest(workdir, "quizzes/keep/quiz.md")
        _write_text(
            workdir / "quizzes/keep/quiz.md",
            """
---
id: keep
title: Keep
format: qml-v2
---

## Q1 [single] (5) {answer_time=60s}
题目一

- A*) 正确
""".strip()
            + "\n",
        )
        return "deadbeef"

    def _fake_build(repo_root, repo_url, git_commit, source_path):
        return {
            "quiz_key": "keep",
            "title": "Keep",
            "source_md": "---\nid: keep\n---\n",
            "spec": {"id": "keep", "title": "Keep", "questions": []},
            "public_spec": {"id": "keep", "title": "Keep", "questions": []},
            "source_path": source_path,
            "git_repo_url": repo_url,
            "git_commit": git_commit,
            "content_hash": "hash-keep",
            "assets": {},
        }

    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service._clone_repo", _fake_clone)
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service._build_exam_candidate", _fake_build)
    monkeypatch.setattr(
        "backend.md_quiz.services.exam_repo_sync_service._sync_exam_candidate",
        lambda candidate, synced_at: {"quiz_key": "keep", "action": "unchanged"},
    )
    monkeypatch.setattr("backend.md_quiz.services.exam_repo_sync_service._write_git_sync_state", lambda **kwargs: kwargs)
    monkeypatch.setattr(
        "backend.md_quiz.services.exam_repo_sync_service.list_quiz_definitions",
        lambda: [
            {
                "quiz_key": "keep",
                "source_path": "quizzes/keep/quiz.md",
                "git_repo_url": "https://example.com/repo.git",
            },
            {
                "quiz_key": "remove-me",
                "source_path": "quizzes/remove-me/quiz.md",
                "git_repo_url": "https://example.com/repo.git",
            },
            {
                "quiz_key": "other-repo",
                "source_path": "quizzes/other/quiz.md",
                "git_repo_url": "https://example.com/other.git",
            },
        ],
    )
    monkeypatch.setattr(
        "backend.md_quiz.services.exam_repo_sync_service.delete_exam_domain_data_by_quiz_key",
        lambda quiz_key: deleted_quiz_keys.append(str(quiz_key)) or {"quiz_definition": 1},
    )

    result = perform_exam_repo_sync("https://example.com/repo.git")

    assert deleted_quiz_keys == ["remove-me", "other-repo"]
    assert result["retired_exams"] == 2
    assert result["deleted_exams"] == 2
