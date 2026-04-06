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

ensure_venv_pip() {
  local python_bin="$1"
  local bootstrap_python="$2"

  if "$python_bin" -m pip --version >/dev/null 2>&1; then
    return 0
  fi

  echo "[python] 检测到虚拟环境缺少 pip，尝试使用 ensurepip 修复"
  if "$python_bin" -m ensurepip --upgrade >/dev/null 2>&1; then
    if "$python_bin" -m pip --version >/dev/null 2>&1; then
      return 0
    fi
  fi

  echo "[python] 虚拟环境内 ensurepip 修复失败，尝试使用系统 Python 补装 pip"
  if "$bootstrap_python" -m ensurepip --upgrade >/dev/null 2>&1; then
    if "$python_bin" -m pip --version >/dev/null 2>&1; then
      return 0
    fi
  fi

  cat >&2 <<'EOF'
缺少 pip，且自动修复失败。
请先确认系统已安装 venv/ensurepip 相关组件，例如 Ubuntu/Debian 上可执行：
  apt-get update
  apt-get install -y python3-venv
然后删除 .venv 后重新执行：
  ./scripts/dev/install-deps.sh python
EOF
  exit 1
}

install_python_deps() {
  local bootstrap_python=""
  bootstrap_python="$(resolve_bootstrap_python)"
  local python_bin=""
  if ! python_bin="$(resolve_venv_python)"; then
    echo "[python] 创建虚拟环境 .venv"
    "$bootstrap_python" -m venv "$ROOT_DIR/.venv"
    python_bin="$(resolve_venv_python)"
  fi

  ensure_venv_pip "$python_bin" "$bootstrap_python"

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
