#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${AIPS_APP_DIR:-/opt/aips}"
START_HOUR="${AIPS_RADIO_LIVE_START_HOUR:-5}"
END_HOUR="${AIPS_RADIO_LIVE_END_HOUR:-19}"
CURRENT_HOUR="$(TZ=America/New_York date +%H)"

if (( 10#${CURRENT_HOUR} >= START_HOUR && 10#${CURRENT_HOUR} < END_HOUR )); then
  echo "Not closing MuzAIk: current Eastern hour ${CURRENT_HOUR} is inside ${START_HOUR}:00-${END_HOUR}:00."
  exit 0
fi

echo "Closing MuzAIk radio window. Gracefully stopping conductor first so it can archive."
pkill -TERM -f "${APP_DIR}/scripts/segment_conductor.py|scripts/segment_conductor.py" || true
sleep 5
pkill -TERM -f "${APP_DIR}/scripts/control_server.py|scripts/control_server.py" || true
sleep 2
pkill -KILL -f "${APP_DIR}/scripts/segment_conductor.py|scripts/segment_conductor.py" || true
pkill -KILL -f "${APP_DIR}/scripts/control_server.py|scripts/control_server.py" || true
"${APP_DIR}/scripts/muzaik_status.sh"
