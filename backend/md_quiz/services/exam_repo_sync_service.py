from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from backend.md_quiz.services import (
    exam_repo_sync_apply as apply_ops,
    exam_repo_sync_migration as migration_ops,
    exam_repo_sync_repo as repo_ops,
    exam_repo_sync_state as state_ops,
)
from backend.md_quiz.services.exam_repo_sync_shared import (
    EXAM_SYNC_JOB_KIND,
    ExamRepoSyncError,
    _utc_now,
)


def read_exam_repo_sync_state() -> dict:
    return state_ops.read_exam_repo_sync_state()


def read_exam_repo_binding() -> dict:
    return state_ops.read_exam_repo_binding()


def enqueue_exam_repo_sync(repo_url: str | None = None) -> dict:
    return state_ops.enqueue_exam_repo_sync(repo_url)


def bind_exam_repo(repo_url: str) -> dict:
    return state_ops.bind_exam_repo(repo_url)


def rebind_exam_repo(repo_url: str) -> dict:
    return state_ops.rebind_exam_repo(repo_url)


def perform_exam_repo_sync(repo_url: str, *, job_id: str | None = None) -> dict:
    normalized_url = repo_ops._normalize_repo_url(repo_url)
    started_at = _utc_now()
    state_ops._write_git_sync_state(
        repo_url=normalized_url,
        last_job_id=job_id or "",
        status="running",
        started_at=started_at,
        last_error="",
    )
    try:
        with tempfile.TemporaryDirectory(prefix="exam-sync-") as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            git_commit = repo_ops._clone_repo(normalized_url, repo_root)
            synced_at = datetime.now(UTC)
            source_paths = repo_ops._load_quiz_repo_manifest(repo_root)

            candidates: list[dict[str, object]] = []
            duplicate_guard: dict[str, str] = {}
            discovered_source_paths: set[str] = set()
            for source_path in source_paths:
                discovered_source_paths.add(source_path)
                markdown_text = (repo_root / source_path).read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
                exam_id = repo_ops._read_frontmatter_exam_id(markdown_text)
                if exam_id:
                    other = duplicate_guard.get(exam_id)
                    if other:
                        raise ExamRepoSyncError(f"仓库内存在重复测验 id：{exam_id}（{other} / {source_path}）")
                    duplicate_guard[exam_id] = source_path
                candidates.append({"source_path": source_path, "raw_exam_id": exam_id})

            discovered_quiz_keys: set[str] = set()
            created_count = 0
            updated_count = 0
            unchanged_count = 0
            error_count = 0
            repo_errors: list[dict[str, str]] = []

            for entry in candidates:
                source_path = str(entry.get("source_path") or "").strip()
                raw_exam_id = str(entry.get("raw_exam_id") or "").strip()
                if raw_exam_id:
                    discovered_quiz_keys.add(raw_exam_id)
                try:
                    candidate = repo_ops._build_exam_candidate(repo_root, normalized_url, git_commit, source_path)
                    result = apply_ops._sync_exam_candidate(candidate, synced_at=synced_at)
                    if result["action"] == "created":
                        created_count += 1
                    elif result["action"] == "updated":
                        updated_count += 1
                    else:
                        unchanged_count += 1
                except Exception as exc:
                    error_count += 1
                    quiz_key = raw_exam_id
                    if not quiz_key:
                        existing_by_path = repo_ops._find_existing_exam_by_source_path(normalized_url, source_path)
                        quiz_key = str((existing_by_path or {}).get("quiz_key") or "").strip()
                    message = str(exc)
                    repo_errors.append({"source_path": source_path, "quiz_key": quiz_key, "error": message})
                    if quiz_key:
                        apply_ops._mark_exam_sync_error(
                            quiz_key=quiz_key,
                            source_path=source_path,
                            repo_url=normalized_url,
                            git_commit=git_commit,
                            message=message,
                            synced_at=synced_at,
                        )

            deleted_count = 0
            for exam in repo_ops.list_quiz_definitions():
                quiz_key = str(exam.get("quiz_key") or "").strip()
                if not quiz_key:
                    continue
                if quiz_key in discovered_quiz_keys:
                    continue
                source_path = str(exam.get("source_path") or "").strip()
                if source_path and source_path in discovered_source_paths:
                    continue
                cleanup = apply_ops.delete_exam_domain_data_by_quiz_key(quiz_key)
                if int(cleanup.get("quiz_definition") or 0) > 0:
                    deleted_count += 1

            finished_at = _utc_now()
            result = {
                "repo_url": normalized_url,
                "git_commit": git_commit,
                "scanned_md": len(source_paths),
                "created_versions": created_count,
                "updated_versions": updated_count,
                "unchanged_versions": unchanged_count,
                "retired_exams": deleted_count,
                "deleted_exams": deleted_count,
                "error_count": error_count,
                "errors": repo_errors,
                "started_at": started_at,
                "finished_at": finished_at,
            }
            state_ops._write_git_sync_state(
                repo_url=normalized_url,
                last_job_id=job_id or "",
                status="done",
                last_commit=git_commit,
                last_error="",
                last_result=result,
                started_at=started_at,
                finished_at=finished_at,
            )
            return result
    except Exception as exc:
        finished_at = _utc_now()
        state_ops._write_git_sync_state(
            repo_url=normalized_url,
            last_job_id=job_id or "",
            status="failed",
            last_error=str(exc),
            started_at=started_at,
            finished_at=finished_at,
        )
        raise


def migrate_legacy_exam_data() -> None:
    migration_ops.migrate_legacy_exam_data()


__all__ = [
    "EXAM_SYNC_JOB_KIND",
    "ExamRepoSyncError",
    "bind_exam_repo",
    "enqueue_exam_repo_sync",
    "migrate_legacy_exam_data",
    "perform_exam_repo_sync",
    "read_exam_repo_binding",
    "read_exam_repo_sync_state",
    "rebind_exam_repo",
]
