#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${AIPS_APP_DIR:-/opt/aips}"
CONTROL_PORT="${AIPS_CONTROL_PORT:-8765}"

echo "== MuzAIk process status =="
pgrep -af "${APP_DIR}/scripts/control_server.py|scripts/control_server.py" || echo "control_server.py: not running"
pgrep -af "${APP_DIR}/scripts/segment_conductor.py|scripts/segment_conductor.py" || echo "segment_conductor.py: not running"

echo
echo "== Port ${CONTROL_PORT} listener =="
if command -v ss >/dev/null 2>&1; then
  ss -ltnp "sport = :${CONTROL_PORT}" || true
else
  lsof -nP -iTCP:"${CONTROL_PORT}" -sTCP:LISTEN || true
fi

echo
echo "== Local API health =="
curl -fsS "http://127.0.0.1:${CONTROL_PORT}/api/radio-status" || true
echo
