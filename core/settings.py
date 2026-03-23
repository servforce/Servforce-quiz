from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    log_level: str
    secret_key: str
    admin_username: str
    admin_password: str
    database_url: str
    storage_dir: Path
    openai_api_key: str
    openai_base_url: str
    openai_model: str


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
    default_url = "postgresql://postgres:admin@127.0.0.1:5433/markdown_quiz"
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


def load_settings() -> Settings:
    load_dotenv()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger = build_logger(log_level)
    return Settings(
        log_level=log_level,
        secret_key=os.getenv("APP_SECRET_KEY", os.getenv("SECRET_KEY", "dev-secret-key")),
        admin_username=os.getenv("ADMIN_USERNAME", "admin"),
        admin_password=os.getenv("ADMIN_PASSWORD", "password"),
        database_url=_normalize_database_url(os.getenv("DATABASE_URL", ""), logger=logger),
        storage_dir=Path(os.getenv("STORAGE_DIR", str(BASE_DIR / "storage"))).resolve(),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_base_url=os.getenv(
            "OPENAI_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
        ).rstrip("/"),
        openai_model=os.getenv("OPENAI_MODEL", ""),
    )
