#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${AIPS_APP_DIR:-/opt/aips}"
PYTHON="${AIPS_PYTHON:-python3}"
CONTROL_HOST="${AIPS_CONTROL_HOST:-127.0.0.1}"
CONTROL_PORT="${AIPS_CONTROL_PORT:-8765}"
SESSION_ID="${AIPS_RADIO_SESSION_ID:-summit-demo}"
SECTION_BARS="${AIPS_SECTION_BARS:-4}"
PREBUFFER_SECTIONS="${AIPS_PREBUFFER_SECTIONS:-2}"
MAX_RECORDING_SECONDS="${AIPS_MAX_RECORDING_SECONDS:-3600}"
AGENT_MODE="${AIPS_AGENT_MODE:-heuristic}"
LOG_DIR="${AIPS_LOG_DIR:-${APP_DIR}/logs}"

mkdir -p "${LOG_DIR}"
cd "${APP_DIR}"

echo "Stopping existing MuzAIk processes, if any..."
pkill -TERM -f "${APP_DIR}/scripts/segment_conductor.py|scripts/segment_conductor.py" || true
pkill -TERM -f "${APP_DIR}/scripts/control_server.py|scripts/control_server.py" || true
sleep 3
pkill -KILL -f "${APP_DIR}/scripts/segment_conductor.py|scripts/segment_conductor.py" || true
pkill -KILL -f "${APP_DIR}/scripts/control_server.py|scripts/control_server.py" || true

echo "Starting control server on ${CONTROL_HOST}:${CONTROL_PORT}..."
nohup "${PYTHON}" scripts/control_server.py --host "${CONTROL_HOST}" --port "${CONTROL_PORT}" \
  >> "${LOG_DIR}/control_server.log" 2>&1 &

echo "Starting segment conductor for session ${SESSION_ID}..."
nohup "${PYTHON}" scripts/segment_conductor.py \
  --session-id "${SESSION_ID}" \
  --section-bars "${SECTION_BARS}" \
  --prebuffer-sections "${PREBUFFER_SECTIONS}" \
  --max-recording-seconds "${MAX_RECORDING_SECONDS}" \
  --agent-mode "${AGENT_MODE}" \
  >> "${LOG_DIR}/segment_conductor.log" 2>&1 &

sleep 2
"${APP_DIR}/scripts/muzaik_status.sh"
