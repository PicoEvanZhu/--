#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

SESSION_NAME="${ENRICH_SESSION:-stock_enrich}"

echo "== enrich screen session =="
screen_output="$(screen -ls 2>/dev/null || true)"
match="$(printf '%s\n' "$screen_output" | rg "$SESSION_NAME" || true)"
if [[ -n "$match" ]]; then
  printf '%s\n' "$match"
else
  echo "no enrichment session"
fi

echo
echo "== enrich api status =="
curl -sS "http://127.0.0.1:8000/api/v1/stocks/enrich/status" || true

echo
echo "== enrich log tail =="
tail -n 40 .run/enrich.log || true
