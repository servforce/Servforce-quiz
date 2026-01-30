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

from config import ADMIN_PASSWORD, ADMIN_USERNAME, SECRET_KEY, STORAGE_DIR, logger
from db import (
    create_candidate,
    delete_candidate,
    get_candidate,
    get_candidate_by_phone,
    bulk_import_candidates,
    has_recent_created_by_phone,
    has_recent_exam_submission_by_phone,
    has_recent_identity,
    init_db,
    list_candidates,
    reset_candidate_exam_state,
    set_candidate_exam_started_at,
    set_candidate_exam_key,
    set_candidate_status,
    mark_exam_deleted,
    update_candidate,
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
from storage.json_store import ensure_dirs, read_json, write_json
from web.auth import admin_required

import openpyxl

# 使用正则表达式 
_NAME_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z·\s]{2,20}$")  # 用来验证一个名字是否符合特定的规则
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")    # 验证一个手机号是否符合特定规则


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
    v = (value or "").strip()   # 去掉前后端的空白字符
    v = v.replace(" ", "").replace("-", "")
    if v.startswith("+86") and len(v) == 12:
        v = v[3:]
    if v.startswith("86") and len(v) == 13:
        v = v[2:]
    return v


_MD_IMAGE_RE = re.compile(r"!\[[^\]]*]\((?P<path>[^)]+)\)")
_FILENAME_UNSAFE_RE = re.compile(r'[\\\\/:*?"<>|]+')


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
        text = html.escape(str(value or ""), quote=False)
        return Markup(mdlib.markdown(text, extensions=["extra", "sane_lists"], output_format="html5"))

    @app.get("/exams/<exam_key>/assets/<path:relpath>")
    def public_exam_asset(exam_key: str, relpath: str):
        base = (STORAGE_DIR / "exams" / exam_key / "assets").resolve()
        p = (base / _safe_relpath(relpath)).resolve()
        if base not in p.parents and p != base:
            abort(404)
        if not p.exists() or not p.is_file():
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
        if exam_q:
            ql = exam_q.lower()
            exams_all = [
                e
                for e in exams_all
                if ql in str(e.get("exam_key") or "").lower()
                or ql in str(e.get("title") or "").lower()
            ]

        per_page = 10
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

        return render_template(
            "admin_dashboard.html",
            exams_all=exams_all,
            exams_page=exams_page,
            exam_page=exam_page,
            total_exams=total_exams,
            total_exam_pages=total_exam_pages,
            exam_q=exam_q,
            candidates=candidates,
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
            return redirect(url_for("admin_exam_detail", exam_key=exam_key))

        # Plain markdown upload (assets must be URLs).
        text = file.read().decode("utf-8", errors="replace")
        try:
            exam_key = _write_exam_to_storage(text, assets=None)
        except QmlParseError as e:
            flash(f"解析失败：{e}（line={e.line}）")
            return redirect(url_for("admin_dashboard"))
        flash(f"上传并解析成功：{exam_key}")
        return redirect(url_for("admin_exam_detail", exam_key=exam_key))

    @app.get("/admin/exams/<exam_key>")     # 根据key值得到试卷细节
    @admin_required
    def admin_exam_detail(exam_key: str):
        spec_path = STORAGE_DIR / "exams" / exam_key / "spec.json"
        if not spec_path.exists():
            abort(404)
        spec = read_json(spec_path)
        return render_template("admin_exam_detail.html", spec=spec)

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
        candidates = list_candidates(query=q)
        return render_template("admin_candidates.html", candidates=candidates, q=q)

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

        # Requirement:
        # - if same (name, phone) exists within 6 months: block
        # - if older than 6 months: overwrite that record and reset it "as new"
        existed = get_candidate_by_phone(phone)
        if existed and str(existed.get("name") or "") == name:
            if has_recent_created_by_phone(phone, months=6):
                flash("候选者6个月以内已参加笔试")
                return redirect(url_for("admin_candidates"))
            try:
                now = datetime.now(timezone.utc)
                update_candidate(int(existed["id"]), name=name, phone=phone, created_at=now)
                reset_candidate_exam_state(int(existed["id"]))
            except Exception:
                flash("更新失败")
                return redirect(url_for("admin_candidates"))
            flash("候选人已覆盖更新（按新创建处理）")
            return redirect(url_for("admin_candidates"))

        try:
            create_candidate(name=name, phone=phone)
        except Exception:
            flash("手机号已存在或写入失败")
            return redirect(url_for("admin_candidates"))
        flash("候选人创建成功")
        return redirect(url_for("admin_candidates"))

    @app.post("/admin/candidates/upload")
    @admin_required
    def admin_candidates_upload():
        file = request.files.get("file")
        if not file or not file.filename:
            flash("请选择 Excel .xlsx 文件")
            return redirect(url_for("admin_candidates"))

        try:
            wb = openpyxl.load_workbook(BytesIO(file.read()), data_only=True)
        except Exception:
            flash("Excel 读取失败，请确认文件格式为 .xlsx")
            return redirect(url_for("admin_candidates"))

        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            flash("文件为空")
            return redirect(url_for("admin_candidates"))

        def _norm_header(v):
            return str(v or "").strip().lower()

        header = [_norm_header(x) for x in (rows[0] or [])]
        header_map = {}
        header_like = any(h in {"name", "phone", "exam_key", "姓名", "手机号", "试卷"} for h in header)
        start_idx = 1 if header_like else 0
        if header_like:
            for i, h in enumerate(header):
                if h in {"name", "姓名"}:
                    header_map["name"] = i
                if h in {"phone", "手机号"}:
                    header_map["phone"] = i
                if h in {"exam_key", "试卷"}:
                    header_map["exam_key"] = i
        else:
            header_map = {"name": 0, "phone": 1, "exam_key": 2}

        records = []
        phones_in_file: set[str] = set()
        for r in rows[start_idx:]:
            if not r:
                continue
            name = str(r[header_map["name"]] or "").strip() if header_map.get("name") is not None else ""
            phone_raw = str(r[header_map["phone"]] or "").strip() if header_map.get("phone") is not None else ""
            exam_key = ""
            if header_map.get("exam_key") is not None and header_map["exam_key"] < len(r):
                exam_key = str(r[header_map["exam_key"]] or "").strip()
            phone = _normalize_phone(phone_raw)

            if not name and not phone:
                continue
            if not _is_valid_name(name) or not _is_valid_phone(phone):
                flash("文件中存在姓名/手机号格式不正确的行，请修正后重新上传")
                return redirect(url_for("admin_candidates"))
            if phone in phones_in_file:
                flash("文件中存在重复手机号，请修正后重新上传")
                return redirect(url_for("admin_candidates"))
            phones_in_file.add(phone)
            records.append({"name": name, "phone": phone, "exam_key": exam_key})

        if not records:
            flash("文件中未读取到有效数据")
            return redirect(url_for("admin_candidates"))

        # Gate: if any phone is within 6 months (by created_at), reject the whole file.
        for r in records:
            if has_recent_created_by_phone(r["phone"], months=6):
                flash("文件中有候选者6个月内已参加笔试，请重新上传文件")
                return redirect(url_for("admin_candidates"))

        try:
            created, updated = bulk_import_candidates(records, overwrite_after_months=6)
        except RuntimeError as e:
            if str(e) == "recent_candidate_in_file":
                flash("文件中有候选者6个月内已参加笔试，请重新上传文件")
                return redirect(url_for("admin_candidates"))
            flash("导入失败")
            return redirect(url_for("admin_candidates"))
        except Exception:
            flash("导入失败")
            return redirect(url_for("admin_candidates"))

        flash(f"导入成功：新增 {created} 条，覆盖更新 {updated} 条")
        return redirect(url_for("admin_candidates"))

    # 修改候选者身份信息
    @app.get("/admin/candidates/<int:candidate_id>/edit")
    @admin_required
    def admin_candidates_edit(candidate_id: int):
        c = get_candidate(candidate_id)
        if not c:
            flash("候选人不存在")
            return redirect(url_for("admin_candidates"))
        return render_template("admin_candidate_edit.html", c=c)

    @app.get("/admin/candidates/<int:candidate_id>/attempt")
    @admin_required
    def admin_candidate_attempt(candidate_id: int):
        c = get_candidate(candidate_id)
        if not c:
            flash("候选人不存在")
            return redirect(url_for("admin_candidates"))
        p = _find_latest_archive(c)
        if not p:
            flash("未找到该候选人的答题归档（可能未提交或归档未生成）")
            return redirect(url_for("admin_candidates"))
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

    # 修改候选人信息
    @app.post("/admin/candidates/<int:candidate_id>/edit")
    @admin_required
    def admin_candidates_edit_post(candidate_id: int):
        c = get_candidate(candidate_id)
        if not c:
            flash("候选人不存在")
            return redirect(url_for("admin_candidates"))

        created_at_raw = (request.form.get("created_at") or "").strip()
        name = (request.form.get("name") or "").strip()
        phone = _normalize_phone(request.form.get("phone") or "")
        if not _is_valid_name(name):
            flash("姓名格式不正确（2-20位中文/英文，可含空格/·）")
            return redirect(url_for("admin_candidates_edit", candidate_id=candidate_id))
        if not _is_valid_phone(phone):
            flash("手机号格式不正确（需为 11 位中国大陆手机号）")
            return redirect(url_for("admin_candidates_edit", candidate_id=candidate_id))

        created_at = None
        if created_at_raw:
            try:
                # datetime-local has no timezone; interpret as UTC for consistency.
                created_at = datetime.fromisoformat(created_at_raw).replace(tzinfo=timezone.utc)
            except Exception:
                flash("创建时间格式不正确")
                return redirect(url_for("admin_candidates_edit", candidate_id=candidate_id))

        try:
            update_candidate(candidate_id, name=name, phone=phone, created_at=created_at)
        except Exception:
            flash("更新失败：手机号可能已存在")
            return redirect(url_for("admin_candidates_edit", candidate_id=candidate_id))
        flash("候选人已更新")
        return redirect(url_for("admin_candidates"))

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
            min_submit_seconds = compute_min_submit_seconds(
                time_limit_seconds, assignment.get("min_submit_seconds")
            )
            if int(assignment.get("min_submit_seconds") or 0) != min_submit_seconds:
                assignment["min_submit_seconds"] = int(min_submit_seconds)
            save_assignment(token, assignment)

        return render_template(
            "public_exam.html",
            token=token,
            spec=public_spec,
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
    # Newest uploads first (by spec.json mtime)
    out.sort(key=lambda x: x.get("_mtime", 0), reverse=True)
    return out


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
        interview=bool(grading.get("interview")),
        remark=str(assignment.get("candidate_remark") or grading.get("overall_reason") or ""),
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
    if not phone or not exam_key:
        return None
    archives_dir = STORAGE_DIR / "archives"
    if not archives_dir.exists():
        return None
    # When exam is deleted we set exam_key to "已删除". In that case, we still want
    # to show the latest archived attempt for this phone.
    matches = []
    pattern = f"*_{phone}_*.json" if exam_key == "已删除" else f"*_{phone}_{exam_key}.json"
    for p in archives_dir.glob(pattern):
        if p.is_file():
            matches.append(p)
    if not matches:
        return None
    matches.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return matches[0]


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
            interview=bool(grading.get("interview")),
            remark=str(assignment.get("candidate_remark") or grading.get("overall_reason") or ""),
        )
    except Exception:
        logger.exception("Sync candidate finished failed (candidate_id=%s)", candidate_id)
        return

# 此文件作为项目入口
if __name__ == "__main__":
    app = create_app()
    # 运行Flask实例对象，debug=True 浏览器出现错误，页面显示错误，port=5050，可以修改  
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
