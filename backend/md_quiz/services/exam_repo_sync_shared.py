from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from backend.md_quiz.services.quiz_metadata import QUIZ_SCHEMA_VERSION

EXAM_SYNC_JOB_KIND = "git_sync_exams"
EXAM_SYNC_STATE_KEY = "exam_repo_sync"
EXAM_REPO_BINDING_KEY = "exam_repo_binding"
EXAM_SYNC_MIGRATION_KEY = "exam_repo_sync_migration"
IMAGE_MAX_BYTES = 1024 * 1024
QUIZ_REPO_MANIFEST = "md-quiz-repo.yaml"
QUIZ_REPO_KIND = "md-quiz-repo"
QUIZ_REPO_SCHEMA_VERSION = QUIZ_SCHEMA_VERSION
_QUIZ_PATH_RE = re.compile(r"^quizzes/(?P<quiz_id>[A-Za-z0-9_-]+)/quiz\.md$")

_MD_IMAGE_RE = re.compile(r"!\[[^\]]*]\((?P<path>[^)]+)\)")
_HTML_IMG_SRC_RE = re.compile(
    r"""<img\b(?P<before>[^>]*?)\bsrc\s*=\s*(?P<quote>["']?)(?P<path>[^"'>\s]+)(?P=quote)(?P<after>[^>]*)>""",
    re.IGNORECASE,
)
_MD_LINK_RE = re.compile(r"(?<!\!)\[[^\]]*]\((?P<path>[^)]+)\)")
_FRONTMATTER_ID_RE = re.compile(r"(?mi)^id:\s*(?P<id>[A-Za-z0-9_-]+)\s*$")
_VERSION_ASSET_RE = re.compile(r"\(/quizzes/(?:versions/[^/]+|[^/]+)/assets/(?P<path>[^)]+)\)")
_HTML_VERSION_ASSET_RE = re.compile(
    r"""<img\b(?P<before>[^>]*?)\bsrc\s*=\s*(?P<quote>["']?)/quizzes/(?:versions/[^/\s"'>]+|[^/\s"'>]+)/assets/(?P<path>[^"'>\s]+)(?P=quote)(?P<after>[^>]*)>""",
    re.IGNORECASE,
)
_LEGACY_ASSET_URL_RE = re.compile(r"^/quizzes/[^/]+/assets/(?P<path>.+)$")
_SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}


class ExamRepoSyncError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


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
    return f"/quizzes/versions/{int(version_id)}/assets/{_safe_relpath(relpath)}"


def _normalize_repo_relpath(raw: str, *, label: str) -> str:
    value = _safe_relpath(raw)
    if not value or any(part == ".." for part in Path(value).parts):
        raise ExamRepoSyncError(f"{label}非法：{raw}")
    return value


def _legacy_repo_migration_hint() -> str:
    return "当前仅支持新版 quiz 仓库规范：仓库根目录需包含 md-quiz-repo.yaml，并使用 quizzes/<quiz_id>/quiz.md 结构"


__all__ = [
    "EXAM_REPO_BINDING_KEY",
    "EXAM_SYNC_JOB_KIND",
    "EXAM_SYNC_MIGRATION_KEY",
    "EXAM_SYNC_STATE_KEY",
    "ExamRepoSyncError",
    "IMAGE_MAX_BYTES",
    "QUIZ_REPO_KIND",
    "QUIZ_REPO_MANIFEST",
    "QUIZ_REPO_SCHEMA_VERSION",
    "_FRONTMATTER_ID_RE",
    "_HTML_IMG_SRC_RE",
    "_HTML_VERSION_ASSET_RE",
    "_LEGACY_ASSET_URL_RE",
    "_MD_IMAGE_RE",
    "_MD_LINK_RE",
    "_QUIZ_PATH_RE",
    "_SUPPORTED_IMAGE_EXTS",
    "_VERSION_ASSET_RE",
    "_is_local_asset_path",
    "_legacy_repo_migration_hint",
    "_normalize_repo_relpath",
    "_safe_relpath",
    "_utc_now",
    "_version_asset_url",
]
