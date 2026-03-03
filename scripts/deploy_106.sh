#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_HOST="${REMOTE_HOST:-root@106.54.39.43}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/pm_ed25519}"
REMOTE_DIR="${REMOTE_DIR:-/www/wwwroot/gp.tianyuyezi.com_backend/app}"
REMOTE_SITE_DIR="${REMOTE_SITE_DIR:-/www/wwwroot/gp.tianyuyezi.com}"

if [[ ! -f "$SSH_KEY" ]]; then
  echo "missing ssh key: $SSH_KEY"
  exit 1
fi

ssh -i "$SSH_KEY" "$REMOTE_HOST" "
set -euo pipefail
rm -rf '$REMOTE_DIR'
mkdir -p '$REMOTE_DIR'
"

tar -C "$ROOT_DIR" \
  --exclude=".git" \
  --exclude=".run" \
  --exclude=".codex-loop" \
  --exclude="backend/.venv" \
  --exclude="frontend/node_modules" \
  -cf - . \
  | ssh -i "$SSH_KEY" "$REMOTE_HOST" "tar -C '$REMOTE_DIR' -xf -"

ssh -i "$SSH_KEY" "$REMOTE_HOST" "
set -euo pipefail
mkdir -p '$REMOTE_SITE_DIR'
cd '$REMOTE_DIR/frontend'
docker run --rm -v \"\$(pwd):/app\" -w /app node:20-bullseye bash -lc '
  npm install
  VITE_API_BASE_URL=/api/v1 npm run build
'
rsync -a --delete '$REMOTE_DIR/frontend/dist/' '$REMOTE_SITE_DIR/'
cd '$REMOTE_DIR/deploy'
docker compose -f docker-compose.106.yml up -d --build
"

echo "deployed to $REMOTE_HOST"
