from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = PROJECT_ROOT
BACKEND_ROOT = PROJECT_ROOT / "backend"


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_csv(name: str) -> tuple[str, ...]:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return ()
    values = [item.strip() for item in raw.split(",")]
    return tuple(item for item in values if item)


def build_logger(level: str) -> logging.Logger:
    logger = logging.getLogger("markdown_quiz")
    if not logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        )
    else:
        logger.setLevel(level)
    return logger


def _normalize_database_url(raw: str, *, logger: logging.Logger) -> str:
    default_url = "postgresql://admin:pasword@127.0.0.1:5433/markdown_quiz"
    value = (raw or "").strip()
    if not value:
        return default_url
    if value.startswith("postgresql+psycopg2://"):
        value = "postgresql://" + value[len("postgresql+psycopg2://") :]
    try:
        parsed = urlsplit(value)
    except Exception:
        logger.warning("Invalid DATABASE_URL, fallback to default: %r", raw)
        return default_url
    if parsed.scheme != "postgresql":
        logger.warning("Unsupported DATABASE_URL scheme, fallback to default: %r", raw)
        return default_url
    if (parsed.hostname or "").lower() != "host":
        return urlunsplit(parsed)
    logger.warning('DATABASE_URL host is "host" (placeholder). Using 127.0.0.1 instead.')
    netloc = parsed.netloc
    if "@" in netloc:
        userinfo, hostport = netloc.rsplit("@", 1)
        if ":" in hostport:
            _host, port = hostport.split(":", 1)
            hostport = f"127.0.0.1:{port}"
        else:
            hostport = "127.0.0.1"
        netloc = f"{userinfo}@{hostport}"
    else:
        if ":" in netloc:
            _host, port = netloc.split(":", 1)
            netloc = f"127.0.0.1:{port}"
        else:
            netloc = "127.0.0.1"
    return urlunsplit(parsed._replace(netloc=netloc))


@dataclass(frozen=True)
class EnvironmentSettings:
    app_env: str
    app_host: str
    app_port: int
    app_secret_key: str
    admin_username: str
    admin_password: str
    database_url: str
    log_level: str
    worker_poll_seconds: float
    scheduler_poll_seconds: float
    scheduler_metrics_interval_seconds: int
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    exam_repo_sync_proxy: str
    mcp_enabled: bool
    mcp_auth_token: str
    mcp_cors_allow_origins: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeConfigDefaults:
    token_daily_threshold: int
    sms_daily_threshold: int
    allow_public_assignments: bool
    min_submit_seconds: int
    ui_theme_name: str


def load_environment_settings() -> EnvironmentSettings:
    load_dotenv()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    app_logger = build_logger(log_level)
    return EnvironmentSettings(
        app_env=os.getenv("APP_ENV", "development"),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=int(os.getenv("PORT", "8000")),
        app_secret_key=os.getenv("APP_SECRET_KEY", os.getenv("SECRET_KEY", "dev-secret-key")),
        admin_username=os.getenv("ADMIN_USERNAME", "admin"),
        admin_password=os.getenv("ADMIN_PASSWORD", "password"),
        database_url=_normalize_database_url(os.getenv("DATABASE_URL", ""), logger=app_logger),
        log_level=log_level,
        worker_poll_seconds=float(os.getenv("WORKER_POLL_SECONDS", "2")),
        scheduler_poll_seconds=float(os.getenv("SCHEDULER_POLL_SECONDS", "5")),
        scheduler_metrics_interval_seconds=int(
            os.getenv("SCHEDULER_METRICS_INTERVAL_SECONDS", "300")
        ),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_base_url=os.getenv(
            "OPENAI_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
        ).rstrip("/"),
        openai_model=os.getenv("OPENAI_MODEL", ""),
        exam_repo_sync_proxy=os.getenv("EXAM_REPO_SYNC_PROXY", "").strip(),
        mcp_enabled=_env_bool("MCP_ENABLED", False),
        mcp_auth_token=os.getenv("MCP_AUTH_TOKEN", "").strip(),
        mcp_cors_allow_origins=_env_csv("MCP_CORS_ALLOW_ORIGINS"),
    )


def load_runtime_defaults() -> RuntimeConfigDefaults:
    return RuntimeConfigDefaults(
        token_daily_threshold=int(os.getenv("RUNTIME_TOKEN_DAILY_THRESHOLD", "500000")),
        sms_daily_threshold=int(os.getenv("RUNTIME_SMS_DAILY_THRESHOLD", "500")),
        allow_public_assignments=_env_bool("RUNTIME_ALLOW_PUBLIC_ASSIGNMENTS", True),
        min_submit_seconds=int(os.getenv("RUNTIME_MIN_SUBMIT_SECONDS", "60")),
        ui_theme_name=os.getenv("RUNTIME_UI_THEME_NAME", "blue-green"),
    )


settings = load_environment_settings()
logger = build_logger(settings.log_level)

LOG_LEVEL = settings.log_level
SECRET_KEY = settings.app_secret_key
ADMIN_USERNAME = settings.admin_username
ADMIN_PASSWORD = settings.admin_password
DATABASE_URL = settings.database_url
OPENAI_API_KEY = settings.openai_api_key
OPENAI_BASE_URL = settings.openai_base_url
OPENAI_MODEL = settings.openai_model
EXAM_REPO_SYNC_PROXY = settings.exam_repo_sync_proxy


__all__ = [
    "ADMIN_PASSWORD",
    "ADMIN_USERNAME",
    "BACKEND_ROOT",
    "BASE_DIR",
    "DATABASE_URL",
    "EXAM_REPO_SYNC_PROXY",
    "EnvironmentSettings",
    "LOG_LEVEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "PROJECT_ROOT",
    "RuntimeConfigDefaults",
    "SECRET_KEY",
    "build_logger",
    "load_environment_settings",
    "load_runtime_defaults",
    "logger",
    "settings",
]
