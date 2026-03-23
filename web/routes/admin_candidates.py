from __future__ import annotations

from web.runtime_support import *


def register_admin_candidate_routes(app: Flask) -> None:
    @app.get("/admin/candidates")
    @admin_required
    def admin_candidates():
        q = (request.args.get("q") or "").strip()
        created_from_raw = (request.args.get("created_from") or "").strip()
        created_to_raw = (request.args.get("created_to") or "").strip()

        if not created_to_raw:
            created_to_raw = datetime.now().date().isoformat()
        if not created_from_raw:
            created_from_raw = (datetime.now().date() - timedelta(days=29)).isoformat()

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

        per_page = 20

        try:
            page = int(request.args.get("page") or "1")
        except Exception:
            page = 1
        page = max(1, page)
        per_page = 20
        try:
            total = count_candidates(
                query=q or None,
                created_from=created_from,
                created_to=created_to,
            )
        except Exception:
            total = 0
        total_pages = (total + per_page - 1) // per_page
        if total_pages > 0:
            page = min(page, total_pages)
        else:
            page = 1

        start = (page - 1) * per_page
        end = start + per_page
        try:
            candidates = list_candidates(
                limit=per_page,
                offset=start,
                query=q or None,
                created_from=created_from,
                created_to=created_to,
            )
        except Exception:
            candidates = []

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

        try:
            log_event(
                "candidate.read",
                actor="admin",
                candidate_id=int(candidate_id),
                meta={
                    "path": request.path,
                    "name": str(c.get("name") or "").strip(),
                    "phone": str(c.get("phone") or "").strip(),
                },
            )
        except Exception:
            pass

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
        highest_rank = _degree_rank(highest)
        edu_show: list[dict] = []
        for e in edu_list:
            d = str(e.get("degree") or "").strip()
            r = _degree_rank(d)
            if highest_rank > 0:
                #
                if r > 0 and r <= highest_rank:
                    edu_show.append(e)
            else:
                edu_show.append(e)

        if not edu_show:
            edu_show = list(edu_list)

        edu_show.sort(
            key=lambda x: (
                _degree_rank(str(x.get("degree") or "")),
                str(x.get("start") or ""),
                str(x.get("end") or ""),
            )
        )
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

        # Prefer displaying experience blocks that preserve resume paragraphs (LLM-provided),
        # otherwise fallback to heuristic raw blocks.
        llm_blocks = details_data.get("experience_blocks") or []
        if isinstance(llm_blocks, list) and any(isinstance(x, dict) for x in llm_blocks):
            experience_blocks = [x for x in llm_blocks if isinstance(x, dict)]
        else:
            experience_blocks = projects_raw_blocks
        # De-dupe blocks caused by merging head fallback + section extraction.
        uniq_blocks: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for b in experience_blocks or []:
            if not isinstance(b, dict):
                continue
            title = str(b.get("title") or "").strip()
            period = str(b.get("period") or "").strip()
            body = str(b.get("body") or "").strip()
            sig = (title, period, body[:120])
            if not title and not body:
                continue
            if sig in seen:
                continue
            seen.add(sig)
            uniq_blocks.append(b)
        experience_blocks = uniq_blocks

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

        def _iso_to_local_str(v: str) -> str:
            s = str(v or "").strip()
            if not s:
                return ""
            try:
                s2 = s.replace("Z", "+00:00")
                return datetime.fromisoformat(s2).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return s

        if phone:
            rows_db = list_exam_archives_for_phone(phone)
            best_by_key: dict[str, dict[str, object]] = {}
            for row_db in rows_db:
                a = row_db.get("archive") if isinstance(row_db, dict) else None
                if not isinstance(a, dict):
                    continue
                token = str(a.get("token") or "").strip()
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
                exam_name = title or exam_key or "未知试卷"

                sort_key = 0.0
                try:
                    sort_key = datetime.fromisoformat(end_at.replace("Z", "+00:00")).timestamp()
                except Exception:
                    try:
                        updated_at = row_db.get("updated_at")
                        sort_key = float(updated_at.timestamp()) if updated_at else 0.0
                    except Exception:
                        sort_key = 0.0

                # De-dup: multiple archive files may exist for the same token (e.g. refresh /done triggers re-archive).
                # Keep the latest one per token+exam_key.
                key = f"{token}::{exam_key}" if token else str(row_db.get("archive_name") or "")
                cur = best_by_key.get(key)
                if cur is None or float(sort_key) >= float(cur.get("_sort_key") or 0.0):
                    best_by_key[key] = {
                        "exam_name": exam_name,
                        "score": str(score),
                        "start_at": start_at,
                        "end_at": end_at,
                        "_sort_key": sort_key,
                        "_archive_name": str(row_db.get("archive_name") or ""),
                    }

            rows = list(best_by_key.values())
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
            experience_blocks=experience_blocks,
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
            flash("操作失败，请稍后重试")
            return redirect(
                url_for("admin_candidate_profile", candidate_id=candidate_id, _anchor="evaluations")
            )

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
            flash("操作失败，请稍后重试")
            return redirect(
                url_for("admin_candidate_profile", candidate_id=candidate_id, _anchor="evaluations")
            )

        flash("保存成功")
        return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id, _anchor="evaluations"))

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
            elif mime.startswith("image/"):
                ext = ".png"
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
        if not (file and getattr(file, "filename", "")):
            flash("请先上传新的简历")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))
        try:
            data = file.read() or b""
        except Exception:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))
        filename = str(file.filename or "")
        mime = str(getattr(file, "mimetype", "") or "")

        if len(data) > 10 * 1024 * 1024:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

        ext = os.path.splitext(filename)[1].lower()
        if ext not in _ALLOWED_RESUME_EXTS:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

        try:
            text = extract_resume_text(data, filename)
        except Exception as e:
            logger.exception("Resume extract failed")
            flash(f"简历解析失败：{type(e).__name__}({e})")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

        resume_llm_total_tokens = 0

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
                with audit_context(meta={}):
                    ident = parse_resume_identity_llm(text or "") or {}
                    parsed_name = str(ident.get("name") or "").strip()
                    parsed_phone = _normalize_phone(str(ident.get("phone") or "").strip())
                    conf2 = ident.get("confidence") or {}
                    phone_conf = _safe_int((conf2.get("phone") if isinstance(conf2, dict) else 0) or 0, 0)
                    name_conf = _safe_int((conf2.get("name") if isinstance(conf2, dict) else 0) or 0, 0)
                    method["identity"] = "llm"
                    method["name"] = "llm"
                    try:
                        ctx = get_audit_context()
                        m = ctx.get("meta")
                        if isinstance(m, dict):
                            resume_llm_total_tokens += int(m.get("llm_total_tokens_sum") or 0)
                    except Exception:
                        pass
            except Exception:
                pass

        # If we have phone but name is missing, do a small LLM call to fill name.
        if _is_valid_phone(parsed_phone) and not _is_valid_name(parsed_name):
            try:
                with audit_context(meta={}):
                    nm = parse_resume_name_llm(text or "") or {}
                    n2 = str(nm.get("name") or "").strip()
                    n2_conf = _safe_int(nm.get("confidence") or 0, 0)
                    if _is_valid_name(n2):
                        parsed_name = n2
                        name_conf = max(_safe_int(name_conf, 0), _safe_int(n2_conf, 0))
                        method["name"] = "llm"
                    try:
                        ctx = get_audit_context()
                        m = ctx.get("meta")
                        if isinstance(m, dict):
                            resume_llm_total_tokens += int(m.get("llm_total_tokens_sum") or 0)
                    except Exception:
                        pass
            except Exception:
                pass

        phone_conf = max(0, min(100, _safe_int(phone_conf, 0)))
        name_conf = max(0, min(100, _safe_int(name_conf, 0)))

        try:
            current_phone = _normalize_phone(str(c.get("phone") or ""))
        except Exception:
            current_phone = ""
        if _is_valid_phone(parsed_phone) and current_phone and parsed_phone != current_phone:
            flash("操作失败，请稍后重试")
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
            logger.exception("Resume details parse failed (cid=%s)", candidate_id)
            details_error = f"{type(e).__name__}: {e}"

        try:
            experience_raw = extract_experience_raw(text or "", max_chars=20000)
            if experience_raw:
                details["projects_raw"] = _clean_projects_raw(experience_raw)
        except Exception:
            pass

        details_status = "failed" if details_error else ("done" if details else "empty")
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
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

        try:
            log_event(
                "candidate.resume.parse",
                actor="admin",
                candidate_id=int(candidate_id),
                llm_total_tokens=(int(resume_llm_total_tokens or 0) or None),
                meta={"reparse": True},
            )
        except Exception:
            pass
        flash("重新解析成功")
        return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

    #
    @app.post("/admin/candidates")
    @admin_required
    def admin_candidates_create():
        name = (request.form.get("name") or "").strip()
        phone = _normalize_phone(request.form.get("phone") or "")
        if not name or not phone:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))
        if not _is_valid_name(name):
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))
        if not _is_valid_phone(phone):
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))

        existed = get_candidate_by_phone(phone)
        if existed:
            flash("候选人已创建，请勿重复创建")
            return redirect(url_for("admin_candidates"))

        try:
            cid = create_candidate(name=name, phone=phone)
            try:
                log_event("candidate.create", actor="admin", candidate_id=int(cid), meta={"name": name, "phone": phone})
            except Exception:
                pass
        except Exception:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))
        flash("候选人创建成功")
        return redirect(url_for("admin_candidates"))

    @app.post("/admin/candidates/quick-create")
    @admin_required
    def admin_candidates_quick_create():
        name = (request.form.get("name") or "").strip()
        phone_input = (request.form.get("phone") or "").strip()
        phone = _normalize_phone(phone_input)
        file = request.files.get("file")

        has_file = bool(file and getattr(file, "filename", ""))
        has_name_phone = bool(name and phone_input)

        # Resume-only creation reuses the existing resume upload flow.
        if has_file and not has_name_phone:
            return admin_candidates_resume_upload()

        # Name + phone creation without resume reuses the existing manual create flow.
        if not has_file:
            return admin_candidates_create()

        if not name or not phone:
            flash("请填写姓名和手机号，或仅上传简历")
            return redirect(url_for("admin_candidates"))
        if not _is_valid_name(name):
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))
        if not _is_valid_phone(phone):
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))

        existed = get_candidate_by_phone(phone)
        if existed:
            flash("候选人已创建，请勿重复创建")
            return redirect(url_for("admin_candidates"))

        try:
            data = file.read() or b""
        except Exception:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))

        if len(data) > 10 * 1024 * 1024:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))

        filename = str(file.filename or "")
        ext = os.path.splitext(filename)[1].lower()
        if ext not in _ALLOWED_RESUME_EXTS:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))

        mime = str(getattr(file, "mimetype", "") or "")

        try:
            cid = create_candidate(name=name, phone=phone)
        except Exception:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))

        resume_meta: dict[str, Any] = {
            "source_filename": filename,
            "source_mime": mime,
            "method": {"quick_create": "manual_with_resume"},
            "details": {"status": "pending"},
        }

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
            logger.exception("Quick create candidate resume save failed (cid=%s)", cid)
            flash("候选人已创建，但简历保存失败")
            return redirect(url_for("admin_candidates"))

        try:
            log_event(
                "candidate.create",
                actor="admin",
                candidate_id=int(cid),
                meta={"name": name, "phone": phone, "with_resume": True},
            )
        except Exception:
            pass
        flash("候选人创建成功")
        return redirect(url_for("admin_candidates"))

    @app.post("/admin/candidates/resume/upload")
    @admin_required
    def admin_candidates_resume_upload():
        file = request.files.get("file")
        if not file or not getattr(file, "filename", ""):
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))

        try:
            data = file.read() or b""
        except Exception:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))

        if len(data) > 10 * 1024 * 1024:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))

        filename = str(file.filename or "")
        ext = os.path.splitext(filename)[1].lower()
        if ext not in _ALLOWED_RESUME_EXTS:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))

        try:
            text = extract_resume_text(data, filename)
        except ValueError:
            flash("操作失败，请稍后重试")
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

        resume_llm_total_tokens = 0
        with audit_context(meta={}):
            parsed_name, phone, name_conf, phone_conf, method = _parse_identity(text or "")
            try:
                ctx = get_audit_context()
                m = ctx.get("meta")
                if isinstance(m, dict):
                    resume_llm_total_tokens += int(m.get("llm_total_tokens_sum") or 0)
            except Exception:
                pass

        if not _is_valid_phone(phone):
            flash("操作失败，请稍后重试")
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
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))

        # Parse full details synchronously so profile page doesn't need to wait.
        details: dict[str, Any] = {}
        details_error = ""
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
            logger.exception("Resume details parse failed (cid=%s)", cid)
            details_error = f"{type(e).__name__}: {e}"

        try:
            experience_raw = extract_experience_raw(text or "", max_chars=20000)
            if experience_raw:
                details["projects_raw"] = _clean_projects_raw(experience_raw)
        except Exception:
            pass

        details_status = "failed" if details_error else ("done" if details else "empty")
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

        try:
            log_event(
                "candidate.resume.parse",
                actor="admin",
                candidate_id=int(cid),
                llm_total_tokens=(int(resume_llm_total_tokens or 0) or None),
            )
        except Exception:
            pass
        if created:
            try:
                log_event("candidate.create", actor="admin", candidate_id=int(cid), meta={"name": name, "phone": phone})
            except Exception:
                pass

        return redirect(url_for("admin_candidates"))

    #
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
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))
        p = _find_latest_archive(c)
        if not p:
            flash("候选者未提交答卷")
            return redirect(url_for("admin_assignments"))
        archive = p.get("archive") if isinstance(p, dict) else None
        if not isinstance(archive, dict):
            flash("答题归档读取失败")
            return redirect(url_for("admin_candidates"))
        try:
            archive = _augment_archive_with_spec(archive)
        except Exception:
            pass
        try:
            ek = str(((archive or {}).get("exam") or {}).get("exam_key") or "").strip()
            tok = str((archive or {}).get("token") or "").strip()
            log_event(
                "exam.result",
                actor="admin",
                candidate_id=int(candidate_id),
                exam_key=(ek or None),
                token=(tok or None),
                meta={"name": str(c.get("name") or "").strip(), "phone": str(c.get("phone") or "").strip()},
            )
        except Exception:
            pass
        return render_template("admin_candidate_attempt.html", archive=archive)

    @app.get("/admin/candidates/<int:candidate_id>/attempts/<path:archive_name>")
    @admin_required
    def admin_candidate_attempt_by_archive(candidate_id: int, archive_name: str):
        c = get_candidate(candidate_id)
        if not c:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))

        phone = str(c.get("phone") or "").strip()
        name = os.path.basename(str(archive_name or "").strip())
        if not name or name != archive_name or "/" in name or "\\" in name:
            abort(404)
        if not phone or f"_{phone}_" not in name:
            abort(404)

        row = get_exam_archive_by_name(name)
        if not row:
            abort(404)
        archive = row.get("archive") if isinstance(row, dict) else None
        if not isinstance(archive, dict):
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
        try:
            ek = str(((archive or {}).get("exam") or {}).get("exam_key") or "").strip()
            tok = str((archive or {}).get("token") or "").strip()
            log_event(
                "exam.result",
                actor="admin",
                candidate_id=int(candidate_id),
                exam_key=(ek or None),
                token=(tok or None),
                meta={"name": str(c.get("name") or "").strip(), "phone": str(c.get("phone") or "").strip()},
            )
        except Exception:
            pass
        return render_template("admin_candidate_attempt.html", archive=archive)

    #
    @app.post("/admin/candidates/<int:candidate_id>/edit")
    @admin_required
    def admin_candidates_edit_post(candidate_id: int):
        # Deprecated: inline editing is now done on the profile page.
        return redirect(url_for("admin_candidate_profile", candidate_id=candidate_id))

    #
    @app.post("/admin/candidates/<int:candidate_id>/delete")
    @admin_required
    def admin_candidates_delete(candidate_id: int):
        c = get_candidate(candidate_id)
        if not c:
            flash("操作失败，请稍后重试")
            return redirect(url_for("admin_candidates"))
        try:
            delete_candidate(candidate_id)
            try:
                log_event(
                    "candidate.delete",
                    actor="admin",
                    candidate_id=int(candidate_id),
                    meta={"name": str(c.get("name") or "").strip(), "phone": str(c.get("phone") or "").strip()},
                )
            except Exception:
                pass
        except Exception:
            flash("删除失败")
            return redirect(url_for("admin_candidates"))
        flash("删除成功")
        return redirect(url_for("admin_candidates"))
