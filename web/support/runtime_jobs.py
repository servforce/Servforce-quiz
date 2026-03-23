from __future__ import annotations

from web.support.deps import *
from web.support.validation import *
from web.support.exams import *

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
    try:
        _start_background_grading(token)
    except Exception:
        pass
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
    Finalize a candidate submission by marking it submitted and scheduling background grading.

    Caller is responsible for locking (assignment_locked) if needed.
    """
    if assignment.get("grading"):
        return

    assignment.setdefault("timing", {})["end_at"] = now.isoformat()
    assignment["status"] = "grading"
    assignment["status_updated_at"] = now.isoformat()
    assignment["grading_started_at"] = assignment.get("grading_started_at") or now.isoformat()
    assignment["graded_at"] = None
    assignment["grading_error"] = None
    assignment["grading"] = {"status": "pending", "queued_at": now.isoformat()}
    save_assignment(token, assignment)

    duration_seconds = _duration_seconds(assignment)
    timing = assignment.get("timing") or {}
    started_at = _parse_iso_dt(timing.get("start_at"))
    submitted_at = _parse_iso_dt(timing.get("end_at"))
    try:
        update_exam_paper_result(
            token,
            status="grading",
            score=None,
            entered_at=started_at,
            finished_at=submitted_at,
        )
    except Exception:
        logger.exception("Update exam_paper grading state failed (token=%s)", token)

    try:
        cid2 = int(assignment.get("candidate_id") or 0)
    except Exception:
        cid2 = 0
    try:
        ek2 = str(assignment.get("exam_key") or "").strip()
    except Exception:
        ek2 = ""
    name2 = ""
    phone2 = ""
    if cid2 > 0:
        try:
            c2 = get_candidate(cid2) or {}
            name2 = str(c2.get("name") or "").strip()
            phone2 = str(c2.get("phone") or "").strip()
        except Exception:
            name2 = ""
            phone2 = ""
    if not phone2:
        try:
            sms2 = assignment.get("sms_verify") or {}
            if isinstance(sms2, dict):
                phone2 = str(sms2.get("phone") or "").strip()
        except Exception:
            pass
    try:
        log_event(
            "exam.finish",
            actor="candidate",
            candidate_id=(cid2 if cid2 > 0 else None),
            exam_key=(ek2 or None),
            token=(str(token or "").strip() or None),
            meta={
                "name": name2,
                "phone": phone2,
                "public_invite": bool(assignment.get("public_invite")),
            },
        )
    except Exception:
        pass


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


_GRADING_THREADS_GUARD = threading.Lock()
_GRADING_RUNNING: set[str] = set()


def _start_background_grading(token: str) -> None:
    t = str(token or "").strip()
    if not t:
        return
    with _GRADING_THREADS_GUARD:
        if t in _GRADING_RUNNING:
            return
        _GRADING_RUNNING.add(t)

    def _runner() -> None:
        try:
            _grade_assignment_background(t)
        finally:
            with _GRADING_THREADS_GUARD:
                _GRADING_RUNNING.discard(t)

    th = threading.Thread(target=_runner, name=f"grading:{t}", daemon=True)
    th.start()


def _grade_assignment_background(token: str) -> None:
    """
    Background grading job: call LLM-based grading and persist results.
    Safe to call multiple times; it will no-op if already graded.
    """
    # Mark as running and capture a stable snapshot.
    with assignment_locked(token):
        assignment = load_assignment(token)
        grading0 = assignment.get("grading") or {}
        if isinstance(grading0, dict) and str(grading0.get("status") or "").strip() == "done":
            return
        if isinstance(grading0, dict) and str(grading0.get("status") or "").strip() == "running":
            return
        now = datetime.now(timezone.utc)
        assignment["grading"] = {"status": "running", "started_at": now.isoformat()}
        assignment["status"] = "grading"
        assignment["status_updated_at"] = now.isoformat()
        assignment["grading_started_at"] = assignment.get("grading_started_at") or now.isoformat()
        assignment["grading_error"] = None
        save_assignment(token, assignment)
        snapshot = dict(assignment)

    grading_llm_total_tokens = 0
    try:
        exam = get_exam_definition(str(snapshot.get("exam_key") or "").strip()) or {}
        spec = exam.get("spec") if isinstance(exam.get("spec"), dict) else {}
        if not spec:
            raise FileNotFoundError(str(snapshot.get("exam_key") or ""))
        with audit_context(meta={}):
            grading = grade_attempt(spec, snapshot)
            if isinstance(grading, dict):
                grading["status"] = "done"
            remark = generate_candidate_remark(spec, snapshot, grading) if grading else ""
            try:
                ctx = get_audit_context()
                m = ctx.get("meta")
                if isinstance(m, dict):
                    grading_llm_total_tokens = int(m.get("llm_total_tokens_sum") or 0)
            except Exception:
                grading_llm_total_tokens = 0
    except Exception as e:
        logger.exception("Background grading failed (token=%s)", token)
        with assignment_locked(token):
            assignment = load_assignment(token)
            assignment["grading"] = {"status": "failed"}
            assignment["grading_error"] = f"{type(e).__name__}: {e}"
            assignment["status"] = "grading"
            assignment["status_updated_at"] = datetime.now(timezone.utc).isoformat()
            save_assignment(token, assignment)
        return

    # Persist grading.
    with assignment_locked(token):
        assignment = load_assignment(token)
        grading0 = assignment.get("grading") or {}
        if isinstance(grading0, dict) and str(grading0.get("status") or "").strip() == "done":
            return
        now2 = datetime.now(timezone.utc)
        assignment["grading"] = grading
        assignment["candidate_remark"] = remark
        assignment["graded_at"] = now2.isoformat()
        assignment["status"] = "graded"
        assignment["status_updated_at"] = now2.isoformat()
        save_assignment(token, assignment)

    # Sync candidate DB row + archive.
    try:
        duration_seconds = _duration_seconds(assignment)
        timing = assignment.get("timing") or {}
        started_at = _parse_iso_dt(timing.get("start_at"))
        submitted_at = _parse_iso_dt(timing.get("end_at"))
        update_exam_paper_result(
            token,
            status="finished",
            score=int((grading or {}).get("total") or 0),
            entered_at=started_at,
            finished_at=submitted_at,
        )
    except Exception:
        logger.exception("Update exam_paper graded result failed (token=%s)", token)
    try:
        cid2 = int((assignment or {}).get("candidate_id") or 0)
    except Exception:
        cid2 = 0
    try:
        ek2 = str((assignment or {}).get("exam_key") or "").strip()
    except Exception:
        ek2 = ""
    try:
        score2 = int((grading or {}).get("total") or 0)
    except Exception:
        score2 = 0
    try:
        log_event(
            "exam.grade",
            actor="system",
            candidate_id=(cid2 if cid2 > 0 else None),
            exam_key=(ek2 or None),
            token=(str(token or "").strip() or None),
            llm_total_tokens=(int(grading_llm_total_tokens or 0) or None),
            meta={"score": score2, "public_invite": bool((assignment or {}).get("public_invite"))},
        )
    except Exception:
        pass
    try:
        _archive_candidate_attempt(assignment, spec=spec)
    except Exception:
        logger.exception("Archive candidate attempt failed (token=%s)", token)


def _auto_collect_loop(*, interval_seconds: int = 15) -> None:
    """
    Background loop: once countdown starts (timing.start_at is set), auto-submit when time is up,
    even if the candidate is not actively on the page.
    """
    while True:
        try:
            for token in list_assignment_tokens():
                try:
                    with assignment_locked(token):
                        assignment = load_assignment(token)
                        g = assignment.get("grading")
                        if isinstance(g, dict) and str(g.get("status") or "").strip() in {"pending", "running"}:
                            # Ensure grading proceeds even after process restarts.
                            try:
                                _start_background_grading(token)
                            except Exception:
                                pass
                            continue
                        if g:
                            continue
                        _finalize_if_time_up(token, assignment)
                except Exception:
                    logger.exception("Auto-collect scan failed (token=%s)", token)
        except Exception:
            logger.exception("Auto-collect loop failed")
        time_module.sleep(interval_seconds)


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


def _stable_archive_filename(phone: str, token: str, exam_key: str) -> str:
    phone_part = _sanitize_archive_part(str(phone or ""))
    token_part = _sanitize_archive_part(str(token or ""))
    exam_part = _sanitize_archive_part(str(exam_key or ""))

    # Stable per token: one attempt -> one archive file (overwrite on re-save).
    # Must keep suffix compatible with existing glob patterns: *_{phone}_*_{exam_key}.json
    suffix_parts = [p for p in (phone_part, token_part, exam_part) if p]
    suffix = "_".join(suffix_parts) or "attempt"
    raw = f"latest_{suffix}".strip("._")
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
    exam = get_exam_definition(str(exam_key or "").strip()) or {}
    public_spec = exam.get("public_spec")
    return public_spec if isinstance(public_spec, dict) else None


def _redact_spec_for_archive(spec: dict) -> dict:
    # 当公开试卷对象缺失时，回退到完整试卷并去掉标准答案。
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
        exam = get_exam_definition(exam_key) or {}
        spec = exam.get("spec") if isinstance(exam.get("spec"), dict) else {}
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

    now_iso = datetime.now(timezone.utc).isoformat()
    token = str(assignment.get("token") or "").strip()
    archive = {
        "saved_at": now_iso,
        "token": token,
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

    filename = _stable_archive_filename(str(c.get("phone") or ""), token, exam_key)
    save_exam_archive(
        archive_name=filename,
        token=token,
        candidate_id=int(candidate_id),
        exam_key=exam_key,
        phone=str(c.get("phone") or ""),
        archive=archive,
    )


def _find_latest_archive(candidate: dict) -> dict[str, Any] | None:
    try:
        phone = str(candidate.get("phone") or "").strip()
    except Exception:
        return None
    if not phone:
        return None
    rows = list_exam_archives_for_phone(phone)
    return rows[0] if rows else None


def _find_archive_by_token(token: str, *, assignment: dict | None = None) -> dict[str, Any] | None:
    row = get_exam_archive_by_token(str(token or "").strip())
    if row:
        return row
    if not assignment:
        return None
    try:
        candidate_id = int(assignment.get("candidate_id") or 0)
    except Exception:
        candidate_id = 0
    if candidate_id <= 0:
        return None
    c = get_candidate(candidate_id) or {}
    phone = str(c.get("phone") or "").strip()
    if not phone:
        return None
    rows = list_exam_archives_for_phone(phone)
    return rows[0] if rows else None


def _augment_archive_with_spec(archive: dict) -> dict:
    """
    尽力用当前试卷定义补全归档里的标签、rubric 和标准答案信息。
    """
    try:
        exam_key = str(((archive.get("exam") or {}).get("exam_key")) or "").strip()
    except Exception:
        exam_key = ""
    if not exam_key:
        return archive
    exam = get_exam_definition(exam_key) or {}
    spec = exam.get("spec")
    if not isinstance(spec, dict):
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


def _sync_exam_paper_finished_from_assignment(assignment: dict) -> None:
    token = str(assignment.get("token") or "").strip()
    if not token:
        return
    grading = assignment.get("grading") or {}
    if not grading:
        return
    if isinstance(grading, dict) and str(grading.get("status") or "").strip() in {"pending", "running"}:
        return
    if not isinstance(grading, dict) or ("total" not in grading):
        return

    timing = assignment.get("timing") or {}
    started_at = _parse_iso_dt(timing.get("start_at"))
    submitted_at = _parse_iso_dt(timing.get("end_at"))
    duration_seconds = _duration_seconds(assignment)
    try:
        try:
            _archive_candidate_attempt(assignment)
        except Exception:
            logger.exception("Archive candidate attempt failed (token=%s)", token)
        update_exam_paper_result(
            token,
            status="finished",
            score=int(grading.get("total") or 0),
            entered_at=started_at,
            finished_at=submitted_at,
        )
    except Exception:
        logger.exception("Sync exam_paper finished failed (token=%s)", token)
        return

__all__ = [name for name in globals() if not name.startswith("__")]
