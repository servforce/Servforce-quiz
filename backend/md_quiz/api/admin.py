from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from .deps import get_container

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminLoginPayload(BaseModel):
    username: str
    password: str


class RuntimeConfigPatch(BaseModel):
    sms_enabled: bool | None = None
    token_daily_threshold: int | None = Field(default=None, ge=0)
    sms_daily_threshold: int | None = Field(default=None, ge=0)
    allow_public_assignments: bool | None = None
    min_submit_seconds: int | None = Field(default=None, ge=0)
    ui_theme_name: str | None = None


class EnqueueJobPayload(BaseModel):
    kind: str
    payload: dict = Field(default_factory=dict)


def _require_admin(request: Request):
    if not request.session.get("admin_logged_in"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="需要先登录后台")


@router.post("/session/login")
def login(payload: AdminLoginPayload, request: Request, container=Depends(get_container)):
    settings = container.settings
    if payload.username != settings.admin_username or payload.password != settings.admin_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    request.session["admin_logged_in"] = True
    request.session["admin_username"] = payload.username
    return {"ok": True, "username": payload.username}


@router.post("/session/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/session")
def session(request: Request):
    return {
        "authenticated": bool(request.session.get("admin_logged_in")),
        "username": request.session.get("admin_username"),
    }


@router.get("/bootstrap")
def bootstrap(request: Request, container=Depends(get_container)):
    _require_admin(request)
    settings = container.settings
    return {
        "brand": {"name": "MD Quiz", "theme": "blue-green"},
        "navigation": [
            {"key": "overview", "label": "新控制台概览", "href": "#/admin/overview"},
            {"key": "jobs", "label": "任务系统", "href": "#/admin/jobs"},
            {"key": "legacy", "label": "旧后台桥接", "href": f"{settings.legacy_mount_path}/admin"},
        ],
        "cards": [
            {"label": "后端架构", "value": "FastAPI + Worker + Scheduler"},
            {"label": "UI 工作区", "value": "ui/ -> static/app"},
            {"label": "兼容模式", "value": "legacy bridge 已启用" if settings.enable_legacy_bridge else "disabled"},
        ],
    }


@router.get("/config")
def get_runtime_config(request: Request, container=Depends(get_container)):
    _require_admin(request)
    return container.runtime_service.get_runtime_config().model_dump()


@router.put("/config")
def update_runtime_config(payload: RuntimeConfigPatch, request: Request, container=Depends(get_container)):
    _require_admin(request)
    updates = payload.model_dump(exclude_none=True)
    return container.runtime_service.update_runtime_config(updates).model_dump()


@router.get("/jobs")
def list_jobs(request: Request, container=Depends(get_container)):
    _require_admin(request)
    return {"items": [item.model_dump() for item in container.job_service.list_jobs()]}


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
def enqueue_job(payload: EnqueueJobPayload, request: Request, container=Depends(get_container)):
    _require_admin(request)
    job = container.job_service.enqueue(payload.kind, payload=payload.payload, source="admin-api")
    return job.model_dump()
