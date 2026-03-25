from __future__ import annotations

import copy
import hashlib
import mimetypes
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from config import STORAGE_DIR, logger
from db import (
    backfill_assignment_exam_version_id,
    backfill_exam_archive_version_id,
    backfill_exam_paper_version_id,
    create_exam_version,
    find_exam_version_by_hash,
    get_exam_definition,
    get_runtime_kv,
    list_exam_archives_by_exam_key,
    list_exam_assets,
    list_exam_definitions,
    list_exam_versions,
    replace_exam_version_assets,
    save_exam_archive,
    save_exam_definition,
    set_exam_public_invite,
    set_runtime_kv,
    update_exam_version_metadata,
    update_exam_version_payload,
)
from qml.parser import QmlParseError, parse_qml_markdown

EXAM_SYNC_JOB_KIND = "git_sync_exams"
EXAM_SYNC_STATE_KEY = "exam_repo_sync"
EXAM_SYNC_MIGRATION_KEY = "exam_repo_sync_migration"
IMAGE_MAX_BYTES = 1024 * 1024

_MD_IMAGE_RE = re.compile(r"!\[[^\]]*]\((?P<path>[^)]+)\)")
_MD_LINK_RE = re.compile(r"(?<!\!)\[[^\]]*]\((?P<path>[^)]+)\)")
_FRONTMATTER_ID_RE = re.compile(r"(?mi)^id:\s*(?P<id>[A-Za-z0-9_-]+)\s*$")
_VERSION_ASSET_RE = re.compile(r"\(/exams/[^)]+/assets/(?P<path>[^)]+)\)")
_LEGACY_ASSET_URL_RE = re.compile(r"^/exams/[^/]+/assets/(?P<path>.+)$")
_SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}


class ExamRepoSyncError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _jobs_store():
    from backend.md_quiz.storage.job_store import JsonJobStore

    runtime_root = Path(STORAGE_DIR).resolve() / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    return JsonJobStore(runtime_root / "jobs.json")


def _safe_relpath(raw: str) -> str:
    value = str(raw or "").strip().strip('"').strip("'")
    value = value.split("#", 1)[0].strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value.lstrip("/")


def _is_local_asset_path(path: str) -> bool:
    if not path:
        return False
    lower = path.lower()
    return not lower.startswith(("http://", "https://", "data:", "mailto:"))


def _version_asset_url(version_id: int, relpath: str) -> str:
    return f"/exams/versions/{int(version_id)}/assets/{_safe_relpath(relpath)}"


def _rewrite_asset_paths_for_version(version_id: int, spec: dict[str, Any], public_spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    out_spec = copy.deepcopy(spec or {})
    out_public = copy.deepcopy(public_spec or {})

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
            stem = str(q.get("stem_md") or "")
            for match in list(_MD_IMAGE_RE.finditer(stem)):
                rel = _safe_relpath(match.group("path"))
                if rel and _is_local_asset_path(rel):
                    stem = stem.replace(f"({match.group('path')})", f"({_version_asset_url(version_id, rel)})")
            stem = _VERSION_ASSET_RE.sub(lambda m: f"({_version_asset_url(version_id, m.group('path'))})", stem)
            media = _safe_relpath(str(q.get("media") or "").strip())
            media_match = _LEGACY_ASSET_URL_RE.match(str(q.get("media") or "").strip())
            if media_match:
                q["media"] = _version_asset_url(version_id, media_match.group("path"))
                q["stem_md"] = stem
                continue
            if media and _is_local_asset_path(media):
                q["media"] = _version_asset_url(version_id, media)
            q["stem_md"] = stem

    _rewrite_doc(out_spec)
    _rewrite_doc(out_public)
    return out_spec, out_public


def _rewrite_archive_asset_urls(archive: dict[str, Any], *, version_id: int) -> dict[str, Any]:
    out = copy.deepcopy(archive or {})
    exam = out.get("exam") if isinstance(out.get("exam"), dict) else {}
    exam["exam_version_id"] = int(version_id)
    for key in ("welcome_image", "end_image"):
        raw = str(exam.get(key) or "").strip()
        match = _LEGACY_ASSET_URL_RE.match(raw)
        if match:
            exam[key] = _version_asset_url(version_id, match.group("path"))
    out["exam"] = exam
    for item in out.get("questions") or []:
        stem = str(item.get("stem_md") or "")
        media = str(item.get("media") or "").strip()
        media_match = _LEGACY_ASSET_URL_RE.match(media)
        if media_match:
            item["media"] = _version_asset_url(version_id, media_match.group("path"))
        if not stem:
            continue

        def _replace(match: re.Match[str]) -> str:
            rel = _safe_relpath(match.group("path"))
            return f"({_version_asset_url(version_id, rel)})"

        item["stem_md"] = _VERSION_ASSET_RE.sub(_replace, stem)
    return out


def _normalize_repo_url(repo_url: str) -> str:
    value = str(repo_url or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ExamRepoSyncError("只支持公共只读 HTTPS Git 仓库地址")
    return value


def _find_existing_exam_by_source_path(repo_url: str, source_path: str) -> dict[str, Any] | None:
    target_repo = str(repo_url or "").strip()
    target_path = str(source_path or "").strip()
    if not target_repo or not target_path:
        return None
    for row in list_exam_definitions():
        if str(row.get("git_repo_url") or "").strip() != target_repo:
            continue
        if str(row.get("source_path") or "").strip() != target_path:
            continue
        return row
    return None


def _read_frontmatter_exam_id(markdown_text: str) -> str:
    text = str(markdown_text or "")
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end < 0:
        return ""
    front = text[: end + 1]
    match = _FRONTMATTER_ID_RE.search(front)
    return str(match.group("id") if match else "").strip()


def _validate_markdown_links(markdown_text: str) -> None:
    for match in _MD_LINK_RE.finditer(markdown_text or ""):
        target = _safe_relpath(match.group("path"))
        if not target or target.startswith("#"):
            continue
        raise ExamRepoSyncError(f"Markdown 只允许引用图片，发现非法链接：{target}")


def _collect_assets(markdown_text: str, spec: dict[str, Any]) -> list[str]:
    refs: set[str] = set()
    for match in _MD_IMAGE_RE.finditer(markdown_text or ""):
        rel = _safe_relpath(match.group("path"))
        if rel and _is_local_asset_path(rel):
            refs.add(rel)
    for key in ("welcome_image", "end_image"):
        rel = _safe_relpath(str(spec.get(key) or "").strip())
        if rel and _is_local_asset_path(rel):
            refs.add(rel)
    for q in spec.get("questions") or []:
        rel = _safe_relpath(str(q.get("media") or "").strip())
        if rel and _is_local_asset_path(rel):
            refs.add(rel)
    return sorted(refs)


def _load_assets(repo_root: Path, refs: list[str]) -> dict[str, tuple[bytes, str]]:
    assets: dict[str, tuple[bytes, str]] = {}
    for rel in refs:
        safe = _safe_relpath(rel)
        if not safe or any(part == ".." for part in Path(safe).parts):
            raise ExamRepoSyncError(f"资源路径非法：{rel}")
        if not safe.startswith("images/"):
            raise ExamRepoSyncError(f"图片必须位于仓库根目录 images/ 下：{rel}")
        suffix = Path(safe).suffix.lower()
        if suffix not in _SUPPORTED_IMAGE_EXTS:
            raise ExamRepoSyncError(f"只允许同步图片资源：{rel}")
        abs_path = (repo_root / safe).resolve()
        if repo_root.resolve() not in abs_path.parents and abs_path != repo_root.resolve():
            raise ExamRepoSyncError(f"资源路径越界：{rel}")
        if not abs_path.exists() or not abs_path.is_file():
            raise ExamRepoSyncError(f"缺少被引用的图片资源：{rel}")
        raw = abs_path.read_bytes()
        if len(raw) > IMAGE_MAX_BYTES:
            raise ExamRepoSyncError(f"图片超过 1MB 限制：{rel}")
        mime = mimetypes.guess_type(str(abs_path.name))[0] or "application/octet-stream"
        if not mime.startswith("image/"):
            raise ExamRepoSyncError(f"资源不是图片：{rel}")
        assets[safe] = (raw, mime)
    return assets


def _snapshot_hash(markdown_text: str, assets: dict[str, tuple[bytes, str]]) -> str:
    hasher = hashlib.sha256()
    normalized = str(markdown_text or "").replace("\r\n", "\n").encode("utf-8", errors="ignore")
    hasher.update(normalized)
    for rel in sorted(assets.keys()):
        payload, _mime = assets[rel]
        hasher.update(rel.encode("utf-8", errors="ignore"))
        hasher.update(b"\0")
        hasher.update(hashlib.sha256(payload).digest())
    return hasher.hexdigest()


def _clone_repo(repo_url: str, workdir: Path) -> str:
    subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, str(workdir)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    proc = subprocess.run(
        ["git", "-C", str(workdir), "rev-parse", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return str(proc.stdout or "").strip()


def _read_git_sync_state() -> dict[str, Any]:
    return get_runtime_kv(EXAM_SYNC_STATE_KEY) or {}


def read_exam_repo_sync_state() -> dict[str, Any]:
    return _read_git_sync_state()


def _write_git_sync_state(**updates: Any) -> dict[str, Any]:
    current = _read_git_sync_state()
    current.update(updates)
    set_runtime_kv(EXAM_SYNC_STATE_KEY, current)
    return current


def enqueue_exam_repo_sync(repo_url: str) -> dict[str, Any]:
    normalized_url = _normalize_repo_url(repo_url)
    store = _jobs_store()
    existing = next(
        (job for job in store.list_jobs() if job.kind == EXAM_SYNC_JOB_KIND and job.status in {"pending", "running"}),
        None,
    )
    if existing is not None:
        _write_git_sync_state(repo_url=normalized_url)
        return {"job_id": existing.id, "created": False, "status": existing.status}
    job = store.enqueue(EXAM_SYNC_JOB_KIND, payload={"repo_url": normalized_url}, source="admin")
    _write_git_sync_state(
        repo_url=normalized_url,
        last_job_id=job.id,
        status="queued",
        queued_at=job.created_at,
        last_error="",
    )
    return {"job_id": job.id, "created": True, "status": job.status}


def _build_exam_candidate(repo_root: Path, repo_url: str, git_commit: str, md_path: Path) -> dict[str, Any]:
    markdown_text = md_path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    _validate_markdown_links(markdown_text)
    raw_exam_id = _read_frontmatter_exam_id(markdown_text)
    if not raw_exam_id:
        raise ExamRepoSyncError("Front matter 缺少 id")
    try:
        spec, public_spec = parse_qml_markdown(markdown_text)
    except QmlParseError as exc:
        raise ExamRepoSyncError(f"{exc}（line={exc.line}）") from exc
    if str(spec.get("id") or "").strip() != raw_exam_id:
        raise ExamRepoSyncError("试卷 id 解析异常")
    assets = _load_assets(repo_root, _collect_assets(markdown_text, spec))
    content_hash = _snapshot_hash(markdown_text, assets)
    return {
        "exam_key": raw_exam_id,
        "title": str(spec.get("title") or "").strip(),
        "source_path": md_path.name,
        "git_repo_url": repo_url,
        "git_commit": git_commit,
        "markdown_text": markdown_text,
        "spec": spec,
        "public_spec": public_spec,
        "assets": assets,
        "content_hash": content_hash,
    }


def _sync_exam_candidate(candidate: dict[str, Any], *, synced_at) -> dict[str, Any]:
    exam_key = str(candidate.get("exam_key") or "").strip()
    title = str(candidate.get("title") or "").strip()
    source_path = str(candidate.get("source_path") or "").strip()
    repo_url = str(candidate.get("git_repo_url") or "").strip()
    git_commit = str(candidate.get("git_commit") or "").strip()
    markdown_text = str(candidate.get("markdown_text") or "")
    spec = candidate.get("spec") or {}
    public_spec = candidate.get("public_spec") or {}
    assets = dict(candidate.get("assets") or {})
    content_hash = str(candidate.get("content_hash") or "").strip()

    existing_version = find_exam_version_by_hash(exam_key, content_hash)
    if existing_version:
        version_id = int(existing_version.get("id") or 0)
        version_no = int(existing_version.get("version_no") or 0)
        update_exam_version_metadata(
            version_id,
            title=title,
            source_path=source_path,
            git_repo_url=repo_url,
            git_commit=git_commit,
        )
        version = existing_version
        action = "unchanged"
    else:
        versions = list_exam_versions(exam_key)
        version_no = (max((int(item.get("version_no") or 0) for item in versions), default=0) + 1)
        version_id = create_exam_version(
            exam_key=exam_key,
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
        replace_exam_version_assets(version_id, assets)
        version = {"id": version_id, "version_no": version_no}
        action = "created" if version_no == 1 else "updated"

    rewritten_spec, rewritten_public = _rewrite_asset_paths_for_version(version_id, spec, public_spec)
    update_exam_version_payload(
        version_id,
        title=title,
        source_md=markdown_text,
        spec=rewritten_spec,
        public_spec=rewritten_public,
    )
    save_exam_definition(
        exam_key=exam_key,
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
        "exam_key": exam_key,
        "version_id": version_id,
        "version_no": version_no,
        "action": action,
    }


def _mark_exam_sync_error(*, exam_key: str, source_path: str, repo_url: str, git_commit: str, message: str, synced_at) -> None:
    existing = get_exam_definition(exam_key)
    title = str((existing or {}).get("title") or "").strip()
    source_md = str((existing or {}).get("source_md") or "")
    spec = (existing or {}).get("spec") or {}
    public_spec = (existing or {}).get("public_spec") or {}
    current_version_id = int((existing or {}).get("current_version_id") or 0) or None
    current_version_no = int((existing or {}).get("current_version_no") or 0) or None
    save_exam_definition(
        exam_key=exam_key,
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
        set_exam_public_invite(exam_key, enabled=False, token=str(existing.get("public_invite_token") or "").strip() or None)


def perform_exam_repo_sync(repo_url: str, *, job_id: str | None = None) -> dict[str, Any]:
    normalized_url = _normalize_repo_url(repo_url)
    started_at = _utc_now()
    _write_git_sync_state(
        repo_url=normalized_url,
        last_job_id=job_id or "",
        status="running",
        started_at=started_at,
        last_error="",
    )
    try:
        with tempfile.TemporaryDirectory(prefix="exam-sync-") as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            git_commit = _clone_repo(normalized_url, repo_root)
            synced_at = datetime.now(UTC)
            md_paths = sorted([path for path in repo_root.iterdir() if path.is_file() and path.suffix.lower() == ".md"], key=lambda p: p.name.lower())

            candidates: list[dict[str, Any]] = []
            duplicate_guard: dict[str, str] = {}
            discovered_source_paths: set[str] = set()
            for md_path in md_paths:
                discovered_source_paths.add(md_path.name)
                markdown_text = md_path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
                exam_id = _read_frontmatter_exam_id(markdown_text)
                if exam_id:
                    other = duplicate_guard.get(exam_id)
                    if other:
                        raise ExamRepoSyncError(f"仓库内存在重复试卷 id：{exam_id}（{other} / {md_path.name}）")
                    duplicate_guard[exam_id] = md_path.name
                candidates.append(
                    {
                        "path": md_path,
                        "raw_exam_id": exam_id,
                    }
                )

            seen_exam_keys: set[str] = set()
            discovered_exam_keys: set[str] = set()
            created_count = 0
            updated_count = 0
            unchanged_count = 0
            error_count = 0
            repo_errors: list[dict[str, str]] = []

            for entry in candidates:
                md_path = entry["path"]
                raw_exam_id = str(entry.get("raw_exam_id") or "").strip()
                if raw_exam_id:
                    discovered_exam_keys.add(raw_exam_id)
                try:
                    candidate = _build_exam_candidate(repo_root, normalized_url, git_commit, md_path)
                    result = _sync_exam_candidate(candidate, synced_at=synced_at)
                    seen_exam_keys.add(str(result["exam_key"]))
                    if result["action"] == "created":
                        created_count += 1
                    elif result["action"] == "updated":
                        updated_count += 1
                    else:
                        unchanged_count += 1
                except Exception as exc:
                    error_count += 1
                    exam_key = raw_exam_id
                    if not exam_key:
                        existing_by_path = _find_existing_exam_by_source_path(normalized_url, md_path.name)
                        exam_key = str((existing_by_path or {}).get("exam_key") or "").strip()
                    message = str(exc)
                    repo_errors.append({"source_path": md_path.name, "exam_key": exam_key, "error": message})
                    if exam_key:
                        _mark_exam_sync_error(
                            exam_key=exam_key,
                            source_path=md_path.name,
                            repo_url=normalized_url,
                            git_commit=git_commit,
                            message=message,
                            synced_at=synced_at,
                        )

            retired_count = 0
            for exam in list_exam_definitions():
                exam_key = str(exam.get("exam_key") or "").strip()
                if not exam_key:
                    continue
                if str(exam.get("git_repo_url") or "").strip() != normalized_url:
                    continue
                if exam_key in discovered_exam_keys:
                    continue
                source_path = str(exam.get("source_path") or "").strip()
                if source_path and source_path in discovered_source_paths:
                    continue
                status = str(exam.get("status") or "").strip() or "active"
                if status != "retired":
                    retired_count += 1
                save_exam_definition(
                    exam_key=exam_key,
                    title=str(exam.get("title") or "").strip(),
                    source_md=str(exam.get("source_md") or ""),
                    spec=exam.get("spec") or {},
                    public_spec=exam.get("public_spec") or {},
                    status="retired",
                    source_path=str(exam.get("source_path") or "").strip() or None,
                    git_repo_url=normalized_url,
                    current_version_id=(int(exam.get("current_version_id") or 0) or None),
                    current_version_no=(int(exam.get("current_version_no") or 0) or None),
                    last_synced_commit=git_commit,
                    last_sync_error="",
                    last_sync_at=synced_at,
                )
                if bool(exam.get("public_invite_enabled")):
                    set_exam_public_invite(exam_key, enabled=False, token=str(exam.get("public_invite_token") or "").strip() or None)

            finished_at = _utc_now()
            result = {
                "repo_url": normalized_url,
                "git_commit": git_commit,
                "scanned_md": len(md_paths),
                "created_versions": created_count,
                "updated_versions": updated_count,
                "unchanged_versions": unchanged_count,
                "retired_exams": retired_count,
                "error_count": error_count,
                "errors": repo_errors,
                "started_at": started_at,
                "finished_at": finished_at,
            }
            _write_git_sync_state(
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
        _write_git_sync_state(
            repo_url=normalized_url,
            last_job_id=job_id or "",
            status="failed",
            last_error=str(exc),
            started_at=started_at,
            finished_at=finished_at,
        )
        raise


def migrate_legacy_exam_data() -> None:
    marker = get_runtime_kv(EXAM_SYNC_MIGRATION_KEY) or {}
    if bool(marker.get("done")):
        return
    migrated = 0
    for exam in list_exam_definitions():
        exam_key = str(exam.get("exam_key") or "").strip()
        if not exam_key:
            continue
        if list_exam_versions(exam_key):
            continue
        title = str(exam.get("title") or "").strip()
        source_md = str(exam.get("source_md") or "")
        spec = exam.get("spec") or {}
        public_spec = exam.get("public_spec") or {}
        legacy_assets = {
            str(item.get("relpath") or "").strip(): (bytes(item.get("content") or b""), str(item.get("mime") or "application/octet-stream"))
            for item in list_exam_assets(exam_key)
            if str(item.get("relpath") or "").strip()
        }
        content_hash = _snapshot_hash(source_md, legacy_assets)
        version_id = create_exam_version(
            exam_key=exam_key,
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
            replace_exam_version_assets(version_id, legacy_assets)
        rewritten_spec, rewritten_public = _rewrite_asset_paths_for_version(version_id, spec, public_spec)
        update_exam_version_payload(
            version_id,
            title=title,
            source_md=source_md,
            spec=rewritten_spec,
            public_spec=rewritten_public,
        )
        save_exam_definition(
            exam_key=exam_key,
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
        backfill_assignment_exam_version_id(exam_key, version_id)
        backfill_exam_paper_version_id(exam_key, version_id)
        backfill_exam_archive_version_id(exam_key, version_id)
        for row in list_exam_archives_by_exam_key(exam_key):
            archive_payload = row.get("archive") if isinstance(row.get("archive"), dict) else {}
            rewritten_archive = _rewrite_archive_asset_urls(archive_payload, version_id=version_id)
            save_exam_archive(
                archive_name=str(row.get("archive_name") or "").strip(),
                token=str(row.get("token") or "").strip(),
                candidate_id=(int(row.get("candidate_id")) if row.get("candidate_id") else None),
                exam_key=exam_key,
                exam_version_id=version_id,
                phone=str(row.get("phone") or "").strip(),
                archive=rewritten_archive,
            )
        migrated += 1
    set_runtime_kv(
        EXAM_SYNC_MIGRATION_KEY,
        {"done": True, "migrated": migrated, "finished_at": _utc_now()},
    )
