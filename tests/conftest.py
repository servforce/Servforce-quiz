import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg2
import pytest
from dotenv import dotenv_values
from psycopg2 import sql


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DEFAULT_DATABASE_URL = "postgresql://admin:pasword@127.0.0.1:5433/md_quiz"
_TEST_DATABASE_SUFFIX = "_pytest"
_TRUNCATE_SQL = """
TRUNCATE TABLE
  system_log,
  process_heartbeat,
  runtime_job,
  runtime_daily_metric,
  runtime_kv,
  quiz_version_asset,
  quiz_archive,
  quiz_paper,
  assignment_record,
  quiz_version,
  quiz_asset,
  quiz_definition,
  candidate
RESTART IDENTITY CASCADE
"""


def _normalize_database_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return _DEFAULT_DATABASE_URL
    if value.startswith("postgresql+psycopg2://"):
        value = "postgresql://" + value[len("postgresql+psycopg2://") :]
    parsed = urlsplit(value)
    if parsed.scheme != "postgresql" or not parsed.hostname or not parsed.path:
        return _DEFAULT_DATABASE_URL
    return urlunsplit(parsed)


def _load_base_database_url() -> str:
    raw = str(os.getenv("DATABASE_URL") or "").strip()
    if raw:
        return _normalize_database_url(raw)
    env_values = dotenv_values(ROOT / ".env")
    return _normalize_database_url(str(env_values.get("DATABASE_URL") or ""))


def _build_pytest_database_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    db_name = parsed.path.lstrip("/") or "md_quiz"
    if not db_name.endswith(_TEST_DATABASE_SUFFIX):
        db_name = f"{db_name}{_TEST_DATABASE_SUFFIX}"
    return urlunsplit(parsed._replace(path=f"/{db_name}"))


def _resolve_pytest_database_url() -> str:
    explicit = str(os.getenv("PYTEST_DATABASE_URL") or "").strip()
    if explicit:
        return _normalize_database_url(explicit)
    return _build_pytest_database_url(_load_base_database_url())


def _connect(database_url: str, *, dbname: str | None = None):
    parsed = urlsplit(database_url)
    return psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port,
        user=parsed.username,
        password=parsed.password,
        dbname=dbname or parsed.path.lstrip("/"),
    )


def _ensure_database_exists(database_url: str) -> None:
    parsed = urlsplit(database_url)
    target_db = parsed.path.lstrip("/")
    last_error: Exception | None = None
    for maintenance_db in ("postgres", "template1"):
        conn = None
        try:
            conn = _connect(database_url, dbname=maintenance_db)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target_db,))
                if cur.fetchone():
                    return
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
                return
        except psycopg2.Error as exc:
            last_error = exc
        finally:
            if conn is not None:
                conn.close()
    raise RuntimeError(f"无法创建 pytest 测试库 {target_db!r}: {last_error}")


_PYTEST_DATABASE_URL = _resolve_pytest_database_url()
_ensure_database_exists(_PYTEST_DATABASE_URL)
os.environ["DATABASE_URL"] = _PYTEST_DATABASE_URL
os.environ.setdefault("APP_ENV", "test")


@pytest.fixture(autouse=True)
def _reset_database_state():
    from backend.md_quiz.storage.db import conn_scope, init_db

    init_db()
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(_TRUNCATE_SQL)
    yield
