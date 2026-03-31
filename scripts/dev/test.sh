#!/usr/bin/env bash
set -euo pipefail

# 用项目自己的虚拟环境运行 pytest。
# 传给这个脚本的参数会原样转发给 pytest。

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

# 固定使用仓库内的解释器，避免测试环境飘到系统 Python。
PYTHON_BIN=""
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif [[ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/Scripts/python.exe"
fi

if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "Missing project python interpreter (.venv/bin/python or .venv/Scripts/python.exe)." >&2
  echo "Run: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt pytest" >&2
  exit 1
fi

# 示例：
#   scripts/dev/test.sh -q
#   scripts/dev/test.sh tests/test_runtime_contract.py
exec "$PYTHON_BIN" -m pytest "$@"
