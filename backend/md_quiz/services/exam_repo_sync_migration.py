from __future__ import annotations

from backend.md_quiz.services.exam_repo_sync_apply import (
    _rewrite_archive_asset_urls,
    _rewrite_asset_paths_for_version,
)
from backend.md_quiz.services.exam_repo_sync_repo import _snapshot_hash
from backend.md_quiz.services.exam_repo_sync_shared import EXAM_SYNC_MIGRATION_KEY, _utc_now
from backend.md_quiz.storage.db import (
    backfill_assignment_quiz_version_id,
    backfill_quiz_archive_version_id,
    backfill_quiz_paper_version_id,
    create_quiz_version,
    get_runtime_kv,
    list_quiz_archives_by_quiz_key,
    list_quiz_assets,
    list_quiz_definitions,
    list_quiz_versions,
    replace_quiz_version_assets,
    save_quiz_archive,
    save_quiz_definition,
    set_runtime_kv,
    update_quiz_version_payload,
)


def migrate_legacy_exam_data() -> None:
    marker = get_runtime_kv(EXAM_SYNC_MIGRATION_KEY) or {}
    if bool(marker.get("done")):
        return
    migrated = 0
    for exam in list_quiz_definitions():
        quiz_key = str(exam.get("quiz_key") or "").strip()
        if not quiz_key:
            continue
        if list_quiz_versions(quiz_key):
            continue
        title = str(exam.get("title") or "").strip()
        source_md = str(exam.get("source_md") or "")
        spec = exam.get("spec") or {}
        public_spec = exam.get("public_spec") or {}
        legacy_assets = {
            str(item.get("relpath") or "").strip(): (bytes(item.get("content") or b""), str(item.get("mime") or "application/octet-stream"))
            for item in list_quiz_assets(quiz_key)
            if str(item.get("relpath") or "").strip()
        }
        content_hash = _snapshot_hash(source_md, legacy_assets)
        version_id = create_quiz_version(
            quiz_key=quiz_key,
            version_no=1,
            title=title,
            source_path=None,
            git_repo_url=None,
            git_commit=None,
            content_hash=content_hash,
            source_md=source_md,
            spec=spec,
            public_spec=public_spec,
        )
        if legacy_assets:
            replace_quiz_version_assets(version_id, legacy_assets)
        rewritten_spec, rewritten_public = _rewrite_asset_paths_for_version(version_id, spec, public_spec)
        update_quiz_version_payload(
            version_id,
            title=title,
            source_md=source_md,
            spec=rewritten_spec,
            public_spec=rewritten_public,
        )
        save_quiz_definition(
            quiz_key=quiz_key,
            title=title,
            source_md=source_md,
            spec=rewritten_spec,
            public_spec=rewritten_public,
            status=str(exam.get("status") or "active") or "active",
            source_path=str(exam.get("source_path") or "").strip() or None,
            git_repo_url=str(exam.get("git_repo_url") or "").strip() or None,
            current_version_id=version_id,
            current_version_no=1,
            last_synced_commit=str(exam.get("last_synced_commit") or "").strip() or None,
            last_sync_error=str(exam.get("last_sync_error") or ""),
            last_sync_at=exam.get("last_sync_at"),
        )
        backfill_assignment_quiz_version_id(quiz_key, version_id)
        backfill_quiz_paper_version_id(quiz_key, version_id)
        backfill_quiz_archive_version_id(quiz_key, version_id)
        for row in list_quiz_archives_by_quiz_key(quiz_key):
            archive_payload = row.get("archive") if isinstance(row.get("archive"), dict) else {}
            rewritten_archive = _rewrite_archive_asset_urls(archive_payload, version_id=version_id)
            save_quiz_archive(
                archive_name=str(row.get("archive_name") or "").strip(),
                token=str(row.get("token") or "").strip(),
                candidate_id=(int(row.get("candidate_id")) if row.get("candidate_id") else None),
                quiz_key=quiz_key,
                quiz_version_id=version_id,
                phone=str(row.get("phone") or "").strip(),
                archive=rewritten_archive,
            )
        migrated += 1
    set_runtime_kv(
        EXAM_SYNC_MIGRATION_KEY,
        {"done": True, "migrated": migrated, "finished_at": _utc_now()},
    )


__all__ = ["migrate_legacy_exam_data"]
