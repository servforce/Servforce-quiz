from __future__ import annotations

from core.settings import BASE_DIR, build_logger, load_settings

settings = load_settings()
logger = build_logger(settings.log_level)

LOG_LEVEL = settings.log_level
SECRET_KEY = settings.secret_key
ADMIN_USERNAME = settings.admin_username
ADMIN_PASSWORD = settings.admin_password
DATABASE_URL = settings.database_url
STORAGE_DIR = settings.storage_dir
OPENAI_API_KEY = settings.openai_api_key
OPENAI_BASE_URL = settings.openai_base_url
OPENAI_MODEL = settings.openai_model

__all__ = [
    "ADMIN_PASSWORD",
    "ADMIN_USERNAME",
    "BASE_DIR",
    "DATABASE_URL",
    "LOG_LEVEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "SECRET_KEY",
    "STORAGE_DIR",
    "logger",
    "settings",
]
