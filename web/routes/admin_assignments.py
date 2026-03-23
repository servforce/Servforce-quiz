from __future__ import annotations

from web.runtime_support import *


def register_admin_assignment_routes(app: Flask) -> None:
    @app.post("/admin/assignments")
    @admin_required
    def admin_assignments_create():
        exam_key = (request.form.get("exam_key") or "").strip()
        candidate_id = int(request.form.get("candidate_id") or "0")
        time_limit_raw = (request.form.get("time_limit_seconds") or "").strip()
        time_limit_seconds = _parse_duration_seconds(time_limit_raw)
        if not time_limit_raw or time_limit_seconds is None:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_assignments"))
        min_submit_seconds_raw = (request.form.get("min_submit_seconds") or "").strip()
        min_submit_seconds: int | None = None
        if min_submit_seconds_raw != "":
            try:
                min_submit_seconds = int(min_submit_seconds_raw)
            except Exception:
                min_submit_seconds = None
        pass_threshold = int(request.form.get("pass_threshold") or "60")
        verify_max_attempts = int(request.form.get("verify_max_attempts") or "3")

        if not get_exam_definition(exam_key):
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_assignments"))

        c = get_candidate(candidate_id)
        if not c:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_assignments"))

        invite_start_date_raw = (request.form.get("invite_start_date") or "").strip()
        invite_end_date_raw = (request.form.get("invite_end_date") or "").strip()
        if not invite_start_date_raw:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_assignments"))
        if not invite_end_date_raw:
            flash("请选择答题结束日期")
            return redirect(url_for("admin_assignments"))
        sd = _parse_date_ymd(invite_start_date_raw) if invite_start_date_raw else None
        ed = _parse_date_ymd(invite_end_date_raw) if invite_end_date_raw else None
        if sd is None:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_assignments"))
        if ed is None:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_assignments"))
        if invite_start_date_raw and sd is None:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_assignments"))
        if invite_end_date_raw and ed is None:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_assignments"))
        if sd is not None and ed is not None and ed < sd:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_assignments"))

        base_url = request.url_root.rstrip("/")
        result = create_assignment(
            exam_key=exam_key,
            candidate_id=candidate_id,
            base_url=base_url,
            phone=str(c.get("phone") or ""),
            invite_start_date=(sd.isoformat() if sd else None),
            invite_end_date=(ed.isoformat() if ed else None),
            time_limit_seconds=time_limit_seconds,
            min_submit_seconds=min_submit_seconds,
            verify_max_attempts=verify_max_attempts,
            pass_threshold=pass_threshold,
        )
        try:
            create_exam_paper(
                candidate_id=candidate_id,
                phone=str(c.get("phone") or ""),
                exam_key=exam_key,
                token=str(result.get("token") or ""),
                invite_start_date=(sd.isoformat() if sd else None),
                invite_end_date=(ed.isoformat() if ed else None),
                status="invited",
            )
        except Exception:
            logger.exception("Create exam_paper failed (candidate_id=%s, exam_key=%s)", candidate_id, exam_key)
        try:
            log_event(
                "assignment.create",
                actor="admin",
                candidate_id=int(candidate_id),
                exam_key=str(exam_key or "").strip(),
                token=str(result.get("token") or "").strip() or None,
                meta={"invite_start_date": (sd.isoformat() if sd else None), "invite_end_date": (ed.isoformat() if ed else None)},
            )
        except Exception:
            pass
        return render_template(
            "admin_assignment_created.html",
            exam_key=exam_key,
            candidate_id=candidate_id,
            token=result["token"],
            url=result["url"],
        )

    #
    @app.get("/admin/qr/<token>.png")
    @admin_required
    def admin_qr(token: str):
        try:
            load_assignment(token)
        except Exception:
            abort(404)
        try:
            import qrcode  # type: ignore
        except Exception:
            abort(500)
        url = f"{request.url_root.rstrip('/')}/t/{str(token or '').strip()}"
        img = qrcode.make(url)
        buf = BytesIO()
        try:
            img.save(buf, format="PNG")
        except TypeError:
            img.save(buf)
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    # 带token的url，加载对应的答卷，并渲染答卷
    @app.get("/admin/result/<token>")
    @admin_required
    def admin_result(token: str):
        assignment = load_assignment(token)
        try:
            cid = int((assignment or {}).get("candidate_id") or 0)
        except Exception:
            cid = 0
        try:
            ek = str((assignment or {}).get("exam_key") or "").strip()
        except Exception:
            ek = ""
        meta: dict[str, Any] | None = None
        if cid > 0:
            try:
                c = get_candidate(cid) or {}
                meta = {"name": str(c.get("name") or "").strip(), "phone": str(c.get("phone") or "").strip()}
            except Exception:
                meta = None
        try:
            log_event(
                "exam.result",
                actor="admin",
                candidate_id=(cid if cid > 0 else None),
                exam_key=(ek or None),
                token=(str(token or "").strip() or None),
                meta=meta,
            )
        except Exception:
            pass
        return render_template("admin_result.html", assignment=assignment)

    @app.get("/admin/attempt/<token>")
    @admin_required
    def admin_attempt(token: str):
        try:
            assignment = load_assignment(token)
        except Exception:
            abort(404)

        row = None
        try:
            row = _find_archive_by_token(token, assignment=assignment)
        except Exception:
            row = None

        if row:
            archive = row.get("archive") if isinstance(row, dict) else None
            if isinstance(archive, dict):
                try:
                    archive = _augment_archive_with_spec(archive)
                except Exception:
                    pass
                try:
                    ek = str(((archive or {}).get("exam") or {}).get("exam_key") or "").strip()
                except Exception:
                    ek = ""
                try:
                    cid = int(((archive or {}).get("candidate") or {}).get("id") or 0)
                except Exception:
                    cid = 0
                meta: dict[str, Any] | None = None
                if cid > 0:
                    try:
                        c = get_candidate(cid) or {}
                        meta = {"name": str(c.get("name") or "").strip(), "phone": str(c.get("phone") or "").strip()}
                    except Exception:
                        meta = None
                try:
                    log_event(
                        "exam.result",
                        actor="admin",
                        candidate_id=(cid if cid > 0 else None),
                        exam_key=(ek or None),
                        token=(str(token or "").strip() or None),
                        meta=meta,
                    )
                except Exception:
                    pass
                return render_template("admin_candidate_attempt.html", archive=archive)

        try:
            cid = int((assignment or {}).get("candidate_id") or 0)
        except Exception:
            cid = 0
        try:
            ek = str((assignment or {}).get("exam_key") or "").strip()
        except Exception:
            ek = ""
        meta: dict[str, Any] | None = None
        if cid > 0:
            try:
                c = get_candidate(cid) or {}
                meta = {"name": str(c.get("name") or "").strip(), "phone": str(c.get("phone") or "").strip()}
            except Exception:
                meta = None
        try:
            log_event(
                "exam.result",
                actor="admin",
                candidate_id=(cid if cid > 0 else None),
                exam_key=(ek or None),
                token=(str(token or "").strip() or None),
                meta=meta,
            )
        except Exception:
            pass
        return render_template("admin_result.html", assignment=assignment)
