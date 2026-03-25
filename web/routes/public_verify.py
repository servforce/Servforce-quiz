from __future__ import annotations

from web.runtime_support import *
from web.runtime_setup import _ensure_exam_paper_for_token


def register_public_verify_routes(app: Flask) -> None:
    @app.get("/p/<public_token>")
    def public_invite_entry(public_token: str):
        """
        Public invite entry: each browser session gets an attempt token.
        Reuses an existing token via cookie to avoid creating multiple records on refresh.
        """
        t = str(public_token or "").strip()
        if not t:
            abort(404)

        exam_key = _resolve_public_invite_exam_key(t)
        if not exam_key:
            abort(404)

        cfg = get_public_invite_config(exam_key)
        if not bool(cfg.get("enabled")) or str(cfg.get("token") or "").strip() != t:
            return render_template(
                "public_unavailable.html",
                title="链接不可用",
                message="当前公开邀约链接已关闭或无效，请联系管理员。",
                start_date="",
                end_date="",
            )

        exam = get_exam_definition(exam_key)
        exam_version_id = resolve_exam_version_id_for_new_assignment(exam_key)
        if not exam or not exam_version_id:
            abort(404)

        cookie_name = f"public_invite_{t}"
        existing = str(request.cookies.get(cookie_name) or "").strip()
        if existing:
            try:
                with assignment_locked(existing):
                    a0 = load_assignment(existing)
                if str(a0.get("exam_key") or "").strip() == exam_key:
                    return redirect(url_for("public_verify_page", token=existing))
            except Exception:
                pass

        base_url = request.url_root.rstrip("/")
        result = create_assignment(
            exam_key=exam_key,
            candidate_id=0,
            exam_version_id=exam_version_id,
            base_url=base_url,
            phone="",
            invite_start_date=None,
            invite_end_date=None,
            time_limit_seconds=7200,
            min_submit_seconds=None,
            verify_max_attempts=3,
            pass_threshold=60,
        )
        token = str(result.get("token") or "").strip()
        if not token:
            abort(500)

        try:
            with assignment_locked(token):
                a = load_assignment(token)
                a["public_invite"] = {"token": t, "exam_key": exam_key, "exam_version_id": exam_version_id}
                save_assignment(token, a)
        except Exception:
            pass

        resp = redirect(url_for("public_verify_page", token=token))
        try:
            resp.set_cookie(cookie_name, token, max_age=7 * 24 * 3600, samesite="Lax")
        except Exception:
            pass
        return resp

    @app.get("/qr/p/<public_token>.png")
    def public_invite_qr(public_token: str):
        t = str(public_token or "").strip()
        if not t:
            abort(404)
        exam_key = _resolve_public_invite_exam_key(t)
        if not exam_key:
            abort(404)
        cfg = get_public_invite_config(exam_key)
        if not bool(cfg.get("enabled")) or str(cfg.get("token") or "").strip() != t:
            abort(404)

        try:
            import qrcode  # type: ignore
        except Exception:
            abort(500)

        public_url = f"{request.url_root.rstrip('/')}/p/{t}"
        img = qrcode.make(public_url)
        buf = BytesIO()
        # qrcode may return either PIL image or PyPNG image depending on installed deps.
        try:
            img.save(buf, format="PNG")
        except TypeError:
            # PyPNGImage.save() does not accept the `format` kwarg.
            img.save(buf)
        buf.seek(0)
        resp = send_file(buf, mimetype="image/png")
        # Avoid browsers caching a stale/broken QR (e.g. previous 404 during index mismatch).
        try:
            resp.headers["Cache-Control"] = "no-store, max-age=0"
            resp.headers["Pragma"] = "no-cache"
        except Exception:
            pass
        return resp

    @app.get("/t/<token>")
    def public_verify_page(token: str):
        with assignment_locked(token):
            assignment = load_assignment(token)
            if str(assignment.get("status") or "").strip() == "expired":
                return render_template(
                    "public_unavailable.html",
                    title="邀约已失效",
                    message="当前答题链接已失效，请联系管理员重新生成新的邀请链接。",
                    start_date="",
                    end_date="",
                )
            st, sd, ed = _invite_window_state(assignment)
            if st in {"not_started", "expired"}:
                if st == "expired":
                    try:
                        if not str((assignment.get("timing") or {}).get("start_at") or "").strip():
                            assignment["status"] = "expired"
                            assignment["status_updated_at"] = datetime.now(timezone.utc).isoformat()
                            save_assignment(token, assignment)
                    except Exception:
                        pass
                title = "未到答题时间" if st == "not_started" else "邀约已失效"
                msg = "当前未到答题时间，请在有效时间范围内进入答题。" if st == "not_started" else "当前邀约已超过有效时间范围，无法开始答题。"
                return render_template(
                    "public_unavailable.html",
                    title=title,
                    message=msg,
                    start_date=(sd.isoformat() if sd else ""),
                    end_date=(ed.isoformat() if ed else ""),
                )
            if assignment.get("grading") or _finalize_if_time_up(token, assignment):
                return redirect(url_for("public_done", token=token))
            _ensure_exam_paper_for_token(token, assignment)

        verify = assignment.get("verify") or {}
        sms = assignment.get("sms_verify") or {}
        return render_template(
            "public_verify.html",
            token=token,
            locked=bool(verify.get("locked")),
            attempts=int(verify.get("attempts") or 0),
            max_attempts=int(assignment.get("verify_max_attempts") or 3),
            sms_verified=bool(sms.get("verified")),
        )

    @app.post("/api/public/sms/send")
    def public_send_sms_code():
        data = request.get_json(silent=True) or {}
        token = str(data.get("token") or "").strip()
        name = str(data.get("name") or "").strip()
        phone = _normalize_phone(str(data.get("phone") or ""))
        if not token or not _is_valid_name(name) or not _is_valid_phone(phone):
            return jsonify({"ok": False, "error": "请输入正确的姓名和手机号。"}), 400

        cooldown_seconds = 60
        max_send = 3
        ttl_seconds = _sms_code_ttl_seconds()
        now = datetime.now(timezone.utc)

        with assignment_locked(token):
            assignment = load_assignment(token)
            if str(assignment.get("status") or "").strip() == "expired":
                return jsonify({"ok": False, "error": "链接已失效。"}), 410

            st, _sd, _ed = _invite_window_state(assignment)
            if st in {"not_started", "expired"}:
                return jsonify({"ok": False, "error": "当前不在可答题时间范围内。"}), 400
            if assignment.get("grading") or _finalize_if_time_up(token, assignment):
                return jsonify({"ok": False, "error": "答题已结束。"}), 400

            verify = assignment.get("verify") or {"attempts": 0, "locked": False}
            if verify.get("locked"):
                return jsonify({"ok": False, "error": "链接已失效。"}), 410

            try:
                candidate_id = int(assignment.get("candidate_id") or 0)
            except Exception:
                candidate_id = 0

            ok = False
            if candidate_id > 0:
                ok = verify_candidate(candidate_id, name=name, phone=phone)
            else:
                existing = None
                try:
                    existing = get_candidate_by_phone(phone)
                except Exception:
                    existing = None
                if existing and int(existing.get("id") or 0) > 0:
                    existing_id = int(existing.get("id") or 0)
                    existing_name = str(existing.get("name") or "").strip()
                    ok = bool(existing_name == name)
                    if ok:
                        assignment["candidate_id"] = existing_id
                        candidate_id = existing_id
                else:
                    ok = True

            if not ok:
                verify["attempts"] = int(verify.get("attempts") or 0) + 1
                if verify["attempts"] >= int(assignment.get("verify_max_attempts") or 3):
                    verify["locked"] = True
                assignment["verify"] = verify
                save_assignment(token, assignment)
                return jsonify({"ok": False, "error": "信息不匹配，请检查后重试。"}), 400

            sms = assignment.get("sms_verify") or {}
            if not sms.get("verified") and int(sms.get("send_count") or 0) >= max_send:
                nowx = datetime.now(timezone.utc)
                assignment["status"] = "expired"
                assignment["status_updated_at"] = nowx.isoformat()
                try:
                    set_exam_paper_status(token, "expired")
                except Exception:
                    pass
                verify["locked"] = True
                assignment["verify"] = verify
                save_assignment(token, assignment)
                return jsonify({"ok": False, "expired": True, "error": "验证码发送次数已达上限，链接已失效。"}), 410

            last_phone = str(sms.get("phone") or "")
            last_sent_at = str(sms.get("last_sent_at") or "").strip()
            if last_phone == phone and last_sent_at:
                last_dt = _parse_iso_datetime(last_sent_at)
                if last_dt is not None:
                    elapsed = (now - last_dt).total_seconds()
                    left = int(cooldown_seconds - elapsed)
                    if left > 0:
                        return jsonify({"ok": False, "cooldown": left, "error": f"请{left}秒后再试。"}), 429

            code = _generate_sms_code(_sms_code_length())
            code_salt = secrets.token_hex(16)
            code_hash = _hash_sms_code(code, code_salt)

            try:
                resp = send_sms_verify_code(phone, code=code, ttl_seconds=ttl_seconds)
            except Exception:
                logger.exception("Send SMS verify code failed")
                return jsonify({"ok": False, "error": "短信服务暂不可用，请稍后重试。"}), 502

            success = bool(resp.get("Success")) and str(resp.get("Code") or "").upper() == "OK"
            if not success:
                return jsonify({"ok": False, "error": str(resp.get("Message") or "发送失败。")}), 502

            biz_id = ""
            model = resp.get("Model")
            if isinstance(model, dict):
                biz_id = str(model.get("BizId") or "").strip()

            sms["phone"] = phone
            sms["last_sent_at"] = now.isoformat()
            sms["expires_at"] = (now + timedelta(seconds=ttl_seconds)).isoformat()
            sms["code_salt"] = code_salt
            sms["code_hash"] = code_hash
            sms["send_count"] = int(sms.get("send_count") or 0) + 1
            if biz_id:
                sms["biz_id"] = biz_id
            assignment["sms_verify"] = sms
            save_assignment(token, assignment)
            try:
                incr_sms_calls_and_alert(1)
            except Exception:
                pass

        return jsonify({
            "ok": True,
            "cooldown": cooldown_seconds,
            "biz_id": biz_id,
            "send_count": int(sms.get("send_count") or 0),
            "send_max": max_send,
        })

    @app.post("/api/public/verify")
    def public_verify():
        wants_json = "application/json" in str(request.headers.get("Accept") or "").lower()
        token = (request.form.get("token") or "").strip()
        name = (request.form.get("name") or "").strip()
        phone = _normalize_phone(request.form.get("phone") or "")
        sms_code = (request.form.get("sms_code") or "").strip()
        log_candidate_id = 0
        log_exam_key = ""
        log_public_invite = False
        log_sms_send_count = 0
        next_redirect = ""

        if not _is_valid_name(name) or not _is_valid_phone(phone):
            if wants_json:
                return jsonify({"ok": False, "error": "姓名或手机号格式不正确。"}), 400
            flash("姓名或手机号格式不正确")
            return redirect(url_for("public_verify_page", token=token))

        with assignment_locked(token):
            assignment = load_assignment(token)
            if str(assignment.get("status") or "").strip() == "expired":
                if wants_json:
                    return jsonify({"ok": False, "expired": True, "error": "当前链接已失效，请联系管理员重新生成。"}), 410
                flash("链接已失效")
                return redirect(url_for("public_verify_page", token=token))

            st, _sd, _ed = _invite_window_state(assignment)
            if st in {"not_started", "expired"}:
                if wants_json:
                    return jsonify({"ok": False, "error": "当前不在可答题时间范围内。"}), 400
                return redirect(url_for("public_verify_page", token=token))

            if assignment.get("grading") or _finalize_if_time_up(token, assignment):
                if wants_json:
                    return jsonify({"ok": False, "error": "答题已结束。"}), 400
                return redirect(url_for("public_done", token=token))

            _ensure_exam_paper_for_token(token, assignment)
            verify = assignment.get("verify") or {"attempts": 0, "locked": False}
            if verify.get("locked"):
                if wants_json:
                    return jsonify({"ok": False, "expired": True, "error": "当前链接已失效，请联系管理员重新生成。"}), 410
                flash("链接已失效")
                return redirect(url_for("public_verify_page", token=token))

            try:
                candidate_id = int(assignment.get("candidate_id") or 0)
            except Exception:
                candidate_id = 0

            if candidate_id > 0:
                ok = verify_candidate(candidate_id, name=name, phone=phone)
            else:
                existing = None
                try:
                    existing = get_candidate_by_phone(phone)
                except Exception:
                    existing = None
                if existing and int(existing.get("id") or 0) > 0:
                    existing_id = int(existing.get("id") or 0)
                    existing_name = str(existing.get("name") or "").strip()
                    ok = bool(existing_name == name)
                    if ok:
                        assignment["candidate_id"] = existing_id
                        candidate_id = existing_id
                else:
                    ok = True

            if ok:
                sms = assignment.get("sms_verify") or {}
                if str(sms.get("phone") or "") != phone:
                    sms["phone"] = phone
                    sms.pop("expires_at", None)
                    sms.pop("code_salt", None)
                    sms.pop("code_hash", None)
                    assignment["sms_verify"] = sms

                if not sms.get("verified"):
                    if not sms_code:
                        if wants_json:
                            return jsonify({"ok": False, "error": "请输入短信验证码。"}), 400
                        flash("请输入短信验证码")
                        return redirect(url_for("public_verify_page", token=token))

                    if not str(sms.get("expires_at") or "").strip() or not str(sms.get("code_hash") or "").strip() or not str(sms.get("code_salt") or "").strip():
                        if wants_json:
                            return jsonify({"ok": False, "error": "请先发送短信验证码。"}), 400
                        flash("请先发送短信验证码")
                        return redirect(url_for("public_verify_page", token=token))

                    exp = _parse_iso_datetime(str(sms.get("expires_at") or ""))
                    if exp is None or exp <= datetime.now(timezone.utc):
                        if wants_json:
                            return jsonify({"ok": False, "error": "验证码已过期，请重新发送。", "clear_sms": True}), 400
                        flash("验证码已过期，请重新发送。")
                        return redirect(url_for("public_verify_page", token=token))

                    salt = str(sms.get("code_salt") or "").strip()
                    expected = str(sms.get("code_hash") or "").strip()
                    actual = _hash_sms_code(sms_code, salt)
                    sms_ok = bool(expected and salt and hmac.compare_digest(expected, actual))
                    if not sms_ok:
                        if int((sms.get("send_count") or 0)) >= 3:
                            nowx = datetime.now(timezone.utc)
                            assignment["status"] = "expired"
                            assignment["status_updated_at"] = nowx.isoformat()
                            try:
                                set_exam_paper_status(token, "expired")
                            except Exception:
                                pass
                            verify["locked"] = True
                            assignment["verify"] = verify
                            save_assignment(token, assignment)
                            if wants_json:
                                return jsonify({"ok": False, "expired": True, "error": "验证码未在规定次数内验证通过，链接已失效，请联系管理员重新生成。", "clear_sms": True}), 410
                            flash("验证码未在规定次数内验证通过，链接已失效，请联系管理员重新生成。")
                            return redirect(url_for("public_verify_page", token=token))

                        if wants_json:
                            return jsonify({"ok": False, "error": "验证码错误，请重试。", "clear_sms": True}), 400
                        save_assignment(token, assignment)
                        flash("验证码错误，请重试。")
                        return redirect(url_for("public_verify_page", token=token))

                    sms["verified"] = True
                    sms["verified_at"] = datetime.now(timezone.utc).isoformat()
                    sms.pop("expires_at", None)
                    sms.pop("code_salt", None)
                    sms.pop("code_hash", None)
                    assignment["sms_verify"] = sms

                if candidate_id <= 0:
                    cand = None
                    try:
                        cand = get_candidate_by_phone(phone)
                    except Exception:
                        cand = None
                    if cand and int(cand.get("id") or 0) > 0:
                        candidate_id = int(cand.get("id") or 0)
                        assignment["candidate_id"] = int(candidate_id)
                    else:
                        assignment["pending_profile"] = {
                            "name": name,
                            "phone": phone,
                            "sms_verified_at": str(sms.get("verified_at") or ""),
                        }
                        now2 = datetime.now(timezone.utc)
                        assignment["status"] = "resume_pending"
                        assignment["status_updated_at"] = now2.isoformat()
                        next_redirect = url_for("public_resume_upload_page", token=token)

                if candidate_id > 0:
                    try:
                        inv = assignment.get("invite_window") or {}
                        if not isinstance(inv, dict):
                            inv = {}
                        invite_start_date = str(inv.get("start_date") or "").strip() or None
                        invite_end_date = str(inv.get("end_date") or "").strip() or None
                        if not get_exam_paper_by_token(token):
                            create_exam_paper(
                                candidate_id=int(candidate_id),
                                phone=phone,
                                exam_key=str(assignment.get("exam_key") or ""),
                                token=token,
                                invite_start_date=invite_start_date,
                                invite_end_date=invite_end_date,
                                status="verified",
                            )
                    except Exception:
                        pass

                    try:
                        set_exam_paper_status(token, "verified")
                    except Exception:
                        pass
                    now2 = datetime.now(timezone.utc)
                    assignment["status"] = "verified"
                    assignment["status_updated_at"] = now2.isoformat()
                    assignment.pop("pending_profile", None)
                    next_redirect = url_for("public_exam_page", token=token)
            else:
                verify["attempts"] = int(verify.get("attempts") or 0) + 1
                if verify["attempts"] >= int(assignment.get("verify_max_attempts") or 3):
                    verify["locked"] = True

            assignment["verify"] = verify
            if ok:
                try:
                    log_candidate_id = int(candidate_id or 0)
                except Exception:
                    log_candidate_id = 0
                log_exam_key = str(assignment.get("exam_key") or "").strip()
                log_public_invite = bool(assignment.get("public_invite"))
                try:
                    sms = assignment.get("sms_verify") or {}
                    log_sms_send_count = int((sms.get("send_count") or 0) if isinstance(sms, dict) else 0)
                except Exception:
                    log_sms_send_count = 0
            save_assignment(token, assignment)

        if ok:
            try:
                log_event(
                    "assignment.verify",
                    actor="candidate",
                    candidate_id=(int(log_candidate_id) if int(log_candidate_id or 0) > 0 else None),
                    exam_key=(log_exam_key or None),
                    token=(token or None),
                    meta={
                        "name": name,
                        "phone": phone,
                        "public_invite": bool(log_public_invite),
                        "sms_send_count": int(log_sms_send_count or 0),
                    },
                )
            except Exception:
                pass
            if not next_redirect:
                next_redirect = url_for("public_exam_page", token=token)
            if wants_json:
                return jsonify({"ok": True, "redirect": next_redirect})
            return redirect(next_redirect)

        if wants_json:
            return jsonify({"ok": False, "error": "信息不匹配，请重试。"}), 400
        flash("信息不匹配，请重试")
        return redirect(url_for("public_verify_page", token=token))
