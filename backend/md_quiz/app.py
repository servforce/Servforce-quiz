from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.md_quiz.api import admin_router, public_router, system_router
from backend.md_quiz.config import PROJECT_ROOT, load_environment_settings, load_runtime_defaults
from backend.md_quiz.models import RuntimeConfig
from backend.md_quiz.services import JobService, RuntimeService
from backend.md_quiz.services import exam_helpers, runtime_bootstrap
from backend.md_quiz.storage import JobStore, ProcessStore, RuntimeConfigStore


@dataclass
class AppContainer:
    settings: object
    runtime_service: RuntimeService
    job_service: JobService


def _build_container() -> AppContainer:
    settings = load_environment_settings()
    defaults = RuntimeConfig(**load_runtime_defaults().__dict__)
    runtime_service = RuntimeService(
        process_store=ProcessStore(),
        runtime_config_store=RuntimeConfigStore(defaults),
    )
    job_service = JobService(JobStore())
    return AppContainer(settings=settings, runtime_service=runtime_service, job_service=job_service)


def _redirect_target(full_path: str, request: Request) -> str:
    normalized = str(full_path or "").lstrip("/")
    target = f"/{normalized}" if normalized else "/admin"
    query = str(request.url.query or "").strip()
    if query:
        return f"{target}?{query}"
    return target


def _serve_spa(root: Path, filename: str) -> FileResponse:
    path = root / filename
    if not path.exists():
        raise FileNotFoundError(str(path))
    return FileResponse(path)


def create_app() -> FastAPI:
    container = _build_container()
    settings = container.settings
    static_root = PROJECT_ROOT / "static"

    @asynccontextmanager
    async def _lifespan(_: FastAPI):
        runtime_bootstrap.bootstrap_runtime()
        container.runtime_service.heartbeat(
            "api", name="api", status="running", message="startup-complete"
        )
        yield

    app = FastAPI(
        title="md-quiz",
        version="3.0.0",
        summary="FastAPI 单栈入口",
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

    if static_root.exists():
        app.mount("/static", StaticFiles(directory=static_root), name="static")

    @app.get("/healthz", include_in_schema=False)
    def _healthz():
        return {"ok": True}

    @app.get("/exams/{exam_key}/assets/{relpath:path}", include_in_schema=False)
    def public_exam_asset(exam_key: str, relpath: str):
        asset = exam_helpers._resolve_exam_asset_payload(exam_key, relpath)
        if not asset:
            return Response(status_code=404)
        content, mime = asset
        return Response(content=content, media_type=mime)

    @app.get("/exams/versions/{version_id}/assets/{relpath:path}", include_in_schema=False)
    def public_exam_version_asset(version_id: int, relpath: str):
        asset = exam_helpers._resolve_exam_asset_payload_by_version(version_id, relpath)
        if not asset:
            return Response(status_code=404)
        content, mime = asset
        return Response(content=content, media_type=mime)

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        if request.session.get("admin_logged_in"):
            return RedirectResponse(url="/admin", status_code=307)
        return RedirectResponse(url="/admin/login", status_code=307)

    @app.api_route(
        "/legacy",
        methods=["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"],
        include_in_schema=False,
    )
    def legacy_root(request: Request):
        return RedirectResponse(url=_redirect_target("", request), status_code=307)

    @app.api_route(
        "/legacy/{full_path:path}",
        methods=["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"],
        include_in_schema=False,
    )
    def legacy_path(full_path: str, request: Request):
        return RedirectResponse(url=_redirect_target(full_path, request), status_code=307)

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/login", include_in_schema=False)
    @app.get("/admin/{full_path:path}", include_in_schema=False)
    def admin_spa(full_path: str | None = None):
        _ = full_path
        return _serve_spa(static_root, "admin/index.html")

    @app.get("/p/{token:path}", include_in_schema=False)
    @app.get("/t/{token:path}", include_in_schema=False)
    @app.get("/resume/{token:path}", include_in_schema=False)
    @app.get("/exam/{token:path}", include_in_schema=False)
    @app.get("/done/{token:path}", include_in_schema=False)
    @app.get("/a/{token:path}", include_in_schema=False)
    def public_spa(token: str):
        _ = token
        return _serve_spa(static_root, "public/index.html")

    return app
