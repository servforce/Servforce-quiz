from __future__ import annotations

from web.runtime_support import *
from web.runtime_setup import _ensure_exam_paper_for_token


def register_public_exam_routes(app: Flask) -> None:
    @app.get("/a/<token>")
    def public_exam_page_alias(token: str):
        # Backward-compat: old exam page entrypoint was "/a/<token>".
        return redirect(url_for("public_exam_page", token=token))

    @app.get("/exam/<token>")
    def public_exam_page(token: str):
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
            if (assignment.get("verify") or {}).get("locked"):
                abort(410)

            candidate_id = int(assignment["candidate_id"])
            c = get_candidate(candidate_id)
            if not c:
                return redirect(url_for("public_verify_page", token=token))

            ep = _ensure_exam_paper_for_token(token, assignment) or {}
            ep_status = str(ep.get("status") or "").strip()
            if ep_status not in {"verified", "in_exam", "grading", "finished"}:
                return redirect(url_for("public_verify_page", token=token))
            if ep_status in {"grading", "finished"} or assignment.get("grading"):
                return redirect(url_for("public_done", token=token))

            # Start countdown only when candidate enters exam page (and never reset on re-verify).
            timing = assignment.setdefault("timing", {})
            started_iso = timing.get("start_at")
            if not started_iso:
                now = datetime.now(timezone.utc)
                timing["start_at"] = now.isoformat()
                try:
                    set_exam_paper_entered_at(token, now)
                except Exception:
                    pass
                try:
                    ek2 = str(assignment.get("exam_key") or "").strip()
                    log_event(
                        "exam.enter",
                        actor="candidate",
                        candidate_id=int(candidate_id),
                        exam_key=(ek2 or None),
                        token=(token or None),
                        meta={
                            "name": str(c.get("name") or "").strip(),
                            "phone": str(c.get("phone") or "").strip(),
                            "public_invite": bool(assignment.get("public_invite")),
                        },
                    )
                except Exception:
                    pass
            # Public invite rule:
            # start_date = enter date (local), end_date = next day (local).
            # Fill only when invite_window is missing; keep existing values unchanged.
            try:
                if bool(assignment.get("public_invite")):
                    inv = assignment.get("invite_window") or {}
                    if not isinstance(inv, dict):
                        inv = {}
                    sd = str(inv.get("start_date") or "").strip()
                    ed = str(inv.get("end_date") or "").strip()
                    if not sd or not ed:
                        started_dt = _parse_iso_dt(str(timing.get("start_at") or "").strip() or None)
                        if started_dt is None:
                            started_dt = datetime.now(timezone.utc)
                        local_day = started_dt.astimezone().date()
                        sd2 = sd or local_day.isoformat()
                        ed2 = ed or (local_day + timedelta(days=1)).isoformat()
                        assignment["invite_window"] = {"start_date": sd2, "end_date": ed2}
                        try:
                            set_exam_paper_invite_window_if_missing(
                                token,
                                invite_start_date=sd2,
                                invite_end_date=ed2,
                            )
                        except Exception:
                            pass
            except Exception:
                pass
            # Transition status to "in_exam" once the candidate enters the exam page.
            try:
                if ep_status == "verified":
                    set_exam_paper_status(token, "in_exam")
            except Exception:
                pass
            try:
                if str(assignment.get("status") or "") not in {"in_exam", "grading", "graded"}:
                    now3 = datetime.now(timezone.utc)
                    assignment["status"] = "in_exam"
                    assignment["status_updated_at"] = now3.isoformat()
                    save_assignment(token, assignment)
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
            exam = get_exam_definition(exam_key) or {}
            public_spec = exam.get("public_spec") if isinstance(exam.get("public_spec"), dict) else None
            if not public_spec:
                abort(404)
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
            assignment = load_assignment(token)
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
            st, _sd, _ed = _invite_window_state(assignment)
            if st in {"not_started", "expired"}:
                return {"ok": False, "error": "invite_window_invalid"}, 403
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
            st, _sd, _ed = _invite_window_state(assignment)
            if st in {"not_started", "expired"}:
                return redirect(url_for("public_verify_page", token=token))
            _ensure_exam_paper_for_token(token, assignment)
        if (assignment.get("verify") or {}).get("locked"):
            abort(410)
        if assignment.get("grading"):
            try:
                g = assignment.get("grading") or {}
                if isinstance(g, dict) and str(g.get("status") or "") in {"pending", "running"}:
                    _start_background_grading(token)
            except Exception:
                pass
            _sync_exam_paper_finished_from_assignment(assignment)
            return redirect(url_for("public_done", token=token))

        now = datetime.now(timezone.utc)
        timing = assignment.setdefault("timing", {})
        started_at = _parse_iso_dt(timing.get("start_at"))
        if not started_at:
            started_at = now
            timing["start_at"] = now.isoformat()
            try:
                set_exam_paper_entered_at(token, started_at)
            except Exception:
                pass

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
                flash(f"未达到最短交卷时长，请至少答题 {mins} 分钟后再提交（还需约 {wait} 秒）。")
                with assignment_locked(token):
                    save_assignment(token, assignment)
                return redirect(url_for("public_exam_page", token=token))
        with assignment_locked(token):
            assignment = load_assignment(token)
            if assignment.get("grading"):
                return redirect(url_for("public_done", token=token))
            _finalize_public_submission(token, assignment, now=now)
        _start_background_grading(token)
        return redirect(url_for("public_done", token=token))

    @app.get("/done/<token>")
    def public_done(token: str):
        assignment = load_assignment(token)
        if assignment.get("grading"):
            try:
                g = assignment.get("grading") or {}
                if isinstance(g, dict) and str(g.get("status") or "") in {"pending", "running"}:
                    _start_background_grading(token)
            except Exception:
                pass
            _sync_exam_paper_finished_from_assignment(assignment)
        return render_template("public_done.html", assignment=assignment)
