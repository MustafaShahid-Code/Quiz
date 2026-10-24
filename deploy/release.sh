#!/usr/bin/env bash
# Runs on the server. Usage: release.sh <release-id>
set -euo pipefail
BASE=/opt/footballquiz
REL="$BASE/releases/$1"
cd "$BASE"
[ -d venv ] || python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r "$REL/requirements.txt"

PREV=$(readlink -f current || true)
ln -sfn "$REL" current.new && mv -Tf current.new current
sudo systemctl restart footballquiz

for i in $(seq 1 20); do
  if curl -fs http://127.0.0.1:8000/healthz >/dev/null; then
    echo "Release $1 is healthy"
    ls -1dt releases/* | tail -n +6 | xargs -r rm -rf   # keep the last 5
    exit 0
  fi
  sleep 1
done

echo "Health check failed - rolling back" >&2
if [ -n "$PREV" ] && [ -d "$PREV" ]; then
  ln -sfn "$PREV" current.new && mv -Tf current.new current
  sudo systemctl restart footballquiz
fi
exit 1
