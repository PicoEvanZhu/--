#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

HOST="${HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_SESSION="${BACKEND_SESSION:-stock_backend}"
FRONTEND_SESSION="${FRONTEND_SESSION:-stock_frontend}"
BACKEND_LOG="$ROOT_DIR/.run/backend.log"
FRONTEND_LOG="$ROOT_DIR/.run/frontend.log"

mkdir -p .run

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

require_command() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "缺少依赖命令：$name"
    exit 1
  fi
}

kill_listener_on_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "${pids:-}" ]]; then
    return
  fi

  while IFS= read -r pid; do
    if [[ -n "${pid:-}" ]]; then
      kill "$pid" 2>/dev/null || true
    fi
  done <<< "$pids"
}

require_command screen
require_command curl
require_command lsof

bash "$ROOT_DIR/scripts/dev_down.sh" >/dev/null 2>&1 || true
kill_listener_on_port "$BACKEND_PORT"
kill_listener_on_port "$FRONTEND_PORT"

: > "$BACKEND_LOG"
: > "$FRONTEND_LOG"

if [[ ! -d backend/.venv ]]; then
  python3 -m venv backend/.venv
fi
source backend/.venv/bin/activate
python -m pip install -q -r backend/requirements.txt

if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && npm install)
fi

backend_cmd="cd \"$ROOT_DIR/backend\" && exec ../backend/.venv/bin/python -m uvicorn app.main:app --host \"$HOST\" --port \"$BACKEND_PORT\" >> \"$BACKEND_LOG\" 2>&1"
frontend_cmd="cd \"$ROOT_DIR/frontend\" && exec npm run dev -- --host \"$HOST\" --port \"$FRONTEND_PORT\" >> \"$FRONTEND_LOG\" 2>&1"

screen -dmS "$BACKEND_SESSION" bash -lc "$backend_cmd"
screen -dmS "$FRONTEND_SESSION" bash -lc "$frontend_cmd"

backend_ok=0
for _ in {1..30}; do
  if curl -sS --max-time 2 "http://127.0.0.1:${BACKEND_PORT}/api/v1/health" >/dev/null 2>&1; then
    backend_ok=1
    break
  fi
  sleep 1
done

frontend_ok=0
for _ in {1..30}; do
  if curl -sS --max-time 2 "http://127.0.0.1:${FRONTEND_PORT}/home" >/dev/null 2>&1; then
    frontend_ok=1
    break
  fi
  sleep 1
done

if [[ "$backend_ok" -ne 1 || "$frontend_ok" -ne 1 ]]; then
  echo "启动失败，请查看日志："
  echo "- $BACKEND_LOG"
  echo "- $FRONTEND_LOG"
  echo "- 当前 screen 会话："
  screen -ls || true
  echo
  echo "backend_log_tail:"
  tail -n 80 "$BACKEND_LOG" || true
  echo
  echo "frontend_log_tail:"
  tail -n 80 "$FRONTEND_LOG" || true
  exit 1
fi

backend_pid="$(lsof -tiTCP:${BACKEND_PORT} -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
frontend_pid="$(lsof -tiTCP:${FRONTEND_PORT} -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"

if [[ -n "$backend_pid" ]]; then
  echo "$backend_pid" > .run/backend.pid
  echo "$backend_pid" > backend.pid
fi
if [[ -n "$frontend_pid" ]]; then
  echo "$frontend_pid" > .run/frontend.pid
  echo "$frontend_pid" > frontend.pid
fi

echo "backend_session=$BACKEND_SESSION"
echo "frontend_session=$FRONTEND_SESSION"
echo "backend_pid=${backend_pid:-unknown}"
echo "frontend_pid=${frontend_pid:-unknown}"
echo "backend_health=$(curl -sS http://127.0.0.1:${BACKEND_PORT}/api/v1/health || true)"
echo "frontend_home_code=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:${FRONTEND_PORT}/home || true)"
echo "backend_log=$BACKEND_LOG"
echo "frontend_log=$FRONTEND_LOG"

echo
echo "打开地址："
echo "- http://127.0.0.1:${FRONTEND_PORT}/home"
echo "- http://127.0.0.1:${FRONTEND_PORT}/dashboard"
echo "- http://127.0.0.1:${BACKEND_PORT}/docs"
echo
echo "服务通过 screen 常驻，不依赖当前终端会话。"
echo "如需查看状态：bash scripts/dev_status.sh"
