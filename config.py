from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logger = logging.getLogger("markdown_quiz")
if not logger.handlers:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = os.getenv("APP_SECRET_KEY", os.getenv("SECRET_KEY", "dev-secret-key"))

# 管理员账号密码
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

# 数据库的url地址
def _get_database_url() -> str:
    default_url = "postgresql://postgres:postgres@127.0.0.1:5432/markdown_quiz"
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        return default_url      # 没有url就用默认的
    url = raw
    if url.startswith("postgresql+psycopg2://"):
        url = "postgresql://" + url[len("postgresql+psycopg2://") :]
    try:
        u = urlsplit(url)
    except Exception:       # 字符错误，抛出错误
        logger.warning("Invalid DATABASE_URL, fallback to default: %r", raw)
        return default_url
    if u.scheme != "postgresql":        # 没有使用postgreSQL数据库
        logger.warning("Unsupported DATABASE_URL scheme, fallback to default: %r", raw)
        return default_url

    # Common mistake: using placeholder host literally as "host"
    if (u.hostname or "").lower() == "host":
        logger.warning('DATABASE_URL host is "host" (placeholder). Using 127.0.0.1 instead.')      # 如果host这个错误的话，则使用127.0.0.1替代
        # replace only hostname part in netloc (keep userinfo/port)
        netloc = u.netloc       # 用户名和密码
        if "@" in netloc:
            userinfo, hostport = netloc.rsplit("@", 1)      # 用户名、密码
            if ":" in hostport:
                _, port = hostport.split(":", 1)
                hostport = f"127.0.0.1:{port}"
            else:
                hostport = "127.0.0.1"
            netloc = f"{userinfo}@{hostport}"
        else:
            if ":" in netloc:
                _, port = netloc.split(":", 1)
                netloc = f"127.0.0.1:{port}"
            else:
                netloc = "127.0.0.1"
        u = u._replace(netloc=netloc)

    return urlunsplit(u)


DATABASE_URL = _get_database_url()

# 没有设置环境变量，就选择根目录文件下的命令
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", str(BASE_DIR / "storage"))).resolve()

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
QWEN_MODEL = os.getenv("QWEN_MODEL", os.getenv("LLM_MODEL", "qwen3-32b"))
LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# LLM provider selection:
# - "openai_compat": OpenAI-compatible HTTP endpoints (DashScope / 讯飞 MaaS / 自建网关等)
# - "ollama": local Ollama server (free, no API key)
# Default: use openai_compat when LLM_API_KEY is set; otherwise fallback to ollama.
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "").strip() or ("openai_compat" if LLM_API_KEY else "ollama")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", os.getenv("LLM_MODEL", "qwen2.5:7b-instruct"))
