from __future__ import annotations

from web.runtime_support import *
from web.runtime_setup import _ensure_exam_paper_for_token


def register_public_resume_routes(app: Flask) -> None:
    @app.get("/resume/<token>")
    def public_resume_upload_page(token: str):
        with assignment_locked(token):
            assignment = load_assignment(token)
            if str(assignment.get("status") or "").strip() == "expired":
                return render_template(
                    "public_unavailable.html",
                    title="链接已失效",
                    message="当前答题链接已失效，请联系管理员重新生成新的邀请链接。",
                    start_date="",
                    end_date="",
                )
            st, sd, ed = _invite_window_state(assignment)
            if st in {"not_started", "expired"}:
                title = "未到答题时间" if st == "not_started" else "邀请已失效"
                msg = "当前未到答题时间，请在有效时间范围内进入答题。" if st == "not_started" else "当前邀请已超过有效时间范围，无法开始答题。"
                return render_template(
                    "public_unavailable.html",
                    title=title,
                    message=msg,
                    start_date=(sd.isoformat() if sd else ""),
                    end_date=(ed.isoformat() if ed else ""),
                )
            if assignment.get("grading") or _finalize_if_time_up(token, assignment):
                return redirect(url_for("public_done", token=token))

            sms = assignment.get("sms_verify") or {}
            if not bool(sms.get("verified")):
                return redirect(url_for("public_verify_page", token=token))

            try:
                candidate_id = int(assignment.get("candidate_id") or 0)
            except Exception:
                candidate_id = 0
            if candidate_id > 0:
                return redirect(url_for("public_exam_page", token=token))

            pending = assignment.get("pending_profile") or {}
            name = str(pending.get("name") or "").strip()
            phone = _normalize_phone(str(pending.get("phone") or sms.get("phone") or "").strip())
            if not name:
                name = "候选人"
            if not _is_valid_phone(phone):
                return redirect(url_for("public_verify_page", token=token))

        return render_template("public_resume_upload.html", token=token, name=name, phone=phone)

    @app.post("/api/public/resume/upload")
    def public_resume_upload():
        wants_json = "application/json" in str(request.headers.get("Accept") or "").lower()
        token = (request.form.get("token") or "").strip()
        f = request.files.get("file")

        if not token:
            if wants_json:
                return jsonify({"ok": False, "error": "缺少 token。"}), 400
            flash("请求无效：缺少 token")
            return redirect(url_for("index"))

        if not f or not getattr(f, "filename", ""):
            if wants_json:
                return jsonify({"ok": False, "error": "请选择简历文件。"}), 400
            flash("请选择简历文件")
            return redirect(url_for("public_resume_upload_page", token=token))

        with assignment_locked(token):
            assignment = load_assignment(token)
            if str(assignment.get("status") or "").strip() == "expired":
                if wants_json:
                    return jsonify({"ok": False, "expired": True, "error": "当前链接已失效。"}), 410
                flash("链接已失效")
                return redirect(url_for("public_verify_page", token=token))

            st, _sd, _ed = _invite_window_state(assignment)
            if st in {"not_started", "expired"}:
                if wants_json:
                    return jsonify({"ok": False, "error": "当前不在可答题时间范围内。"}), 400
                return redirect(url_for("public_verify_page", token=token))

            sms = assignment.get("sms_verify") or {}
            if not bool(sms.get("verified")):
                if wants_json:
                    return jsonify({"ok": False, "error": "请先完成验证码验证。"}), 400
                return redirect(url_for("public_verify_page", token=token))

            try:
                candidate_id = int(assignment.get("candidate_id") or 0)
            except Exception:
                candidate_id = 0
            if candidate_id > 0:
                if wants_json:
                    return jsonify({"ok": True, "redirect": url_for("public_exam_page", token=token)})
                return redirect(url_for("public_exam_page", token=token))

            pending = assignment.get("pending_profile") or {}
            name = str(pending.get("name") or "").strip()
            phone = _normalize_phone(str(pending.get("phone") or sms.get("phone") or "").strip())

        if not _is_valid_name(name) or not _is_valid_phone(phone):
            if wants_json:
                return jsonify({"ok": False, "error": "候选人信息不完整，请重新验证。"}), 400
            flash("候选人信息不完整，请重新验证")
            return redirect(url_for("public_verify_page", token=token))

        try:
            data = f.read() or b""
        except Exception:
            if wants_json:
                return jsonify({"ok": False, "error": "简历文件读取失败。"}), 400
            flash("简历文件读取失败")
            return redirect(url_for("public_resume_upload_page", token=token))

        if len(data) > 10 * 1024 * 1024:
            if wants_json:
                return jsonify({"ok": False, "error": "简历文件过大（需小于等于10MB）。"}), 400
            flash("简历文件过大（需小于等于10MB）")
            return redirect(url_for("public_resume_upload_page", token=token))

        filename = str(f.filename or "")
        ext = os.path.splitext(filename)[1].lower()
        if ext not in _ALLOWED_RESUME_EXTS:
            if wants_json:
                return jsonify({"ok": False, "error": "仅支持上传 PDF/Word（DOCX）或图片简历。"}), 400
            flash("仅支持上传 PDF/Word（DOCX）或图片简历")
            return redirect(url_for("public_resume_upload_page", token=token))

        try:
            text = extract_resume_text(data, filename)
        except Exception as e:
            logger.exception("Public resume extract failed")
            if wants_json:
                return jsonify({"ok": False, "error": f"简历解析失败：{type(e).__name__}"}), 500
            flash(f"简历解析失败：{type(e).__name__}")
            return redirect(url_for("public_resume_upload_page", token=token))

        parsed_phone = ""
        parsed_name = ""
        name_conf = 0
        phone_conf = 0
        try:
            ident = parse_resume_identity_fast(text or "") or {}
            parsed_name = str(ident.get("name") or "").strip()
            parsed_phone = _normalize_phone(str(ident.get("phone") or "").strip())
            conf = ident.get("confidence") or {}
            if isinstance(conf, dict):
                name_conf = _safe_int(conf.get("name") or 0, 0)
                phone_conf = _safe_int(conf.get("phone") or 0, 0)
        except Exception:
            pass

        if _is_valid_phone(parsed_phone) and parsed_phone != phone:
            if wants_json:
                return jsonify({"ok": False, "error": "简历手机号与验证手机号不一致，请检查后重试。"}), 400
            flash("简历手机号与验证手机号不一致，请检查后重试")
            return redirect(url_for("public_resume_upload_page", token=token))

        details: dict[str, Any] = {}
        details_error = ""
        resume_llm_total_tokens = 0
        try:
            with audit_context(meta={}):
                parsed_details = parse_resume_details_llm(text or "")
                if isinstance(parsed_details, dict):
                    details = parsed_details
                try:
                    ctx = get_audit_context()
                    m = ctx.get("meta")
                    if isinstance(m, dict):
                        resume_llm_total_tokens += int(m.get("llm_total_tokens_sum") or 0)
                except Exception:
                    pass
        except Exception as e:
            details_error = f"{type(e).__name__}: {e}"

        cid = 0
        created = False
        cand = None
        try:
            cand = get_candidate_by_phone(phone)
        except Exception:
            cand = None
        if cand and int(cand.get("id") or 0) > 0:
            cid = int(cand.get("id") or 0)
        else:
            try:
                cid = int(create_candidate(name=name, phone=phone))
                created = True
            except Exception:
                try:
                    cand2 = get_candidate_by_phone(phone)
                    cid = int((cand2 or {}).get("id") or 0)
                except Exception:
                    cid = 0

        if cid <= 0:
            if wants_json:
                return jsonify({"ok": False, "error": "创建候选人失败，请稍后重试。"}), 500
            flash("创建候选人失败，请稍后重试")
            return redirect(url_for("public_resume_upload_page", token=token))

        if created:
            try:
                log_event(
                    "candidate.create",
                    actor="candidate",
                    candidate_id=cid,
                    meta={"name": name, "phone": phone, "public_invite": True},
                )
            except Exception:
                pass

        if _is_valid_name(parsed_name):
            try:
                c0 = get_candidate(cid) or {}
                old_name = str(c0.get("name") or "").strip()
                if old_name in {"", "未知"}:
                    update_candidate(cid, name=parsed_name, phone=phone)
            except Exception:
                pass

        mime = str(getattr(f, "mimetype", "") or "")
        resume_meta: dict[str, Any] = {
            "extracted": {"name": parsed_name, "phone": parsed_phone or phone},
            "confidence": {"name": max(0, min(100, name_conf)), "phone": max(0, min(100, phone_conf))},
            "source_filename": filename,
            "source_mime": mime,
            "details": {
                "status": ("failed" if details_error else ("done" if details else "empty")),
                "data": details,
                "parsed_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        if details_error:
            resume_meta["details"]["error"] = details_error  # type: ignore[index]

        try:
            update_candidate_resume(
                cid,
                resume_bytes=data,
                resume_filename=filename,
                resume_mime=mime,
                resume_size=len(data),
                resume_parsed=resume_meta,
            )
        except Exception:
            logger.exception("Public resume save failed (cid=%s)", cid)
            if wants_json:
                return jsonify({"ok": False, "error": "简历保存失败，请稍后重试。"}), 500
            flash("简历保存失败，请稍后重试")
            return redirect(url_for("public_resume_upload_page", token=token))

        with assignment_locked(token):
            assignment = load_assignment(token)
            assignment["candidate_id"] = int(cid)
            assignment.pop("pending_profile", None)
            now2 = datetime.now(timezone.utc)
            assignment["status"] = "verified"
            assignment["status_updated_at"] = now2.isoformat()
            try:
                inv = assignment.get("invite_window") or {}
                if not isinstance(inv, dict):
                    inv = {}
                invite_start_date = str(inv.get("start_date") or "").strip() or None
                invite_end_date = str(inv.get("end_date") or "").strip() or None
                if not get_exam_paper_by_token(token):
                    create_exam_paper(
                        candidate_id=int(cid),
                        phone=phone,
                        exam_key=str(assignment.get("exam_key") or ""),
                        token=token,
                        invite_start_date=invite_start_date,
                        invite_end_date=invite_end_date,
                        status="verified",
                    )
                else:
                    set_exam_paper_status(token, "verified")
            except Exception:
                pass
            save_assignment(token, assignment)

        try:
            log_event(
                "candidate.resume.parse",
                actor="candidate",
                candidate_id=int(cid),
                exam_key=(str(assignment.get("exam_key") or "").strip() or None),
                token=(token or None),
                llm_total_tokens=(int(resume_llm_total_tokens or 0) or None),
                meta={"public_invite": True},
            )
        except Exception:
            pass

        redirect_to = url_for("public_exam_page", token=token)
        if wants_json:
            return jsonify({"ok": True, "redirect": redirect_to})
        return redirect(redirect_to)
