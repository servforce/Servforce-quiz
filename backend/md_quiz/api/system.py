from __future__ import annotations

from fastapi import APIRouter, Depends

from .deps import get_container

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def get_health(container=Depends(get_container)):
    runtime = container.runtime_service
    runtime.heartbeat("api", name="api", message="http-ready")
    return {
        "status": "ok",
        "service": "md-quiz",
        "mode": "fastapi",
        "legacy_bridge": container.settings.enable_legacy_bridge,
    }


@router.get("/processes")
def get_processes(container=Depends(get_container)):
    return {"items": [item.model_dump() for item in container.runtime_service.list_processes()]}


@router.get("/bootstrap")
def get_bootstrap(container=Depends(get_container)):
    return {
        "brand": {
            "name": "MD Quiz",
            "tagline": "蓝绿主题的招聘考试控制台",
            "primary": "#2563eb",
            "accent": "#22c55e",
        },
        "ui": {
            "path": "/",
            "legacy_path": container.settings.legacy_mount_path,
        },
        "runtime_config": container.runtime_service.get_runtime_config().model_dump(),
    }
