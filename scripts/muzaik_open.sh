#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${AIPS_APP_DIR:-/opt/aips}"
START_HOUR="${AIPS_RADIO_LIVE_START_HOUR:-5}"
END_HOUR="${AIPS_RADIO_LIVE_END_HOUR:-19}"
CURRENT_HOUR="$(TZ=America/New_York date +%H)"

if (( 10#${CURRENT_HOUR} < START_HOUR || 10#${CURRENT_HOUR} >= END_HOUR )); then
  echo "Not starting MuzAIk: current Eastern hour ${CURRENT_HOUR} is outside ${START_HOUR}:00-${END_HOUR}:00."
  exit 0
fi

echo "Opening MuzAIk radio window."
"${APP_DIR}/scripts/muzaik_restart.sh"
