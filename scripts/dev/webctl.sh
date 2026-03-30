#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

PID_DIR="tmp/pids"
LOG_DIR="tmp/logs"
PID_FILE="${PID_DIR}/web.pid"
LOG_FILE="${LOG_DIR}/web.log"

mkdir -p "$PID_DIR" "$LOG_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PYTHON_BIN=""
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif [[ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/Scripts/python.exe"
fi
IS_WINDOWS_PYTHON=0
if [[ "$PYTHON_BIN" == *.exe ]]; then
  IS_WINDOWS_PYTHON=1
fi

APP_HOST="${APP_HOST:-0.0.0.0}"
PORT="${PORT:-5000}"
STATUS_HOST="$APP_HOST"
if [[ -z "$STATUS_HOST" || "$STATUS_HOST" == "0.0.0.0" || "$STATUS_HOST" == "::" ]]; then
  STATUS_HOST="127.0.0.1"
fi
BASE_URL="http://${STATUS_HOST}:${PORT}"

usage() {
  cat <<'EOF'
Usage: ./scripts/dev/webctl.sh <command>

Commands:
  run       Run web service in foreground
  start     Start web service in background
  stop      Stop background web service
  restart   Stop then start
  status    Show running status
  logs      Tail web log

Managed files:
  pid: tmp/pids/web.pid
  log: tmp/logs/web.log
EOF
}

ensure_python() {
  if [[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]]; then
    return 0
  fi
  echo "[web] missing project python interpreter (.venv/bin/python or .venv/Scripts/python.exe)" >&2
  echo "[web] run: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
}

to_windows_path() {
  local path_in="$1"
  if [[ -z "$path_in" ]]; then
    echo "[web] empty path cannot be converted to Windows format" >&2
    exit 1
  fi

  if command -v wslpath >/dev/null 2>&1; then
    wslpath -w "$path_in"
    return 0
  fi

  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$path_in"
    return 0
  fi

  if [[ "$path_in" =~ ^[A-Za-z]:\\ ]]; then
    printf '%s\n' "$path_in"
    return 0
  fi

  if [[ "$path_in" =~ ^/([A-Za-z])/(.*)$ ]]; then
    local drive="${BASH_REMATCH[1]}"
    local rest="${BASH_REMATCH[2]}"
    rest="${rest//\//\\}"
    printf '%s\n' "${drive^^}:\\${rest}"
    return 0
  fi

  echo "[web] cannot convert path to Windows format: ${path_in}" >&2
  exit 1
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
  if [[ -z "$pid" ]]; then
    return 1
  fi
  if [[ "$IS_WINDOWS_PYTHON" == "1" ]]; then
    powershell.exe -NoProfile -Command "if (Get-Process -Id ${pid} -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >/dev/null 2>&1
    return $?
  fi
  kill -0 "$pid" >/dev/null 2>&1
}

wait_for_port() {
  local host="$1"
  local port="$2"
  local timeout_seconds="${3:-20}"
  local pid="$4"
  local i
  for ((i=0; i<timeout_seconds * 2; i++)); do
    if ! is_running "$pid"; then
      echo "[web] process exited during startup; inspect ${LOG_FILE}" >&2
      return 1
    fi
    if "$PYTHON_BIN" - "$host" "$port" >/dev/null 2>&1 <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket()
sock.settimeout(0.5)
try:
    sock.connect((host, port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
    then
      return 0
    fi
    sleep 0.5
  done
  echo "[web] port ${host}:${port} not ready after ${timeout_seconds}s; inspect ${LOG_FILE}" >&2
  return 1
}

print_runtime_info() {
  local pid="${1:-}"
  echo "[web] host=${APP_HOST}"
  echo "[web] port=${PORT}"
  echo "[web] url=${BASE_URL}"
  if [[ -n "$pid" ]]; then
    echo "[web] pid=${pid}"
  fi
  echo "[web] log=${LOG_FILE}"
}

do_run() {
  ensure_python
  export APP_HOST
  export PORT
  export APP_DEBUG="${APP_DEBUG:-1}"
  export APP_USE_RELOADER="${APP_USE_RELOADER:-$APP_DEBUG}"
  echo "[web] running in foreground"
  print_runtime_info
  exec "$PYTHON_BIN" app.py
}

do_start() {
  ensure_python
  local existing
  existing="$(read_pid "$PID_FILE")"
  if is_running "$existing"; then
    echo "[web] already running"
    print_runtime_info "$existing"
    return 0
  fi

  rm -f "$PID_FILE" >/dev/null 2>&1 || true
  : >"$LOG_FILE"

  export APP_HOST
  export PORT
  export APP_DEBUG="${APP_DEBUG:-0}"
  export APP_USE_RELOADER="${APP_USE_RELOADER:-0}"

  echo "[web] starting in background"
  local pid=""
  if [[ "$IS_WINDOWS_PYTHON" == "1" ]]; then
    local win_python win_root win_log arg ps_command
    win_python="$(to_windows_path "$PYTHON_BIN")"
    win_root="$(to_windows_path "$ROOT_DIR")"
    win_log="$(to_windows_path "$LOG_FILE")"
    arg="\"\"${win_python}\" app.py >> \"${win_log}\" 2>&1\""
    ps_command="\$env:APP_HOST='${APP_HOST}'; \$env:PORT='${PORT}'; \$env:APP_DEBUG='${APP_DEBUG}'; \$env:APP_USE_RELOADER='${APP_USE_RELOADER}'; \$p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', '${arg}' -WorkingDirectory '${win_root}' -WindowStyle Hidden -PassThru; Write-Output \$p.Id"
    pid="$(
      powershell.exe -NoProfile -Command "$ps_command" \
      | tr -d '\r'
    )"
  else
    nohup "$PYTHON_BIN" app.py >>"$LOG_FILE" 2>&1 &
    pid="$!"
  fi
  write_pid "$PID_FILE" "$pid"

  if ! wait_for_port "$STATUS_HOST" "$PORT" 20 "$pid"; then
    return 1
  fi

  echo "[web] started"
  print_runtime_info "$pid"
}

do_stop() {
  local pid
  pid="$(read_pid "$PID_FILE")"
  if ! is_running "$pid"; then
    echo "[web] not running"
    rm -f "$PID_FILE" >/dev/null 2>&1 || true
    return 0
  fi

  echo "[web] stopping pid=${pid}"
  if [[ "$IS_WINDOWS_PYTHON" == "1" ]]; then
    taskkill.exe /PID "$pid" /T /F >/dev/null 2>&1 || true
  else
    kill "$pid" >/dev/null 2>&1 || true
  fi

  local i
  for i in {1..20}; do
    if ! is_running "$pid"; then
      rm -f "$PID_FILE" >/dev/null 2>&1 || true
      echo "[web] stopped"
      return 0
    fi
    sleep 0.1
  done

  echo "[web] force killing pid=${pid}"
  if [[ "$IS_WINDOWS_PYTHON" == "1" ]]; then
    taskkill.exe /PID "$pid" /T /F >/dev/null 2>&1 || true
  else
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$PID_FILE" >/dev/null 2>&1 || true
  echo "[web] stopped"
}

do_status() {
  local pid
  pid="$(read_pid "$PID_FILE")"
  if is_running "$pid"; then
    echo "[web] status=running"
    print_runtime_info "$pid"
  else
    echo "[web] status=stopped"
    print_runtime_info
  fi
}

do_logs() {
  touch "$LOG_FILE"
  echo "[web] tail -f ${LOG_FILE}"
  exec tail -f "$LOG_FILE"
}

cmd="${1:-status}"
case "$cmd" in
  run)
    do_run
    ;;
  start)
    do_start
    ;;
  stop)
    do_stop
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  status)
    do_status
    ;;
  logs)
    do_logs
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "[web] unknown command: ${cmd}" >&2
    usage >&2
    exit 2
    ;;
esac
