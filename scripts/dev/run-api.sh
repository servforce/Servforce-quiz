#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source scripts/dev/load-env.sh
fi

export PYTHONPATH="${ROOT_DIR}:${ROOT_DIR}/backend"
PY="${PY:-python3}"
if [[ -x .venv/bin/python ]]; then PY=".venv/bin/python"; fi

APP_HOST="${APP_HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

exec "$PY" -m uvicorn backend.md_quiz.main:app --host "$APP_HOST" --port "$PORT"
