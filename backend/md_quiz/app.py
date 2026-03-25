from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
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


def _redirect_target(full_path: str, request: Request) -> str:
    normalized = str(full_path or "").lstrip("/")
    target = f"/{normalized}" if normalized else "/admin"
    query = str(request.url.query or "").strip()
    if query:
        return f"{target}?{query}"
    return target


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
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.app_secret_key,
        session_cookie="api_session",
    )

    app.include_router(system_router)
    app.include_router(admin_router)
    app.include_router(public_router)

    static_root = PROJECT_ROOT / "static"
    if static_root.exists():
        app.mount("/static", StaticFiles(directory=static_root), name="static")

    @app.get("/healthz", include_in_schema=False)
    def _healthz():
        return {"ok": True}

    @app.api_route(
        "/legacy",
        methods=["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"],
        include_in_schema=False,
    )
    def _legacy_root(request: Request):
        return RedirectResponse(url=_redirect_target("", request), status_code=307)

    @app.api_route(
        "/legacy/{full_path:path}",
        methods=["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"],
        include_in_schema=False,
    )
    def _legacy_path(full_path: str, request: Request):
        return RedirectResponse(url=_redirect_target(full_path, request), status_code=307)

    app.mount("/", build_legacy_bridge(), name="legacy-root")

    return app
