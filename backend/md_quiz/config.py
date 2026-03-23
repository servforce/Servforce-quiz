from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
STATIC_ROOT = PROJECT_ROOT / "static"
UI_ROOT = PROJECT_ROOT / "ui"
STORAGE_ROOT = PROJECT_ROOT / "storage"
TMP_ROOT = PROJECT_ROOT / "tmp"


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class EnvironmentSettings:
    app_env: str
    app_host: str
    app_port: int
    app_secret_key: str
    admin_username: str
    admin_password: str
    database_url: str
    storage_dir: Path
    log_level: str
    enable_legacy_bridge: bool
    legacy_mount_path: str
    enable_ui_dev_proxy: bool
    ui_build_dir: Path
    worker_poll_seconds: float
    scheduler_poll_seconds: float
    scheduler_metrics_interval_seconds: int


@dataclass(frozen=True)
class RuntimeConfigDefaults:
    sms_enabled: bool
    token_daily_threshold: int
    sms_daily_threshold: int
    allow_public_assignments: bool
    min_submit_seconds: int
    ui_theme_name: str


def load_environment_settings() -> EnvironmentSettings:
    load_dotenv()
    storage_dir = Path(os.getenv("STORAGE_DIR", str(STORAGE_ROOT))).resolve()
    return EnvironmentSettings(
        app_env=os.getenv("APP_ENV", "development"),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=int(os.getenv("PORT", "8000")),
        app_secret_key=os.getenv("APP_SECRET_KEY", os.getenv("SECRET_KEY", "dev-secret-key")),
        admin_username=os.getenv("ADMIN_USERNAME", "admin"),
        admin_password=os.getenv("ADMIN_PASSWORD", "password"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg2://postgres:admin@127.0.0.1:5433/markdown_quiz",
        ),
        storage_dir=storage_dir,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        enable_legacy_bridge=_env_bool("ENABLE_LEGACY_BRIDGE", True),
        legacy_mount_path=os.getenv("LEGACY_MOUNT_PATH", "/legacy").rstrip("/") or "/legacy",
        enable_ui_dev_proxy=_env_bool("ENABLE_UI_DEV_PROXY", False),
        ui_build_dir=Path(os.getenv("UI_BUILD_DIR", str(STATIC_ROOT / "app"))).resolve(),
        worker_poll_seconds=float(os.getenv("WORKER_POLL_SECONDS", "2")),
        scheduler_poll_seconds=float(os.getenv("SCHEDULER_POLL_SECONDS", "5")),
        scheduler_metrics_interval_seconds=int(
            os.getenv("SCHEDULER_METRICS_INTERVAL_SECONDS", "300")
        ),
    )


def load_runtime_defaults() -> RuntimeConfigDefaults:
    return RuntimeConfigDefaults(
        sms_enabled=_env_bool("RUNTIME_SMS_ENABLED", False),
        token_daily_threshold=int(os.getenv("RUNTIME_TOKEN_DAILY_THRESHOLD", "500000")),
        sms_daily_threshold=int(os.getenv("RUNTIME_SMS_DAILY_THRESHOLD", "500")),
        allow_public_assignments=_env_bool("RUNTIME_ALLOW_PUBLIC_ASSIGNMENTS", True),
        min_submit_seconds=int(os.getenv("RUNTIME_MIN_SUBMIT_SECONDS", "60")),
        ui_theme_name=os.getenv("RUNTIME_UI_THEME_NAME", "blue-green"),
    )
