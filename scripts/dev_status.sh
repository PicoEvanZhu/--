#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_SESSION="${BACKEND_SESSION:-stock_backend}"
FRONTEND_SESSION="${FRONTEND_SESSION:-stock_frontend}"
BACKEND_LOG="${BACKEND_LOG:-.run/backend.log}"
FRONTEND_LOG="${FRONTEND_LOG:-.run/frontend.log}"

echo "== screen sessions =="
screen_output="$(screen -ls 2>/dev/null || true)"
sessions="$(printf '%s\n' "$screen_output" | rg "$BACKEND_SESSION|$FRONTEND_SESSION" || true)"
if [[ -n "$sessions" ]]; then
  printf '%s\n' "$sessions"
else
  echo "no app sessions"
fi

echo
echo "== listeners =="
lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN || true
lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN || true

echo
echo "== health check =="
curl -sS --max-time 3 -o /dev/null -w "frontend /home HTTP %{http_code}\n" "http://127.0.0.1:${FRONTEND_PORT}/home" || true
curl -sS --max-time 3 -o /dev/null -w "backend /health HTTP %{http_code}\n" "http://127.0.0.1:${BACKEND_PORT}/api/v1/health" || true

echo
echo "== log tail (frontend) =="
if [[ -f "$FRONTEND_LOG" ]]; then
  ls -lT "$FRONTEND_LOG" || true
  tail -n 40 "$FRONTEND_LOG" || true
else
  echo "missing log: $FRONTEND_LOG"
fi

echo
echo "== log tail (backend) =="
if [[ -f "$BACKEND_LOG" ]]; then
  ls -lT "$BACKEND_LOG" || true
  tail -n 40 "$BACKEND_LOG" || true
else
  echo "missing log: $BACKEND_LOG"
fi
