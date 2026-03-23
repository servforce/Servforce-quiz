from __future__ import annotations

from fastapi import APIRouter, Depends

from .deps import get_container

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/bootstrap")
def bootstrap(container=Depends(get_container)):
    config = container.runtime_service.get_runtime_config()
    return {
        "brand": {"name": "MD Quiz", "theme": config.ui_theme_name},
        "flows": [
            {"key": "verify", "label": "身份验证", "href": "#/public/verify"},
            {"key": "exam", "label": "在线答题", "href": "#/public/exam"},
            {"key": "resume", "label": "简历上传", "href": "#/public/resume"},
        ],
        "features": {
            "sms_enabled": config.sms_enabled,
            "allow_public_assignments": config.allow_public_assignments,
            "min_submit_seconds": config.min_submit_seconds,
        },
    }
