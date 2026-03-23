#!/usr/bin/env bash
set -euo pipefail

# 用项目自己的虚拟环境启动 Flask Web 应用。
# 如果存在 .env，就先加载，保证本地开发配置与日常运行一致。

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

# 在启动 Python 前，把 .env 里的变量导出到当前 shell。
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# 固定使用仓库内的解释器，避免跑到系统 Python 上导致依赖不一致。
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing .venv/bin/python. Run: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
  exit 1
fi

# app.py 是兼容入口，会负责装配并启动 Flask 应用。
exec "$PYTHON_BIN" app.py
