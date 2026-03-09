#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_HOST="${REMOTE_HOST:-root@106.54.39.43}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/pm_ed25519}"
REMOTE_DIR="${REMOTE_DIR:-/www/wwwroot/gp.tianyuyezi.com_backend/app}"
REMOTE_SITE_DIR="${REMOTE_SITE_DIR:-/www/wwwroot/gp.tianyuyezi.com}"

export COPYFILE_DISABLE=1

if [[ ! -f "$SSH_KEY" ]]; then
  echo "missing ssh key: $SSH_KEY"
  exit 1
fi

(
  cd "$ROOT_DIR/frontend"
  npx -y node@20 ./node_modules/typescript/bin/tsc --noEmit
  VITE_API_BASE_URL=/api/v1 npx -y node@20 ./node_modules/vite/bin/vite.js build
)

ssh -i "$SSH_KEY" "$REMOTE_HOST" "
set -euo pipefail
BACKUP_DIR=\$(mktemp -d)
if [ -f '$REMOTE_DIR/backend/.env' ]; then cp '$REMOTE_DIR/backend/.env' \"\$BACKUP_DIR/backend.env\"; fi
if [ -f '$REMOTE_DIR/frontend/.env' ]; then cp '$REMOTE_DIR/frontend/.env' \"\$BACKUP_DIR/frontend.env\"; fi
rm -rf '$REMOTE_DIR'
mkdir -p '$REMOTE_DIR/backend' '$REMOTE_DIR/frontend'
if [ -f \"\$BACKUP_DIR/backend.env\" ]; then cp \"\$BACKUP_DIR/backend.env\" '$REMOTE_DIR/backend/.env'; fi
if [ -f \"\$BACKUP_DIR/frontend.env\" ]; then cp \"\$BACKUP_DIR/frontend.env\" '$REMOTE_DIR/frontend/.env'; fi
rm -rf \"\$BACKUP_DIR\"
"

tar -C "$ROOT_DIR" \
  --exclude=".git" \
  --exclude=".run" \
  --exclude=".codex-loop" \
  --exclude="backend/.venv" \
  --exclude="backend/*.db" \
  --exclude="backend/.env" \
  --exclude="frontend/.env" \
  --exclude="frontend/node_modules" \
  -cf - . \
  | ssh -i "$SSH_KEY" "$REMOTE_HOST" "tar -C '$REMOTE_DIR' -xf -"

ssh -i "$SSH_KEY" "$REMOTE_HOST" "
set -euo pipefail
mkdir -p '$REMOTE_SITE_DIR'
rsync -a --delete '$REMOTE_DIR/frontend/dist/' '$REMOTE_SITE_DIR/'
cd '$REMOTE_DIR/deploy'
docker compose -f docker-compose.106.yml up -d --build
"

echo "deployed to $REMOTE_HOST"
