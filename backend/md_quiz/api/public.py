from __future__ import annotations

import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.md_quiz.config import load_runtime_defaults
from backend.md_quiz.services import exam_helpers, runtime_bootstrap, runtime_jobs, support_deps as deps
from backend.md_quiz.services import validation_helpers

router = APIRouter(prefix="/api/public", tags=["public"])


class SmsSendPayload(BaseModel):
    token: str
    name: str
    phone: str


class VerifyPayload(BaseModel):
    token: str
    name: str
    phone: str
    sms_code: str = ""


class InviteEnsurePayload(BaseModel):
    public_token: str | None = None


def _public_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _compute_exam_stats(spec: dict[str, Any]) -> dict[str, Any]:
    questions = list(spec.get("questions") or [])
    counts_by_type: dict[str, int] = {}
    total_points = 0
    for question in questions:
        qtype = str(question.get("type") or "").strip() or "unknown"
        counts_by_type[qtype] = int(counts_by_type.get(qtype, 0)) + 1
        try:
            total_points += int(question.get("max_points") or 0)
        except Exception:
            continue
    return {
        "total_questions": len(questions),
        "total_points": total_points,
        "counts_by_type": counts_by_type,
    }


def _invite_window_payload(start_date: Any, end_date: Any) -> dict[str, str]:
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value or "").strip()

    return {"start_date": _stringify(start_date), "end_date": _stringify(end_date)}


def _bootstrap_attempt(token: str) -> dict[str, Any]:
    token = str(token or "").strip()
    if not token:
        raise HTTPException(status_code=404, detail="token 不存在")

    with deps.assignment_locked(token):
        assignment = deps.load_assignment(token)
        if assignment.get("grading"):
            try:
                grading = assignment.get("grading") or {}
                if isinstance(grading, dict) and str(grading.get("status") or "") in {"pending", "running"}:
                    runtime_jobs._start_background_grading(token)
            except Exception:
                pass
            runtime_jobs._sync_exam_paper_finished_from_assignment(assignment)
        else:
            runtime_jobs._finalize_if_time_up(token, assignment)
        assignment = deps.load_assignment(token)
        runtime_bootstrap._ensure_exam_paper_for_token(token, assignment)

    invite_state, start_date, end_date = exam_helpers._invite_window_state(assignment)
    verify = assignment.get("verify") or {}
    if not isinstance(verify, dict):
        verify = {}
    sms = assignment.get("sms_verify") or {}
    if not isinstance(sms, dict):
        sms = {}
    pending_profile = assignment.get("pending_profile") or {}
    if not isinstance(pending_profile, dict):
        pending_profile = {}
    status_text = str(assignment.get("status") or "").strip()

    try:
        candidate_id = int(assignment.get("candidate_id") or 0)
    except Exception:
        candidate_id = 0

    if invite_state == "not_started":
        return {
            "token": token,
            "step": "unavailable",
            "assignment": assignment,
            "invite_window": _invite_window_payload(start_date, end_date),
            "unavailable": {
                "title": "未到答题时间",
                "message": "当前未到答题时间，请在有效时间范围内进入答题。",
            },
        }

    if status_text == "expired" or (
        invite_state == "expired"
        and not str(((assignment.get("timing") or {}).get("start_at") or "")).strip()
    ):
        return {
            "token": token,
            "step": "unavailable",
            "assignment": assignment,
            "invite_window": _invite_window_payload(start_date, end_date),
            "unavailable": {
                "title": "邀约已失效",
                "message": "当前答题链接已失效，请联系管理员重新生成新的邀请链接。",
            },
        }

    if verify.get("locked"):
        return {
            "token": token,
            "step": "verify",
            "assignment": assignment,
            "invite_window": _invite_window_payload(start_date, end_date),
            "verify": {
                "locked": True,
                "attempts": int(verify.get("attempts") or 0),
                "max_attempts": int(assignment.get("verify_max_attempts") or 3),
                "sms_verified": bool(sms.get("verified")),
            },
        }

    grading = assignment.get("grading") or {}
    if grading or status_text in {"grading", "graded"}:
        if isinstance(grading, dict) and str(grading.get("status") or "") in {"pending", "running"}:
            try:
                runtime_jobs._start_background_grading(token)
            except Exception:
                pass
        runtime_jobs._sync_exam_paper_finished_from_assignment(assignment)
        return {
            "token": token,
            "step": "done",
            "assignment": assignment,
            "invite_window": _invite_window_payload(start_date, end_date),
            "result": {
                "grading": grading,
                "candidate_remark": assignment.get("candidate_remark"),
                "graded_at": assignment.get("graded_at"),
                "status": str((grading or {}).get("status") or "").strip(),
                "total_score": (grading or {}).get("total"),
            },
        }

    if not bool(sms.get("verified")):
        return {
            "token": token,
            "step": "verify",
            "assignment": assignment,
            "invite_window": _invite_window_payload(start_date, end_date),
            "verify": {
                "locked": False,
                "attempts": int(verify.get("attempts") or 0),
                "max_attempts": int(assignment.get("verify_max_attempts") or 3),
                "sms_verified": False,
                "name": str(pending_profile.get("name") or ""),
                "phone": str(sms.get("phone") or pending_profile.get("phone") or ""),
            },
        }

    if candidate_id <= 0:
        return {
            "token": token,
            "step": "resume",
            "assignment": assignment,
            "invite_window": _invite_window_payload(start_date, end_date),
            "resume": {
                "name": str(pending_profile.get("name") or "候选人").strip() or "候选人",
                "phone": validation_helpers._normalize_phone(
                    str(pending_profile.get("phone") or sms.get("phone") or "").strip()
                ),
            },
        }

    exam_snapshot = exam_helpers.get_exam_snapshot_for_assignment(assignment) or {}
    public_spec = exam_snapshot.get("public_spec") if isinstance(exam_snapshot.get("public_spec"), dict) else {}
    if not public_spec:
        raise HTTPException(status_code=404, detail="试卷不存在")
    public_spec = exam_helpers.build_render_ready_public_spec(public_spec)
    quiz_metadata = exam_helpers.build_quiz_metadata(public_spec)

    time_limit_seconds = int(assignment.get("time_limit_seconds") or 0)
    min_submit_seconds = deps.compute_min_submit_seconds(
        time_limit_seconds,
        assignment.get("min_submit_seconds"),
    )
    if int(assignment.get("min_submit_seconds") or 0) != min_submit_seconds:
        with deps.assignment_locked(token):
            assignment = deps.load_assignment(token)
            assignment["min_submit_seconds"] = int(min_submit_seconds)
            deps.save_assignment(token, assignment)

    current_step = "exam"
    return {
        "token": token,
        "step": current_step,
        "assignment": assignment,
        "invite_window": _invite_window_payload(start_date, end_date),
        "exam": {
            "exam_key": str(assignment.get("exam_key") or "").strip(),
            "title": str(public_spec.get("title") or "").strip(),
            "description": str(public_spec.get("description") or "").strip(),
            "tags": list(quiz_metadata["tags"]),
            "schema_version": quiz_metadata["schema_version"],
            "format": str(quiz_metadata["format"] or "").strip(),
            "question_count": int(quiz_metadata["question_count"]),
            "question_counts": dict(quiz_metadata["question_counts"]),
            "estimated_duration_minutes": int(quiz_metadata["estimated_duration_minutes"]),
            "trait": dict(quiz_metadata["trait"]),
            "spec": public_spec,
            "stats": _compute_exam_stats(public_spec),
            "remaining_seconds": runtime_jobs._remaining_seconds(assignment),
            "time_limit_seconds": time_limit_seconds,
            "min_submit_seconds": min_submit_seconds,
            "answers": assignment.get("answers") or {},
            "entered_at": str(((assignment.get("timing") or {}).get("start_at") or "")).strip(),
        },
    }


def _public_runtime_config() -> dict[str, Any]:
    defaults = load_runtime_defaults()
    payload = {
        "sms_enabled": bool(defaults.sms_enabled),
        "token_daily_threshold": int(defaults.token_daily_threshold),
        "sms_daily_threshold": int(defaults.sms_daily_threshold),
        "allow_public_assignments": bool(defaults.allow_public_assignments),
        "min_submit_seconds": int(defaults.min_submit_seconds),
        "ui_theme_name": str(defaults.ui_theme_name or "blue-green"),
    }
    current = deps.get_runtime_kv("runtime_config") or {}
    if isinstance(current, dict):
        payload.update(current)
    return payload


@router.get("/bootstrap")
def bootstrap():
    config = _public_runtime_config()
    return {
        "brand": {"name": "MD Quiz", "theme": str(config.get("ui_theme_name") or "blue-green")},
        "features": {
            "sms_enabled": bool(config.get("sms_enabled", False)),
            "allow_public_assignments": bool(config.get("allow_public_assignments", True)),
            "min_submit_seconds": int(config.get("min_submit_seconds") or 60),
        },
    }


@router.post("/invites/{public_token}/ensure")
def ensure_public_invite(public_token: str, request: Request):
    token_value = str(public_token or "").strip()
    if not token_value:
        raise HTTPException(status_code=404, detail="公开邀约不存在")

    exam_key = exam_helpers._resolve_public_invite_exam_key(token_value)
    if not exam_key:
        raise HTTPException(status_code=404, detail="公开邀约不存在")
    cfg = exam_helpers.get_public_invite_config(exam_key)
    if not bool(cfg.get("enabled")) or str(cfg.get("token") or "").strip() != token_value:
        raise HTTPException(status_code=410, detail="当前公开邀约链接已关闭或无效")

    exam = deps.get_exam_definition(exam_key)
    exam_version_id = exam_helpers.resolve_exam_version_id_for_new_assignment(exam_key)
    if not exam or not exam_version_id:
        raise HTTPException(status_code=404, detail="试卷不存在")

    cookie_name = f"public_invite_{token_value}"
    existing = str(request.cookies.get(cookie_name) or "").strip()
    if existing:
        try:
            with deps.assignment_locked(existing):
                assignment = deps.load_assignment(existing)
            if str(assignment.get("exam_key") or "").strip() == exam_key:
                response = JSONResponse({"ok": True, "token": existing, "redirect": f"/t/{existing}"})
                response.set_cookie(cookie_name, existing, max_age=7 * 24 * 3600, samesite="lax")
                return response
        except Exception:
            pass

    result = deps.create_assignment(
        exam_key=exam_key,
        candidate_id=0,
        exam_version_id=exam_version_id,
        base_url=_public_base_url(request),
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
        raise HTTPException(status_code=500, detail="创建公开邀约失败")

    try:
        with deps.assignment_locked(token):
            assignment = deps.load_assignment(token)
            assignment["public_invite"] = {
                "token": token_value,
                "exam_key": exam_key,
                "exam_version_id": exam_version_id,
            }
            deps.save_assignment(token, assignment)
    except Exception:
        pass

    response = JSONResponse({"ok": True, "token": token, "redirect": f"/t/{token}"})
    response.set_cookie(cookie_name, token, max_age=7 * 24 * 3600, samesite="lax")
    return response


@router.get("/invites/{public_token}/qr.png")
def public_invite_qr(public_token: str, request: Request):
    token_value = str(public_token or "").strip()
    if not token_value:
        raise HTTPException(status_code=404, detail="公开邀约不存在")
    exam_key = exam_helpers._resolve_public_invite_exam_key(token_value)
    if not exam_key:
        raise HTTPException(status_code=404, detail="公开邀约不存在")
    cfg = exam_helpers.get_public_invite_config(exam_key)
    if not bool(cfg.get("enabled")) or str(cfg.get("token") or "").strip() != token_value:
        raise HTTPException(status_code=404, detail="公开邀约不存在")
    try:
        import qrcode  # type: ignore
    except Exception as exc:
        raise HTTPException(status_code=500, detail="二维码依赖不可用") from exc
    public_url = f"{_public_base_url(request)}/p/{token_value}"
    image = qrcode.make(public_url)
    buffer = BytesIO()
    try:
        image.save(buffer, format="PNG")
    except TypeError:
        image.save(buffer)
    headers = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}
    return Response(content=buffer.getvalue(), media_type="image/png", headers=headers)


@router.get("/attempt/{token}")
def get_attempt_bootstrap(token: str):
    return _bootstrap_attempt(token)


@router.post("/attempt/{token}/enter")
def enter_exam(token: str):
    with deps.assignment_locked(token):
        assignment = deps.load_assignment(token)
        if str(assignment.get("status") or "").strip() == "expired":
            raise HTTPException(status_code=410, detail="当前答题链接已失效")
        invite_state, _, _ = exam_helpers._invite_window_state(assignment)
        if invite_state in {"not_started", "expired"}:
            raise HTTPException(status_code=400, detail="当前不在可答题时间范围内")
        if (assignment.get("verify") or {}).get("locked"):
            raise HTTPException(status_code=410, detail="当前链接已失效")

        try:
            candidate_id = int(assignment.get("candidate_id") or 0)
        except Exception:
            candidate_id = 0
        if candidate_id <= 0:
            raise HTTPException(status_code=400, detail="请先完成身份验证")

        runtime_bootstrap._ensure_exam_paper_for_token(token, assignment)
        timing = assignment.setdefault("timing", {})
        if not timing.get("start_at"):
            now = datetime.now(timezone.utc)
            timing["start_at"] = now.isoformat()
            try:
                deps.set_exam_paper_entered_at(token, now)
            except Exception:
                pass
            try:
                candidate = deps.get_candidate(candidate_id) or {}
                deps.log_event(
                    "exam.enter",
                    actor="candidate",
                    candidate_id=int(candidate_id),
                    exam_key=(str(assignment.get("exam_key") or "").strip() or None),
                    token=(token or None),
                    meta={
                        "name": str(candidate.get("name") or "").strip(),
                        "phone": str(candidate.get("phone") or "").strip(),
                        "public_invite": bool(assignment.get("public_invite")),
                    },
                )
            except Exception:
                pass
        try:
            deps.set_exam_paper_status(token, "in_exam")
        except Exception:
            pass
        if str(assignment.get("status") or "").strip() not in {"in_exam", "grading", "graded"}:
            assignment["status"] = "in_exam"
            assignment["status_updated_at"] = datetime.now(timezone.utc).isoformat()
            deps.save_assignment(token, assignment)
    return _bootstrap_attempt(token)


@router.post("/sms/send")
def public_send_sms_code(payload: SmsSendPayload):
    token = str(payload.token or "").strip()
    name = str(payload.name or "").strip()
    phone = validation_helpers._normalize_phone(payload.phone)
    if not token or not validation_helpers._is_valid_name(name) or not validation_helpers._is_valid_phone(phone):
        raise HTTPException(status_code=400, detail="请输入正确的姓名和手机号")

    cooldown_seconds = 60
    max_send = 3
    ttl_seconds = validation_helpers._sms_code_ttl_seconds()
    now = datetime.now(timezone.utc)

    with deps.assignment_locked(token):
        assignment = deps.load_assignment(token)
        if str(assignment.get("status") or "").strip() == "expired":
            raise HTTPException(status_code=410, detail="链接已失效")

        invite_state, _, _ = exam_helpers._invite_window_state(assignment)
        if invite_state in {"not_started", "expired"}:
            raise HTTPException(status_code=400, detail="当前不在可答题时间范围内")
        if assignment.get("grading") or runtime_jobs._finalize_if_time_up(token, assignment):
            raise HTTPException(status_code=400, detail="答题已结束")

        verify = assignment.get("verify") or {"attempts": 0, "locked": False}
        if verify.get("locked"):
            raise HTTPException(status_code=410, detail="链接已失效")

        try:
            candidate_id = int(assignment.get("candidate_id") or 0)
        except Exception:
            candidate_id = 0

        if candidate_id > 0:
            ok = deps.verify_candidate(candidate_id, name=name, phone=phone)
        else:
            existed = deps.get_candidate_by_phone(phone)
            if existed and int(existed.get("id") or 0) > 0:
                ok = bool(str(existed.get("name") or "").strip() == name)
                if ok:
                    assignment["candidate_id"] = int(existed.get("id") or 0)
            else:
                ok = True

        if not ok:
            verify["attempts"] = int(verify.get("attempts") or 0) + 1
            if verify["attempts"] >= int(assignment.get("verify_max_attempts") or 3):
                verify["locked"] = True
            assignment["verify"] = verify
            deps.save_assignment(token, assignment)
            raise HTTPException(status_code=400, detail="信息不匹配，请检查后重试")

        sms = assignment.get("sms_verify") or {}
        if not sms.get("verified") and int(sms.get("send_count") or 0) >= max_send:
            assignment["status"] = "expired"
            assignment["status_updated_at"] = now.isoformat()
            try:
                deps.set_exam_paper_status(token, "expired")
            except Exception:
                pass
            verify["locked"] = True
            assignment["verify"] = verify
            deps.save_assignment(token, assignment)
            raise HTTPException(status_code=410, detail="验证码发送次数已达上限，链接已失效")

        last_phone = str(sms.get("phone") or "")
        last_sent_at = str(sms.get("last_sent_at") or "").strip()
        if last_phone == phone and last_sent_at:
            last_dt = validation_helpers._parse_iso_datetime(last_sent_at)
            if last_dt is not None:
                elapsed = (now - last_dt).total_seconds()
                left = int(cooldown_seconds - elapsed)
                if left > 0:
                    raise HTTPException(status_code=429, detail=f"请 {left} 秒后再试")

        code = validation_helpers._generate_sms_code(validation_helpers._sms_code_length())
        code_salt = secrets.token_hex(16)
        code_hash = validation_helpers._hash_sms_code(code, code_salt)

        try:
            response = deps.send_sms_verify_code(phone, code=code, ttl_seconds=ttl_seconds)
        except Exception as exc:
            deps.logger.exception("Send SMS verify code failed")
            raise HTTPException(status_code=502, detail="短信服务暂不可用，请稍后重试") from exc

        success = bool(response.get("Success")) and str(response.get("Code") or "").upper() == "OK"
        if not success:
            raise HTTPException(status_code=502, detail=str(response.get("Message") or "发送失败"))

        biz_id = ""
        model = response.get("Model")
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
        deps.save_assignment(token, assignment)
        try:
            deps.incr_sms_calls_and_alert(1)
        except Exception:
            pass

    return {
        "ok": True,
        "cooldown": cooldown_seconds,
        "biz_id": biz_id,
        "send_count": int(sms.get("send_count") or 0),
        "send_max": max_send,
    }


@router.post("/verify")
def public_verify(payload: VerifyPayload):
    token = str(payload.token or "").strip()
    name = str(payload.name or "").strip()
    phone = validation_helpers._normalize_phone(payload.phone)
    sms_code = str(payload.sms_code or "").strip()

    if not validation_helpers._is_valid_name(name) or not validation_helpers._is_valid_phone(phone):
        raise HTTPException(status_code=400, detail="姓名或手机号格式不正确")

    log_candidate_id = 0
    log_exam_key = ""
    log_public_invite = False
    log_sms_send_count = 0
    redirect_to = ""

    with deps.assignment_locked(token):
        assignment = deps.load_assignment(token)
        if str(assignment.get("status") or "").strip() == "expired":
            raise HTTPException(status_code=410, detail="当前链接已失效，请联系管理员重新生成")

        invite_state, _, _ = exam_helpers._invite_window_state(assignment)
        if invite_state in {"not_started", "expired"}:
            raise HTTPException(status_code=400, detail="当前不在可答题时间范围内")

        if assignment.get("grading") or runtime_jobs._finalize_if_time_up(token, assignment):
            raise HTTPException(status_code=400, detail="答题已结束")

        runtime_bootstrap._ensure_exam_paper_for_token(token, assignment)
        verify = assignment.get("verify") or {"attempts": 0, "locked": False}
        if verify.get("locked"):
            raise HTTPException(status_code=410, detail="当前链接已失效，请联系管理员重新生成")

        try:
            candidate_id = int(assignment.get("candidate_id") or 0)
        except Exception:
            candidate_id = 0

        if candidate_id > 0:
            ok = deps.verify_candidate(candidate_id, name=name, phone=phone)
        else:
            existing = deps.get_candidate_by_phone(phone)
            if existing and int(existing.get("id") or 0) > 0:
                existing_id = int(existing.get("id") or 0)
                ok = bool(str(existing.get("name") or "").strip() == name)
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
                    raise HTTPException(status_code=400, detail="请输入短信验证码")
                if not str(sms.get("expires_at") or "").strip() or not str(sms.get("code_hash") or "").strip() or not str(sms.get("code_salt") or "").strip():
                    raise HTTPException(status_code=400, detail="请先发送短信验证码")

                expires_at = validation_helpers._parse_iso_datetime(str(sms.get("expires_at") or ""))
                if expires_at is None or expires_at <= datetime.now(timezone.utc):
                    raise HTTPException(status_code=400, detail="验证码已过期，请重新发送")

                salt = str(sms.get("code_salt") or "").strip()
                expected = str(sms.get("code_hash") or "").strip()
                actual = validation_helpers._hash_sms_code(sms_code, salt)
                sms_ok = bool(expected and salt and hmac.compare_digest(expected, actual))
                if not sms_ok:
                    if int((sms.get("send_count") or 0)) >= 3:
                        assignment["status"] = "expired"
                        assignment["status_updated_at"] = datetime.now(timezone.utc).isoformat()
                        try:
                            deps.set_exam_paper_status(token, "expired")
                        except Exception:
                            pass
                        verify["locked"] = True
                        assignment["verify"] = verify
                        deps.save_assignment(token, assignment)
                        raise HTTPException(
                            status_code=410,
                            detail="验证码未在规定次数内验证通过，链接已失效，请联系管理员重新生成",
                        )
                    deps.save_assignment(token, assignment)
                    raise HTTPException(status_code=400, detail="验证码错误，请重试")

                sms["verified"] = True
                sms["verified_at"] = datetime.now(timezone.utc).isoformat()
                sms.pop("expires_at", None)
                sms.pop("code_salt", None)
                sms.pop("code_hash", None)
                assignment["sms_verify"] = sms

            if candidate_id <= 0:
                existed = deps.get_candidate_by_phone(phone)
                if existed and int(existed.get("id") or 0) > 0:
                    candidate_id = int(existed.get("id") or 0)
                    assignment["candidate_id"] = int(candidate_id)
                else:
                    assignment["pending_profile"] = {
                        "name": name,
                        "phone": phone,
                        "sms_verified_at": str((assignment.get("sms_verify") or {}).get("verified_at") or ""),
                    }
                    assignment["status"] = "resume_pending"
                    assignment["status_updated_at"] = datetime.now(timezone.utc).isoformat()
                    redirect_to = f"/resume/{token}"

            if candidate_id > 0:
                try:
                    invite_window = assignment.get("invite_window") or {}
                    if not isinstance(invite_window, dict):
                        invite_window = {}
                    invite_start_date = str(invite_window.get("start_date") or "").strip() or None
                    invite_end_date = str(invite_window.get("end_date") or "").strip() or None
                    if not deps.get_exam_paper_by_token(token):
                        deps.create_exam_paper(
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
                    deps.set_exam_paper_status(token, "verified")
                except Exception:
                    pass
                assignment["status"] = "verified"
                assignment["status_updated_at"] = datetime.now(timezone.utc).isoformat()
                assignment.pop("pending_profile", None)
                redirect_to = f"/exam/{token}"
        else:
            verify["attempts"] = int(verify.get("attempts") or 0) + 1
            if verify["attempts"] >= int(assignment.get("verify_max_attempts") or 3):
                verify["locked"] = True

        assignment["verify"] = verify
        if not ok:
            deps.save_assignment(token, assignment)
            raise HTTPException(status_code=400, detail="信息不匹配，请重试")

        try:
            log_candidate_id = int(candidate_id or 0)
        except Exception:
            log_candidate_id = 0
        log_exam_key = str(assignment.get("exam_key") or "").strip()
        log_public_invite = bool(assignment.get("public_invite"))
        try:
            sms_state = assignment.get("sms_verify") or {}
            log_sms_send_count = int((sms_state.get("send_count") or 0) if isinstance(sms_state, dict) else 0)
        except Exception:
            log_sms_send_count = 0
        deps.save_assignment(token, assignment)

    try:
        deps.log_event(
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
    return {"ok": True, "redirect": redirect_to or f"/exam/{token}"}


@router.post("/resume/upload")
def public_resume_upload(request: Request, token: str = "", file: UploadFile = File(...)):
    token = str(token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="缺少 token")
    data = _read_resume_bytes(file)
    filename = str(file.filename or "")
    mime = str(file.content_type or "")

    with deps.assignment_locked(token):
        assignment = deps.load_assignment(token)
        if str(assignment.get("status") or "").strip() == "expired":
            raise HTTPException(status_code=410, detail="当前链接已失效")
        invite_state, _, _ = exam_helpers._invite_window_state(assignment)
        if invite_state in {"not_started", "expired"}:
            raise HTTPException(status_code=400, detail="当前不在可答题时间范围内")
        sms = assignment.get("sms_verify") or {}
        if not bool(sms.get("verified")):
            raise HTTPException(status_code=400, detail="请先完成验证码验证")

        try:
            existing_candidate_id = int(assignment.get("candidate_id") or 0)
        except Exception:
            existing_candidate_id = 0
        if existing_candidate_id > 0:
            return {"ok": True, "redirect": f"/exam/{token}"}

        pending = assignment.get("pending_profile") or {}
        name = str(pending.get("name") or "").strip()
        phone = validation_helpers._normalize_phone(str(pending.get("phone") or sms.get("phone") or "").strip())

    if not validation_helpers._is_valid_name(name) or not validation_helpers._is_valid_phone(phone):
        raise HTTPException(status_code=400, detail="候选人信息不完整，请重新验证")

    payload = _parse_resume_payload(data=data, filename=filename, mime=mime, current_phone=phone)
    parsed_phone = validation_helpers._normalize_phone(str(payload.get("parsed_phone") or "").strip())
    if validation_helpers._is_valid_phone(parsed_phone) and parsed_phone != phone:
        raise HTTPException(status_code=400, detail="简历手机号与验证手机号不一致，请检查后重试")

    candidate = deps.get_candidate_by_phone(phone)
    created = False
    if candidate and int(candidate.get("id") or 0) > 0:
        candidate_id = int(candidate.get("id") or 0)
    else:
        try:
            candidate_id = int(deps.create_candidate(name=name, phone=phone))
            created = True
        except Exception:
            candidate_retry = deps.get_candidate_by_phone(phone)
            candidate_id = int((candidate_retry or {}).get("id") or 0)
    if candidate_id <= 0:
        raise HTTPException(status_code=500, detail="创建候选人失败，请稍后重试")

    parsed_name = str(payload.get("parsed_name") or "").strip()
    if validation_helpers._is_valid_name(parsed_name):
        try:
            current = deps.get_candidate(candidate_id) or {}
            if str(current.get("name") or "").strip() in {"", "未知"}:
                deps.update_candidate(candidate_id, name=parsed_name, phone=phone)
        except Exception:
            pass

    deps.update_candidate_resume(
        candidate_id,
        resume_bytes=data,
        resume_filename=filename,
        resume_mime=mime,
        resume_size=len(data),
        resume_parsed=payload["resume_parsed"],
    )

    with deps.assignment_locked(token):
        assignment = deps.load_assignment(token)
        assignment["candidate_id"] = int(candidate_id)
        assignment.pop("pending_profile", None)
        assignment["status"] = "verified"
        assignment["status_updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            invite_window = assignment.get("invite_window") or {}
            if not isinstance(invite_window, dict):
                invite_window = {}
            invite_start_date = str(invite_window.get("start_date") or "").strip() or None
            invite_end_date = str(invite_window.get("end_date") or "").strip() or None
            if not deps.get_exam_paper_by_token(token):
                deps.create_exam_paper(
                    candidate_id=int(candidate_id),
                    phone=phone,
                    exam_key=str(assignment.get("exam_key") or ""),
                    token=token,
                    invite_start_date=invite_start_date,
                    invite_end_date=invite_end_date,
                    status="verified",
                )
            else:
                deps.set_exam_paper_status(token, "verified")
        except Exception:
            pass
        deps.save_assignment(token, assignment)

    try:
        if created:
            deps.log_event(
                "candidate.create",
                actor="candidate",
                candidate_id=candidate_id,
                meta={"name": name, "phone": phone, "public_invite": True},
            )
        deps.log_event(
            "candidate.resume.parse",
            actor="candidate",
            candidate_id=int(candidate_id),
            exam_key=(str(assignment.get("exam_key") or "").strip() or None),
            token=(token or None),
            llm_total_tokens=(int(payload.get("llm_total_tokens") or 0) or None),
            meta={"public_invite": True},
        )
    except Exception:
        pass
    return {"ok": True, "redirect": f"/exam/{token}"}


@router.post("/answers/{token}")
async def public_save_answer(token: str, request: Request):
    with deps.assignment_locked(token):
        assignment = deps.load_assignment(token)
        if (assignment.get("verify") or {}).get("locked"):
            raise HTTPException(status_code=410, detail="当前链接已失效")
        if assignment.get("grading") or runtime_jobs._finalize_if_time_up(token, assignment):
            raise HTTPException(status_code=409, detail="already_submitted")

        question_id = ""
        value: Any = None
        content_type = str(request.headers.get("content-type") or "").lower()
        if "application/json" in content_type:
            body = await request.json()
            if isinstance(body, dict):
                question_id = str(body.get("question_id") or "").strip()
                value = body.get("answer")
        else:
            form = await request.form()
            question_id = str(form.get("question_id") or "").strip()
            multi = form.getlist("answer[]")
            if multi:
                value = multi
            else:
                value = form.get("answer")

        if not question_id or value is None:
            return {"ok": True}
        assignment.setdefault("answers", {})[question_id] = value
        deps.save_assignment(token, assignment)
    return {"ok": True}


@router.post("/answers_bulk/{token}")
async def public_save_answers_bulk(token: str, request: Request):
    body = await request.json()
    answers = body.get("answers") if isinstance(body, dict) else None
    if not isinstance(answers, dict):
        raise HTTPException(status_code=400, detail="invalid_payload")
    with deps.assignment_locked(token):
        assignment = deps.load_assignment(token)
        invite_state, _, _ = exam_helpers._invite_window_state(assignment)
        if invite_state in {"not_started", "expired"}:
            raise HTTPException(status_code=403, detail="invite_window_invalid")
        if (assignment.get("verify") or {}).get("locked"):
            raise HTTPException(status_code=410, detail="当前链接已失效")
        if assignment.get("grading") or runtime_jobs._finalize_if_time_up(token, assignment):
            raise HTTPException(status_code=409, detail="already_submitted")
        out = assignment.setdefault("answers", {})
        for key, value in answers.items():
            qid = str(key or "").strip()
            if not qid or value is None:
                continue
            out[qid] = [str(item) for item in value] if isinstance(value, list) else str(value)
        deps.save_assignment(token, assignment)
    return {"ok": True}


@router.post("/submit/{token}")
def public_submit(token: str):
    with deps.assignment_locked(token):
        assignment = deps.load_assignment(token)
        invite_state, _, _ = exam_helpers._invite_window_state(assignment)
        if invite_state in {"not_started", "expired"}:
            raise HTTPException(status_code=400, detail="当前不在可答题时间范围内")
        runtime_bootstrap._ensure_exam_paper_for_token(token, assignment)
        if (assignment.get("verify") or {}).get("locked"):
            raise HTTPException(status_code=410, detail="当前链接已失效")
        if assignment.get("grading"):
            grading = assignment.get("grading") or {}
            if isinstance(grading, dict) and str(grading.get("status") or "") in {"pending", "running"}:
                try:
                    runtime_jobs._start_background_grading(token)
                except Exception:
                    pass
            runtime_jobs._sync_exam_paper_finished_from_assignment(assignment)
            return {"ok": True, "redirect": f"/done/{token}"}

        now = datetime.now(timezone.utc)
        timing = assignment.setdefault("timing", {})
        started_at = runtime_jobs._parse_iso_dt(timing.get("start_at"))
        if not started_at:
            started_at = now
            timing["start_at"] = now.isoformat()
            try:
                deps.set_exam_paper_entered_at(token, started_at)
            except Exception:
                pass

        time_limit_seconds = int(assignment.get("time_limit_seconds") or 0)
        min_submit_seconds = deps.compute_min_submit_seconds(
            time_limit_seconds,
            assignment.get("min_submit_seconds"),
        )
        if int(assignment.get("min_submit_seconds") or 0) != min_submit_seconds:
            assignment["min_submit_seconds"] = int(min_submit_seconds)

        elapsed = max(0, int((now - started_at).total_seconds()))
        if time_limit_seconds > 0 and min_submit_seconds > 0 and elapsed < min_submit_seconds and elapsed < time_limit_seconds:
            wait_seconds = max(0, int(min_submit_seconds - elapsed))
            deps.save_assignment(token, assignment)
            raise HTTPException(
                status_code=400,
                detail=f"未达到最短交卷时长，请至少答题 {(min_submit_seconds + 59) // 60} 分钟后再提交",
                headers={"X-Wait-Seconds": str(wait_seconds)},
            )

        assignment = deps.load_assignment(token)
        if assignment.get("grading"):
            return {"ok": True, "redirect": f"/done/{token}"}
        runtime_jobs._finalize_public_submission(token, assignment, now=now)
    runtime_jobs._start_background_grading(token)
    return {"ok": True, "redirect": f"/done/{token}"}


def _read_resume_bytes(file: UploadFile) -> bytes:
    if not file or not getattr(file, "filename", ""):
        raise HTTPException(status_code=400, detail="请选择简历文件")
    try:
        data = file.file.read() or b""
    except Exception as exc:
        raise HTTPException(status_code=400, detail="简历文件读取失败") from exc
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="简历文件过大，需小于等于 10MB")
    ext = os.path.splitext(str(file.filename or ""))[1].lower()
    if ext not in validation_helpers._ALLOWED_RESUME_EXTS:
        raise HTTPException(status_code=400, detail="仅支持 PDF、DOCX 或图片简历")
    return data


def _parse_resume_payload(*, data: bytes, filename: str, mime: str, current_phone: str) -> dict[str, Any]:
    try:
        text = deps.extract_resume_text(data, filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"简历解析失败：{type(exc).__name__}") from exc

    parsed_phone = ""
    parsed_name = ""
    name_conf = 0
    phone_conf = 0
    llm_total_tokens = 0
    try:
        ident = deps.parse_resume_identity_fast(text or "") or {}
        parsed_name = str(ident.get("name") or "").strip()
        parsed_phone = validation_helpers._normalize_phone(str(ident.get("phone") or "").strip())
        conf = ident.get("confidence") or {}
        if isinstance(conf, dict):
            name_conf = validation_helpers._safe_int(conf.get("name") or 0, 0)
            phone_conf = validation_helpers._safe_int(conf.get("phone") or 0, 0)
    except Exception:
        pass

    if validation_helpers._is_valid_phone(parsed_phone) and parsed_phone != current_phone:
        raise HTTPException(status_code=400, detail="简历手机号与验证手机号不一致，请检查后重试")

    details: dict[str, Any] = {}
    details_error = ""
    try:
        with deps.audit_context(meta={}):
            parsed_details = deps.parse_resume_details_llm(text or "")
            if isinstance(parsed_details, dict):
                details = parsed_details
            ctx = deps.get_audit_context()
            meta = ctx.get("meta")
            if isinstance(meta, dict):
                llm_total_tokens += int(meta.get("llm_total_tokens_sum") or 0)
    except Exception as exc:
        details_error = f"{type(exc).__name__}: {exc}"

    return {
        "resume_parsed": {
            "extracted": {"name": parsed_name, "phone": parsed_phone or current_phone},
            "confidence": {
                "name": max(0, min(100, name_conf)),
                "phone": max(0, min(100, phone_conf)),
            },
            "source_filename": filename,
            "source_mime": mime,
            "details": {
                "status": "failed" if details_error else ("done" if details else "empty"),
                "data": details,
                "parsed_at": datetime.now(timezone.utc).isoformat(),
                **({"error": details_error} if details_error else {}),
            },
        },
        "parsed_name": parsed_name,
        "llm_total_tokens": llm_total_tokens,
    }
