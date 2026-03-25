from __future__ import annotations

from web.runtime_support import *


def register_admin_exam_routes(app: Flask) -> None:
    def _load_exam_or_404(exam_key: str) -> dict[str, Any]:
        exam = get_exam_definition(str(exam_key or "").strip())
        if not exam:
            abort(404)
        return exam

    def _status_label(status: str) -> str:
        mapping = {
            "active": "可发布",
            "retired": "已退役",
            "sync_error": "同步异常",
        }
        return mapping.get(str(status or "").strip(), "未知")

    def _compute_exam_stats(spec: dict) -> dict:
        questions = list(spec.get("questions") or [])
        counts_by_type: dict[str, int] = {}
        points_by_type: dict[str, int] = {}
        total_points = 0
        for q in questions:
            qtype = str(q.get("type") or "").strip() or "unknown"
            counts_by_type[qtype] = int(counts_by_type.get(qtype, 0)) + 1
            try:
                pts = int(q.get("max_points") or 0)
            except Exception:
                pts = 0
            points_by_type[qtype] = int(points_by_type.get(qtype, 0)) + pts
            total_points += pts
        return {
            "total_questions": len(questions),
            "total_points": int(total_points),
            "counts_by_type": counts_by_type,
            "points_by_type": points_by_type,
        }

    def _render_exam_detail(
        *,
        exam: dict[str, Any],
        selected_version: dict[str, Any] | None,
        exam_sort_id: int | None,
    ):
        exam_key = str(exam.get("exam_key") or "").strip()
        current_version_id = int(exam.get("current_version_id") or 0)
        selected_version_id = int((selected_version or {}).get("id") or 0)
        spec = (selected_version or {}).get("spec") or exam.get("spec") or {}
        exam_stats = _compute_exam_stats(spec)
        cfg = get_public_invite_config(exam_key)
        public_enabled = bool(cfg.get("enabled"))
        public_token = str(cfg.get("token") or "").strip()
        base_url = request.url_root.rstrip("/")
        public_url = f"{base_url}/p/{public_token}" if (public_enabled and public_token) else ""
        public_qr_url = url_for("public_invite_qr", public_token=public_token) if (public_enabled and public_token) else ""
        version_history = []
        for item in list_exam_versions(exam_key):
            vid = int(item.get("id") or 0)
            version_history.append(
                {
                    "id": vid,
                    "version_no": int(item.get("version_no") or 0),
                    "git_commit": str(item.get("git_commit") or "").strip(),
                    "source_path": str(item.get("source_path") or "").strip(),
                    "created_at": item.get("created_at"),
                    "is_selected": bool(selected_version_id and vid == selected_version_id),
                    "is_current": bool(current_version_id and vid == current_version_id),
                    "href": url_for("admin_exam_version_detail", version_id=vid),
                }
            )
        can_create_invite = (
            str(exam.get("status") or "").strip() == "active"
            and current_version_id > 0
            and selected_version_id == current_version_id
        )
        return render_template(
            "admin_exam_detail.html",
            spec=spec,
            exam_key=exam_key,
            exam_sort_id=exam_sort_id,
            view="detail",
            exam_stats=exam_stats,
            public_invite_enabled=public_enabled,
            public_invite_url=public_url,
            public_invite_qr_url=public_qr_url,
            exam_status=str(exam.get("status") or "").strip() or "active",
            exam_status_label=_status_label(str(exam.get("status") or "").strip()),
            exam_current_version_id=current_version_id,
            exam_current_version_no=int(exam.get("current_version_no") or 0),
            exam_sync_error=str(exam.get("last_sync_error") or ""),
            exam_source_path=str(exam.get("source_path") or "").strip(),
            exam_last_synced_commit=str(exam.get("last_synced_commit") or "").strip(),
            can_create_invite=can_create_invite,
            selected_version=selected_version or {},
            selected_version_id=selected_version_id,
            selected_version_no=int((selected_version or {}).get("version_no") or 0),
            version_history=version_history,
            exam_sync_state=read_exam_repo_sync_state(),
        )

    @app.post("/admin/exams/ai")
    @admin_required
    def admin_exams_ai_generate():
        flash("大模型自动出试卷入口已下线，请改用 Git 仓库同步。")
        return redirect(url_for("admin_exams"))

    @app.post("/admin/exams/ai/check")
    @admin_required
    def admin_exams_ai_check():
        return jsonify({"ok": False, "error": "功能已下线，请改用 Git 仓库同步。"}), 410

    @app.post("/admin/exams/upload")
    @admin_required
    def admin_exams_upload():
        flash("试卷上传入口已下线，请改用 Git 仓库同步。")
        return redirect(url_for("admin_exams"))

    @app.post("/admin/exams/sync")
    @admin_required
    def admin_exams_sync():
        repo_url = str(request.form.get("repo_url") or "").strip()
        try:
            result = enqueue_exam_repo_sync(repo_url)
        except Exception as exc:
            flash(f"同步任务创建失败：{exc}")
            return redirect(url_for("admin_exams"))
        try:
            log_event(
                "exam.sync.enqueue",
                actor="admin",
                meta={
                    "repo_url": repo_url,
                    "job_id": str(result.get("job_id") or ""),
                    "created": bool(result.get("created")),
                },
            )
        except Exception:
            pass
        if bool(result.get("created")):
            flash("试卷仓库同步任务已创建，后台将异步处理。")
        else:
            flash("已有试卷同步任务正在运行，已复用现有任务。")
        return redirect(url_for("admin_exams"))

    @app.get("/admin/exams/<exam_key>")
    @admin_required
    def admin_exam_detail(exam_key: str):
        sort_id = _sort_id_from_exam_key(exam_key)
        if sort_id:
            return redirect(url_for("admin_exam_detail_by_sort_id", exam_id=sort_id))
        try:
            log_event("exam.read", actor="admin", exam_key=str(exam_key or "").strip(), meta={"path": request.path, "view": "detail"})
        except Exception:
            pass
        exam = _load_exam_or_404(exam_key)
        selected_version = None
        current_version_id = int(exam.get("current_version_id") or 0)
        if current_version_id > 0:
            selected_version = get_exam_version_snapshot(current_version_id)
        return _render_exam_detail(exam=exam, selected_version=selected_version, exam_sort_id=None)

    @app.get("/admin/exams/<int:exam_id>")
    @admin_required
    def admin_exam_detail_by_sort_id(exam_id: int):
        exam_key = _exam_key_from_sort_id(exam_id)
        if not exam_key:
            abort(404)
        exam = _load_exam_or_404(exam_key)
        selected_version = None
        current_version_id = int(exam.get("current_version_id") or 0)
        if current_version_id > 0:
            selected_version = get_exam_version_snapshot(current_version_id)
        return _render_exam_detail(exam=exam, selected_version=selected_version, exam_sort_id=int(exam_id))

    @app.get("/admin/exam-versions/<int:version_id>")
    @admin_required
    def admin_exam_version_detail(version_id: int):
        version = get_exam_version_snapshot(version_id)
        if not version:
            abort(404)
        exam = _load_exam_or_404(str(version.get("exam_key") or ""))
        try:
            log_event(
                "exam.read",
                actor="admin",
                exam_key=str(version.get("exam_key") or "").strip(),
                meta={"path": request.path, "view": "version", "exam_version_id": int(version_id)},
            )
        except Exception:
            pass
        return _render_exam_detail(
            exam=exam,
            selected_version=version,
            exam_sort_id=_sort_id_from_exam_key(str(version.get("exam_key") or "")),
        )

    @app.get("/admin/exams/<int:exam_id>/edit")
    @admin_required
    def admin_exam_edit_by_sort_id(exam_id: int):
        exam_key = _exam_key_from_sort_id(exam_id)
        if not exam_key:
            abort(404)
        flash("试卷在线编辑入口已下线，请改用外部 Git 仓库。")
        return redirect(url_for("admin_exam_detail_by_sort_id", exam_id=int(exam_id)))

    @app.post("/admin/exams/<int:exam_id>/edit")
    @admin_required
    def admin_exam_edit_save_by_sort_id(exam_id: int):
        flash("试卷在线编辑入口已下线，请改用外部 Git 仓库。")
        return redirect(url_for("admin_exam_detail_by_sort_id", exam_id=int(exam_id)))

    @app.get("/admin/exams/<int:exam_id>/paper")
    @admin_required
    def admin_exam_paper_by_sort_id(exam_id: int):
        exam_key = _exam_key_from_sort_id(exam_id)
        if not exam_key:
            abort(404)
        return redirect(url_for("admin_exam_detail_by_sort_id", exam_id=int(exam_id)))

    @app.get("/admin/exams/<exam_key>/edit")
    @admin_required
    def admin_exam_edit(exam_key: str):
        flash("试卷在线编辑入口已下线，请改用外部 Git 仓库。")
        return redirect(url_for("admin_exam_detail", exam_key=exam_key))

    @app.post("/admin/exams/<exam_key>/edit")
    @admin_required
    def admin_exam_edit_save(exam_key: str):
        flash("试卷在线编辑入口已下线，请改用外部 Git 仓库。")
        return redirect(url_for("admin_exam_detail", exam_key=exam_key))

    @app.get("/admin/exams/<exam_key>/paper")
    @admin_required
    def admin_exam_paper(exam_key: str):
        sort_id = _sort_id_from_exam_key(exam_key)
        if sort_id:
            return redirect(url_for("admin_exam_detail_by_sort_id", exam_id=sort_id))
        return redirect(url_for("admin_exam_detail", exam_key=exam_key))

    @app.post("/admin/exams/<exam_key>/delete")
    @admin_required
    def admin_exam_delete(exam_key: str):
        flash("试卷删除入口已下线，请通过 Git 仓库移除试卷文件。")
        return redirect(url_for("admin_exam_detail", exam_key=exam_key))

    @app.post("/admin/exams/<exam_key>/public-invite")
    @admin_required
    def admin_exam_public_invite_toggle(exam_key: str):
        ek = str(exam_key or "").strip()
        exam = get_exam_definition(ek)
        if not ek or not exam:
            return jsonify({"ok": False, "error": "exam_not_found"}), 404

        enabled_raw = None
        data = request.get_json(silent=True)
        if isinstance(data, dict):
            enabled_raw = data.get("enabled")
        if enabled_raw is None:
            enabled_raw = request.form.get("enabled")
        enabled = str(enabled_raw).strip().lower() in {"1", "true", "on", "yes"}

        cfg = set_public_invite_enabled(ek, enabled)
        public_token = str(cfg.get("token") or "").strip()
        try:
            log_event(
                "exam.public_invite.enable" if enabled else "exam.public_invite.disable",
                actor="admin",
                exam_key=str(ek or "").strip(),
                meta={"public_token": public_token},
            )
        except Exception:
            pass
        base_url = request.url_root.rstrip("/")
        public_url = f"{base_url}/p/{public_token}" if public_token else ""
        qr_url = url_for("public_invite_qr", public_token=public_token) if public_token else ""
        return jsonify(
            {
                "ok": True,
                "enabled": bool(cfg.get("enabled")),
                "token": public_token,
                "public_url": public_url,
                "qr_url": qr_url,
            }
        )
