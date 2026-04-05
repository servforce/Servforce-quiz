from __future__ import annotations

import copy
from typing import Any

from backend.md_quiz.services.exam_repo_sync_shared import (
    _HTML_IMG_SRC_RE,
    _HTML_VERSION_ASSET_RE,
    _LEGACY_ASSET_URL_RE,
    _MD_IMAGE_RE,
    _VERSION_ASSET_RE,
    _is_local_asset_path,
    _safe_relpath,
    _version_asset_url,
)
from backend.md_quiz.storage.db import (
    create_quiz_version,
    delete_exam_domain_data_by_quiz_key,
    find_quiz_version_by_hash,
    get_quiz_definition,
    list_quiz_versions,
    replace_quiz_version_assets,
    save_quiz_definition,
    set_exam_public_invite,
    update_quiz_version_metadata,
    update_quiz_version_payload,
)


def _rewrite_asset_paths_for_version(version_id: int, spec: dict[str, Any], public_spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    out_spec = copy.deepcopy(spec or {})
    out_public = copy.deepcopy(public_spec or {})

    def _rewrite_text(text: str) -> str:
        out = str(text or "")
        for match in list(_MD_IMAGE_RE.finditer(out)):
            raw_target = str(match.group("path") or "").strip()
            if _LEGACY_ASSET_URL_RE.match(raw_target):
                continue
            rel = _safe_relpath(raw_target)
            if rel and _is_local_asset_path(rel):
                out = out.replace(f"({match.group('path')})", f"({_version_asset_url(version_id, rel)})")

        def _replace_html_img(match) -> str:
            raw_target = str(match.group("path") or "").strip()
            if _LEGACY_ASSET_URL_RE.match(raw_target):
                return match.group(0)
            rel = _safe_relpath(raw_target)
            if not rel or not _is_local_asset_path(rel):
                return match.group(0)
            before = match.group("before") or ""
            quote = match.group("quote") or '"'
            after = match.group("after") or ""
            return f'<img{before}src={quote}{_version_asset_url(version_id, rel)}{quote}{after}>'

        def _replace_legacy_html_img(match) -> str:
            rel = _safe_relpath(match.group("path"))
            before = match.group("before") or ""
            quote = match.group("quote") or '"'
            after = match.group("after") or ""
            return f'<img{before}src={quote}{_version_asset_url(version_id, rel)}{quote}{after}>'

        out = _HTML_IMG_SRC_RE.sub(_replace_html_img, out)
        out = _VERSION_ASSET_RE.sub(lambda m: f"({_version_asset_url(version_id, m.group('path'))})", out)
        out = _HTML_VERSION_ASSET_RE.sub(_replace_legacy_html_img, out)
        return out

    def _rewrite_doc(doc: dict[str, Any]) -> None:
        for key in ("welcome_image", "end_image"):
            raw = str(doc.get(key) or "").strip()
            match = _LEGACY_ASSET_URL_RE.match(raw)
            if match:
                doc[key] = _version_asset_url(version_id, match.group("path"))
                continue
            value = _safe_relpath(raw)
            if value and _is_local_asset_path(value):
                doc[key] = _version_asset_url(version_id, value)
        for q in doc.get("questions") or []:
            stem = _rewrite_text(str(q.get("stem_md") or ""))
            rubric = _rewrite_text(str(q.get("rubric") or ""))
            media = _safe_relpath(str(q.get("media") or "").strip())
            media_match = _LEGACY_ASSET_URL_RE.match(str(q.get("media") or "").strip())
            if media_match:
                q["media"] = _version_asset_url(version_id, media_match.group("path"))
                q["stem_md"] = stem
                if q.get("rubric") is not None:
                    q["rubric"] = rubric
                continue
            if media and _is_local_asset_path(media):
                q["media"] = _version_asset_url(version_id, media)
            q["stem_md"] = stem
            if q.get("rubric") is not None:
                q["rubric"] = rubric

    _rewrite_doc(out_spec)
    _rewrite_doc(out_public)
    return out_spec, out_public


def _rewrite_archive_asset_urls(archive: dict[str, Any], *, version_id: int) -> dict[str, Any]:
    out = copy.deepcopy(archive or {})
    exam = out.get("exam") if isinstance(out.get("exam"), dict) else {}
    exam["quiz_version_id"] = int(version_id)
    for key in ("welcome_image", "end_image"):
        raw = str(exam.get(key) or "").strip()
        match = _LEGACY_ASSET_URL_RE.match(raw)
        if match:
            exam[key] = _version_asset_url(version_id, match.group("path"))
    out["exam"] = exam
    for item in out.get("questions") or []:
        stem = str(item.get("stem_md") or "")
        rubric = str(item.get("rubric") or "")
        media = str(item.get("media") or "").strip()
        media_match = _LEGACY_ASSET_URL_RE.match(media)
        if media_match:
            item["media"] = _version_asset_url(version_id, media_match.group("path"))

        def _replace(match) -> str:
            rel = _safe_relpath(match.group("path"))
            return f"({_version_asset_url(version_id, rel)})"

        def _replace_html(match) -> str:
            rel = _safe_relpath(match.group("path"))
            before = match.group("before") or ""
            quote = match.group("quote") or '"'
            after = match.group("after") or ""
            return f'<img{before}src={quote}{_version_asset_url(version_id, rel)}{quote}{after}>'

        if stem:
            stem = _VERSION_ASSET_RE.sub(_replace, stem)
            item["stem_md"] = _HTML_VERSION_ASSET_RE.sub(_replace_html, stem)
        if rubric:
            rubric = _VERSION_ASSET_RE.sub(_replace, rubric)
            item["rubric"] = _HTML_VERSION_ASSET_RE.sub(_replace_html, rubric)
    return out


def _sync_exam_candidate(candidate: dict[str, Any], *, synced_at) -> dict[str, Any]:
    quiz_key = str(candidate.get("quiz_key") or "").strip()
    title = str(candidate.get("title") or "").strip()
    source_path = str(candidate.get("source_path") or "").strip()
    repo_url = str(candidate.get("git_repo_url") or "").strip()
    git_commit = str(candidate.get("git_commit") or "").strip()
    markdown_text = str(candidate.get("markdown_text") or "")
    spec = candidate.get("spec") or {}
    public_spec = candidate.get("public_spec") or {}
    assets = dict(candidate.get("assets") or {})
    content_hash = str(candidate.get("content_hash") or "").strip()

    existing_version = find_quiz_version_by_hash(quiz_key, content_hash)
    if existing_version:
        version_id = int(existing_version.get("id") or 0)
        version_no = int(existing_version.get("version_no") or 0)
        update_quiz_version_metadata(
            version_id,
            title=title,
            source_path=source_path,
            git_repo_url=repo_url,
            git_commit=git_commit,
        )
        action = "unchanged"
    else:
        versions = list_quiz_versions(quiz_key)
        version_no = (max((int(item.get("version_no") or 0) for item in versions), default=0) + 1)
        version_id = create_quiz_version(
            quiz_key=quiz_key,
            version_no=version_no,
            title=title,
            source_path=source_path,
            git_repo_url=repo_url,
            git_commit=git_commit,
            content_hash=content_hash,
            source_md=markdown_text,
            spec=spec,
            public_spec=public_spec,
        )
        replace_quiz_version_assets(version_id, assets)
        action = "created" if version_no == 1 else "updated"

    rewritten_spec, rewritten_public = _rewrite_asset_paths_for_version(version_id, spec, public_spec)
    update_quiz_version_payload(
        version_id,
        title=title,
        source_md=markdown_text,
        spec=rewritten_spec,
        public_spec=rewritten_public,
    )
    save_quiz_definition(
        quiz_key=quiz_key,
        title=title,
        source_md=markdown_text,
        spec=rewritten_spec,
        public_spec=rewritten_public,
        status="active",
        source_path=source_path,
        git_repo_url=repo_url,
        current_version_id=version_id,
        current_version_no=version_no,
        last_synced_commit=git_commit,
        last_sync_error="",
        last_sync_at=synced_at,
    )
    return {
        "quiz_key": quiz_key,
        "version_id": version_id,
        "version_no": version_no,
        "action": action,
    }


def _mark_exam_sync_error(*, quiz_key: str, source_path: str, repo_url: str, git_commit: str, message: str, synced_at) -> None:
    existing = get_quiz_definition(quiz_key)
    title = str((existing or {}).get("title") or "").strip()
    source_md = str((existing or {}).get("source_md") or "")
    spec = (existing or {}).get("spec") or {}
    public_spec = (existing or {}).get("public_spec") or {}
    current_version_id = int((existing or {}).get("current_version_id") or 0) or None
    current_version_no = int((existing or {}).get("current_version_no") or 0) or None
    save_quiz_definition(
        quiz_key=quiz_key,
        title=title,
        source_md=source_md,
        spec=spec,
        public_spec=public_spec,
        status="sync_error",
        source_path=source_path,
        git_repo_url=repo_url,
        current_version_id=current_version_id,
        current_version_no=current_version_no,
        last_synced_commit=git_commit,
        last_sync_error=message,
        last_sync_at=synced_at,
    )
    if existing and bool(existing.get("public_invite_enabled")):
        set_exam_public_invite(quiz_key, enabled=False, token=str(existing.get("public_invite_token") or "").strip() or None)


__all__ = [
    "_mark_exam_sync_error",
    "_rewrite_archive_asset_urls",
    "_rewrite_asset_paths_for_version",
    "_sync_exam_candidate",
]
