#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage: ./scripts/dev/webctl.sh <command>

Commands:
  run       兼容别名，前台运行当前 FastAPI API 进程
  start     兼容别名，转发到 ./scripts/dev/devctl.sh start
  stop      兼容别名，转发到 ./scripts/dev/devctl.sh stop
  restart   兼容别名，转发到 ./scripts/dev/devctl.sh restart
  status    兼容别名，转发到 ./scripts/dev/devctl.sh status
  logs      兼容别名，转发到 ./scripts/dev/devctl.sh logs
EOF
}

legacy_notice() {
  echo "[webctl] 旧 Flask/web 单进程入口已移除，当前脚本仅保留为兼容别名。" >&2
}

cmd="${1:-status}"
case "$cmd" in
  run)
    legacy_notice
    exec bash scripts/dev/run-api.sh
    ;;
  start | stop | restart | status | logs)
    legacy_notice
    exec bash scripts/dev/devctl.sh "$cmd"
    ;;
  -h | --help | help)
    usage
    ;;
  *)
    echo "[webctl] unknown command: ${cmd}" >&2
    usage >&2
    exit 2
    ;;
esac
