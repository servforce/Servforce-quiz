#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source scripts/dev/load-env.sh
fi

PID_DIR="tmp/pids"
LOG_DIR="tmp/logs"
API_PID_FILE="${PID_DIR}/api.pid"
WORKER_PID_FILE="${PID_DIR}/worker.pid"
SCHED_PID_FILE="${PID_DIR}/scheduler.pid"
API_LOG_FILE="${LOG_DIR}/api.log"
WORKER_LOG_FILE="${LOG_DIR}/worker.log"
SCHED_LOG_FILE="${LOG_DIR}/scheduler.log"

mkdir -p "$PID_DIR" "$LOG_DIR"

build_admin_css() {
  if [[ -f "${ROOT_DIR}/static/package.json" ]]; then
    echo "[ui] building admin css"
    (cd "${ROOT_DIR}/static" && npm run build:admin-css)
  fi
}

usage() {
  cat <<'EOF'
Usage: ./scripts/dev/devctl.sh <command>

Commands:
  start
  stop
  restart
  status
  logs
EOF
}

read_pid() {
  local file="$1"
  if [[ -f "$file" ]]; then
    tr -d '\n' <"$file" || true
  fi
}

write_pid() {
  local file="$1"
  local pid="$2"
  echo -n "$pid" >"$file"
}

is_running() {
  local pid="${1:-}"
  if [[ -z "${pid:-}" ]]; then
    return 1
  fi
  kill -0 "$pid" >/dev/null 2>&1
}

start_one() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  shift 3
  local existing
  existing="$(read_pid "$pid_file")"
  if is_running "$existing"; then
    echo "[${name}] already running pid=${existing}"
    return 0
  fi
  : >"$log_file"
  nohup "$@" >>"$log_file" 2>&1 &
  local pid="$!"
  write_pid "$pid_file" "$pid"
  echo "[${name}] started pid=${pid} log=${log_file}"
}

stop_one() {
  local name="$1"
  local pid_file="$2"
  local pid
  pid="$(read_pid "$pid_file")"
  if ! is_running "$pid"; then
    echo "[${name}] stopped"
    rm -f "$pid_file"
    return 0
  fi
  kill "$pid" >/dev/null 2>&1 || true
  for _ in {1..30}; do
    if ! is_running "$pid"; then
      rm -f "$pid_file"
      echo "[${name}] stopped"
      return 0
    fi
    sleep 0.2
  done
  kill -9 "$pid" >/dev/null 2>&1 || true
  rm -f "$pid_file"
  echo "[${name}] killed pid=${pid}"
}

do_start() {
  build_admin_css
  start_one api "$API_PID_FILE" "$API_LOG_FILE" bash scripts/dev/run-api.sh
  start_one worker "$WORKER_PID_FILE" "$WORKER_LOG_FILE" bash scripts/dev/run-worker.sh
  start_one scheduler "$SCHED_PID_FILE" "$SCHED_LOG_FILE" bash scripts/dev/run-scheduler.sh
}

do_stop() {
  stop_one scheduler "$SCHED_PID_FILE"
  stop_one worker "$WORKER_PID_FILE"
  stop_one api "$API_PID_FILE"
}

do_status() {
  local api_pid worker_pid sched_pid
  api_pid="$(read_pid "$API_PID_FILE")"
  worker_pid="$(read_pid "$WORKER_PID_FILE")"
  sched_pid="$(read_pid "$SCHED_PID_FILE")"
  if is_running "$api_pid"; then
    echo "[api] running pid=${api_pid}"
  else
    echo "[api] stopped"
  fi
  if is_running "$worker_pid"; then
    echo "[worker] running pid=${worker_pid}"
  else
    echo "[worker] stopped"
  fi
  if is_running "$sched_pid"; then
    echo "[scheduler] running pid=${sched_pid}"
  else
    echo "[scheduler] stopped"
  fi
}

do_logs() {
  tail -n 100 -f "$API_LOG_FILE" "$WORKER_LOG_FILE" "$SCHED_LOG_FILE"
}

case "${1:-}" in
  start) do_start ;;
  stop) do_stop ;;
  restart) do_stop; do_start ;;
  status) do_status ;;
  logs) do_logs ;;
  *) usage; exit 1 ;;
esac
