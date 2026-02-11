from __future__ import annotations

import html
import os
import re
import shutil
import threading
import time
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from markupsafe import Markup

from config import ADMIN_PASSWORD, ADMIN_USERNAME, BASE_DIR, SECRET_KEY, STORAGE_DIR, logger
from db import (
    create_candidate,
    delete_candidate,
    get_candidate,
    get_candidate_by_phone,
    get_candidate_resume,
    has_recent_exam_submission_by_phone,
    init_db,
    list_candidates,
    reset_candidate_exam_state,
    set_candidate_exam_started_at,
    set_candidate_exam_key,
    set_candidate_status,
    mark_exam_deleted,
    rename_exam_key,
    update_candidate,
    update_candidate_resume,
    update_candidate_resume_parsed,
    update_candidate_result,
    verify_candidate,
)
import markdown as mdlib
from qml.parser import QmlParseError, parse_qml_markdown
from services.assignment_service import (
    assignment_locked,
    compute_min_submit_seconds,
    create_assignment,
    load_assignment,
    save_assignment,
)
from services.grading_service import generate_candidate_remark, grade_attempt
from services.resume_service import (
    extract_resume_text,
    extract_resume_section,
    parse_resume_details_llm,
    parse_resume_identity_fast,
    parse_resume_identity_llm,
    parse_resume_name_llm,
)
from services.university_tags import classify_university
from storage.json_store import ensure_dirs, read_json, write_json
from web.auth import admin_required

# 使用正则表达式 
_NAME_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z·\s]{2,20}$")  # 用来验证一个名字是否符合特定的规则
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")    # 验证一个手机号是否符合特定规则
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


# 接收一个字符串类型的参数 value，返回一个布尔值 True 或 False，表示该名字是否有效
def _is_valid_name(value: str) -> bool:
    v = (value or "").strip()
    return bool(_NAME_RE.fullmatch(v))

# 字符串类型的参数 value，并返回一个布尔值，表示传入的手机号是否有效
def _is_valid_phone(value: str) -> bool:
    v = (value or "").strip()
    v = v.replace(" ", "").replace("-", "")
    if v.startswith("+86"):
        v = v[3:]
    if v.startswith("86") and len(v) == 13:
        v = v[2:]
    return bool(_PHONE_RE.fullmatch(v))

# 将输入的手机号都变成标准的输出
def _normalize_phone(value: str) -> str:
    v = (value or "").strip()
    v = v.translate(_FULLWIDTH_DIGITS)
    digits = re.sub(r"\D+", "", v)
    if digits.startswith("0086"):
        digits = digits[4:]
    if digits.startswith("86") and len(digits) >= 13:
        cand = digits[2:]
        if _PHONE_RE.fullmatch(cand):
            digits = cand
    if len(digits) > 11:
        tail = digits[-11:]
        if _PHONE_RE.fullmatch(tail):
            digits = tail
    return digits


def _clean_projects_raw(text: str) -> str:
    """
    Best-effort cleanup for displaying the raw "项目经历" section:
    - remove the leading section label ("项目经历/项目经验") if it is glued to content
    - add line breaks before common field labels for readability
    """
    s = str(text or "").strip()
    if not s:
        return ""

    # Remove leading label.
    s = re.sub(r"^\s*(项目经历|项目经验)\s*[:：\-—]*\s*", "", s)
    # Sometimes PDF extraction glues the label to the next token without spaces/punctuation.
    if s.startswith("项目经历") or s.startswith("项目经验"):
        s = s[4:].lstrip()

    # Add line breaks before common labels when they appear inline.
    labels = ["内容：", "工作：", "职责：", "项目成果：", "项目结果：", "项目描述："]
    for lab in labels:
        s = re.sub(rf"(?<!\n){re.escape(lab)}", "\n" + lab, s)

    # Normalize excessive blank lines.
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


_PROJECT_PERIOD_RE = re.compile(
    r"(?P<period>(?:19|20)\d{2}年\d{1,2}月\s*-\s*(?:19|20)\d{2}年\d{1,2}月)"
)


def _split_projects_raw(text: str) -> list[dict[str, str]]:
    """
    Split projects_raw into blocks and render in a "title | period" layout without rewriting content.
    Returns: [{"title":..., "period":..., "body":...}, ...]
    """
    s = str(text or "").strip()
    if not s:
        return []

    # Match "title + period" even if it appears mid-line (PDF glue).
    head_re = re.compile(
        r"(?P<title>[^\n]{2,120}?)\s*(?P<period>(?:19|20)\d{2}年\d{1,2}月\s*-\s*(?:19|20)\d{2}年\d{1,2}月)"
    )
    matches = list(head_re.finditer(s))
    if not matches:
        return []

    out: list[dict[str, str]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(s)

        full_title = str(m.group("title") or "").strip()
        # Keep only the last line as title (avoid swallowing previous content when glued).
        if "\n" in full_title:
            full_title = full_title.splitlines()[-1].strip()
        full_title = re.sub(r"^\s*(项目经历|项目经验)\s*[:：\-—]*\s*", "", full_title).strip()

        period = str(m.group("period") or "").strip()

        # If the extracted "title" accidentally contains a previous project's tail such as "项目成果：...论文基于...基于XXX",
        # move the prefix back to the previous block and keep only the actual project name for this block.
        title = full_title
        if any(k in full_title for k in ("项目成果", "项目结果", "成果")) and "基于" in full_title:
            split_pos = full_title.rfind("基于")
            if split_pos > 0:
                prefix = full_title[:split_pos].strip()
                candidate = full_title[split_pos:].strip()
                if prefix and out:
                    prev = out[-1]
                    prev_body = (prev.get("body") or "").rstrip()
                    if prev_body:
                        prev_body += "\n"
                    prev["body"] = (prev_body + prefix).strip()
                title = candidate
        # Another common pattern: "...论文基于占用网格..." -> keep "基于占用网格..." as project name.
        if "论文基于" in title:
            tail = title.split("论文基于")[-1].strip()
            if tail and not tail.startswith("基于"):
                tail = "基于" + tail
            title = tail or title

        body = s[m.end() : end].strip()
        body = body.lstrip("：: \t-—")
        body = re.sub(r"\n{3,}", "\n\n", body).strip()

        # Skip obviously-bad titles.
        if not title or len(title) > 120:
            continue
        out.append({"title": title, "period": period, "body": body})

    return out[:8]


def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


_MD_IMAGE_RE = re.compile(r"!\[[^\]]*]\((?P<path>[^)]+)\)")
_FILENAME_UNSAFE_RE = re.compile(r'[\\\\/:*?"<>|]+')


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


def _resolve_exam_asset_file(exam_key: str, relpath: str) -> Path | None:
    """
    Resolve an asset file path.

    Primary: `storage/exams/<exam_key>/assets/<relpath>`
    Fallback (dev-friendly): `<repo>/examples/<relpath>`
    """
    rp = _safe_relpath(relpath)
    exam_assets_base = (STORAGE_DIR / "exams" / str(exam_key or "") / "assets").resolve()
    try:
        p = (exam_assets_base / rp).resolve()
    except Exception:
        p = exam_assets_base / rp
    if exam_assets_base not in p.parents and p != exam_assets_base:
        return None
    if p.exists() and p.is_file():
        return p

    examples_base = (BASE_DIR / "examples").resolve()
    try:
        p2 = (examples_base / rp).resolve()
    except Exception:
        p2 = examples_base / rp
    if examples_base not in p2.parents and p2 != examples_base:
        return None
    if p2.exists() and p2.is_file():
        return p2
    return None


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


def _write_exam_to_storage(exam_text: str, *, assets: dict[str, bytes] | None = None) -> str:
    spec, public_spec = parse_qml_markdown(exam_text)
    exam_key = spec["id"]
    exam_dir = STORAGE_DIR / "exams" / exam_key
    exam_dir.mkdir(parents=True, exist_ok=True)
    (exam_dir / "source.md").write_text(exam_text, encoding="utf-8")

    if assets:
        for rel, content in assets.items():
            rel2 = _safe_relpath(rel)
            if not rel2:
                continue
            out_path = exam_dir / "assets" / rel2
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(content)

    _rewrite_exam_asset_paths(exam_key, spec, public_spec)
    write_json(exam_dir / "spec.json", spec)
    write_json(exam_dir / "public.json", public_spec)
    return exam_key


def _rewrite_exam_in_dir(exam_key: str, exam_text: str) -> None:
    spec, public_spec = parse_qml_markdown(exam_text)
    parsed_key = str(spec.get("id") or "")
    if parsed_key != str(exam_key or ""):
        raise ValueError("exam_key mismatch after parse")

    exam_dir = STORAGE_DIR / "exams" / str(exam_key or "")
    exam_dir.mkdir(parents=True, exist_ok=True)
    (exam_dir / "source.md").write_text(exam_text, encoding="utf-8")
    _rewrite_exam_asset_paths(exam_key, spec, public_spec)
    write_json(exam_dir / "spec.json", spec)
    write_json(exam_dir / "public.json", public_spec)


def _migrate_assignment_exam_key(old_exam_key: str, new_exam_key: str) -> int:
    """
    Best-effort migration: update assignment JSON files to keep tokens working
    after an exam_key rename.
    Returns number of updated assignment files.
    """
    updated = 0
    assignments_dir = STORAGE_DIR / "assignments"
    if not assignments_dir.exists():
        return 0
    for p in assignments_dir.glob("*.json"):
        try:
            a = read_json(p)
        except Exception:
            continue
        if str(a.get("exam_key") or "") != str(old_exam_key or ""):
            continue
        a["exam_key"] = str(new_exam_key or "")
        try:
            write_json(p, a)
            updated += 1
        except Exception:
            logger.exception("Failed to migrate assignment exam_key: %s", p)
    return updated


def _migrate_archives_exam_key(old_exam_key: str, new_exam_key: str) -> int:
    """
    Best-effort migration: rename archived attempt files and update embedded exam_key.
    This keeps "候选人答题情况" and archive enrichment working after an exam_key rename.
    """
    old_exam_key = str(old_exam_key or "").strip()
    new_exam_key = str(new_exam_key or "").strip()
    if not old_exam_key or not new_exam_key or old_exam_key == new_exam_key:
        return 0

    archives_dir = STORAGE_DIR / "archives"
    if not archives_dir.exists():
        return 0

    old_suffix = _sanitize_archive_part(old_exam_key)
    new_suffix = _sanitize_archive_part(new_exam_key)
    if not old_suffix or not new_suffix:
        return 0

    migrated = 0
    for p in archives_dir.glob(f"*_{old_suffix}.json"):
        if not p.is_file():
            continue
        stem = p.stem
        if not stem.endswith(f"_{old_suffix}"):
            continue
        new_stem = stem[: -(len(old_suffix) + 1)] + f"_{new_suffix}"
        new_path = p.with_name(new_stem + ".json")
        if new_path.exists():
            continue
        try:
            p.rename(new_path)
        except Exception:
            continue

        try:
            archive = read_json(new_path)
            exam = archive.get("exam") or {}
            if isinstance(exam, dict) and str(exam.get("exam_key") or "").strip() == old_exam_key:
                exam["exam_key"] = new_exam_key
                archive["exam"] = exam
                write_json(new_path, archive)
        except Exception:
            pass
        migrated += 1

    return migrated


def _admin_update_exam_from_source(old_exam_key: str, new_source_md: str) -> str:
    spec_tmp, _public_tmp = parse_qml_markdown(new_source_md)
    new_exam_key = str(spec_tmp.get("id") or "").strip()
    if not new_exam_key:
        raise ValueError("missing exam id")

    old_exam_key = str(old_exam_key or "").strip()
    if new_exam_key != old_exam_key:
        old_dir = STORAGE_DIR / "exams" / old_exam_key
        new_dir = STORAGE_DIR / "exams" / new_exam_key
        if new_dir.exists():
            raise FileExistsError(f"target exam id already exists: {new_exam_key}")
        if not old_dir.exists():
            raise FileNotFoundError("exam not found")
        old_dir.rename(new_dir)

        try:
            rename_exam_key(old_exam_key, new_exam_key)
        except Exception:
            logger.exception("Failed to migrate candidate.exam_key: %s -> %s", old_exam_key, new_exam_key)
        _migrate_assignment_exam_key(old_exam_key, new_exam_key)
        _migrate_archives_exam_key(old_exam_key, new_exam_key)

    _rewrite_exam_in_dir(new_exam_key, new_source_md)
    return new_exam_key
    
def create_app() -> Flask:
    app = Flask(__name__)   # 确定项目根目录，确定templates和static路径
    app.secret_key = SECRET_KEY #  Flask 用来加密和签名 session 数据的密钥

    ensure_dirs()   # 生成试卷和二维码
    # 创建数据库失败，则退出程序
    try:
        init_db()
    except RuntimeError as e:
        raise SystemExit(str(e))

    # Auto-collect: once countdown starts, keep decreasing even if candidate leaves the page.
    # Start only once (avoid Flask reloader double-start).
    if os.getenv("ENABLE_AUTO_COLLECT", "1").strip().lower() not in {"0", "false", "no"}:
        if os.getenv("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
            threading.Thread(target=_auto_collect_loop, daemon=True).start()

    # Flask 的全局错误处理器
    @app.errorhandler(FileNotFoundError)
    def _handle_file_not_found(_e):
        return "Not Found", 404

    @app.template_filter("md")
    def _render_md(value: str) -> Markup:
        # Escape HTML tags/entities to avoid XSS, but keep quotes so code samples display normally.
        # Also protect TeX math so Markdown doesn't consume `\\\\` row separators (hard line breaks).
        protected, math_repls = _protect_math_for_markdown(value)
        text = html.escape(protected, quote=False)
        rendered = mdlib.markdown(
            text,
            extensions=[
                "markdown.extensions.fenced_code",
                "markdown.extensions.footnotes",
                "markdown.extensions.attr_list",
                "markdown.extensions.def_list",
                "markdown.extensions.tables",
                "markdown.extensions.abbr",
                "markdown.extensions.md_in_html",
                "markdown.extensions.sane_lists",
            ],
            output_format="html5",
        )
        for token, math_html in math_repls:
            rendered = rendered.replace(token, math_html)
        return Markup(rendered)

    @app.get("/exams/<exam_key>/assets/<path:relpath>")
    def public_exam_asset(exam_key: str, relpath: str):
        p = _resolve_exam_asset_file(exam_key, relpath)
        if not p:
            abort(404)
        return send_file(p)

    @app.get("/")   # session 里是否已登录管理员，决定跳转到后台首页还是登录页
    def index():
        if session.get("admin_logged_in"):      # 说明管理员已经登录(键不存在的不报错)
            return redirect(url_for("admin_dashboard"))     # 跳转到admin_dashboard对应的页面去，反向寻到url
        return redirect(url_for("admin_login"))     # 没登录就跳转到登录页面，通过这个函数反向推测url路径，可以在修改路由后方便修改页面

    # ---------------- Admin ----------------
    # get是从后端调用数据和页面的
    @app.get("/admin/login")    # 注册一个路由，调用下面函数
    def admin_login():
        return render_template("admin_login.html")     # 渲染并返回页面

    # post是将浏览器的数据传入后端进行验证的
    @app.post("/admin/login")
    def admin_login_post():
        username = (request.form.get("username") or "").strip()     # 取表单的数据
        password = (request.form.get("password") or "").strip()
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True       # 写入session标记admin_logged_in = True
            return redirect(url_for("admin_dashboard"))     # admin_dashboard，管理员首页
        flash("账号或密码错误")
        return redirect(url_for("admin_login"))     # 登录失败就重新填入

    # 退出功能
    @app.post("/admin/logout")      # 点击按钮激发退出页面功能
    def admin_logout():     
        session.clear()     # 把session里的所有数据清空
        return redirect(url_for("admin_login"))     # 重新回到登录页面对应的路由

    @app.get("/admin")     # 进入到登录主页面
    @admin_required     # session.get("admin_logged_in")只有管理员登录后才能查看这个页面
    def admin_dashboard():
        exams_all = _list_exams()   # 获取考试列表
        candidates = list_candidates(limit=200)  # 获取考生列表，最多取 200 条

        exam_q = (request.args.get("exam_q") or "").strip()
        attempt_q = (request.args.get("attempt_q") or "").strip()
        assign_exam_key = (request.args.get("assign_exam_key") or "").strip()
        assign_candidate_id = (request.args.get("assign_candidate_id") or "").strip()
        if exam_q:
            ql = exam_q.lower()
            digits = ql.isdigit()
            exams_all = [
                e
                for e in exams_all
                if ql in str(e.get("exam_key") or "").lower()
                or ql in str(e.get("title") or "").lower()
                or (digits and ql in str(e.get("id") or ""))
            ]

        # Always show most recently updated first.
        exams_all.sort(key=lambda x: float(x.get("_mtime") or 0), reverse=True)

        per_page = 20
        try:
            exam_page = int(request.args.get("exam_page") or "1")
        except Exception:
            exam_page = 1
        exam_page = max(1, exam_page)
        total_exams = len(exams_all)
        total_exam_pages = (total_exams + per_page - 1) // per_page
        if total_exam_pages > 0:
            exam_page = min(exam_page, total_exam_pages)
        else:
            exam_page = 1

        start = (exam_page - 1) * per_page
        end = start + per_page
        exams_page = exams_all[start:end]
        for e in exams_page:
            try:
                mtime = float(e.get("_mtime") or 0)
            except Exception:
                mtime = 0
            if mtime > 0:
                try:
                    e["updated_at"] = datetime.fromtimestamp(mtime)
                except Exception:
                    e["updated_at"] = None
            else:
                e["updated_at"] = None

        attempt_candidates = []
        for c in candidates:
            p = None
            try:
                p = _find_latest_archive(c)
            except Exception:
                p = None
            if not p:
                continue

            # Prefer the exam_key recorded in the archive file. This keeps the table stable
            # even if the candidate.exam_key changed after an exam rename.
            display_exam_key = str(c.get("exam_key") or "")
            try:
                a = read_json(p)
                display_exam_key = str(((a.get("exam") or {}).get("exam_key")) or "") or display_exam_key
            except Exception:
                pass
            attempt_candidates.append(
                {
                    "id": int(c.get("id") or 0),
                    "name": str(c.get("name") or ""),
                    "phone": str(c.get("phone") or ""),
                    "exam_key": display_exam_key,
                    "score": c.get("score"),
                    "exam_started_at": c.get("exam_started_at"),
                    "exam_submitted_at": c.get("exam_submitted_at"),
                    "attempt_href": url_for("admin_candidate_attempt", candidate_id=int(c.get("id") or 0)),
                }
            )

        if attempt_q:
            ql = attempt_q.lower()
            attempt_candidates = [
                x
                for x in attempt_candidates
                if ql in str(x.get("name") or "").lower()
                or ql in str(x.get("phone") or "").lower()
                or ql in str(x.get("exam_key") or "").lower()
            ]

        attempt_per_page = 20

        try:
            attempt_page = int(request.args.get("attempt_page") or "1")
        except Exception:
            attempt_page = 1
        attempt_page = max(1, attempt_page)
        total_attempts = len(attempt_candidates)
        total_attempt_pages = (total_attempts + attempt_per_page - 1) // attempt_per_page
        if total_attempt_pages > 0:
            attempt_page = min(attempt_page, total_attempt_pages)
        else:
            attempt_page = 1

        start2 = (attempt_page - 1) * attempt_per_page
        end2 = start2 + attempt_per_page
        attempt_candidates_page = attempt_candidates[start2:end2]

        return render_template(
            "admin_dashboard.html",
            exams_all=exams_all,
            exams_page=exams_page,
            exam_page=exam_page,
            total_exams=total_exams,
            total_exam_pages=total_exam_pages,
            exam_q=exam_q,
            exam_per_page=per_page,
            attempt_q=attempt_q,
            assign_exam_key=assign_exam_key,
            assign_candidate_id=assign_candidate_id,
            candidates=candidates,
            attempt_candidates=attempt_candidates_page,
            attempt_page=attempt_page,
            total_attempts=total_attempts,
            total_attempt_pages=total_attempt_pages,
            attempt_per_page=attempt_per_page,
        )

    @app.post("/admin/exams/upload")    # 上传
    @admin_required        #  必须在管理员登录后才能看到 
    def admin_exams_upload():
        file = request.files.get("file")
        if not file or not file.filename:
            flash("请选择 .md 或 .zip 文件")
            return redirect(url_for("admin_dashboard"))
        filename = (file.filename or "").lower()

        # Support a zip package containing the markdown + img/ assets.
        if filename.endswith(".zip"):
            try:
                zf = zipfile.ZipFile(BytesIO(file.read()))
            except Exception:
                flash("ZIP 读取失败，请确认文件格式为 .zip")
                return redirect(url_for("admin_dashboard"))

            md_names = [n for n in zf.namelist() if not n.endswith("/") and n.lower().endswith(".md")]
            if not md_names:
                flash("ZIP 中未找到 .md 文件")
                return redirect(url_for("admin_dashboard"))

            md_names.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
            md_name = md_names[0]
            try:
                text = zf.read(md_name).decode("utf-8", errors="replace")
            except Exception:
                flash("Markdown 读取失败")
                return redirect(url_for("admin_dashboard"))

            try:
                spec_tmp, _public_tmp = parse_qml_markdown(text)
            except QmlParseError as e:
                flash(f"解析失败：{e}（line={e.line}）")
                return redirect(url_for("admin_dashboard"))

            assets_needed: set[str] = set()
            assets_needed |= _collect_md_assets(text)
            for k in ("welcome_image", "end_image"):
                v = _safe_relpath(str(spec_tmp.get(k) or "").strip())
                if _is_local_asset_path(v):
                    assets_needed.add(v)

            md_dir = str(Path(md_name).parent).replace("\\", "/").strip(".")
            assets: dict[str, bytes] = {}
            z_names = set(zf.namelist())
            for rel in sorted(assets_needed):
                rel_norm = _safe_relpath(rel)
                candidates = [rel_norm]
                if md_dir and md_dir not in {".", ""}:
                    candidates.append(f"{md_dir}/{rel_norm}")
                found = None
                for cand in candidates:
                    if cand in z_names:
                        found = cand
                        break
                if not found:
                    continue
                try:
                    assets[rel_norm] = zf.read(found)
                except Exception:
                    continue

            try:
                exam_key = _write_exam_to_storage(text, assets=assets)
            except QmlParseError as e:
                flash(f"解析失败：{e}（line={e.line}）")
                return redirect(url_for("admin_dashboard"))
            flash(f"上传并解析成功：{exam_key}")
            sort_id = _sort_id_from_exam_key(exam_key)
            if sort_id:
                return redirect(url_for("admin_exam_detail_by_sort_id", exam_id=sort_id))
            return redirect(url_for("admin_exam_detail", exam_key=exam_key))

        # Plain markdown upload (assets must be URLs).
        text = file.read().decode("utf-8", errors="replace")
        try:
            exam_key = _write_exam_to_storage(text, assets=None)
        except QmlParseError as e:
            flash(f"解析失败：{e}（line={e.line}）")
            return redirect(url_for("admin_dashboard"))
        flash(f"上传并解析成功：{exam_key}")
        sort_id = _sort_id_from_exam_key(exam_key)
        if sort_id:
            return redirect(url_for("admin_exam_detail_by_sort_id", exam_id=sort_id))
        return redirect(url_for("admin_exam_detail", exam_key=exam_key))

    @app.get("/admin/exams/<exam_key>")     # 根据key值得到试卷细节
    @admin_required
    @admin_required
    def admin_exam_detail(exam_key: str):
        sort_id = _sort_id_from_exam_key(exam_key)
        if sort_id:
            return redirect(url_for("admin_exam_detail_by_sort_id", exam_id=sort_id))
        spec_path = STORAGE_DIR / "exams" / exam_key / "spec.json"
        if not spec_path.exists():
            abort(404)
        spec = read_json(spec_path)
        exam_stats = _compute_exam_stats(spec)

        return render_template(
            "admin_exam_detail.html",
            spec=spec,
            exam_key=exam_key,
            exam_sort_id=None,
            view="detail",
            exam_stats=exam_stats,
        )

    def _compute_exam_stats(spec: dict) -> dict:
        questions = list(spec.get("questions") or [])
        counts_by_type: dict[str, int] = {}
        points_by_type: dict[str, int] = {}
        total_points = 0
        for q in questions:
            t = str(q.get("type") or "").strip() or "unknown"
            counts_by_type[t] = int(counts_by_type.get(t, 0)) + 1
            try:
                pts = int(q.get("max_points") or 0)
            except Exception:
                pts = 0
            points_by_type[t] = int(points_by_type.get(t, 0)) + pts
            total_points += pts
        return {
            "total_questions": len(questions),
            "total_points": int(total_points),
            "counts_by_type": counts_by_type,
            "points_by_type": points_by_type,
        }

    @app.get("/admin/exams/<int:exam_id>")  # sort-id URL (newest=larger id)
    @admin_required
    def admin_exam_detail_by_sort_id(exam_id: int):
        exam_key = _exam_key_from_sort_id(exam_id)
        if not exam_key:
            abort(404)
        spec_path = STORAGE_DIR / "exams" / exam_key / "spec.json"
        if not spec_path.exists():
            abort(404)
        spec = read_json(spec_path)
        exam_stats = _compute_exam_stats(spec)
        return render_template(
            "admin_exam_detail.html",
            spec=spec,
            exam_key=exam_key,
            exam_sort_id=int(exam_id),
            view="detail",
            exam_stats=exam_stats,
        )

    @app.get("/admin/exams/<int:exam_id>/edit")
    @admin_required
    def admin_exam_edit_by_sort_id(exam_id: int):
        exam_key = _exam_key_from_sort_id(exam_id)
        if not exam_key:
            abort(404)
        exam_dir = STORAGE_DIR / "exams" / exam_key
        source_path = exam_dir / "source.md"
        spec_path = exam_dir / "spec.json"
        if not source_path.exists() or not spec_path.exists():
            abort(404)
        try:
            source_md = source_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            source_md = ""
        spec = read_json(spec_path)
        return render_template(
            "admin_exam_edit.html",
            exam_key=exam_key,
            exam_sort_id=int(exam_id),
            spec=spec,
            source_md=source_md,
            view="edit",
        )

    @app.post("/admin/exams/<int:exam_id>/edit")
    @admin_required
    def admin_exam_edit_save_by_sort_id(exam_id: int):
        exam_key = _exam_key_from_sort_id(exam_id)
        if not exam_key:
            abort(404)
        new_source_md = request.form.get("source_md") or ""
        new_source_md = new_source_md.replace("\r\n", "\n")
        if not new_source_md.strip():
            flash("内容不能为空")
            return redirect(url_for("admin_exam_edit_by_sort_id", exam_id=int(exam_id)))
        try:
            new_exam_key = _admin_update_exam_from_source(exam_key, new_source_md)
        except FileExistsError as e:
            flash(str(e))
            return redirect(url_for("admin_exam_edit_by_sort_id", exam_id=int(exam_id)))
        except QmlParseError as e:
            flash(f"解析失败：{e}（line={e.line}）")
            return render_template(
                "admin_exam_edit.html",
                exam_key=exam_key,
                exam_sort_id=int(exam_id),
                spec=read_json(STORAGE_DIR / "exams" / exam_key / "spec.json"),
                source_md=new_source_md,
                view="edit",
            )
        except Exception as e:
            logger.exception("Edit exam failed (exam_key=%s)", exam_key)
            flash(f"保存失败：{e}")
            return redirect(url_for("admin_exam_edit_by_sort_id", exam_id=int(exam_id)))
        flash("已保存并重新解析")
        new_sort_id = _sort_id_from_exam_key(new_exam_key)
        if new_sort_id:
            return redirect(url_for("admin_exam_detail_by_sort_id", exam_id=int(new_sort_id)))
        return redirect(url_for("admin_exam_detail", exam_key=new_exam_key))

    @app.get("/admin/exams/<int:exam_id>/paper")
    @admin_required
    def admin_exam_paper_by_sort_id(exam_id: int):
        exam_key = _exam_key_from_sort_id(exam_id)
        if not exam_key:
            abort(404)
        public_path = STORAGE_DIR / "exams" / exam_key / "public.json"
        spec_path = STORAGE_DIR / "exams" / exam_key / "spec.json"
        if not public_path.exists() or not spec_path.exists():
            abort(404)
        public_spec = read_json(public_path)
        spec = read_json(spec_path)
        exam_stats = _compute_exam_stats(spec)
        return render_template(
            "admin_exam_paper.html",
            exam_key=exam_key,
            exam_sort_id=int(exam_id),
            spec=public_spec,
            title=str(spec.get("title") or ""),
            description=str(spec.get("description") or ""),
            exam_stats=exam_stats,
            view="paper",
        )

    @app.get("/admin/exams/<exam_key>/edit")
    @admin_required
    def admin_exam_edit(exam_key: str):
        sort_id = _sort_id_from_exam_key(exam_key)
        if sort_id:
            return redirect(url_for("admin_exam_edit_by_sort_id", exam_id=sort_id))
        exam_dir = STORAGE_DIR / "exams" / exam_key
        source_path = exam_dir / "source.md"
        spec_path = exam_dir / "spec.json"
        if not source_path.exists() or not spec_path.exists():
            abort(404)
        try:
            source_md = source_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            source_md = ""
        spec = read_json(spec_path)
        return render_template(
            "admin_exam_edit.html",
            exam_key=exam_key,
            exam_sort_id=None,
            spec=spec,
            source_md=source_md,
            view="edit",
        )

    @app.post("/admin/exams/<exam_key>/edit")
    @admin_required
    def admin_exam_edit_save(exam_key: str):
        new_source_md = request.form.get("source_md") or ""
        new_source_md = new_source_md.replace("\r\n", "\n")
        if not new_source_md.strip():
            flash("内容不能为空")
            return redirect(url_for("admin_exam_edit", exam_key=exam_key))
        try:
            new_exam_key = _admin_update_exam_from_source(exam_key, new_source_md)
        except FileExistsError as e:
            flash(str(e))
            return redirect(url_for("admin_exam_edit", exam_key=exam_key))
        except QmlParseError as e:
            flash(f"解析失败：{e}（line={e.line}）")
            return render_template(
                "admin_exam_edit.html",
                exam_key=exam_key,
                exam_sort_id=_sort_id_from_exam_key(exam_key),
                spec=read_json(STORAGE_DIR / "exams" / exam_key / "spec.json"),
                source_md=new_source_md,
                view="edit",
            )
        except Exception as e:
            logger.exception("Edit exam failed (exam_key=%s)", exam_key)
            flash(f"保存失败：{e}")
            return redirect(url_for("admin_exam_edit", exam_key=exam_key))
        flash("已保存并重新解析")
        return redirect(url_for("admin_exam_detail", exam_key=new_exam_key))

    @app.get("/admin/exams/<exam_key>/paper")
    @admin_required
    def admin_exam_paper(exam_key: str):
        sort_id = _sort_id_from_exam_key(exam_key)
        if sort_id:
            return redirect(url_for("admin_exam_paper_by_sort_id", exam_id=sort_id))
        public_path = STORAGE_DIR / "exams" / exam_key / "public.json"
        spec_path = STORAGE_DIR / "exams" / exam_key / "spec.json"
        if not public_path.exists() or not spec_path.exists():
            abort(404)
        public_spec = read_json(public_path)
        spec = read_json(spec_path)
        exam_stats = _compute_exam_stats(spec)
        return render_template(
            "admin_exam_paper.html",
            exam_key=exam_key,
            exam_sort_id=None,
            spec=public_spec,
            title=str(spec.get("title") or ""),
            description=str(spec.get("description") or ""),
            exam_stats=exam_stats,
            view="paper",
        )

    @app.post("/admin/exams/<exam_key>/delete")
    @admin_required
    def admin_exam_delete(exam_key: str):
        exam_dir = STORAGE_DIR / "exams" / exam_key
        if not exam_dir.exists():
            flash("试卷不存在或已删除")
            return redirect(url_for("admin_dashboard") + "#tab-exams")

        affected = 0
        try:
            affected = mark_exam_deleted(exam_key)
        except Exception:
            logger.exception("Mark exam deleted failed (exam_key=%s)", exam_key)

        deleted_assignments = 0
        deleted_qr = 0
        assignments_dir = STORAGE_DIR / "assignments"
        if assignments_dir.exists():
            for p in assignments_dir.glob("*.json"):
                try:
                    a = read_json(p)
                except Exception:
                    continue
                if str(a.get("exam_key") or "") != exam_key:
                    continue
                token = str(a.get("token") or p.stem)
                try:
                    p.unlink(missing_ok=True)
                    deleted_assignments += 1
                except Exception:
                    pass
                qr_path = STORAGE_DIR / "qr" / f"{token}.png"
                try:
                    if qr_path.exists():
                        qr_path.unlink(missing_ok=True)
                        deleted_qr += 1
                except Exception:
                    pass

        try:
            shutil.rmtree(exam_dir)
        except Exception:
            logger.exception("Delete exam dir failed: %s", exam_dir)
            flash("删除失败：试卷目录无法删除（请检查文件占用/权限）")
            return redirect(url_for("admin_exam_detail", exam_key=exam_key))

        # Success: keep UI quiet (no flash), user can see result from list refresh.
        return redirect(url_for("admin_dashboard") + "#tab-exams")

    # 候选者信息
    @app.get("/admin/candidates")
    @admin_required
    def admin_candidates():
        q = (request.args.get("q") or "").strip()
        created_from_raw = (request.args.get("created_from") or "").strip()
        created_to_raw = (request.args.get("created_to") or "").strip()

        def _parse_dt(v: str, *, end_of_day: bool = False) -> datetime | None:
            s = str(v or "").strip()
            if not s:
                return None
            try:
                # Supports "YYYY-MM-DD" and "YYYY-MM-DDTHH:MM".
                dt = datetime.fromisoformat(s)
            except Exception:
                return None
            if s.count("-") == 2 and "T" not in s and " " not in s:
                if end_of_day:
                    return dt.replace(hour=23, minute=59, second=59, microsecond=999999)
                return dt.replace(hour=0, minute=0, second=0, microsecond=0)
            return dt

        created_from = _parse_dt(created_from_raw, end_of_day=False)
        created_to = _parse_dt(created_to_raw, end_of_day=True)

        candidates_all = list_candidates(query=q, created_from=created_from, created_to=created_to)

        per_page = 20

        try:
            page = int(request.args.get("page") or "1")
        except Exception:
            page = 1
        page = max(1, page)
        total = len(candidates_all)
        total_pages = (total + per_page - 1) // per_page
        if total_pages > 0:
            page = min(page, total_pages)
        else:
            page = 1

        start = (page - 1) * per_page
        end = start + per_page
        candidates = candidates_all[start:end]

        return render_template(
            "admin_candidates.html",
            candidates=candidates,
            q=q,
            created_from=created_from_raw,
            created_to=created_to_raw,
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages,
        )

    @app.get("/admin/candidates/<int:candidate_id>")
    @admin_required
    def admin_candidate_profile(candidate_id: int):
        c = get_candidate(candidate_id)
        if not c:
            abort(404)

        parsed = c.get("resume_parsed") or {}
        if not isinstance(parsed, dict):
            parsed = {}
        details = parsed.get("details") or {}
        if not isinstance(details, dict):
            details = {}
        details_status = str(details.get("status") or "")
        details_data = details.get("data") or {}
        if not isinstance(details_data, dict):
            details_data = {}

        def _degree_rank(v: str) -> int:
            s = str(v or "").strip()
            order = {"高中": 1, "大专": 2, "本科": 3, "硕士": 4, "博士": 5}
            return order.get(s, 0)

        def _highest_degree(educations: list[dict]) -> str:
            best = ""
            best_r = 0
            for e in educations or []:
                if not isinstance(e, dict):
                    continue
                d = str(e.get("degree") or "").strip()
                r = _degree_rank(d)
                if r > best_r:
                    best_r = r
                    best = d
            if best:
                return best
            return str(details_data.get("highest_education") or "").strip()

        educations = details_data.get("educations") or []
        if not isinstance(educations, list):
            educations = []
        edu_list = [e for e in educations if isinstance(e, dict)]

        highest = _highest_degree(edu_list)
        show_degrees: set[str] = set()
        if highest == "博士":
            show_degrees = {"本科", "硕士", "博士"}
        elif highest == "硕士":
            show_degrees = {"本科", "硕士"}
        elif highest == "本科":
            show_degrees = {"本科"}
        elif highest:
            show_degrees = {highest}

        edu_show = [e for e in edu_list if not show_degrees or str(e.get("degree") or "") in show_degrees]
        edu_show.sort(key=lambda x: _degree_rank(str(x.get("degree") or "")))
        for e in edu_show:
            try:
                tag, label = classify_university(str(e.get("school") or ""))
            except Exception:
                tag, label = "", ""
            e["school_tag"] = tag
            e["school_tag_label"] = label

        email = ""
        emails = details_data.get("emails") or []
        if isinstance(emails, list) and emails:
            email = str(emails[0] or "").strip()

        english = details_data.get("english") or {}
        if not isinstance(english, dict):
            english = {}

        projects = details_data.get("projects") or []
        if not isinstance(projects, list):
            projects = []
        projects = [p for p in projects if isinstance(p, dict)]
        projects_raw = ""
        try:
            projects_raw = str(details_data.get("projects_raw") or "").strip()
        except Exception:
            projects_raw = ""
        projects_raw_blocks: list[dict[str, str]] = []
        if projects_raw:
            try:
                projects_raw_blocks = _split_projects_raw(projects_raw)
            except Exception:
                projects_raw_blocks = []

        evaluation_llm = ""
        try:
            evaluation_llm = str(details_data.get("evaluation") or "").strip()
        except Exception:
            evaluation_llm = ""
        if not evaluation_llm:
            try:
                evaluation_llm = str(details_data.get("summary") or "").strip()
            except Exception:
                evaluation_llm = ""

        evaluation_admin = ""
        try:
            evaluation_admin = str(details_data.get("admin_evaluation") or "").strip()
        except Exception:
            evaluation_admin = ""

        admin_evaluations: list[dict[str, str]] = []
        try:
            raw_list = details_data.get("admin_evaluations")
        except Exception:
            raw_list = None
        if isinstance(raw_list, list):
            for it in raw_list:
                if not isinstance(it, dict):
                    continue
                text = str(it.get("text") or "").strip()
                at = str(it.get("at") or "").strip()
                if not text:
                    continue
                at_display = ""
                if at:
                    try:
                        at_display = datetime.fromisoformat(at).astimezone().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    except Exception:
                        at_display = at
                admin_evaluations.append({"text": text, "at": at, "at_display": at_display})
        elif evaluation_admin:
            # Backward-compat: previously stored as a single concatenated string.
            blocks = [b.strip() for b in re.split(r"\n\s*\n", evaluation_admin) if b.strip()]
            for b in blocks:
                lines = [ln.rstrip() for ln in (b or "").splitlines()]
                if not lines:
                    continue
                at = ""
                text_lines = lines
                m = re.match(r"^\[(.+?)\]\s*$", lines[0].strip())
                if m:
                    at = m.group(1).strip()
                    text_lines = lines[1:]
                text = "\n".join(text_lines).strip()
                if not text:
                    continue
                admin_evaluations.append({"text": text, "at": at, "at_display": at})

        # Attempt results: show only submitted + scored attempts from archives.
        attempt_results: list[dict[str, str]] = []
        try:
            phone = str(c.get("phone") or "").strip()
        except Exception:
            phone = ""
        archives_dir = STORAGE_DIR / "archives"

        def _iso_to_local_str(v: str) -> str:
            s = str(v or "").strip()
            if not s:
                return ""
            try:
                s2 = s.replace("Z", "+00:00")
                return datetime.fromisoformat(s2).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return s

        if phone and archives_dir.exists():
            files = [p for p in archives_dir.glob(f"*_{phone}_*.json") if p.is_file()]
            rows: list[dict[str, object]] = []
            for p in files:
                try:
                    a = read_json(p)
                except Exception:
                    continue
                if not isinstance(a, dict):
                    continue
                timing = a.get("timing") or {}
                if not isinstance(timing, dict):
                    timing = {}
                start_at = str(timing.get("start_at") or "").strip()
                end_at = str(timing.get("end_at") or "").strip()
                score = a.get("total_score")
                if not end_at or score is None:
                    continue
                exam = a.get("exam") or {}
                if not isinstance(exam, dict):
                    exam = {}
                title = str(exam.get("title") or "").strip()
                exam_key = str(exam.get("exam_key") or "").strip()
                exam_name = title or exam_key or "—"

                sort_key = 0.0
                try:
                    sort_key = datetime.fromisoformat(end_at.replace("Z", "+00:00")).timestamp()
                except Exception:
                    try:
                        sort_key = float(p.stat().st_mtime)
                    except Exception:
                        sort_key = 0.0

                rows.append(
                    {
                        "exam_name": exam_name,
                        "score": str(score),
                        "start_at": start_at,
                        "end_at": end_at,
                        "_sort_key": sort_key,
                        "_archive_name": str(p.name),
                    }
                )

            rows.sort(key=lambda x: float(x.get("_sort_key") or 0.0))
            for i, r in enumerate(rows, start=1):
                attempt_results.append(
                    {
                        "no": str(i),
                        "exam_name": str(r.get("exam_name") or ""),
                        "score": str(r.get("score") or ""),
                        "start_at": _iso_to_local_str(str(r.get("start_at") or "")),
                        "end_at": _iso_to_local_str(str(r.get("end_at") or "")),
                        "attempt_href": url_for(
                            "admin_candidate_attempt_by_archive",
                            candidate_id=candidate_id,
                            archive_name=str(r.get("_archive_name") or ""),
                        ),
                    }
                )

        return render_template(
            "admin_candidate_profile.html",
            c=c,
            gender=str(details_data.get("gender") or "").strip(),
            email=email,
            highest_education=str(details_data.get("highest_education") or "").strip(),
            educations=edu_show,
            english=english,
            projects=projects,
            projects_raw=projects_raw,
            projects_raw_blocks=projects_raw_blocks,
            attempt_results=attempt_results,
            evaluation_llm=evaluation_llm,
            evaluation_admin=evaluation_admin,
            admin_evaluations=admin_evaluations,
            details_status=details_status,
            details_error=str(details.get("error") or ""),
        )

    @app.post("/admin/candidates/<int:candidate_id>/evaluation/update")
    @admin_required
    def admin_candidate_evaluation_update(candidate_id: int):
        c = get_candidate(candidate_id)
        if not c:
            abort(404)

        evaluation = str(request.form.get("evaluation") or "").strip()
        if not evaluation:
            flash("请输入评价内容")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

        parsed = c.get("resume_parsed") or {}
        if not isinstance(parsed, dict):
            parsed = {}
        details = parsed.get("details") or {}
        if not isinstance(details, dict):
            details = {}
        details_data = details.get("data") or {}
        if not isinstance(details_data, dict):
            details_data = {}

        try:
            existing = details_data.get("admin_evaluations")
        except Exception:
            existing = None
        items: list[dict[str, str]] = []
        if isinstance(existing, list):
            for it in existing:
                if not isinstance(it, dict):
                    continue
                text = str(it.get("text") or "").strip()
                at = str(it.get("at") or "").strip()
                if not text:
                    continue
                items.append({"text": text, "at": at})
        else:
            # Backward-compat: migrate old string blob into list on first append.
            try:
                prev_blob = str(details_data.get("admin_evaluation") or "").strip()
            except Exception:
                prev_blob = ""
            if prev_blob:
                blocks = [b.strip() for b in re.split(r"\n\s*\n", prev_blob) if b.strip()]
                for b in blocks:
                    lines = [ln.rstrip() for ln in (b or "").splitlines()]
                    if not lines:
                        continue
                    at = ""
                    text_lines = lines
                    m = re.match(r"^\[(.+?)\]\s*$", lines[0].strip())
                    if m:
                        at = m.group(1).strip()
                        text_lines = lines[1:]
                    text = "\n".join(text_lines).strip()
                    if not text:
                        continue
                    items.append({"text": text, "at": at})

        now_iso = datetime.now(timezone.utc).isoformat()
        items.append({"text": evaluation, "at": now_iso})
        details_data["admin_evaluations"] = items
        # Keep legacy key for compatibility with older pages/records.
        details_data["admin_evaluation"] = ""

        details["data"] = details_data
        parsed["details"] = details

        try:
            # Do NOT touch resume_parsed_at here: it represents the LLM parse time,
            # and must not be tied to admin evaluation save time.
            update_candidate_resume_parsed(
                candidate_id, resume_parsed=parsed, touch_resume_parsed_at=False
            )
        except Exception:
            logger.exception("Update candidate evaluation failed (cid=%s)", candidate_id)
            flash("保存失败：评价写入失败")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

        flash("评价已保存")
        return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

    @app.get("/admin/candidates/<int:candidate_id>/resume/download")
    @admin_required
    def admin_candidate_resume_download(candidate_id: int):
        c = get_candidate(candidate_id)
        if not c:
            abort(404)

        r = get_candidate_resume(candidate_id)
        if not r:
            abort(404)
        data = r.get("resume_bytes") or b""
        if not isinstance(data, (bytes, bytearray)) or len(data) <= 0:
            abort(404)

        raw_name = str(r.get("resume_filename") or "").strip()
        name = os.path.basename(raw_name) if raw_name else ""
        if not name:
            ext = ""
            mime = str(r.get("resume_mime") or "").lower().strip()
            if "pdf" in mime:
                ext = ".pdf"
            elif "word" in mime or "docx" in mime:
                ext = ".docx"
            elif "markdown" in mime or mime.endswith("/md"):
                ext = ".md"
            elif "text" in mime:
                ext = ".txt"
            name = f"candidate_{candidate_id}_resume{ext or '.bin'}"

        mime = str(r.get("resume_mime") or "").strip() or "application/octet-stream"
        return send_file(
            BytesIO(data),
            mimetype=mime,
            as_attachment=True,
            download_name=name,
        )

    @app.post("/admin/candidates/<int:candidate_id>/resume/reparse")
    @admin_required
    def admin_candidate_resume_reparse(candidate_id: int):
        c = get_candidate(candidate_id)
        if not c:
            abort(404)

        file = request.files.get("file")
        if not file or not getattr(file, "filename", ""):
            flash("请选择简历文件")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

        try:
            data = file.read() or b""
        except Exception:
            flash("简历文件读取失败")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

        if len(data) > 10 * 1024 * 1024:
            flash("简历文件过大（需小于等于 10MB）")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

        filename = str(file.filename or "")
        ext = os.path.splitext(filename)[1].lower()
        if ext not in {".pdf", ".docx", ".txt", ".md"}:
            flash("暂不支持该文件类型（仅支持 PDF/DOCX/TXT/MD）")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

        try:
            text = extract_resume_text(data, filename)
        except Exception as e:
            logger.exception("Resume extract failed")
            flash(f"简历解析失败：{type(e).__name__}({e})")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

        mime = str(getattr(file, "mimetype", "") or "")

        # Keep behavior aligned with /admin/candidates/resume/upload:
        # - Parse identity from resume, but DO NOT change candidate phone.
        # - If extracted phone conflicts with current candidate phone, reject to avoid accidental overwrite.
        # - If candidate name is unknown, fill it from resume.
        parsed_name = ""
        parsed_phone = ""
        name_conf = 0
        phone_conf = 0
        method: dict[str, str] = {"identity": "fast", "name": "fast"}
        try:
            fast = parse_resume_identity_fast(text or "") or {}
            parsed_name = str(fast.get("name") or "").strip()
            parsed_phone = _normalize_phone(str(fast.get("phone") or "").strip())
            conf = fast.get("confidence") or {}
            phone_conf = _safe_int((conf.get("phone") if isinstance(conf, dict) else 0) or 0, 0)
            name_conf = _safe_int((conf.get("name") if isinstance(conf, dict) else 0) or 0, 0)
        except Exception:
            parsed_name = ""
            parsed_phone = ""

        # If phone is missing/invalid, fallback to LLM (blocking), same as upload.
        if not _is_valid_phone(parsed_phone):
            try:
                ident = parse_resume_identity_llm(text or "") or {}
                parsed_name = str(ident.get("name") or "").strip()
                parsed_phone = _normalize_phone(str(ident.get("phone") or "").strip())
                conf2 = ident.get("confidence") or {}
                phone_conf = _safe_int((conf2.get("phone") if isinstance(conf2, dict) else 0) or 0, 0)
                name_conf = _safe_int((conf2.get("name") if isinstance(conf2, dict) else 0) or 0, 0)
                method["identity"] = "llm"
                method["name"] = "llm"
            except Exception:
                pass

        # If we have phone but name is missing, do a small LLM call to fill name.
        if _is_valid_phone(parsed_phone) and not _is_valid_name(parsed_name):
            try:
                nm = parse_resume_name_llm(text or "") or {}
                n2 = str(nm.get("name") or "").strip()
                n2_conf = _safe_int(nm.get("confidence") or 0, 0)
                if _is_valid_name(n2):
                    parsed_name = n2
                    name_conf = max(_safe_int(name_conf, 0), _safe_int(n2_conf, 0))
                    method["name"] = "llm"
            except Exception:
                pass

        phone_conf = max(0, min(100, _safe_int(phone_conf, 0)))
        name_conf = max(0, min(100, _safe_int(name_conf, 0)))

        try:
            current_phone = _normalize_phone(str(c.get("phone") or ""))
        except Exception:
            current_phone = ""
        if _is_valid_phone(parsed_phone) and current_phone and parsed_phone != current_phone:
            flash("重新上传的简历手机号与当前候选人不一致，已阻止覆盖（请确认文件是否选错）。")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

        try:
            current_name = str(c.get("name") or "").strip()
        except Exception:
            current_name = ""
        if current_name in {"", "未知"} and _is_valid_name(parsed_name):
            try:
                update_candidate(candidate_id, name=parsed_name, phone=current_phone or parsed_phone)
            except Exception:
                pass

        details: dict[str, Any] = {}
        details_error = ""
        try:
            parsed_details = parse_resume_details_llm(text or "")
            if isinstance(parsed_details, dict):
                details = parsed_details
        except Exception as e:
            logger.exception("Resume details parse failed (cid=%s)", candidate_id)
            details_error = f"{type(e).__name__}: {e}"

        try:
            projects_raw = extract_resume_section(
                text or "",
                section_keywords=["项目经历", "项目经验", "科研项目", "课程设计", "毕业设计", "比赛项目"],
                stop_keywords=[
                    "教育",
                    "教育经历",
                    "教育背景",
                    "学习经历",
                    "实习",
                    "实习经历",
                    "工作经历",
                    "技能",
                    "专业技能",
                    "证书",
                    "获奖",
                    "荣誉",
                    "自我评价",
                    "个人总结",
                ],
                max_chars=6500,
            )
            if projects_raw:
                details["projects_raw"] = _clean_projects_raw(projects_raw)
        except Exception:
            pass

        details_status = "done" if details else ("failed" if details_error else "empty")
        details_block: dict[str, Any] = {
            "status": details_status,
            "data": details,
            "parsed_at": datetime.now(timezone.utc).isoformat(),
        }
        if details_error:
            details_block["error"] = details_error

        parsed = c.get("resume_parsed") or {}
        if not isinstance(parsed, dict):
            parsed = {}
        parsed["extracted"] = {"name": parsed_name, "phone": parsed_phone}
        parsed["confidence"] = {"name": name_conf, "phone": phone_conf}
        parsed["method"] = method
        parsed["source_filename"] = filename
        parsed["source_mime"] = mime
        parsed["details"] = details_block

        try:
            update_candidate_resume(
                candidate_id,
                resume_bytes=data,
                resume_filename=filename,
                resume_mime=mime,
                resume_size=len(data),
                resume_parsed=parsed,
            )
        except Exception:
            logger.exception("Update candidate resume failed (cid=%s)", candidate_id)
            flash("重新解析失败（数据库写入失败）")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

        flash("重新上传成功")
        return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

    # 添加候选者信息，采用post
    @app.post("/admin/candidates")
    @admin_required
    def admin_candidates_create():
        name = (request.form.get("name") or "").strip()
        phone = _normalize_phone(request.form.get("phone") or "")
        if not name or not phone:
            flash("姓名/手机号必填")
            return redirect(url_for("admin_candidates"))
        if not _is_valid_name(name):
            flash("姓名格式不正确（2-20位中文/英文，可含空格/·）")
            return redirect(url_for("admin_candidates"))
        if not _is_valid_phone(phone):
            flash("手机号格式不正确（需为 11 位中国大陆手机号）")
            return redirect(url_for("admin_candidates"))

        existed = get_candidate_by_phone(phone)
        if existed:
            try:
                now = datetime.now(timezone.utc)
                cid = int(existed["id"])
                update_candidate(cid, name=name, phone=phone, created_at=now)
                reset_candidate_exam_state(cid)
            except Exception:
                flash("更新失败")
                return redirect(url_for("admin_candidates"))
            flash("候选人已覆盖更新（按新创建处理）")
            return redirect(url_for("admin_candidates"))

        try:
            cid = create_candidate(name=name, phone=phone)
        except Exception:
            flash("手机号已存在或写入失败")
            return redirect(url_for("admin_candidates"))
        flash("候选人创建成功")
        return redirect(url_for("admin_candidates"))

    @app.post("/admin/candidates/resume/upload")
    @admin_required
    def admin_candidates_resume_upload():
        file = request.files.get("file")
        if not file or not getattr(file, "filename", ""):
            flash("请选择简历文件")
            return redirect(url_for("admin_candidates"))

        try:
            data = file.read() or b""
        except Exception:
            flash("简历文件读取失败")
            return redirect(url_for("admin_candidates"))

        if len(data) > 10 * 1024 * 1024:
            flash("简历文件过大（需小于等于 10MB）")
            return redirect(url_for("admin_candidates"))

        filename = str(file.filename or "")
        ext = os.path.splitext(filename)[1].lower()
        if ext not in {".pdf", ".docx", ".txt", ".md"}:
            flash("暂不支持该文件类型（仅支持 PDF/DOCX/TXT/MD）")
            return redirect(url_for("admin_candidates"))

        try:
            text = extract_resume_text(data, filename)
        except ValueError:
            flash("暂不支持该文件类型（仅支持 PDF/DOCX/TXT/MD）")
            return redirect(url_for("admin_candidates"))
        except RuntimeError as e:
            flash(f"简历解析失败：{e}")
            return redirect(url_for("admin_candidates"))
        except Exception as e:
            logger.exception("Resume extract failed")
            flash(f"简历解析失败：{type(e).__name__}({e})")
            return redirect(url_for("admin_candidates"))

        mime = str(getattr(file, "mimetype", "") or "")

        def _parse_identity(t: str) -> tuple[str, str, int, int, dict[str, str]]:
            fast = parse_resume_identity_fast(t or "") or {}
            parsed_name = str(fast.get("name") or "").strip()
            phone = _normalize_phone(str(fast.get("phone") or "").strip())
            conf = fast.get("confidence") or {}
            phone_conf = _safe_int((conf.get("phone") if isinstance(conf, dict) else 0) or 0, 0)
            name_conf = _safe_int((conf.get("name") if isinstance(conf, dict) else 0) or 0, 0)
            method: dict[str, str] = {"identity": "fast", "name": "fast"}

            # Phone is required to locate candidate; if fast parse fails, fallback to LLM (blocking).
            if not _is_valid_phone(phone):
                ident = parse_resume_identity_llm(t or "") or {}
                parsed_name = str(ident.get("name") or "").strip()
                phone = _normalize_phone(str(ident.get("phone") or "").strip())
                conf2 = ident.get("confidence") or {}
                phone_conf = _safe_int((conf2.get("phone") if isinstance(conf2, dict) else 0) or 0, 0)
                name_conf = _safe_int((conf2.get("name") if isinstance(conf2, dict) else 0) or 0, 0)
                method["identity"] = "llm"
                method["name"] = "llm"

            # If we have phone but name is missing, do a small LLM call to fill name (still stage 1).
            if _is_valid_phone(phone) and not _is_valid_name(parsed_name):
                nm = parse_resume_name_llm(t or "") or {}
                n2 = str(nm.get("name") or "").strip()
                n2_conf = _safe_int(nm.get("confidence") or 0, 0)
                if _is_valid_name(n2):
                    parsed_name = n2
                    name_conf = max(_safe_int(name_conf, 0), _safe_int(n2_conf, 0))
                    method["name"] = "llm"

            phone_conf = max(0, min(100, _safe_int(phone_conf, 0)))
            name_conf = max(0, min(100, _safe_int(name_conf, 0)))
            return parsed_name, phone, name_conf, phone_conf, method

        parsed_name, phone, name_conf, phone_conf, method = _parse_identity(text or "")

        if not _is_valid_phone(phone):
            flash("未识别到有效手机号，无法入库（请检查简历内容或换可复制文本）")
            return redirect(url_for("admin_candidates"))

        name = parsed_name if _is_valid_name(parsed_name) else "未知"

        meta = {
            "extracted": {"name": parsed_name, "phone": phone},
            "confidence": {"name": name_conf, "phone": phone_conf},
            "source_filename": filename,
            "source_mime": mime,
            "method": method,
            "details": {"status": "pending"},
        }

        def _upsert_candidate_by_phone(*, phone: str, name: str) -> tuple[int, bool]:
            existed = get_candidate_by_phone(phone)
            if existed:
                cid = _safe_int(existed.get("id") or 0, 0)
                try:
                    old_name = str(existed.get("name") or "").strip()
                except Exception:
                    old_name = ""
                if cid > 0 and old_name in {"", "未知"} and name != "未知":
                    try:
                        update_candidate(cid, name=name, phone=phone)
                    except Exception:
                        pass
                return cid, False

            try:
                cid = create_candidate(name=name, phone=phone)
                return _safe_int(cid, 0), True
            except Exception:
                existed2 = get_candidate_by_phone(phone) or {}
                cid = _safe_int(existed2.get("id") or 0, 0)
                return cid, False

        cid, created = _upsert_candidate_by_phone(phone=phone, name=name)

        if cid <= 0:
            flash("简历入库失败：无法定位候选人记录（手机号可能已存在且异常）")
            return redirect(url_for("admin_candidates"))

        # Parse full details synchronously so profile page doesn't need to wait.
        details: dict[str, Any] = {}
        details_error = ""
        try:
            parsed_details = parse_resume_details_llm(text or "")
            if isinstance(parsed_details, dict):
                details = parsed_details
        except Exception as e:
            logger.exception("Resume details parse failed (cid=%s)", cid)
            details_error = f"{type(e).__name__}: {e}"

        try:
            projects_raw = extract_resume_section(
                text or "",
                section_keywords=["项目经历", "项目经验", "科研项目", "课程设计", "毕业设计", "比赛项目"],
                stop_keywords=[
                    "教育",
                    "教育经历",
                    "教育背景",
                    "学习经历",
                    "实习",
                    "实习经历",
                    "工作经历",
                    "技能",
                    "专业技能",
                    "证书",
                    "获奖",
                    "荣誉",
                    "自我评价",
                    "个人总结",
                ],
                max_chars=6500,
            )
            if projects_raw:
                details["projects_raw"] = _clean_projects_raw(projects_raw)
        except Exception:
            pass

        details_status = "done" if details else ("failed" if details_error else "empty")
        details_block: dict[str, Any] = {
            "status": details_status,
            "data": details,
            "parsed_at": datetime.now(timezone.utc).isoformat(),
        }
        if details_error:
            details_block["error"] = details_error
        meta["details"] = details_block

        try:
            update_candidate_resume(
                cid,
                resume_bytes=data,
                resume_filename=filename,
                resume_mime=mime,
                resume_size=len(data),
                resume_parsed=meta,
            )
        except Exception:
            logger.exception("Update candidate resume failed (cid=%s)", cid)
            flash("简历保存失败（数据库写入失败）")
            return redirect(url_for("admin_candidates"))

        msg = "简历上传成功，候选人已创建" if created else "简历上传成功，已更新候选人简历"
        if name == "未知":
            msg += "（提示：姓名未识别成功，请手动编辑或换可复制文本简历）"
        if phone_conf and phone_conf < 60:
            msg += f"（提示：手机号提取置信度较低 {phone_conf}/100，请核对）"
        if name_conf and name_conf < 60:
            msg += f"（提示：姓名提取置信度较低 {name_conf}/100，请核对）"
        flash(msg)
        return redirect(url_for("admin_candidates"))

    # 修改候选者身份信息
    @app.get("/admin/candidates/<int:candidate_id>/edit")
    @admin_required
    def admin_candidates_edit(candidate_id: int):
        # Deprecated: inline editing is now done on the profile page.
        return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

    @app.get("/admin/candidates/<int:candidate_id>/attempt")
    @admin_required
    def admin_candidate_attempt(candidate_id: int):
        c = get_candidate(candidate_id)
        if not c:
            flash("候选人不存在")
            return redirect(url_for("admin_candidates"))
        if str(c.get("status") or "") != "finished":
            flash("候选者未提交答卷")
            return redirect(url_for("admin_dashboard") + "#tab-assign")
        p = _find_latest_archive(c)
        if not p:
            flash("候选者未提交答卷")
            return redirect(url_for("admin_dashboard") + "#tab-assign")
        try:
            archive = read_json(p)
        except Exception:
            flash("答题归档读取失败")
            return redirect(url_for("admin_candidates"))
        try:
            archive = _augment_archive_with_spec(archive)
        except Exception:
            pass
        return render_template("admin_candidate_attempt.html", archive=archive)

    @app.get("/admin/candidates/<int:candidate_id>/attempts/<path:archive_name>")
    @admin_required
    def admin_candidate_attempt_by_archive(candidate_id: int, archive_name: str):
        c = get_candidate(candidate_id)
        if not c:
            flash("候选人不存在")
            return redirect(url_for("admin_candidates"))

        phone = str(c.get("phone") or "").strip()
        name = os.path.basename(str(archive_name or "").strip())
        if not name or name != archive_name or "/" in name or "\\" in name:
            abort(404)
        if not phone or f"_{phone}_" not in name:
            abort(404)

        p = STORAGE_DIR / "archives" / name
        try:
            if not p.exists() or not p.is_file():
                abort(404)
        except Exception:
            abort(404)

        try:
            archive = read_json(p)
        except Exception:
            flash("答题归档读取失败")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))
        try:
            # Extra safety: ensure archive belongs to the same candidate.
            cand = archive.get("candidate") or {}
            if str(cand.get("phone") or "").strip() != phone:
                abort(404)
        except Exception:
            abort(404)

        try:
            archive = _augment_archive_with_spec(archive)
        except Exception:
            pass
        return render_template("admin_candidate_attempt.html", archive=archive)

    # 修改候选人信息
    @app.post("/admin/candidates/<int:candidate_id>/edit")
    @admin_required
    def admin_candidates_edit_post(candidate_id: int):
        # Deprecated: inline editing is now done on the profile page.
        return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

    # 删除候选者身份信息
    @app.post("/admin/candidates/<int:candidate_id>/delete")
    @admin_required
    def admin_candidates_delete(candidate_id: int):
        c = get_candidate(candidate_id)
        if not c:
            flash("候选人不存在")
            return redirect(url_for("admin_candidates"))
        try:
            delete_candidate(candidate_id)
        except Exception:
            flash("删除失败")
            return redirect(url_for("admin_candidates"))
        flash("候选人已删除")
        return redirect(url_for("admin_candidates"))

    # 分发试卷
    @app.post("/admin/assignments")
    @admin_required
    def admin_assignments_create():
        exam_key = (request.form.get("exam_key") or "").strip()
        candidate_id = int(request.form.get("candidate_id") or "0")
        time_limit_seconds = _parse_duration_seconds(request.form.get("time_limit_seconds")) or 7200
        pass_threshold = int(request.form.get("pass_threshold") or "60")
        verify_max_attempts = int(request.form.get("verify_max_attempts") or "3")

        spec_path = STORAGE_DIR / "exams" / exam_key / "spec.json"
        if not spec_path.exists():
            flash("试卷不存在")
            return redirect(url_for("admin_dashboard"))

        c = get_candidate(candidate_id)
        if not c:
            flash("候选人不存在")
            return redirect(url_for("admin_dashboard"))

        if has_recent_exam_submission_by_phone(str(c.get("phone") or ""), months=6):
            flash("候选者6个月内已参加笔试，无法再次分发试卷")
            return redirect(url_for("admin_dashboard"))
        set_candidate_status(candidate_id, "distributed")
        set_candidate_exam_key(candidate_id, exam_key)

        base_url = request.url_root.rstrip("/")
        result = create_assignment(
            exam_key=exam_key,
            candidate_id=candidate_id,
            base_url=base_url,
            time_limit_seconds=time_limit_seconds,
            verify_max_attempts=verify_max_attempts,
            pass_threshold=pass_threshold,
        )
        return render_template(
            "admin_assignment_created.html",
            exam_key=exam_key,
            candidate_id=candidate_id,
            token=result["token"],
            url=result["url"],
        )

    # 生成二维码图片
    @app.get("/admin/qr/<token>.png")
    @admin_required
    def admin_qr(token: str):
        qr_path = STORAGE_DIR / "qr" / f"{token}.png"
        if not qr_path.exists():
            abort(404)
        return send_file(qr_path, mimetype="image/png")

    # 带token的url，加载对应的答卷，并渲染答卷
    @app.get("/admin/result/<token>")
    @admin_required
    def admin_result(token: str):
        assignment = load_assignment(token)
        return render_template("admin_result.html", assignment=assignment)

    # ---------------- Candidate ----------------
    @app.get("/t/<token>")
    def public_verify_page(token: str):
        with assignment_locked(token):
            assignment = load_assignment(token)
            if assignment.get("grading") or _finalize_if_time_up(token, assignment):
                return redirect(url_for("public_done", token=token))
        verify = assignment.get("verify") or {}
        c = get_candidate(int(assignment.get("candidate_id") or 0))
        if c and c.get("status") == "finished":
            return redirect(url_for("public_done", token=token))
        return render_template(
            "public_verify.html",
            token=token,
            locked=bool(verify.get("locked")),
            attempts=int(verify.get("attempts") or 0),
            max_attempts=int(assignment.get("verify_max_attempts") or 3),
        )

    # 验证候选者信息进入答卷
    @app.post("/api/public/verify")
    def public_verify():
        token = (request.form.get("token") or "").strip()
        name = (request.form.get("name") or "").strip()
        phone = _normalize_phone(request.form.get("phone") or "")
        if not _is_valid_name(name) or not _is_valid_phone(phone):
            flash("姓名或手机号格式不正确")
            return redirect(url_for("public_verify_page", token=token))
        with assignment_locked(token):
            assignment = load_assignment(token)
            if assignment.get("grading") or _finalize_if_time_up(token, assignment):
                return redirect(url_for("public_done", token=token))
            verify = assignment.get("verify") or {"attempts": 0, "locked": False}
            if verify.get("locked"):
                flash("链接已失效")
                return redirect(url_for("public_verify_page", token=token))

            candidate_id = int(assignment["candidate_id"])
            c0 = get_candidate(candidate_id)
            if c0 and c0.get("status") == "finished":
                return redirect(url_for("public_done", token=token))
            ok = verify_candidate(candidate_id, name=name, phone=phone)
            if ok:
                c = get_candidate(candidate_id)
                if c and c.get("status") != "finished":
                    set_candidate_status(candidate_id, "verified")
            else:
                verify["attempts"] = int(verify.get("attempts") or 0) + 1
                if verify["attempts"] >= int(assignment.get("verify_max_attempts") or 3):
                    verify["locked"] = True

            assignment["verify"] = verify
            save_assignment(token, assignment)

        if ok:
            c = get_candidate(candidate_id)
            if c and c.get("status") == "finished":
                return redirect(url_for("public_done", token=token))
            return redirect(url_for("public_exam_page", token=token))

        flash("信息不匹配，请重试")
        return redirect(url_for("public_verify_page", token=token))

    @app.get("/a/<token>")
    def public_exam_page(token: str):
        with assignment_locked(token):
            assignment = load_assignment(token)
            if (assignment.get("verify") or {}).get("locked"):
                abort(410)

            candidate_id = int(assignment["candidate_id"])
            c = get_candidate(candidate_id)
            if not c or c["status"] not in {"verified", "finished"}:
                return redirect(url_for("public_verify_page", token=token))
            if c["status"] == "finished" or assignment.get("grading"):
                return redirect(url_for("public_done", token=token))

            # Start countdown only when candidate enters exam page (and never reset on re-verify).
            timing = assignment.setdefault("timing", {})
            started_iso = timing.get("start_at")
            if not started_iso:
                now = datetime.now(timezone.utc)
                timing["start_at"] = now.isoformat()
                try:
                    set_candidate_exam_started_at(candidate_id, now)
                except Exception:
                    pass

            time_limit_seconds = int(assignment.get("time_limit_seconds") or 0)
            remaining = _remaining_seconds(assignment)
            if time_limit_seconds > 0 and remaining <= 0:
                # Time is up: auto-submit on server side (robust even if browser is closed).
                now = datetime.now(timezone.utc)
                try:
                    _finalize_public_submission(token, assignment, now=now)
                except Exception:
                    logger.exception("Auto-submit failed (token=%s)", token)
                return redirect(url_for("public_done", token=token))

            exam_key = assignment["exam_key"]
            public_path = STORAGE_DIR / "exams" / exam_key / "public.json"
            public_spec = read_json(public_path)
            exam_stats = _compute_exam_stats(public_spec)
            min_submit_seconds = compute_min_submit_seconds(
                time_limit_seconds, assignment.get("min_submit_seconds")
            )
            if int(assignment.get("min_submit_seconds") or 0) != min_submit_seconds:
                assignment["min_submit_seconds"] = int(min_submit_seconds)
            save_assignment(token, assignment)

        return render_template(
            "public_exam.html",
            token=token,
            exam_key=exam_key,
            spec=public_spec,
            exam_stats=exam_stats,
            type_label_map={
                "single": "单选",
                "multiple": "多选",
                "short": "简答",
                "unknown": "其他",
            },
            remaining_seconds=remaining,
            time_limit_seconds=time_limit_seconds,
            min_submit_seconds=min_submit_seconds,
            answers=assignment.get("answers") or {},
        )

    @app.post("/api/public/answers/<token>")
    def public_save_answers(token: str):
        with assignment_locked(token):
            assignment = load_assignment(token)     # 将答题数据存入到json中
            if (assignment.get("verify") or {}).get("locked"):
                abort(410)
            if assignment.get("grading") or _finalize_if_time_up(token, assignment):
                return {"ok": False, "error": "already_submitted"}, 409
            qid = (request.form.get("question_id") or "").strip()
            if not qid:
                return {"ok": True}
            value = request.form.get("answer")
            multi = request.form.getlist("answer[]")
            if multi:
                value = multi
            if value is None:
                # Don't overwrite existing answer with null/None.
                return {"ok": True}
            assignment.setdefault("answers", {})[qid] = value
            save_assignment(token, assignment)
        return {"ok": True}

    @app.post("/api/public/answers_bulk/<token>")
    def public_save_answers_bulk(token: str):
        data = request.get_json(silent=True) or {}
        answers = data.get("answers")
        if not isinstance(answers, dict):
            return {"ok": False, "error": "invalid_payload"}, 400

        with assignment_locked(token):
            assignment = load_assignment(token)
            if (assignment.get("verify") or {}).get("locked"):
                abort(410)
            if assignment.get("grading") or _finalize_if_time_up(token, assignment):
                return {"ok": False, "error": "already_submitted"}

            out = assignment.setdefault("answers", {})
            for k, v in answers.items():
                qid = str(k or "").strip()
                if not qid:
                    continue
                if isinstance(v, list):
                    out[qid] = [str(x) for x in v]
                elif v is None:
                    continue
                else:
                    out[qid] = str(v)
            save_assignment(token, assignment)
        return {"ok": True}

    @app.post("/api/public/submit/<token>")
    def public_submit(token: str):
        with assignment_locked(token):
            assignment = load_assignment(token)
        if (assignment.get("verify") or {}).get("locked"):
            abort(410)
        if assignment.get("grading"):
            _sync_candidate_finished_from_assignment(assignment)
            return redirect(url_for("public_done", token=token))

        now = datetime.now(timezone.utc)
        timing = assignment.setdefault("timing", {})
        started_at = _parse_iso_dt(timing.get("start_at"))
        if not started_at:
            started_at = now
            timing["start_at"] = now.isoformat()

        time_limit_seconds = int(assignment.get("time_limit_seconds") or 0)
        min_submit_seconds = compute_min_submit_seconds(
            time_limit_seconds, assignment.get("min_submit_seconds")
        )
        if int(assignment.get("min_submit_seconds") or 0) != min_submit_seconds:
            assignment["min_submit_seconds"] = int(min_submit_seconds)

        elapsed = max(0, int((now - started_at).total_seconds()))
        if time_limit_seconds > 0 and min_submit_seconds > 0:
            # Allow submit when time is up (auto-submit); otherwise enforce ">= half duration".
            if elapsed < min_submit_seconds and elapsed < time_limit_seconds:
                wait = max(0, int(min_submit_seconds - elapsed))
                mins = (min_submit_seconds + 59) // 60
                flash(f"需考试开始后满 {mins} 分钟才可交卷（还需等待 {wait} 秒）")
                with assignment_locked(token):
                    save_assignment(token, assignment)
                return redirect(url_for("public_exam_page", token=token))
        with assignment_locked(token):
            assignment = load_assignment(token)
            if assignment.get("grading"):
                return redirect(url_for("public_done", token=token))
            _finalize_public_submission(token, assignment, now=now)
        return redirect(url_for("public_done", token=token))

    @app.get("/done/<token>")
    def public_done(token: str):
        assignment = load_assignment(token)
        if assignment.get("grading"):
            _sync_candidate_finished_from_assignment(assignment)
        return render_template("public_done.html", assignment=assignment)

    return app

# 目录里扫描所有考试文件夹，读取每个考试的 spec.json，整理成一个列表返回
def _list_exams():
    exams_dir = STORAGE_DIR / "exams"
    out = []
    if not exams_dir.exists():
        return out
    for p in exams_dir.iterdir():
        # 如果没有这个子项那么跳过
        spec_path = p / "spec.json"
        if not spec_path.exists():
            continue
        # 如果有一个考试不能读取，就跳过在读取其余的
        try:
            spec = read_json(spec_path)
        except Exception:
            continue
        # 将试卷id ，title和问题存到out中
        try:
            mtime = spec_path.stat().st_mtime
        except Exception:
            mtime = 0
        out.append(
            {
                "exam_key": p.name,
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


def _remaining_seconds(assignment: dict) -> int:
    limit = int(assignment.get("time_limit_seconds") or 0)
    start = (assignment.get("timing") or {}).get("start_at")
    if not start or limit <= 0:
        return 0
    try:
        started = datetime.fromisoformat(start.replace("Z", "+00:00"))
    except Exception:
        return 0
    used = int((datetime.now(timezone.utc) - started).total_seconds())
    return max(0, limit - used)


def _is_time_up(assignment: dict, *, now: datetime | None = None) -> bool:
    limit = int(assignment.get("time_limit_seconds") or 0)
    if limit <= 0:
        return False
    started_at = _parse_iso_dt((assignment.get("timing") or {}).get("start_at"))
    if not started_at:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    elapsed = max(0, int((now - started_at).total_seconds()))
    return elapsed >= limit


def _finalize_if_time_up(token: str, assignment: dict, *, now: datetime | None = None) -> bool:
    if assignment.get("grading"):
        return True
    if now is None:
        now = datetime.now(timezone.utc)
    if not _is_time_up(assignment, now=now):
        return False
    _finalize_public_submission(token, assignment, now=now)
    return True


def _duration_seconds(assignment: dict) -> int | None:
    timing = assignment.get("timing") or {}
    start = timing.get("start_at")
    end = timing.get("end_at")
    if not start or not end:
        return None
    try:
        started = datetime.fromisoformat(start.replace("Z", "+00:00"))
        ended = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return max(0, int((ended - started).total_seconds()))
    except Exception:
        return None


def _finalize_public_submission(token: str, assignment: dict, *, now: datetime) -> None:
    """
    Finalize a candidate submission by grading and persisting results.

    Caller is responsible for locking (assignment_locked) if needed.
    """
    if assignment.get("grading"):
        return

    assignment.setdefault("timing", {})["end_at"] = now.isoformat()
    spec = read_json(STORAGE_DIR / "exams" / assignment["exam_key"] / "spec.json")
    grading = grade_attempt(spec, assignment)
    assignment["grading"] = grading
    assignment["candidate_remark"] = generate_candidate_remark(spec, assignment, grading)
    save_assignment(token, assignment)

    duration_seconds = _duration_seconds(assignment)
    timing = assignment.get("timing") or {}
    started_at = _parse_iso_dt(timing.get("start_at"))
    submitted_at = _parse_iso_dt(timing.get("end_at"))
    update_candidate_result(
        int(assignment["candidate_id"]),
        status="finished",
        score=int(grading.get("total") or 0),
        exam_started_at=started_at,
        exam_submitted_at=submitted_at,
        duration_seconds=duration_seconds,
    )

    try:
        _archive_candidate_attempt(assignment, spec=spec)
    except Exception:
        logger.exception("Archive candidate attempt failed (token=%s)", token)


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _auto_collect_loop(*, interval_seconds: int = 15) -> None:
    """
    Background loop: once countdown starts (timing.start_at is set), auto-submit when time is up,
    even if the candidate is not actively on the page.
    """
    while True:
        try:
            assignments_dir = STORAGE_DIR / "assignments"
            if assignments_dir.exists():
                for p in assignments_dir.glob("*.json"):
                    token = p.stem
                    try:
                        with assignment_locked(token):
                            assignment = load_assignment(token)
                            if assignment.get("grading"):
                                continue
                            _finalize_if_time_up(token, assignment)
                    except Exception:
                        logger.exception("Auto-collect scan failed (token=%s)", token)
        except Exception:
            logger.exception("Auto-collect loop failed")
        time.sleep(interval_seconds)


def _parse_duration_seconds(value: str | None) -> int:
    v = (value or "").strip()
    if not v:
        return 0
    if ":" not in v:
        try:
            return max(0, int(v))
        except Exception:
            return 0

    parts = [p.strip() for p in v.split(":")]
    if len(parts) not in (2, 3):
        return 0
    try:
        nums = [int(p) for p in parts]
    except Exception:
        return 0
    if any(n < 0 for n in nums):
        return 0

    if len(nums) == 3:
        h, m, s = nums
    else:
        h = 0
        m, s = nums
    if m >= 60 or s >= 60:
        return 0
    return h * 3600 + m * 60 + s


def _archive_filename(name: str, phone: str, exam_key: str) -> str:
    raw = f"{(name or '').strip()}_{(phone or '').strip()}_{(exam_key or '').strip()}"
    raw = _FILENAME_UNSAFE_RE.sub("_", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    raw = raw.replace(" ", "_")
    raw = raw.strip("._")
    if not raw:
        raw = "candidate"
    if len(raw) > 160:
        raw = raw[:160].rstrip("._")
    return f"{raw}.json"


def _sanitize_archive_part(value: str) -> str:
    raw = (value or "").strip()
    raw = _FILENAME_UNSAFE_RE.sub("_", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    raw = raw.replace(" ", "_")
    raw = raw.strip("._")
    return raw


def _try_load_public_spec(exam_key: str) -> dict | None:
    public_path = STORAGE_DIR / "exams" / exam_key / "public.json"
    try:
        if public_path.exists():
            return read_json(public_path)
    except Exception:
        return None
    return None


def _redact_spec_for_archive(spec: dict) -> dict:
    # If public.json is missing, fall back to spec but avoid storing correct answers.
    out = dict(spec or {})
    questions = []
    for q in (spec or {}).get("questions", []) or []:
        q2 = dict(q)
        if q2.get("options"):
            opts = []
            for o in q2.get("options") or []:
                oo = dict(o)
                oo.pop("correct", None)
                opts.append(oo)
            q2["options"] = opts
        questions.append(q2)
    out["questions"] = questions
    return out


def _archive_candidate_attempt(assignment: dict, *, spec: dict | None = None) -> None:
    try:
        candidate_id = int(assignment.get("candidate_id") or 0)
    except Exception:
        return
    if candidate_id <= 0:
        return

    c = get_candidate(candidate_id)
    if not c:
        return
    exam_key = str(assignment.get("exam_key") or "")
    if not exam_key:
        return

    grading = assignment.get("grading") or {}
    answers = assignment.get("answers") or {}

    # Use full spec when available to persist correct answers for admin review.
    if spec is None:
        try:
            spec = read_json(STORAGE_DIR / "exams" / exam_key / "spec.json")
        except Exception:
            spec = {}
    public_spec = _try_load_public_spec(exam_key)
    if public_spec is None:
        public_spec = _redact_spec_for_archive(spec or {})

    scored_by_qid: dict[str, dict] = {}
    for d in (grading.get("objective") or []):
        scored_by_qid[str(d.get("qid"))] = dict(d)
    for d in (grading.get("subjective") or []):
        scored_by_qid[str(d.get("qid"))] = dict(d)

    spec_by_qid = {str(q.get("qid") or ""): q for q in ((spec or {}).get("questions") or [])}
    public_by_qid = {str(q.get("qid") or ""): q for q in (public_spec.get("questions") or [])}

    questions_out = []
    for qid, full_q in spec_by_qid.items():
        pub_q = public_by_qid.get(qid) or {}
        qtype = full_q.get("type") or pub_q.get("type")
        sd = scored_by_qid.get(qid) or {}
        ans = answers.get(qid)
        options_out = None
        if qtype in {"single", "multiple"}:
            options_out = []
            for o in (full_q.get("options") or []):
                options_out.append(
                    {
                        "key": o.get("key"),
                        "text": o.get("text"),
                        "correct": bool(o.get("correct")),
                    }
                )
        item = {
            "qid": qid,
            "label": full_q.get("label") or pub_q.get("label") or qid,
            "type": qtype,
            "max_points": full_q.get("max_points") or full_q.get("points") or pub_q.get("max_points") or pub_q.get("points"),
            "stem_md": pub_q.get("stem_md") or full_q.get("stem_md"),
            "options": options_out or pub_q.get("options"),
            "rubric": full_q.get("rubric"),
            "answer": ans,
            "score": sd.get("score"),
            "score_max": sd.get("max") or (full_q.get("max_points") or full_q.get("points") or pub_q.get("max_points") or pub_q.get("points")),
            "reason": sd.get("reason"),
        }
        questions_out.append(item)

    # Keep ordering consistent with spec.
    def _qid_key(x: dict) -> int:
        v = str(x.get("qid") or "")
        m = re.match(r"^Q(\\d+)$", v)
        return int(m.group(1)) if m else 10**9

    questions_out.sort(key=_qid_key)

    archive = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "candidate": {"id": c.get("id"), "name": c.get("name"), "phone": c.get("phone")},
        "exam": {
            "exam_key": exam_key,
            "title": public_spec.get("title"),
            "description": public_spec.get("description"),
        },
        "timing": assignment.get("timing") or {},
        "time_limit_seconds": int(assignment.get("time_limit_seconds") or 0),
        "min_submit_seconds": int(assignment.get("min_submit_seconds") or 0),
        "total_score": grading.get("total"),
        "raw_scored": grading.get("raw_scored"),
        "raw_total": grading.get("raw_total"),
        "grading": grading,
        "answers": answers,
        "questions": questions_out,
    }

    filename = _archive_filename(str(c.get("name") or ""), str(c.get("phone") or ""), exam_key)
    path = STORAGE_DIR / "archives" / filename
    write_json(Path(path), archive)


def _find_latest_archive(candidate: dict) -> Path | None:
    try:
        phone = str(candidate.get("phone") or "").strip()
        exam_key = str(candidate.get("exam_key") or "").strip()
    except Exception:
        return None
    if not phone:
        return None
    archives_dir = STORAGE_DIR / "archives"
    if not archives_dir.exists():
        return None

    def _pick_latest(pattern: str) -> Path | None:
        matches = [p for p in archives_dir.glob(pattern) if p.is_file()]
        if not matches:
            return None
        matches.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return matches[0]

    # Primary: match by phone + current exam_key.
    # Fallback: match by phone only (covers exam_key renames or cleared exam_key).
    if exam_key and exam_key != "已删除":
        hit = _pick_latest(f"*_{phone}_{exam_key}.json")
        if hit:
            return hit
    return _pick_latest(f"*_{phone}_*.json")


def _augment_archive_with_spec(archive: dict) -> dict:
    """
    Best-effort: enrich an existing archive with correct answers/labels from spec.json
    when available. This helps older archives created before we started persisting
    correct options.
    """
    try:
        exam_key = str(((archive.get("exam") or {}).get("exam_key")) or "").strip()
    except Exception:
        exam_key = ""
    if not exam_key:
        return archive
    try:
        spec = read_json(STORAGE_DIR / "exams" / exam_key / "spec.json")
    except Exception:
        return archive

    spec_by_qid = {str(q.get("qid") or ""): q for q in (spec.get("questions") or [])}
    for q in (archive.get("questions") or []):
        qid = str(q.get("qid") or "")
        full_q = spec_by_qid.get(qid) or {}
        if not q.get("label") and (full_q.get("label") or full_q.get("qid")):
            q["label"] = full_q.get("label") or full_q.get("qid")
        if not q.get("rubric") and full_q.get("rubric"):
            q["rubric"] = full_q.get("rubric")
        if q.get("type") in {"single", "multiple"}:
            # If options don't carry correctness, fill them from spec.
            opts = q.get("options") or []
            has_correct = any(isinstance(o, dict) and ("correct" in o) for o in opts)
            if not has_correct and full_q.get("options"):
                q["options"] = [
                    {"key": o.get("key"), "text": o.get("text"), "correct": bool(o.get("correct"))}
                    for o in (full_q.get("options") or [])
                ]
        if not q.get("stem_md") and full_q.get("stem_md"):
            q["stem_md"] = full_q.get("stem_md")
    return archive


def _sync_candidate_finished_from_assignment(assignment: dict) -> None:
    grading = assignment.get("grading") or {}
    if not grading:
        return
    try:
        candidate_id = int(assignment.get("candidate_id") or 0)
    except Exception:
        return
    if candidate_id <= 0:
        return

    c = get_candidate(candidate_id)
    if not c or c.get("status") == "finished":
        return

    timing = assignment.get("timing") or {}
    started_at = _parse_iso_dt(timing.get("start_at"))
    submitted_at = _parse_iso_dt(timing.get("end_at"))
    duration_seconds = _duration_seconds(assignment)
    try:
        try:
            _archive_candidate_attempt(assignment)
        except Exception:
            logger.exception("Archive candidate attempt failed (candidate_id=%s)", candidate_id)
        update_candidate_result(
            candidate_id,
            status="finished",
            score=int(grading.get("total") or 0),
            exam_started_at=started_at,
            exam_submitted_at=submitted_at,
            duration_seconds=duration_seconds,
        )
    except Exception:
        logger.exception("Sync candidate finished failed (candidate_id=%s)", candidate_id)
        return

# 此文件作为项目入口
if __name__ == "__main__":
    app = create_app()
    # 运行Flask实例对象，debug=True 浏览器出现错误，页面显示错误，port=5050，可以修改  
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
