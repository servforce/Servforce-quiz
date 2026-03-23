from __future__ import annotations

from web.runtime_support import *


def register_admin_exam_routes(app: Flask) -> None:
    def _load_exam_or_404(exam_key: str) -> dict[str, Any]:
        exam = get_exam_definition(str(exam_key or "").strip())
        if not exam:
            abort(404)
        return exam

    @app.post("/admin/exams/ai")
    @admin_required
    def admin_exams_ai_generate():
        def _ai_notice_redirect(msg: str, *, ok: bool = False):
            txt = str(msg or "").strip()[:220]
            level = "ok" if ok else "error"
            return redirect(url_for("admin_exams", ai_notice=txt, ai_notice_level=level))

        op = str(request.form.get("op") or "generate").strip().lower()
        prompt = str(request.form.get("ai_exam_prompt") or "").strip()
        include_diagrams = str(request.form.get("ai_include_diagrams") or "").strip().lower() in {
            "1",
            "true",
            "on",
            "yes",
        }

        check = check_exam_prompt_completeness(prompt)
        missing = check.get("missing") if isinstance(check, dict) else []
        if not isinstance(missing, list):
            missing = []

        if op == "check":
            if bool(check.get("complete")):
                return _ai_notice_redirect("提示词检查通过，可以直接生成试卷。", ok=True)
            else:
                return _ai_notice_redirect("提示词不完整：" + "；".join([str(x) for x in missing[:8]]) + "。请补充后再生成。")

        if not bool(check.get("complete")):
            return _ai_notice_redirect("提示词不完整：" + "；".join([str(x) for x in missing[:8]]) + "。请补充后再生成。")

        ai_llm_tokens = 0
        try:
            with audit_context(meta={}):
                exam_md, assets, meta = generate_exam_from_prompt(prompt, include_diagrams=bool(include_diagrams))
                ctx = get_audit_context()
                ctx_meta = ctx.get("meta") if isinstance(ctx.get("meta"), dict) else {}
                try:
                    ai_llm_tokens = int(ctx_meta.get("llm_total_tokens_sum") or 0)
                except Exception:
                    ai_llm_tokens = 0
        except Exception as e:
            logger.exception("AI exam generation failed before storage")
            return _ai_notice_redirect(f"自动生成失败：{e}")

        try:
            exam_key = _write_exam_to_storage(exam_md, assets=assets, ensure_unique_key=True)
        except QmlParseError as e:
            logger.exception("AI exam generation parse/save failed: QML parse error")
            return _ai_notice_redirect(f"生成内容解析失败：{e}（line={e.line}）。请完善提示词后重试。")
        except Exception as e:
            logger.exception("AI exam generation save failed")
            return _ai_notice_redirect(f"保存生成试卷失败：{e}")

        try:
            q_cnt = int((meta or {}).get("question_count") or 0)
        except Exception:
            q_cnt = 0
        try:
            a_cnt = int((meta or {}).get("asset_count") or 0)
        except Exception:
            a_cnt = 0
        msg_ok = f"自动生成并解析成功：{exam_key}（题目 {q_cnt}，示意图 {a_cnt}）"
        try:
            log_event(
                "exam.upload",
                actor="admin",
                exam_key=str(exam_key or "").strip(),
                llm_total_tokens=(int(ai_llm_tokens or 0) if int(ai_llm_tokens or 0) > 0 else None),
                meta={
                    "source": "ai.generate",
                    "prompt_chars": int(len(prompt)),
                    "question_count": int(q_cnt),
                    "asset_count": int(a_cnt),
                    "include_diagrams": bool(include_diagrams),
                    "llm_total_tokens_sum": int(ai_llm_tokens or 0),
                },
            )
        except Exception:
            pass
        return _ai_notice_redirect(msg_ok, ok=True)

    @app.post("/admin/exams/ai/check")
    @admin_required
    def admin_exams_ai_check():
        prompt = str(request.form.get("ai_exam_prompt") or "").strip()
        try:
            check = check_exam_prompt_completeness(prompt)
            missing = check.get("missing") if isinstance(check, dict) else []
            if not isinstance(missing, list):
                missing = []
            complete = bool(check.get("complete")) if isinstance(check, dict) else False
            score = int(check.get("score") or 0) if isinstance(check, dict) else 0
            return jsonify(
                {
                    "ok": True,
                    "complete": complete,
                    "score": score,
                    "missing": [str(x) for x in missing[:12]],
                }
            )
        except Exception as e:
            logger.exception("AI prompt check failed")
            return jsonify({"ok": False, "complete": False, "missing": [], "error": f"检查异常：{type(e).__name__}"}), 500

    @app.post("/admin/exams/upload")    # 上传
    @admin_required
    def admin_exams_upload():
        file = request.files.get("file")
        if not file or not file.filename:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_dashboard"))
        filename = (file.filename or "").lower()

        # Support a zip package containing the markdown + img/ assets.
        if filename.endswith(".zip"):
            try:
                zf = zipfile.ZipFile(BytesIO(file.read()))
            except Exception:
                flash("操作失败，请稍后重试")
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
            try:
                log_event("exam.upload", actor="admin", exam_key=str(exam_key or "").strip(), meta={"filename": md_name})
            except Exception:
                pass
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
        try:
            log_event("exam.upload", actor="admin", exam_key=str(exam_key or "").strip(), meta={"filename": str(file.filename or "")})
        except Exception:
            pass
        sort_id = _sort_id_from_exam_key(exam_key)
        if sort_id:
            return redirect(url_for("admin_exam_detail_by_sort_id", exam_id=sort_id))
        return redirect(url_for("admin_exam_detail", exam_key=exam_key))

    @app.get("/admin/exams/<exam_key>")
    @admin_required
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
        spec = exam.get("spec") or {}
        exam_stats = _compute_exam_stats(spec)
        cfg = get_public_invite_config(exam_key)
        public_enabled = bool(cfg.get("enabled"))
        public_token = str(cfg.get("token") or "").strip()
        base_url = request.url_root.rstrip("/")
        public_url = f"{base_url}/p/{public_token}" if (public_enabled and public_token) else ""
        public_qr_url = url_for("public_invite_qr", public_token=public_token) if (public_enabled and public_token) else ""

        return render_template(
            "admin_exam_detail.html",
            spec=spec,
            exam_key=exam_key,
            exam_sort_id=None,
            view="detail",
            exam_stats=exam_stats,
            public_invite_enabled=public_enabled,
            public_invite_url=public_url,
            public_invite_qr_url=public_qr_url,
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
        try:
            log_event("exam.read", actor="admin", exam_key=str(exam_key or "").strip(), meta={"path": request.path, "view": "detail"})
        except Exception:
            pass
        exam = _load_exam_or_404(exam_key)
        spec = exam.get("spec") or {}
        exam_stats = _compute_exam_stats(spec)
        cfg = get_public_invite_config(exam_key)
        public_enabled = bool(cfg.get("enabled"))
        public_token = str(cfg.get("token") or "").strip()
        base_url = request.url_root.rstrip("/")
        public_url = f"{base_url}/p/{public_token}" if (public_enabled and public_token) else ""
        public_qr_url = url_for("public_invite_qr", public_token=public_token) if (public_enabled and public_token) else ""
        return render_template(
            "admin_exam_detail.html",
            spec=spec,
            exam_key=exam_key,
            exam_sort_id=int(exam_id),
            view="detail",
            exam_stats=exam_stats,
            public_invite_enabled=public_enabled,
            public_invite_url=public_url,
            public_invite_qr_url=public_qr_url,
        )

    @app.get("/admin/exams/<int:exam_id>/edit")
    @admin_required
    def admin_exam_edit_by_sort_id(exam_id: int):
        exam_key = _exam_key_from_sort_id(exam_id)
        if not exam_key:
            abort(404)
        try:
            log_event("exam.read", actor="admin", exam_key=str(exam_key or "").strip(), meta={"path": request.path, "view": "edit"})
        except Exception:
            pass
        exam = _load_exam_or_404(exam_key)
        source_md = str(exam.get("source_md") or "")
        spec = exam.get("spec") or {}
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
            exam = _load_exam_or_404(exam_key)
            return render_template(
                "admin_exam_edit.html",
                exam_key=exam_key,
                exam_sort_id=int(exam_id),
                spec=exam.get("spec") or {},
                source_md=new_source_md,
                view="edit",
            )
        except Exception as e:
            logger.exception("Edit exam failed (exam_key=%s)", exam_key)
            flash(f"保存失败：{e}")
            return redirect(url_for("admin_exam_edit_by_sort_id", exam_id=int(exam_id)))
        flash("已保存并重新解析")
        try:
            log_event("exam.update", actor="admin", exam_key=str(new_exam_key or "").strip(), meta={"from_exam_key": str(exam_key or "").strip()})
        except Exception:
            pass
        new_sort_id = _sort_id_from_exam_key(new_exam_key)
        if new_sort_id:
            return redirect(url_for("admin_exam_detail_by_sort_id", exam_id=int(new_sort_id)))
        try:
            log_event("exam.update", actor="admin", exam_key=str(new_exam_key or "").strip(), meta={"from_exam_key": str(exam_key or "").strip()})
        except Exception:
            pass
        return redirect(url_for("admin_exam_detail", exam_key=new_exam_key))

    @app.get("/admin/exams/<int:exam_id>/paper")
    @admin_required
    def admin_exam_paper_by_sort_id(exam_id: int):
        exam_key = _exam_key_from_sort_id(exam_id)
        if not exam_key:
            abort(404)
        try:
            log_event("exam.read", actor="admin", exam_key=str(exam_key or "").strip(), meta={"path": request.path, "view": "paper"})
        except Exception:
            pass
        exam = _load_exam_or_404(exam_key)
        public_spec = exam.get("public_spec") or {}
        spec = exam.get("spec") or {}
        exam_stats = _compute_exam_stats(spec)
        cfg = get_public_invite_config(exam_key)
        public_enabled = bool(cfg.get("enabled"))
        public_token = str(cfg.get("token") or "").strip()
        base_url = request.url_root.rstrip("/")
        public_url = f"{base_url}/p/{public_token}" if (public_enabled and public_token) else ""
        public_qr_url = url_for("public_invite_qr", public_token=public_token) if (public_enabled and public_token) else ""
        return render_template(
            "admin_exam_paper.html",
            exam_key=exam_key,
            exam_sort_id=int(exam_id),
            spec=public_spec,
            title=str(spec.get("title") or ""),
            description=str(spec.get("description") or ""),
            exam_stats=exam_stats,
            view="paper",
            public_invite_enabled=public_enabled,
            public_invite_url=public_url,
            public_invite_qr_url=public_qr_url,
        )

    @app.get("/admin/exams/<exam_key>/edit")
    @admin_required
    def admin_exam_edit(exam_key: str):
        sort_id = _sort_id_from_exam_key(exam_key)
        if sort_id:
            return redirect(url_for("admin_exam_edit_by_sort_id", exam_id=sort_id))
        try:
            log_event("exam.read", actor="admin", exam_key=str(exam_key or "").strip(), meta={"path": request.path, "view": "edit"})
        except Exception:
            pass
        exam = _load_exam_or_404(exam_key)
        source_md = str(exam.get("source_md") or "")
        spec = exam.get("spec") or {}
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
            exam = _load_exam_or_404(exam_key)
            return render_template(
                "admin_exam_edit.html",
                exam_key=exam_key,
                exam_sort_id=_sort_id_from_exam_key(exam_key),
                spec=exam.get("spec") or {},
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
        try:
            log_event("exam.read", actor="admin", exam_key=str(exam_key or "").strip(), meta={"path": request.path, "view": "paper"})
        except Exception:
            pass
        exam = _load_exam_or_404(exam_key)
        public_spec = exam.get("public_spec") or {}
        spec = exam.get("spec") or {}
        exam_stats = _compute_exam_stats(spec)
        cfg = get_public_invite_config(exam_key)
        public_enabled = bool(cfg.get("enabled"))
        public_token = str(cfg.get("token") or "").strip()
        base_url = request.url_root.rstrip("/")
        public_url = f"{base_url}/p/{public_token}" if (public_enabled and public_token) else ""
        public_qr_url = url_for("public_invite_qr", public_token=public_token) if (public_enabled and public_token) else ""
        return render_template(
            "admin_exam_paper.html",
            exam_key=exam_key,
            exam_sort_id=None,
            spec=public_spec,
            title=str(spec.get("title") or ""),
            description=str(spec.get("description") or ""),
            exam_stats=exam_stats,
            view="paper",
            public_invite_enabled=public_enabled,
            public_invite_url=public_url,
            public_invite_qr_url=public_qr_url,
        )

    @app.post("/admin/exams/<exam_key>/delete")
    @admin_required
    def admin_exam_delete(exam_key: str):
        if not get_exam_definition(exam_key):
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_exams"))

        affected = 0
        try:
            affected = mark_exam_deleted(exam_key)
        except Exception:
            logger.exception("Mark exam deleted failed (exam_key=%s)", exam_key)

        try:
            delete_exam_definition(exam_key)
        except Exception:
            logger.exception("Delete exam definition failed: %s", exam_key)
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_exam_detail", exam_key=exam_key))
        try:
            delete_exam_assets(exam_key)
        except Exception:
            logger.exception("Delete exam assets failed: %s", exam_key)

        # Success: keep UI quiet (no flash), user can see result from list refresh.
        try:
            log_event("exam.delete", actor="admin", exam_key=str(exam_key or "").strip(), meta={"affected": int(affected or 0)})
        except Exception:
            pass
        return redirect(url_for("admin_exams"))

    @app.post("/admin/exams/<exam_key>/public-invite")
    @admin_required
    def admin_exam_public_invite_toggle(exam_key: str):
        """
        Enable/disable a public invite for an exam.

        When enabled, the exam gets a stable public token and can be accessed via:
        - /p/<public_token> (each visitor gets their own attempt token)
        - /qr/p/<public_token>.png (QR for the public URL)
        """
        ek = str(exam_key or "").strip()
        if not ek or not get_exam_definition(ek):
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
