#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

SESSION_NAME="${ENRICH_SESSION:-stock_enrich}"
FORCE_FLAG="${ENRICH_FORCE:-true}"
MARKET="${ENRICH_MARKET:-}"
LIMIT="${ENRICH_LIMIT:-}"
SLEEP_MS="${ENRICH_SLEEP_MS:-120}"

mkdir -p .run

if [[ ! -d backend/.venv ]]; then
  python3 -m venv backend/.venv
fi
source backend/.venv/bin/activate
python -m pip install -q -r backend/requirements.txt

screen_output="$(screen -ls 2>/dev/null || true)"
session_ids="$(printf '%s\n' "$screen_output" | rg "[.]${SESSION_NAME}[[:space:]]" | awk '{print $1}' || true)"
if [[ -n "$session_ids" ]]; then
  while IFS= read -r session_id; do
    if [[ -n "$session_id" ]]; then
      screen -S "$session_id" -X quit || true
    fi
  done <<< "$session_ids"
fi

cmd="cd \"$ROOT_DIR\" && DATABASE_URL='${DATABASE_URL:-}' backend/.venv/bin/python scripts/enrich_universe.py --sleep-ms $SLEEP_MS"
if [[ "$FORCE_FLAG" == "true" ]]; then
  cmd+=" --force"
fi
if [[ -n "$MARKET" ]]; then
  cmd+=" --market '$MARKET'"
fi
if [[ -n "$LIMIT" ]]; then
  cmd+=" --limit $LIMIT"
fi
cmd+=" >> '$ROOT_DIR/.run/enrich.log' 2>&1"

screen -dmS "$SESSION_NAME" bash -lc "$cmd"

echo "enrich_session=$SESSION_NAME"
echo "log_file=$ROOT_DIR/.run/enrich.log"
echo "status_api=http://127.0.0.1:8000/api/v1/stocks/enrich/status"
echo "查看日志: tail -f $ROOT_DIR/.run/enrich.log"
