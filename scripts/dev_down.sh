#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_SESSION="${BACKEND_SESSION:-stock_backend}"
FRONTEND_SESSION="${FRONTEND_SESSION:-stock_frontend}"

kill_pid_file() {
  local file="$1"
  if [[ -f "$file" ]]; then
    local pid
    pid="$(cat "$file" 2>/dev/null || true)"
    if [[ -n "${pid:-}" ]]; then
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$file"
  fi
}

kill_pid_file .run/backend.pid
kill_pid_file .run/frontend.pid
kill_pid_file backend.pid
kill_pid_file frontend.pid

screen_output="$(screen -ls 2>/dev/null || true)"
if printf '%s\n' "$screen_output" | rg -q "[.]${BACKEND_SESSION}[[:space:]]"; then
  screen -S "$BACKEND_SESSION" -X quit 2>/dev/null || true
fi
if printf '%s\n' "$screen_output" | rg -q "[.]${FRONTEND_SESSION}[[:space:]]"; then
  screen -S "$FRONTEND_SESSION" -X quit 2>/dev/null || true
fi

pkill -f "uvicorn app.main:app .*--port ${BACKEND_PORT}" 2>/dev/null || true
pkill -f "vite .*--port ${FRONTEND_PORT}" 2>/dev/null || true

echo "stopped"
