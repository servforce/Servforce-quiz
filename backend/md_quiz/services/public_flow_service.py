from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from backend.md_quiz.services import exam_helpers, resume_ingest_service, runtime_bootstrap, runtime_jobs
from backend.md_quiz.services import support_deps as deps
from backend.md_quiz.services import validation_helpers
from backend.md_quiz.storage import JobStore

_SMS_COOLDOWN_SECONDS = 60
_SMS_SEND_MAX = 3
_SMS_VERIFY_CODE_LENGTH = 4


def ensure_public_invite(public_token: str, request: Request) -> JSONResponse:
    token_value = str(public_token or "").strip()
    if not token_value:
        raise HTTPException(status_code=404, detail="公开邀约不存在")

    quiz_key = exam_helpers._resolve_public_invite_quiz_key(token_value)
    if not quiz_key:
        raise HTTPException(status_code=404, detail="公开邀约不存在")
    cfg = exam_helpers.get_public_invite_config(quiz_key)
    if not bool(cfg.get("enabled")) or str(cfg.get("token") or "").strip() != token_value:
        raise HTTPException(status_code=410, detail="当前公开邀约链接已关闭或无效")

    quiz = deps.get_quiz_definition(quiz_key)
    quiz_version_id = exam_helpers.resolve_quiz_version_id_for_new_assignment(quiz_key)
    if not quiz or not quiz_version_id:
        raise HTTPException(status_code=404, detail="测验不存在")
    time_limit_seconds = exam_helpers.compute_quiz_time_limit_seconds(
        (quiz.get("public_spec") if isinstance(quiz.get("public_spec"), dict) else {}) or {}
    )

    cookie_name = f"public_invite_{token_value}"
    existing = str(request.cookies.get(cookie_name) or "").strip()
    if existing:
        try:
            with deps.assignment_locked(existing):
                assignment = deps.load_assignment(existing)
            if str(assignment.get("quiz_key") or "").strip() == quiz_key:
                response = JSONResponse({"ok": True, "token": existing, "redirect": f"/t/{existing}"})
                response.set_cookie(cookie_name, existing, max_age=7 * 24 * 3600, samesite="lax")
                return response
        except Exception:
            pass

    result = deps.create_assignment(
        quiz_key=quiz_key,
        candidate_id=0,
        quiz_version_id=quiz_version_id,
        base_url=str(request.base_url).rstrip("/"),
        phone="",
        invite_start_date=None,
        invite_end_date=None,
        time_limit_seconds=time_limit_seconds,
        min_submit_seconds=0,
        require_phone_verification=True,
        verify_max_attempts=3,
    )
    token = str(result.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=500, detail="创建公开邀约失败")

    try:
        with deps.assignment_locked(token):
            assignment = deps.load_assignment(token)
            assignment["public_invite"] = {
                "token": token_value,
                "quiz_key": quiz_key,
                "quiz_version_id": quiz_version_id,
            }
            deps.save_assignment(token, assignment)
    except Exception:
        pass

    response = JSONResponse({"ok": True, "token": token, "redirect": f"/t/{token}"})
    response.set_cookie(cookie_name, token, max_age=7 * 24 * 3600, samesite="lax")
    return response


def send_sms_code(*, token: str, name: str = "", phone: str = "") -> dict[str, Any]:
    token = str(token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="缺少 token")

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
        if not validation_helpers._require_phone_verification(assignment):
            raise HTTPException(status_code=400, detail="当前邀约未启用短信认证")

        try:
            candidate_id = int(assignment.get("candidate_id") or 0)
        except Exception:
            candidate_id = 0
        mode = "public_identity"
        if candidate_id > 0 and not bool(assignment.get("public_invite")):
            mode = "direct_phone"
        verify = assignment.get("verify") or {"attempts": 0, "locked": False}
        if verify.get("locked"):
            raise HTTPException(status_code=410, detail="链接已失效")

        if mode == "direct_phone":
            candidate = deps.get_candidate(candidate_id) or {}
            name = str(candidate.get("name") or "").strip()
            phone = validation_helpers._normalize_phone(str(candidate.get("phone") or "").strip())
            if candidate_id <= 0 or not validation_helpers._is_valid_phone(phone):
                raise HTTPException(status_code=400, detail="当前邀约缺少有效手机号，请联系管理员")
            ok = True
        else:
            name = str(name or "").strip()
            phone = validation_helpers._normalize_phone(phone)
            if not validation_helpers._is_valid_name(name) or not validation_helpers._is_valid_phone(phone):
                raise HTTPException(status_code=400, detail="请输入正确的姓名和手机号")
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
        if mode == "public_identity":
            assignment["pending_profile"] = {"name": name, "phone": phone}
        if not sms.get("verified") and int(sms.get("send_count") or 0) >= _SMS_SEND_MAX:
            assignment["status"] = "expired"
            assignment["status_updated_at"] = now.isoformat()
            try:
                deps.set_quiz_paper_status(token, "expired")
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
                left = int(_SMS_COOLDOWN_SECONDS - elapsed)
                if left > 0:
                    raise HTTPException(status_code=429, detail=f"请 {left} 秒后再试")

        try:
            response = deps.send_sms_verify_code(phone)
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
        sms["verified"] = False
        sms.pop("verified_at", None)
        sms["send_count"] = int(sms.get("send_count") or 0) + 1
        if biz_id:
            sms["biz_id"] = biz_id
        else:
            sms.pop("biz_id", None)
        sms.pop("expires_at", None)
        sms.pop("code_salt", None)
        sms.pop("code_hash", None)
        assignment["sms_verify"] = sms
        deps.save_assignment(token, assignment)
        try:
            deps.incr_sms_calls_and_alert(1)
        except Exception:
            pass

    normalized_phone = validation_helpers._normalize_phone(phone)
    masked_phone = ""
    if len(normalized_phone) == 11:
        masked_phone = f"{normalized_phone[:3]}****{normalized_phone[-4:]}"
    return {
        "ok": True,
        "cooldown": _SMS_COOLDOWN_SECONDS,
        "biz_id": biz_id,
        "send_count": int(sms.get("send_count") or 0),
        "send_max": _SMS_SEND_MAX,
        "mode": mode,
        "masked_phone": masked_phone,
    }


def verify_assignment(*, token: str, name: str = "", phone: str = "", sms_code: str = "") -> dict[str, Any]:
    token = str(token or "").strip()
    sms_code = str(sms_code or "").strip()

    log_candidate_id = 0
    log_quiz_key = ""
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

        runtime_bootstrap._ensure_quiz_paper_for_token(token, assignment)
        require_phone_verification = validation_helpers._require_phone_verification(assignment)
        verify = assignment.get("verify") or {"attempts": 0, "locked": False}
        if require_phone_verification and verify.get("locked"):
            raise HTTPException(status_code=410, detail="当前链接已失效，请联系管理员重新生成")

        try:
            candidate_id = int(assignment.get("candidate_id") or 0)
        except Exception:
            candidate_id = 0
        mode = "public_identity"
        if candidate_id > 0 and not bool(assignment.get("public_invite")):
            mode = "direct_phone"

        if mode == "direct_phone":
            candidate = deps.get_candidate(candidate_id) or {}
            name = str(candidate.get("name") or "").strip()
            phone = validation_helpers._normalize_phone(str(candidate.get("phone") or "").strip())
            if candidate_id <= 0 or not validation_helpers._is_valid_phone(phone):
                raise HTTPException(status_code=400, detail="当前邀约缺少有效手机号，请联系管理员")
            ok = True
        else:
            name = str(name or "").strip()
            phone = validation_helpers._normalize_phone(phone)
            if not validation_helpers._is_valid_name(name) or not validation_helpers._is_valid_phone(phone):
                raise HTTPException(status_code=400, detail="姓名或手机号格式不正确")
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
            if require_phone_verification and not sms.get("verified"):
                if not sms_code:
                    raise HTTPException(status_code=400, detail="请输入短信验证码")
                if not sms_code.isdigit() or len(sms_code) != _SMS_VERIFY_CODE_LENGTH:
                    raise HTTPException(status_code=400, detail="请输入 4 位数字验证码")
                if int(sms.get("send_count") or 0) <= 0:
                    raise HTTPException(status_code=400, detail="请先发送短信验证码")
                if str(sms.get("phone") or "").strip() != phone:
                    raise HTTPException(status_code=400, detail="手机号与已发送验证码不一致，请重新发送")

                try:
                    check_response = deps.check_sms_verify_code(phone, sms_code)
                except Exception as exc:
                    deps.logger.exception("Check SMS verify code failed")
                    raise HTTPException(status_code=502, detail="短信服务暂不可用，请稍后重试") from exc
                model = check_response.get("Model") if isinstance(check_response, dict) else None
                sms_ok = bool(check_response.get("Success")) and str(check_response.get("Code") or "").upper() == "OK"
                if sms_ok and isinstance(model, dict):
                    for key in ("IsCodeValid", "VerifySuccess", "IsCorrect", "Valid"):
                        if key in model and model.get(key) is False:
                            sms_ok = False
                            break
                if not sms_ok:
                    if int(sms.get("send_count") or 0) >= 3:
                        assignment["status"] = "expired"
                        assignment["status_updated_at"] = datetime.now(timezone.utc).isoformat()
                        try:
                            deps.set_quiz_paper_status(token, "expired")
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
                    detail = str((check_response or {}).get("Message") or "").strip() or "验证码错误，请重试"
                    raise HTTPException(status_code=400, detail=detail)

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
                    assignment["candidate_id"] = candidate_id
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
                    if not deps.get_quiz_paper_by_token(token):
                        deps.create_quiz_paper(
                            candidate_id=int(candidate_id),
                            phone=phone,
                            quiz_key=str(assignment.get("quiz_key") or ""),
                            token=token,
                            source_kind=("public" if assignment.get("public_invite") else "direct"),
                            invite_start_date=invite_start_date,
                            invite_end_date=invite_end_date,
                            status="verified",
                        )
                except Exception:
                    pass
                try:
                    deps.set_quiz_paper_status(token, "verified")
                except Exception:
                    pass
                assignment["status"] = "verified"
                assignment["status_updated_at"] = datetime.now(timezone.utc).isoformat()
                assignment.pop("pending_profile", None)
                redirect_to = f"/quiz/{token}"
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
        log_quiz_key = str(assignment.get("quiz_key") or "").strip()
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
            quiz_key=(log_quiz_key or None),
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
    return {"ok": True, "redirect": redirect_to or f"/quiz/{token}"}


def upload_public_resume(*, token: str, file: UploadFile) -> dict[str, Any]:
    token = str(token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="缺少 token")
    data = resume_ingest_service.read_resume_bytes(file)
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
            return {"ok": True, "redirect": f"/quiz/{token}"}

        pending = assignment.get("pending_profile") or {}
        name = str(pending.get("name") or "").strip()
        phone = validation_helpers._normalize_phone(str(pending.get("phone") or sms.get("phone") or "").strip())
        quiz_key = str(assignment.get("quiz_key") or "").strip()

    if not validation_helpers._is_valid_name(name) or not validation_helpers._is_valid_phone(phone):
        raise HTTPException(status_code=400, detail="候选人信息不完整，请重新验证")

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

    pending_resume_parsed = {
        "extracted": {"name": name, "phone": phone},
        "confidence": {"name": 0, "phone": 100},
        "source_filename": filename,
        "source_mime": mime,
        "method": {"identity": "pending", "name": "pending", "details": "pending"},
        "details": {
            "status": "pending",
            "data": {},
            "parsed_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    deps.update_candidate_resume(
        candidate_id,
        resume_bytes=data,
        resume_filename=filename,
        resume_mime=mime,
        resume_size=len(data),
        resume_parsed=pending_resume_parsed,
    )

    try:
        JobStore().enqueue(
            "resume_parse",
            payload={
                "candidate_id": int(candidate_id),
                "expected_phone": phone,
                "token": token,
                "quiz_key": quiz_key,
            },
            source="public_resume_upload",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="简历解析任务创建失败，请稍后重试") from exc

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
            if not deps.get_quiz_paper_by_token(token):
                deps.create_quiz_paper(
                    candidate_id=int(candidate_id),
                    phone=phone,
                    quiz_key=str(assignment.get("quiz_key") or ""),
                    token=token,
                    source_kind="public",
                    invite_start_date=invite_start_date,
                    invite_end_date=invite_end_date,
                    status="verified",
                )
            else:
                deps.set_quiz_paper_status(token, "verified")
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
    except Exception:
        pass
    return {"ok": True, "redirect": f"/quiz/{token}"}
