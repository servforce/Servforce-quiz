#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage: ./scripts/dev/install-deps.sh [all|python|node]

Commands:
  all     安装 Python 和前端依赖（默认）
  python  创建/复用 .venv 并安装 Python 依赖
  node    安装 static/ 下的前端依赖
EOF
}

resolve_venv_python() {
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    echo "$ROOT_DIR/.venv/bin/python"
    return 0
  fi
  if [[ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]]; then
    echo "$ROOT_DIR/.venv/Scripts/python.exe"
    return 0
  fi
  return 1
}

resolve_bootstrap_python() {
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi
  echo "缺少可用的 Python 解释器（python3 或 python）。" >&2
  exit 1
}

install_python_deps() {
  local python_bin=""
  if ! python_bin="$(resolve_venv_python)"; then
    local bootstrap_python=""
    bootstrap_python="$(resolve_bootstrap_python)"
    echo "[python] 创建虚拟环境 .venv"
    "$bootstrap_python" -m venv "$ROOT_DIR/.venv"
    python_bin="$(resolve_venv_python)"
  fi

  echo "[python] 安装 requirements.txt 和 pytest"
  "$python_bin" -m pip install --upgrade pip
  "$python_bin" -m pip install -r requirements.txt pytest
}

install_node_deps() {
  if [[ ! -f "$ROOT_DIR/static/package.json" ]]; then
    echo "[node] 未找到 static/package.json，跳过前端依赖安装"
    return 0
  fi
  if ! command -v npm >/dev/null 2>&1; then
    echo "缺少 npm，无法安装 static/ 前端依赖。" >&2
    exit 1
  fi

  echo "[node] 安装 static/ 前端依赖"
  (
    cd "$ROOT_DIR/static"
    npm ci
  )
}

case "${1:-all}" in
  all)
    install_python_deps
    install_node_deps
    ;;
  python)
    install_python_deps
    ;;
  node)
    install_node_deps
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
