from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.md_quiz.api import admin_router, public_router, system_router
from backend.md_quiz.config import PROJECT_ROOT, load_environment_settings, load_runtime_defaults
from backend.md_quiz.legacy import build_legacy_bridge
from backend.md_quiz.models import RuntimeConfig
from backend.md_quiz.services import JobService, RuntimeService
from backend.md_quiz.storage import JsonJobStore, JsonProcessStore, JsonRuntimeConfigStore


@dataclass
class AppContainer:
    settings: object
    runtime_service: RuntimeService
    job_service: JobService


def _build_container() -> AppContainer:
    settings = load_environment_settings()
    defaults = RuntimeConfig(**load_runtime_defaults().__dict__)
    runtime_root = settings.storage_dir / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    runtime_service = RuntimeService(
        process_store=JsonProcessStore(runtime_root / "processes.json"),
        runtime_config_store=JsonRuntimeConfigStore(runtime_root / "runtime-config.json", defaults),
    )
    job_service = JobService(JsonJobStore(runtime_root / "jobs.json"))
    return AppContainer(settings=settings, runtime_service=runtime_service, job_service=job_service)
def _resolve_ui_index(ui_build_dir: Path) -> Path | None:
    index_path = ui_build_dir / "index.html"
    if index_path.exists():
        return index_path
    return None


def create_app() -> FastAPI:
    container = _build_container()
    settings = container.settings

    @asynccontextmanager
    async def _lifespan(_: FastAPI):
        container.runtime_service.heartbeat(
            "api", name="api", status="running", message="startup-complete"
        )
        yield

    app = FastAPI(
        title="md-quiz",
        version="2.0.0-alpha",
        summary="FastAPI + Worker + Scheduler 重构入口",
        lifespan=_lifespan,
    )
    app.state.container = container
    app.add_middleware(SessionMiddleware, secret_key=settings.app_secret_key)

    app.include_router(system_router)
    app.include_router(admin_router)
    app.include_router(public_router)

    static_root = PROJECT_ROOT / "static"
    if static_root.exists():
        app.mount("/static", StaticFiles(directory=static_root), name="static")

    if settings.enable_legacy_bridge:
        app.mount(settings.legacy_mount_path, build_legacy_bridge())
        @app.get("/legacy", include_in_schema=False)
        def _legacy_root():
            return RedirectResponse(url=f"{settings.legacy_mount_path}/admin")

    @app.get("/healthz", include_in_schema=False)
    def _healthz():
        return {"ok": True}

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa_fallback(full_path: str = ""):
        index_path = _resolve_ui_index(settings.ui_build_dir)
        if index_path is None:
            return {
                "message": "UI 尚未构建，请先执行 scripts/dev/build-ui.sh",
                "ui_build_dir": str(settings.ui_build_dir),
                "legacy_url": f"{settings.legacy_mount_path}/admin" if settings.enable_legacy_bridge else None,
            }
        return FileResponse(index_path)

    return app
