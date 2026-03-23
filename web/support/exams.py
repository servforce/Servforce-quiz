from __future__ import annotations

import mimetypes

from web.support.deps import *
from web.support.validation import *

def _invite_window_state(assignment: dict, *, now: datetime | None = None) -> tuple[str, date | None, date | None]:
    """
    Returns (state, start_date, end_date):
    - state: ok | not_started | expired
    - start/end are local dates (day granularity)

    Expiration is judged only if the candidate has not started the exam yet.
    """
    a = assignment or {}
    inv = a.get("invite_window") or {}
    if not isinstance(inv, dict):
        inv = {}
    sd = _parse_date_ymd(str(inv.get("start_date") or ""))
    ed = _parse_date_ymd(str(inv.get("end_date") or ""))

    if now is None:
        now = datetime.now().astimezone()
    else:
        now = now.astimezone()
    tz = now.tzinfo

    timing = a.get("timing") or {}
    if isinstance(timing, dict) and str(timing.get("start_at") or "").strip():
        return "ok", sd, ed

    if sd is not None:
        start_at = datetime.combine(sd, dt_time.min, tzinfo=tz)
        if now < start_at:
            return "not_started", sd, ed

    if ed is not None:
        end_at = datetime.combine(ed, dt_time.max, tzinfo=tz)
        if now > end_at:
            return "expired", sd, ed

    return "ok", sd, ed


_MD_IMAGE_RE = re.compile(r"!\[[^\]]*]\((?P<path>[^)]+)\)")
_FILENAME_UNSAFE_RE = re.compile(r'[\\\\/:*?"<>|]+')
_PUBLIC_INVITE_GUARD = threading.Lock()


def get_public_invite_config(exam_key: str) -> dict[str, object]:
    row = get_exam_public_invite(str(exam_key or "").strip()) or {}
    if not row:
        return {"enabled": False, "token": ""}
    enabled = bool(row.get("public_invite_enabled"))
    token = str(row.get("public_invite_token") or "").strip()
    return {"enabled": enabled, "token": token}

def _hash_token_base64url(seed: str, *, length: int = 10) -> str:
    """
    Deterministic, URL-safe token: base64url(sha256(seed)) truncated to `length`.
    """
    raw = hashlib.sha256(seed.encode("utf-8", errors="ignore")).digest()
    b64 = base64.urlsafe_b64encode(raw).decode("ascii", errors="ignore").rstrip("=")
    return b64[:length]


def _compute_public_invite_token_for_exam(*, exam_key: str, created_at: str, title: str, length: int = 10) -> str:
    """
    Generate a stable public invite token for an exam based on exam metadata.

    Seed includes: created_at, exam_key (id), title. Token is base64url hash (10 chars).
    Collision-safe: appends a suffix and re-hashes if token already taken by another exam.
    """
    ek = str(exam_key or "").strip()
    ca = str(created_at or "").strip()
    tt = str(title or "").strip()
    if not ek or not ca:
        raise ValueError("missing exam_key/created_at")

    base_seed = f"{ek}\n{tt}\n{ca}"
    for n in range(0, 50):
        seed = base_seed if n == 0 else f"{base_seed}\n#{n}"
        t = _hash_token_base64url(seed, length=length)
        if not t:
            continue
        bound = get_exam_key_by_public_invite_token(t)
        if not bound or bound == ek:
            return t
    raise RuntimeError("Failed to allocate a collision-free public invite token")


def set_public_invite_enabled(exam_key: str, enabled: bool) -> dict[str, object]:
    ek = str(exam_key or "").strip()
    if not ek:
        return {"enabled": False, "token": ""}
    exam = get_exam_definition(ek)
    if not exam:
        return {"enabled": False, "token": ""}

    with _PUBLIC_INVITE_GUARD:
        token0 = str(exam.get("public_invite_token") or "").strip()
        created_at0 = str(exam.get("created_at") or "").strip()
        title0 = str(exam.get("title") or "").strip()
        if enabled:
            token = _compute_public_invite_token_for_exam(exam_key=ek, created_at=created_at0, title=title0, length=10)
        else:
            token = token0 if token0 else None
        try:
            set_exam_public_invite(ek, enabled=bool(enabled), token=(token or None))
        except Exception:
            return {"enabled": False, "token": ""}
    return {"enabled": bool(enabled), "token": token}

def _resolve_public_invite_exam_key(public_token: str) -> str:
    t = str(public_token or "").strip()
    if not t:
        return ""
    return get_exam_key_by_public_invite_token(t)


def _protect_math_for_markdown(raw: str) -> tuple[str, list[tuple[str, str]]]:
    """
    Python-Markdown treats trailing backslashes as hard line breaks and can
    consume TeX row separators like `\\\\` at end-of-line (e.g. inside `cases`).
    To keep MathJax/TeX intact, temporarily replace math segments with tokens
    before markdown processing, then restore them in the generated HTML.
    """

    text = str(raw or "")
    replacements: list[tuple[str, str]] = []
    out: list[str] = []

    def is_escaped(pos: int) -> bool:
        # Consider a '$' escaped if preceded by an odd number of backslashes.
        bs = 0
        j = pos - 1
        while j >= 0 and text[j] == "\\":
            bs += 1
            j -= 1
        return (bs % 2) == 1

    i = 0
    while i < len(text):
        if text.startswith("$$", i) and not is_escaped(i):
            j = i + 2
            while True:
                k = text.find("$$", j)
                if k < 0:
                    break
                if not is_escaped(k):
                    seg = text[i : k + 2]
                    token = f"@@MATH{len(replacements)}@@"
                    replacements.append((token, html.escape(seg, quote=False)))
                    out.append(token)
                    i = k + 2
                    break
                j = k + 1
            else:
                # Unreachable; keep structure explicit.
                pass
            if i != j and out and out[-1].startswith("@@MATH"):
                continue

        if text.startswith("\\[", i):
            k = text.find("\\]", i + 2)
            if k >= 0:
                seg = text[i : k + 2]
                token = f"@@MATH{len(replacements)}@@"
                replacements.append((token, html.escape(seg, quote=False)))
                out.append(token)
                i = k + 2
                continue

        if text.startswith("\\(", i):
            k = text.find("\\)", i + 2)
            if k >= 0:
                seg = text[i : k + 2]
                token = f"@@MATH{len(replacements)}@@"
                replacements.append((token, html.escape(seg, quote=False)))
                out.append(token)
                i = k + 2
                continue

        if text[i] == "$" and not is_escaped(i) and not text.startswith("$$", i):
            j = i + 1
            while True:
                k = text.find("$", j)
                if k < 0:
                    break
                if not is_escaped(k):
                    seg = text[i : k + 1]
                    token = f"@@MATH{len(replacements)}@@"
                    replacements.append((token, html.escape(seg, quote=False)))
                    out.append(token)
                    i = k + 1
                    break
                j = k + 1
            if out and out[-1].startswith("@@MATH"):
                continue

        out.append(text[i])
        i += 1

    return "".join(out), replacements


def _safe_relpath(raw: str) -> str:
    p = (raw or "").strip().strip('"').strip("'")
    p = p.split("#", 1)[0].strip()
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def _is_local_asset_path(p: str) -> bool:
    if not p:
        return False
    lower = p.lower()
    if lower.startswith(("http://", "https://", "data:", "mailto:")):
        return False
    return True


def _collect_md_assets(markdown_text: str) -> set[str]:
    assets: set[str] = set()
    for m in _MD_IMAGE_RE.finditer(markdown_text or ""):
        p = _safe_relpath(m.group("path"))
        if _is_local_asset_path(p):
            assets.add(p)
    return assets


def _asset_url(exam_key: str, relpath: str) -> str:
    return f"/exams/{exam_key}/assets/{_safe_relpath(relpath)}"


def _resolve_exam_asset_payload(exam_key: str, relpath: str) -> tuple[bytes, str] | None:
    rp = _safe_relpath(relpath)
    if not rp:
        return None
    if any(part == ".." for part in Path(rp).parts):
        return None
    try:
        return get_exam_asset(str(exam_key or "").strip(), rp)
    except Exception:
        return None


# 试卷资源处理：将 Markdown 中的本地资源路径统一重写为受控访问 URL。
def _rewrite_exam_asset_paths(exam_key: str, spec: dict, public_spec: dict) -> None:
    for k in ("welcome_image", "end_image"):
        v = str(spec.get(k) or "").strip()
        if v:
            spec[k] = _asset_url(exam_key, v) if _is_local_asset_path(v) else v
        v2 = str(public_spec.get(k) or "").strip()
        if v2:
            public_spec[k] = _asset_url(exam_key, v2) if _is_local_asset_path(v2) else v2

    for q in (spec.get("questions") or []):
        stem = str(q.get("stem_md") or "")
        for p in _collect_md_assets(stem):
            stem = stem.replace(f"({p})", f"({_asset_url(exam_key, p)})")
        q["stem_md"] = stem
    for q in (public_spec.get("questions") or []):
        stem = str(q.get("stem_md") or "")
        for p in _collect_md_assets(stem):
            stem = stem.replace(f"({p})", f"({_asset_url(exam_key, p)})")
        q["stem_md"] = stem


# 首次写入试卷：解析 Markdown -> 落盘 source/spec/public -> 同步资源文件。
def _write_exam_to_storage(
    exam_text: str,
    *,
    assets: dict[str, bytes] | None = None,
    ensure_unique_key: bool = False,
) -> str:
    spec, public_spec = parse_qml_markdown(exam_text)
    exam_key = spec["id"]
    if ensure_unique_key and get_exam_definition(exam_key):
        base = str(exam_key or "").strip()[:52] or "exam-ai"
        stamp = datetime.now().strftime("%m%d%H%M%S")
        new_key = f"{base}-{stamp}"
        n = 1
        while get_exam_definition(new_key):
            n += 1
            new_key = f"{base}-{stamp}-{n}"
        exam_key = new_key[:64]
        spec["id"] = exam_key
        try:
            public_spec["id"] = exam_key
        except Exception:
            pass
        # 保持 source_md 中的试卷 id 与最终入库的 exam_key 一致。
        exam_text = re.sub(r"(?mi)^id:\s*.+$", f"id: {exam_key}", str(exam_text or ""), count=1)

    if assets is not None:
        assets_to_save: dict[str, tuple[bytes, str]] = {}
        for rel, content in assets.items():
            rel2 = _safe_relpath(rel)
            if not rel2:
                continue
            mime = mimetypes.guess_type(rel2)[0] or "application/octet-stream"
            assets_to_save[rel2] = (bytes(content or b""), mime)
        replace_exam_assets(exam_key, assets_to_save)

    _rewrite_exam_asset_paths(exam_key, spec, public_spec)
    save_exam_definition(
        exam_key=exam_key,
        title=str(spec.get("title") or "").strip(),
        source_md=exam_text,
        spec=spec,
        public_spec=public_spec,
    )
    return exam_key


# 覆写已有试卷目录（用于编辑保存）。
def _rewrite_exam_in_dir(exam_key: str, exam_text: str) -> None:
    spec, public_spec = parse_qml_markdown(exam_text)
    parsed_key = str(spec.get("id") or "")
    if parsed_key != str(exam_key or ""):
        raise ValueError("exam_key mismatch after parse")

    _rewrite_exam_asset_paths(exam_key, spec, public_spec)
    save_exam_definition(
        exam_key=str(exam_key or "").strip(),
        title=str(spec.get("title") or "").strip(),
        source_md=exam_text,
        spec=spec,
        public_spec=public_spec,
    )


def _migrate_assignment_exam_key(old_exam_key: str, new_exam_key: str) -> int:
    """exam_key 变更时，迁移 assignment 记录中的关联键。"""
    try:
        return int(rename_assignment_exam_key(old_exam_key, new_exam_key) or 0)
    except Exception:
        logger.exception("Failed to migrate assignment exam_key: %s -> %s", old_exam_key, new_exam_key)
        return 0


# exam_key 变更时，迁移历史归档文件名与归档内部 exam_key。
def _migrate_archives_exam_key(old_exam_key: str, new_exam_key: str) -> int:
    try:
        return int(rename_exam_archives_exam_key(old_exam_key, new_exam_key) or 0)
    except Exception:
        logger.exception("Failed to migrate archives exam_key: %s -> %s", old_exam_key, new_exam_key)
        return 0


# 管理端更新试卷：必要时先改目录/关联键，再重写 spec/public。
def _admin_update_exam_from_source(old_exam_key: str, new_source_md: str) -> str:
    spec_tmp, _public_tmp = parse_qml_markdown(new_source_md)
    new_exam_key = str(spec_tmp.get("id") or "").strip()
    if not new_exam_key:
        raise ValueError("missing exam id")

    old_exam_key = str(old_exam_key or "").strip()
    if new_exam_key != old_exam_key:
        if get_exam_definition(new_exam_key):
            raise FileExistsError(f"target exam id already exists: {new_exam_key}")
        if not get_exam_definition(old_exam_key):
            raise FileNotFoundError("exam not found")

        try:
            rename_exam_key(old_exam_key, new_exam_key)
        except Exception:
            logger.exception("Failed to migrate candidate.exam_key: %s -> %s", old_exam_key, new_exam_key)
        try:
            rename_exam_definition(old_exam_key, new_exam_key)
        except Exception:
            logger.exception("Failed to migrate exam definition: %s -> %s", old_exam_key, new_exam_key)
        try:
            rename_exam_assets(old_exam_key, new_exam_key)
        except Exception:
            logger.exception("Failed to migrate exam assets: %s -> %s", old_exam_key, new_exam_key)
        _migrate_assignment_exam_key(old_exam_key, new_exam_key)
        _migrate_archives_exam_key(old_exam_key, new_exam_key)

    _rewrite_exam_in_dir(new_exam_key, new_source_md)
    return new_exam_key


# Flask 应用工厂：注册路由并初始化存储、数据库与后台任务。

def _list_exams():
    out = []
    for row in list_exam_definitions():
        spec = row.get("spec") or {}
        updated_at = row.get("updated_at") or row.get("created_at")
        mtime = 0.0
        try:
            if updated_at:
                mtime = float(updated_at.timestamp())
        except Exception:
            mtime = 0.0
        out.append(
            {
                "exam_key": str(row.get("exam_key") or "").strip(),
                "title": spec.get("title", ""),
                "count": len(spec.get("questions", [])),
                "_mtime": mtime,
            }
        )
    # Assign an incremental id by upload/parse order (oldest -> newest),
    # then sort by id desc (newest first).
    out.sort(key=lambda x: x.get("_mtime", 0))
    for idx, item in enumerate(out, start=1):
        item["id"] = idx
    out.sort(key=lambda x: x.get("id", 0), reverse=True)
    return out


def _exam_key_from_sort_id(exam_id: int) -> str | None:
    try:
        exam_id = int(exam_id)
    except Exception:
        return None
    if exam_id <= 0:
        return None
    for e in _list_exams():
        try:
            if int(e.get("id") or 0) == exam_id:
                v = str(e.get("exam_key") or "").strip()
                return v or None
        except Exception:
            continue
    return None


def _sort_id_from_exam_key(exam_key: str) -> int | None:
    k = str(exam_key or "").strip()
    if not k:
        return None
    for e in _list_exams():
        if str(e.get("exam_key") or "") == k:
            try:
                v = int(e.get("id") or 0)
            except Exception:
                v = 0
            return v or None
    return None


__all__ = [name for name in globals() if not name.startswith("__")]
