from __future__ import annotations

from web.runtime_support import *


def register_admin_shell_routes(app: Flask) -> None:
    # ---------------- Admin ----------------
    @app.context_processor
    def _inject_system_status():
        try:
            if not session.get("admin_logged_in"):
                return {}
        except Exception:
            return {}
        try:
            # Never block template render on live status aggregation.
            # The topbar is hydrated asynchronously by system_status.js after first paint.
            return {"system_status_summary": _peek_cached_system_status_summary()}
        except Exception:
            return {"system_status_summary": {}}

    # get是从后端调用数据和页面的
    @app.get("/admin/login")
    def admin_login():
        return render_template("admin_login.html")

    #
    @app.post("/admin/login")
    def admin_login_post():
        username = (request.form.get("username") or "").strip()     # 取表单的数据
        password = (request.form.get("password") or "").strip()
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True       # 写入session标记admin_logged_in = True
            return redirect(url_for("admin_dashboard"))     # admin_dashboard，管理员首页
        flash("账号或密码错误")
        return redirect(url_for("admin_login"))

    #
    @app.post("/admin/logout")
    def admin_logout():     
        session.clear()
        return redirect(url_for("admin_login"))

    @app.get("/admin/api/system-status/summary")
    @admin_required
    def admin_system_status_summary_api():
        return jsonify(_get_cached_system_status_summary())

    @app.get("/admin/api/system-status")
    @admin_required
    def admin_system_status_api():
        today = datetime.now().astimezone().date()
        start_day = _parse_date_ymd(request.args.get("start") or "") or (today - timedelta(days=29))
        end_day = _parse_date_ymd(request.args.get("end") or "") or today
        data = _compute_system_status_range(start_day=start_day, end_day=end_day)
        return jsonify({"ok": True, "config": _load_system_status_cfg(), "data": data})

    @app.post("/admin/api/system-status/config")
    @admin_required
    def admin_system_status_config_api():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            body = {}
        cfg = _save_system_status_cfg(body)
        try:
            # Re-check once after threshold changes:
            # if still over limit, emit one fresh alert snapshot.
            emit_alerts_for_current_snapshot()
        except Exception:
            pass
        return jsonify({"ok": True, "config": cfg, "summary": _get_cached_system_status_summary(force=True)})

    @app.post("/admin/api/system-status/alerts/cleanup")
    @admin_required
    def admin_system_alerts_cleanup_api():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            body = {}
        day = str(body.get("day") or "").strip()
        kind = str(body.get("kind") or "").strip()
        try:
            deleted = int(cleanup_duplicate_system_alert_logs(day=(day or None), kind=(kind or None)))
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True, "deleted": deleted, "day": day, "kind": kind})

    @app.post("/admin/api/system-status/alerts/backfill")
    @admin_required
    def admin_system_alerts_backfill_api():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            body = {}
        day = str(body.get("day") or "").strip()
        kind = str(body.get("kind") or "").strip()
        if not day or kind not in {"llm_tokens", "sms_calls"}:
            return jsonify({"ok": False, "error": "invalid day/kind"}), 400
        try:
            inserted = int(backfill_missing_system_alert_levels(day=day, kind=kind))
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True, "inserted": inserted, "day": day, "kind": kind})

    def _admin_status_label(v: str) -> str:
        s = _normalize_exam_status(v)
        m = {
            "verified": "验证通过",
            "invited": "已邀约",
            "in_exam": "正在答题",
            "grading": "正在判卷",
            "finished": "判卷结束",
            "expired": "失效",
        }
        return m.get(s, "未知")

    def _admin_looks_deleted_marker(text: str) -> bool:
        s = str(text or "").strip().lower()
        if not s:
            return False
        if s in {"已删除", "deleted", "????", "???", "null", "none", "历史试卷"}:
            return True
        if "?" in s and len(s) <= 12:
            return True
        return "删除" in s and len(s) <= 8

    def _build_admin_exams_context(args) -> dict[str, Any]:
        exams_all = _list_exams()   # 获取考试列表
        try:
            sync_state = read_exam_repo_sync_state()
        except Exception:
            sync_state = {}
        exam_q = (request.args.get("exam_q") or "").strip()
        ai_notice = (args.get("ai_notice") or "").strip()
        ai_notice_level = (args.get("ai_notice_level") or "").strip().lower()
        if ai_notice_level not in {"ok", "error"}:
            ai_notice_level = "error"
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

        exams_all.sort(key=lambda x: float(x.get("_mtime") or 0), reverse=True)
        per_page = 20
        try:
            exam_page = int(args.get("exam_page") or "1")
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

            try:
                cfg = get_public_invite_config(str(e.get("exam_key") or ""))
            except Exception:
                cfg = {"enabled": False, "token": ""}
            e["public_invite_enabled"] = bool(cfg.get("enabled"))
            e["public_invite_token"] = str(cfg.get("token") or "").strip()

        return {
            "exams_all": exams_all,
            "exams_page": exams_page,
            "exam_page": exam_page,
            "total_exams": total_exams,
            "total_exam_pages": total_exam_pages,
            "exam_q": exam_q,
            "exam_per_page": per_page,
            "ai_exam_prompt": "",
            "ai_exam_include_diagrams": False,
            "ai_notice": ai_notice,
            "ai_notice_level": ai_notice_level,
            "exam_sync_state": sync_state,
            "exam_repo_url": str(sync_state.get("repo_url") or "").strip(),
        }

    def _build_assignment_attempts_context(args) -> dict[str, Any]:
        cache_key = (
            str(args.get("exam_q") or "").strip(),
            str(args.get("attempt_q") or "").strip(),
            str(args.get("attempt_start_from") or "").strip(),
            str(args.get("attempt_start_to") or "").strip(),
            str(args.get("assign_exam_key") or "").strip(),
            str(args.get("assign_candidate_id") or "").strip(),
            str(args.get("attempt_page") or "1").strip() or "1",
        )
        cached = _get_cached_assignments_context(cache_key)
        if cached is not None:
            return cached

        exams_all = _list_exams()
        active_exams = [e for e in exams_all if str(e.get("status") or "") == "active" and int(e.get("current_version_id") or 0) > 0]
        candidates = list_candidates(limit=200)
        exam_q = (args.get("exam_q") or "").strip()
        attempt_q = (args.get("attempt_q") or "").strip()
        attempt_start_from_raw = (args.get("attempt_start_from") or "").strip()
        attempt_start_to_raw = (args.get("attempt_start_to") or "").strip()
        assign_exam_key = (args.get("assign_exam_key") or "").strip()
        assign_candidate_id = (args.get("assign_candidate_id") or "").strip()

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
        exams_all.sort(key=lambda x: float(x.get("_mtime") or 0), reverse=True)
        active_exams.sort(key=lambda x: float(x.get("_mtime") or 0), reverse=True)

        attempt_per_page = 20
        try:
            attempt_page = int(args.get("attempt_page") or "1")
        except Exception:
            attempt_page = 1
        attempt_page = max(1, attempt_page)

        attempt_start_from = _parse_date_ymd(attempt_start_from_raw) if attempt_start_from_raw else None
        attempt_start_to = _parse_date_ymd(attempt_start_to_raw) if attempt_start_to_raw else None
        invite_start_from = attempt_start_from.isoformat() if attempt_start_from else None
        invite_start_to = attempt_start_to.isoformat() if attempt_start_to else None

        try:
            total_attempts = count_exam_papers(
                query=attempt_q or None,
                invite_start_from=invite_start_from,
                invite_start_to=invite_start_to,
            )
        except Exception:
            total_attempts = 0
        total_attempt_pages = (total_attempts + attempt_per_page - 1) // attempt_per_page
        if total_attempt_pages > 0:
            attempt_page = min(attempt_page, total_attempt_pages)
        else:
            attempt_page = 1

        offset = (attempt_page - 1) * attempt_per_page
        try:
            rows = list_exam_papers(
                query=attempt_q or None,
                invite_start_from=invite_start_from,
                invite_start_to=invite_start_to,
                limit=attempt_per_page,
                offset=offset,
            )
        except Exception:
            rows = []

        def _date_to_iso(v) -> str:
            if v is None:
                return ""
            if isinstance(v, date):
                return v.isoformat()
            s = str(v).strip()
            return s

        today_local = datetime.now().astimezone().date()

        attempt_candidates_page: list[dict[str, Any]] = []
        for r in rows:
            token = str(r.get("token") or "").strip()
            status = _normalize_exam_status(r.get("status"))

            invite_start_date = _date_to_iso(r.get("invite_start_date"))
            invite_end_date = _date_to_iso(r.get("invite_end_date"))

            if token and (not invite_start_date or not invite_end_date):
                # 页面渲染阶段只做只读兜底，不在这里做写回修正。
                # invite_window 仍以 assignment 当前状态为准，用于补全展示字段。
                try:
                    with assignment_locked(token):
                        a = load_assignment(token)
                        inv = a.get("invite_window") or {}
                        if isinstance(inv, dict):
                            invite_start_date = invite_start_date or str(inv.get("start_date") or "").strip()
                            invite_end_date = invite_end_date or str(inv.get("end_date") or "").strip()
                        if not invite_start_date or not invite_end_date:
                            t0 = a.get("timing") or {}
                            if isinstance(t0, dict):
                                started0 = _parse_iso_dt(str(t0.get("start_at") or "").strip() or None)
                                if started0 is not None:
                                    d0 = started0.astimezone().date()
                                    invite_start_date = invite_start_date or d0.isoformat()
                                    invite_end_date = invite_end_date or (d0 + timedelta(days=1)).isoformat()
                except Exception:
                    pass

            if token and status in {"invited", "verified"} and not r.get("entered_at"):
                ed = _parse_date_ymd(invite_end_date) if invite_end_date else None
                if ed is not None and today_local > ed:
                    status = "expired"

            candidate_id = int(r.get("candidate_id") or 0)
            name = str(r.get("name") or "").strip()
            candidate_deleted = bool(r.get("candidate_deleted_at"))
            if _admin_looks_deleted_marker(name) or not name:
                name = f"候选人#{candidate_id}" if candidate_id > 0 else "候选人"
            if candidate_id > 0 and (not candidate_deleted) and name.startswith("候选人#"):
                try:
                    recovered_name = str(get_candidate_name_from_logs(candidate_id) or "").strip()
                except Exception:
                    recovered_name = ""
                if recovered_name:
                    name = recovered_name
            candidate_clickable = (candidate_id > 0) and (not candidate_deleted)

            exam_key = str(r.get("exam_key") or "").strip()
            if _admin_looks_deleted_marker(exam_key):
                recovered_exam_key = ""
                if token:
                    try:
                        with assignment_locked(token):
                            a2 = load_assignment(token)
                            recovered_exam_key = str(a2.get("exam_key") or "").strip()
                    except Exception:
                        recovered_exam_key = ""
                exam_key = recovered_exam_key if recovered_exam_key else "历史试卷"
            exam_exists = bool(exam_key and get_exam_definition(exam_key))
            exam_version_id = int(r.get("exam_version_id") or 0)
            exam_href = None
            if exam_version_id > 0:
                exam_href = url_for("admin_exam_version_detail", version_id=exam_version_id)
            elif exam_exists and exam_key:
                exam_href = url_for("admin_exam_detail", exam_key=exam_key)

            attempt_href = None
            attempt_msg = None
            if token:
                if status == "finished":
                    attempt_href = url_for("admin_attempt", token=token)
                else:
                    attempt_msg = f"当前状态：{_admin_status_label(status)}，不可查看答题结果"

            attempt_candidates_page.append(
                {
                    "attempt_id": int(r.get("attempt_id") or 0),
                    "candidate_id": candidate_id,
                    "candidate_clickable": candidate_clickable,
                    "name": name,
                    "phone": str(r.get("phone") or ""),
                    "exam_key": exam_key,
                    "exam_version_id": exam_version_id,
                    "exam_exists": exam_exists,
                    "exam_href": exam_href,
                    "token": token,
                    "status": status,
                    "status_label": _admin_status_label(status),
                    "score": r.get("score"),
                    "invite_start_date": invite_start_date,
                    "invite_end_date": invite_end_date,
                    "attempt_href": attempt_href,
                    "attempt_msg": attempt_msg,
                }
            )

        result = {
            "exams_all": active_exams,
            "assign_exam_key": assign_exam_key,
            "assign_candidate_id": assign_candidate_id,
            "candidates": candidates,
            "attempt_q": attempt_q,
            "attempt_start_from": attempt_start_from_raw,
            "attempt_start_to": attempt_start_to_raw,
            "attempt_candidates": attempt_candidates_page,
            "attempt_page": attempt_page,
            "total_attempts": total_attempts,
            "total_attempt_pages": total_attempt_pages,
            "attempt_per_page": attempt_per_page,
            "exam_q": exam_q,
        }
        _set_cached_assignments_context(cache_key, result)
        return result

    def _build_admin_logs_context(args) -> dict[str, Any]:
        chart_start_raw = (args.get("chart_start") or "").strip()
        chart_end_raw = (args.get("chart_end") or "").strip()
        cache_key = (
            str(args.get("log_page") or "1").strip() or "1",
            chart_start_raw,
            chart_end_raw,
        )
        cached = _get_cached_logs_context(cache_key)
        if cached is not None:
            return cached
        log_per_page = 20
        try:
            log_page = int(args.get("log_page") or "1")
        except Exception:
            log_page = 1
        log_page = max(1, log_page)

        try:
            log_counts = count_operation_logs_by_category()
        except Exception:
            log_counts = {"candidate": 0, "exam": 0, "grading": 0, "assignment": 0, "system": 0}

        try:
            total_logs = int(count_operation_logs() or 0)
        except Exception:
            total_logs = 0
        total_log_pages = (total_logs + log_per_page - 1) // log_per_page
        total_log_pages = max(1, int(total_log_pages or 1))
        log_page = min(log_page, total_log_pages)

        log_offset = (log_page - 1) * log_per_page
        try:
            ops = list_operation_logs(limit=log_per_page, offset=log_offset)
        except Exception:
            ops = []

        chart_days: list[str] = []
        chart_counts: list[int] = []
        chart_range_start = ""
        chart_range_end = ""
        try:
            now_local = datetime.now().astimezone()
            local_tz = now_local.tzinfo
            today_local2 = now_local.date()

            start_day = _parse_date_ymd(chart_start_raw) if chart_start_raw else None
            end_day = _parse_date_ymd(chart_end_raw) if chart_end_raw else None

            # Default: last 30 days (inclusive), ending today (local).
            if end_day is None:
                end_day = today_local2
            if start_day is None:
                start_day = end_day - timedelta(days=29)

            # Guardrails: no future dates and reasonable span.
            if end_day > today_local2:
                end_day = today_local2
            if start_day > end_day:
                start_day = end_day - timedelta(days=29)
            max_span_days = 180
            if (end_day - start_day).days > max_span_days:
                start_day = end_day - timedelta(days=max_span_days)

            chart_range_start = start_day.isoformat() if start_day else ""
            chart_range_end = end_day.isoformat() if end_day else ""

            start_local_dt = datetime.combine(start_day, dt_time.min, tzinfo=local_tz)
            end_local_dt = datetime.combine(end_day, dt_time.max, tzinfo=local_tz)
            try:
                tz_offset_seconds = int((now_local.utcoffset() or timedelta(0)).total_seconds())
            except Exception:
                tz_offset_seconds = 0

            daily = list_operation_daily_counts(
                tz_offset_seconds=tz_offset_seconds,
                at_from=start_local_dt.astimezone(timezone.utc),
                at_to=end_local_dt.astimezone(timezone.utc),
            )
            m2: dict[str, int] = {}
            for r2 in daily or []:
                d = r2.get("day")
                cnt = r2.get("cnt")
                k = str(d)[:10]
                try:
                    m2[k] = int(cnt or 0)
                except Exception:
                    m2[k] = 0
            span = max(0, min(max_span_days, (end_day - start_day).days))
            for i in range(span + 1):
                d2 = start_day + timedelta(days=i)
                k2 = d2.isoformat()
                chart_days.append(k2)
                chart_counts.append(int(m2.get(k2, 0)))
        except Exception:
            chart_days = []
            chart_counts = []
            chart_range_start = ""
            chart_range_end = ""

        def _type_label(et: str) -> tuple[str, str]:
            if et.startswith("candidate."):
                return "candidate", "候选者操作"
            if et in {"assignment.create", "exam.enter", "exam.finish"}:
                return "assignment", "答题邀约"
            if et == "system.alert" or et.startswith("sms."):
                return "system", "系统"
            if et == "exam.grade":
                return "grading", "判卷操作"
            if et.startswith("exam."):
                return "exam", "试卷操作"
            return "assignment", "答题邀约"

        def _fmt_person(name: str | None, phone: str | None, cid: Any) -> str:
            n = str(name or "").strip()
            p = _normalize_phone(str(phone or "").strip())
            if n and p:
                return f"{n} {p}"
            if n:
                return n
            if p:
                return p
            try:
                return f"candidate_id={int(cid)}" if cid is not None else ""
            except Exception:
                return ""

        def _detail_text(it: dict[str, Any]) -> str:
            return _oplog_detail_text_v2(it)

        def _type_label_v2(et: str) -> tuple[str, str]:
            return _oplog_type_label_v2(et)

        def _detail_text_v2(it: dict[str, Any]) -> str:
            return _oplog_detail_text_v2(it)

        for it in ops:
            et = str(it.get("event_type") or "").strip()
            k, label = _type_label_v2(et)
            it["type_key"] = k
            it["type_label"] = label
            it["detail_text"] = _detail_text_v2(it)

        result = {
            "logs": ops,
            "log_page": log_page,
            "total_logs": total_logs,
            "total_log_pages": total_log_pages,
            "log_per_page": log_per_page,
            "log_counts": log_counts,
            "chart_days": chart_days,
            "chart_counts": chart_counts,
            "chart_range_start": chart_range_start,
            "chart_range_end": chart_range_end,
        }
        _set_cached_logs_context(cache_key, result)
        return result

    def _build_admin_status_context() -> dict[str, Any]:
        return {}

    @app.get("/admin")
    @admin_required
    def admin_dashboard():
        return redirect(url_for("admin_exams"))

    @app.get("/admin/exams")
    @admin_required
    def admin_exams():
        return render_template("admin_exams.html", **_build_admin_exams_context(request.args))

    @app.get("/admin/assignments")
    @admin_required
    def admin_assignments():
        return render_template("admin_assignments.html", **_build_assignment_attempts_context(request.args))

    @app.get("/admin/logs")
    @admin_required
    def admin_logs():
        return render_template("admin_logs.html", **_build_admin_logs_context(request.args))

    @app.get("/admin/status")
    @admin_required
    def admin_status():
        return render_template("admin_status.html", **_build_admin_status_context())

    @app.get("/admin/api/attempt-status")
    @admin_required
    def admin_attempt_status_api():
        tokens_raw = (request.args.get("tokens") or "").strip()
        tokens = [t.strip() for t in tokens_raw.split(",") if t.strip()]
        tokens = tokens[:50]

        def status_label(v: str) -> str:
            s = _normalize_exam_status(v)
            m = {
                "verified": "验证通过",
                "invited": "已邀约",
                "in_exam": "正在答题",
                "grading": "正在判卷",
                "finished": "判卷结束",
                "expired": "失效",
            }
            return m.get(s, "未知")

        def date_to_iso(v) -> str:
            if v is None:
                return ""
            if isinstance(v, date):
                return v.isoformat()
            return str(v).strip()

        today_local = datetime.now().astimezone().date()

        items: list[dict[str, Any]] = []
        for token in tokens:
            ep = get_exam_paper_by_token(token) or {}
            if not ep:
                continue

            status = _normalize_exam_status(ep.get("status"))
            entered_at = ep.get("entered_at")
            invite_end_date = date_to_iso(ep.get("invite_end_date"))

            if status in {"invited", "verified"} and not entered_at:
                ed = _parse_date_ymd(invite_end_date) if invite_end_date else None
                if ed is not None and today_local > ed:
                    status = "expired"

            items.append(
                {
                    "token": token,
                    "status": status,
                    "status_label": status_label(status),
                    "score": ep.get("score"),
                }
            )

        return jsonify({"items": items})

    @app.get("/admin/api/operation-logs/updates")
    @admin_required
    def admin_operation_logs_updates_api():
        try:
            after_id = int(request.args.get("after_id") or "0")
        except Exception:
            after_id = 0
        try:
            limit = int(request.args.get("limit") or "20")
        except Exception:
            limit = 20
        limit = max(1, min(50, limit))

        try:
            rows = list_operation_logs_after_id(after_id=after_id, limit=limit)
        except Exception:
            rows = []

        out: list[dict[str, Any]] = []
        for it in rows or []:
            et = str(it.get("event_type") or "").strip()
            k, label = _oplog_type_label_v2(et)
            it2 = dict(it)
            it2["type_key"] = k
            it2["type_label"] = label
            it2["detail_text"] = _oplog_detail_text_v2(it2)
            at = it2.get("at")
            at_str = ""
            try:
                if at:
                    at_str = at.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                at_str = ""
            out.append(
                {
                    "id": int(it2.get("id") or 0),
                    "at": at_str,
                    "type_key": str(it2.get("type_key") or "system"),
                    "type_label": str(it2.get("type_label") or ""),
                    "detail_text": str(it2.get("detail_text") or ""),
                }
            )

        # id ASC so the client can prepend in reverse order (keep "newest first" view).
        out.sort(key=lambda x: int(x.get("id") or 0))
        return jsonify({"ok": True, "items": out})
