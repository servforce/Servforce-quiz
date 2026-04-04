from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from backend.md_quiz.services.admin_agent_service import AdminAgentService
from backend.md_quiz.services import support_deps as deps

MCP_PATH = "/mcp"
MCP_DOCS_PATH = "/docs/reference/mcp.md"


def build_mcp_bootstrap_payload(settings: Any) -> dict[str, Any]:
    enabled = bool(getattr(settings, "mcp_enabled", False))
    return {
        "enabled": enabled,
        "path": MCP_PATH,
        "transport": "streamable-http",
        "auth_scheme": "bearer",
        "docs_path": MCP_DOCS_PATH,
    }


class McpBearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, token: str):
        super().__init__(app)
        self.token = str(token or "").strip()

    async def dispatch(self, request, call_next):
        if not str(request.url.path or "").startswith(MCP_PATH):
            return Response(status_code=404)
        if request.method == "OPTIONS":
            return await call_next(request)
        expected = self.token
        actual = str(request.headers.get("authorization") or "").strip()
        if not expected or actual != f"Bearer {expected}":
            return Response(
                content='{"error":"unauthorized"}',
                status_code=401,
                media_type="application/json",
            )
        return await call_next(request)


def create_mcp_server(*, container: Any, settings: Any) -> tuple[Any, FastAPI]:
    if not getattr(settings, "mcp_enabled", False):
        raise RuntimeError("MCP is disabled")
    token = str(getattr(settings, "mcp_auth_token", "") or "").strip()
    if not token:
        raise RuntimeError("MCP_ENABLED=1 时必须设置 MCP_AUTH_TOKEN")
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.server.transport_security import TransportSecuritySettings
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 mcp 依赖，请先安装 requirements.txt 中的 MCP SDK") from exc

    service = AdminAgentService(
        runtime_service=container.runtime_service,
        job_service=container.job_service,
        settings=settings,
    )
    # 这里的 MCP 是作为现有 FastAPI 子应用挂载，外层域名和 Host 由主应用/反向代理决定。
    # SDK 的 localhost Host 白名单保护会误伤正常远程访问，因此显式关闭该校验。
    server = FastMCP(
        "MD Quiz",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    def _audit(tool_name: str, call: Callable[[], Any]) -> Any:
        started = time.monotonic()
        try:
            result = call()
        except Exception as exc:
            try:
                deps.log_event(
                    "mcp.tool.error",
                    actor="mcp",
                    meta={
                        "tool": tool_name,
                        "duration_ms": round((time.monotonic() - started) * 1000, 1),
                        "error_type": type(exc).__name__,
                    },
                )
            except Exception:
                pass
            raise
        try:
            deps.log_event(
                "mcp.tool.call",
                actor="mcp",
                meta={
                    "tool": tool_name,
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                    "result_type": type(result).__name__,
                },
            )
        except Exception:
            pass
        return result

    @server.tool()
    def system_health() -> dict[str, Any]:
        """查看 API 健康状态。"""
        return _audit("system_health", service.system_health)

    @server.tool()
    def system_processes() -> dict[str, Any]:
        """查看 API / Worker / Scheduler 进程心跳。"""
        return _audit("system_processes", service.system_processes)

    @server.tool()
    def runtime_config_get() -> dict[str, Any]:
        """查看运行时配置。"""
        return _audit("runtime_config_get", service.runtime_config_get)

    @server.tool()
    def runtime_config_update(
        token_daily_threshold: int | None = None,
        sms_daily_threshold: int | None = None,
        allow_public_assignments: bool | None = None,
        min_submit_seconds: int | None = None,
        ui_theme_name: str | None = None,
    ) -> dict[str, Any]:
        """更新运行时配置。"""

        def _call() -> dict[str, Any]:
            payload = {
                "token_daily_threshold": token_daily_threshold,
                "sms_daily_threshold": sms_daily_threshold,
                "allow_public_assignments": allow_public_assignments,
                "min_submit_seconds": min_submit_seconds,
                "ui_theme_name": ui_theme_name,
            }
            updates = {key: value for key, value in payload.items() if value is not None}
            return service.runtime_config_update(updates)

        return _audit("runtime_config_update", _call)

    @server.tool()
    def system_status_summary() -> dict[str, Any]:
        """查看系统状态摘要。"""
        return _audit("system_status_summary", service.system_status_summary)

    @server.tool()
    def system_status_range(start: str = "", end: str = "") -> dict[str, Any]:
        """按日期区间查看系统状态。"""
        return _audit("system_status_range", lambda: service.system_status_range(start=start, end=end))

    @server.tool()
    def system_status_update_thresholds(
        llm_tokens_limit: int | None = None,
        sms_calls_limit: int | None = None,
    ) -> dict[str, Any]:
        """更新系统状态阈值。"""
        return _audit(
            "system_status_update_thresholds",
            lambda: service.system_status_update_thresholds(
                {
                    "llm_tokens_limit": llm_tokens_limit,
                    "sms_calls_limit": sms_calls_limit,
                }
            ),
        )

    @server.tool()
    def job_list() -> dict[str, Any]:
        """列出后台任务。"""
        return _audit("job_list", service.job_list)

    @server.tool()
    def job_get(job_id: str) -> dict[str, Any] | None:
        """查看单个后台任务。"""
        return _audit("job_get", lambda: service.job_get(job_id))

    @server.tool()
    def job_wait(job_id: str, timeout_seconds: int = 30, poll_seconds: float = 1.0) -> dict[str, Any]:
        """等待后台任务结束。"""
        return _audit(
            "job_wait",
            lambda: service.job_wait(
                job_id,
                timeout_seconds=timeout_seconds,
                poll_seconds=poll_seconds,
            ),
        )

    @server.tool()
    def quiz_repo_get_binding() -> dict[str, Any]:
        """查看当前测验仓库绑定和同步状态。"""
        return _audit("quiz_repo_get_binding", service.quiz_repo_get_binding)

    @server.tool()
    def quiz_repo_bind(repo_url: str) -> dict[str, Any]:
        """首次绑定测验仓库。"""
        return _audit("quiz_repo_bind", lambda: service.quiz_repo_bind(repo_url))

    @server.tool()
    def quiz_repo_rebind(repo_url: str, confirm: bool = False) -> dict[str, Any]:
        """重新绑定测验仓库。高危操作，默认预检。"""
        return _audit("quiz_repo_rebind", lambda: service.quiz_repo_rebind(repo_url, confirm=confirm))

    @server.tool()
    def quiz_repo_sync() -> dict[str, Any]:
        """创建或复用测验仓库同步任务。"""
        return _audit("quiz_repo_sync", service.quiz_repo_sync)

    @server.tool()
    def quiz_list(query: str = "") -> dict[str, Any]:
        """查看测验列表。"""
        return _audit("quiz_list", lambda: service.quiz_list(query=query))

    @server.tool()
    def quiz_get(quiz_key: str) -> dict[str, Any]:
        """查看单个测验详情。"""
        return _audit("quiz_get", lambda: service.quiz_get(quiz_key))

    @server.tool()
    def quiz_set_public_invite(quiz_key: str, enabled: bool) -> dict[str, Any]:
        """开启或关闭测验公开邀约。"""
        return _audit("quiz_set_public_invite", lambda: service.quiz_set_public_invite(quiz_key, enabled=enabled))

    @server.tool()
    def candidate_list(
        query: str = "",
        created_from: str = "",
        created_to: str = "",
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """查看候选人列表。默认手机号脱敏。"""
        return _audit(
            "candidate_list",
            lambda: service.candidate_list(
                query=query,
                created_from=created_from,
                created_to=created_to,
                page=page,
                per_page=per_page,
            ),
        )

    @server.tool()
    def candidate_ensure(name: str, phone: str) -> dict[str, Any]:
        """按手机号幂等创建或返回候选人。"""
        return _audit("candidate_ensure", lambda: service.candidate_ensure(name=name, phone=phone))

    @server.tool()
    def candidate_get(candidate_id: int, include_sensitive: bool = False) -> dict[str, Any]:
        """查看候选人详情。默认敏感字段脱敏。"""
        return _audit("candidate_get", lambda: service.candidate_get(candidate_id, include_sensitive=include_sensitive))

    @server.tool()
    def candidate_add_evaluation(candidate_id: int, evaluation: str) -> dict[str, Any]:
        """为候选人追加管理员评价。"""
        return _audit(
            "candidate_add_evaluation",
            lambda: service.candidate_add_evaluation(candidate_id, evaluation=evaluation),
        )

    @server.tool()
    def candidate_delete(candidate_id: int, confirm: bool = False) -> dict[str, Any]:
        """删除候选人。高危操作，默认预检。"""
        return _audit("candidate_delete", lambda: service.candidate_delete(candidate_id, confirm=confirm))

    @server.tool()
    def assignment_list(
        query: str = "",
        start_from: str = "",
        start_to: str = "",
        end_from: str = "",
        end_to: str = "",
        page: int = 1,
        per_page: int = 20,
        include_sensitive: bool = False,
    ) -> dict[str, Any]:
        """查看邀约与答题列表。默认手机号脱敏。"""
        return _audit(
            "assignment_list",
            lambda: service.assignment_list(
                query=query,
                start_from=start_from,
                start_to=start_to,
                end_from=end_from,
                end_to=end_to,
                page=page,
                per_page=per_page,
                include_sensitive=include_sensitive,
            ),
        )

    @server.tool()
    def assignment_create(
        quiz_key: str,
        candidate_id: int,
        invite_start_date: str,
        invite_end_date: str,
        require_phone_verification: bool = False,
        ignore_timing: bool = False,
        verify_max_attempts: int = 3,
    ) -> dict[str, Any]:
        """创建新的答题邀约。"""
        return _audit(
            "assignment_create",
            lambda: service.assignment_create(
                quiz_key=quiz_key,
                candidate_id=candidate_id,
                invite_start_date=invite_start_date,
                invite_end_date=invite_end_date,
                require_phone_verification=require_phone_verification,
                ignore_timing=ignore_timing,
                verify_max_attempts=verify_max_attempts,
            ),
        )

    @server.tool()
    def assignment_get(token: str, include_sensitive: bool = False) -> dict[str, Any]:
        """查看单个邀约和结果。默认只返回摘要。"""
        return _audit("assignment_get", lambda: service.assignment_get(token, include_sensitive=include_sensitive))

    @server.tool()
    def assignment_set_handling(token: str, handled: bool, handled_by: str = "mcp") -> dict[str, Any]:
        """设置答题结果的处理状态。"""
        return _audit(
            "assignment_set_handling",
            lambda: service.assignment_set_handling(token, handled=handled, handled_by=handled_by),
        )

    @server.tool()
    def assignment_delete(token: str, confirm: bool = False) -> dict[str, Any]:
        """删除邀约。高危操作，默认预检。"""
        return _audit("assignment_delete", lambda: service.assignment_delete(token, confirm=confirm))

    server.settings.streamable_http_path = MCP_PATH
    mcp_http_app = server.streamable_http_app()

    app = FastAPI()
    if getattr(settings, "mcp_cors_allow_origins", ()):
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(getattr(settings, "mcp_cors_allow_origins", ())),
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Mcp-Session-Id"],
            expose_headers=["Mcp-Session-Id"],
        )
    app.add_middleware(McpBearerAuthMiddleware, token=token)
    app.mount("/", mcp_http_app)
    return server, app
