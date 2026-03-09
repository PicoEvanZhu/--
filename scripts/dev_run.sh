#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

HOST="${HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

mkdir -p .run

if [[ ! -f backend/.env ]]; then
  echo "缺少 backend/.env。项目已切换为 MySQL-only，请先配置 DATABASE_URL。"
  exit 1
fi
db_url="$(grep -E '^DATABASE_URL=' backend/.env | head -n 1 | cut -d= -f2- || true)"
if [[ -z "$db_url" ]]; then
  echo "backend/.env 未配置 DATABASE_URL。"
  exit 1
fi
if [[ "$db_url" != mysql+pymysql://* ]]; then
  echo "仅支持 mysql+pymysql:// 连接串，当前为: $db_url"
  exit 1
fi

if [[ ! -d backend/.venv ]]; then
  python3 -m venv backend/.venv
fi
source backend/.venv/bin/activate
python -m pip install -q -r backend/requirements.txt

if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && npm install)
fi

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

(
  cd backend
  ../backend/.venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$BACKEND_PORT"
) > .run/backend.log 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > .run/backend.pid
echo "$BACKEND_PID" > backend.pid

(
  cd frontend
  npm run dev -- --host "$HOST" --port "$FRONTEND_PORT"
) > .run/frontend.log 2>&1 &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > .run/frontend.pid
echo "$FRONTEND_PID" > frontend.pid

echo "开发服务已启动（前台常驻模式）："
echo "- 前端: http://127.0.0.1:${FRONTEND_PORT}/home"
echo "- 后端: http://127.0.0.1:${BACKEND_PORT}/docs"
echo "停止请按 Ctrl+C"

echo ""
echo "最近日志（Ctrl+C 可退出）："

tail -n 20 .run/backend.log || true
echo "---"
tail -n 20 .run/frontend.log || true

echo ""
echo "服务运行中..."

wait_for_any() {
  while true; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      wait "$BACKEND_PID" || true
      return $?
    fi
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
      wait "$FRONTEND_PID" || true
      return $?
    fi
    sleep 1
  done
}

wait_for_any
status=$?
echo "检测到服务退出，状态码: $status"
exit "$status"
