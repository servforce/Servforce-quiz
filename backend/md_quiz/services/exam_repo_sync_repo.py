from __future__ import annotations

import hashlib
import mimetypes
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from backend.md_quiz.config import EXAM_REPO_SYNC_PROXY
from backend.md_quiz.parsers.qml import QmlParseError, parse_qml_markdown
from backend.md_quiz.services.exam_repo_sync_shared import (
    IMAGE_MAX_BYTES,
    QUIZ_REPO_KIND,
    QUIZ_REPO_MANIFEST,
    QUIZ_REPO_SCHEMA_VERSION,
    ExamRepoSyncError,
    _FRONTMATTER_ID_RE,
    _HTML_IMG_SRC_RE,
    _LEGACY_ASSET_URL_RE,
    _MD_IMAGE_RE,
    _MD_LINK_RE,
    _QUIZ_PATH_RE,
    _SUPPORTED_IMAGE_EXTS,
    _is_local_asset_path,
    _legacy_repo_migration_hint,
    _normalize_repo_relpath,
    _safe_relpath,
)
from backend.md_quiz.services.quiz_metadata import apply_quiz_metadata
from backend.md_quiz.storage.db import list_quiz_definitions


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
    for row in list_quiz_definitions():
        if str(row.get("git_repo_url") or "").strip() != target_repo:
            continue
        if str(row.get("source_path") or "").strip() != target_path:
            continue
        return row
    return None


def _load_quiz_repo_manifest(repo_root: Path) -> list[str]:
    manifest_path = repo_root / QUIZ_REPO_MANIFEST
    if not manifest_path.exists() or not manifest_path.is_file():
        raise ExamRepoSyncError(f"仓库缺少 {QUIZ_REPO_MANIFEST}；{_legacy_repo_migration_hint()}")
    readme_path = repo_root / "README.md"
    if not readme_path.exists() or not readme_path.is_file():
        raise ExamRepoSyncError("仓库缺少 README.md")

    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception as exc:
        raise ExamRepoSyncError(f"{QUIZ_REPO_MANIFEST} 解析失败：{exc}") from exc
    if not isinstance(raw, dict):
        raise ExamRepoSyncError(f"{QUIZ_REPO_MANIFEST} 必须是 YAML mapping")
    try:
        schema_version = int(raw.get("schema_version"))
    except Exception as exc:
        raise ExamRepoSyncError(f"{QUIZ_REPO_MANIFEST} 缺少有效 schema_version") from exc
    if schema_version != QUIZ_REPO_SCHEMA_VERSION:
        raise ExamRepoSyncError(f"{QUIZ_REPO_MANIFEST} 仅支持 schema_version: {QUIZ_REPO_SCHEMA_VERSION}")
    if str(raw.get("kind") or "").strip() != QUIZ_REPO_KIND:
        raise ExamRepoSyncError(f"{QUIZ_REPO_MANIFEST} kind 必须为 {QUIZ_REPO_KIND}")

    quizzes = raw.get("quizzes")
    if not isinstance(quizzes, list) or not quizzes:
        raise ExamRepoSyncError(f"{QUIZ_REPO_MANIFEST} quizzes 必须是非空列表")

    paths: list[str] = []
    seen_paths: set[str] = set()
    repo_root_resolved = repo_root.resolve()
    for item in quizzes:
        if not isinstance(item, dict):
            raise ExamRepoSyncError(f"{QUIZ_REPO_MANIFEST} quizzes 条目必须是对象")
        source_path = _normalize_repo_relpath(str(item.get("path") or "").strip(), label="manifest path")
        if not _QUIZ_PATH_RE.fullmatch(source_path):
            raise ExamRepoSyncError(f"manifest path 只支持 quizzes/<quiz_id>/quiz.md：{source_path}")
        if source_path in seen_paths:
            raise ExamRepoSyncError(f"{QUIZ_REPO_MANIFEST} 存在重复 quiz path：{source_path}")
        abs_path = (repo_root / source_path).resolve()
        if repo_root_resolved not in abs_path.parents:
            raise ExamRepoSyncError(f"manifest path 越界：{source_path}")
        if not abs_path.exists() or not abs_path.is_file():
            raise ExamRepoSyncError(f"manifest path 不存在：{source_path}")
        seen_paths.add(source_path)
        paths.append(source_path)
    return paths


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
    for match in _HTML_IMG_SRC_RE.finditer(markdown_text or ""):
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


def _load_assets(quiz_root: Path, refs: list[str]) -> dict[str, tuple[bytes, str]]:
    assets: dict[str, tuple[bytes, str]] = {}
    quiz_root_resolved = quiz_root.resolve()
    for rel in refs:
        safe = _normalize_repo_relpath(rel, label="资源路径")
        if not safe or any(part == ".." for part in Path(safe).parts):
            raise ExamRepoSyncError(f"资源路径非法：{rel}")
        if not safe.startswith("assets/"):
            raise ExamRepoSyncError(f"图片必须位于当前 quiz 目录 assets/ 下：{rel}")
        suffix = Path(safe).suffix.lower()
        if suffix not in _SUPPORTED_IMAGE_EXTS:
            raise ExamRepoSyncError(f"只允许同步图片资源：{rel}")
        abs_path = (quiz_root / safe).resolve()
        if quiz_root_resolved not in abs_path.parents and abs_path != quiz_root_resolved:
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
    git_args = ["git"]
    proxy = str(EXAM_REPO_SYNC_PROXY or "").strip()
    if proxy:
        git_args.extend(["-c", f"http.proxy={proxy}"])
    try:
        subprocess.run(
            [*git_args, "clone", "--depth", "1", repo_url, str(workdir)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = str(exc.stderr or exc.stdout or exc).strip()
        raise ExamRepoSyncError(f"git clone 失败：{detail or '未知错误'}") from exc
    try:
        proc = subprocess.run(
            ["git", "-C", str(workdir), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = str(exc.stderr or exc.stdout or exc).strip()
        raise ExamRepoSyncError(f"读取仓库 commit 失败：{detail or '未知错误'}") from exc
    return str(proc.stdout or "").strip()


def _build_exam_candidate(repo_root: Path, repo_url: str, git_commit: str, source_path: str) -> dict[str, Any]:
    normalized_path = _normalize_repo_relpath(source_path, label="quiz path")
    match = _QUIZ_PATH_RE.fullmatch(normalized_path)
    if not match:
        raise ExamRepoSyncError(f"quiz path 只支持 quizzes/<quiz_id>/quiz.md：{normalized_path}")
    quiz_id = str(match.group("quiz_id") or "").strip()
    repo_root_resolved = repo_root.resolve()
    md_path = (repo_root / normalized_path).resolve()
    if repo_root_resolved not in md_path.parents:
        raise ExamRepoSyncError(f"quiz path 越界：{normalized_path}")
    quiz_root = md_path.parent
    markdown_text = md_path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    _validate_markdown_links(markdown_text)
    raw_exam_id = _read_frontmatter_exam_id(markdown_text)
    if not raw_exam_id:
        raise ExamRepoSyncError("Front matter 缺少 id")
    if raw_exam_id != quiz_id:
        raise ExamRepoSyncError(f"Front matter id 必须与目录名一致：{quiz_id}")
    try:
        spec, public_spec = parse_qml_markdown(markdown_text)
    except QmlParseError as exc:
        raise ExamRepoSyncError(f"{exc}（line={exc.line}）") from exc
    spec = apply_quiz_metadata(spec, default_schema_version=QUIZ_REPO_SCHEMA_VERSION)
    public_spec = apply_quiz_metadata(public_spec, default_schema_version=QUIZ_REPO_SCHEMA_VERSION)
    if str(spec.get("id") or "").strip() != raw_exam_id:
        raise ExamRepoSyncError("测验 id 解析异常")
    assets = _load_assets(quiz_root, _collect_assets(markdown_text, spec))
    content_hash = _snapshot_hash(markdown_text, assets)
    return {
        "quiz_key": raw_exam_id,
        "title": str(spec.get("title") or "").strip(),
        "source_path": normalized_path,
        "git_repo_url": repo_url,
        "git_commit": git_commit,
        "markdown_text": markdown_text,
        "spec": spec,
        "public_spec": public_spec,
        "assets": assets,
        "content_hash": content_hash,
    }


__all__ = [
    "_build_exam_candidate",
    "_clone_repo",
    "_find_existing_exam_by_source_path",
    "_load_assets",
    "_load_quiz_repo_manifest",
    "_normalize_repo_url",
    "_read_frontmatter_exam_id",
    "_snapshot_hash",
]
