#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.runtime.local"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Copy .env.runtime.local.example and add your runtime secrets." >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

python3 -m arena_agent.tap.local_claude_server --host 127.0.0.1 --port 8080 &
SERVER_PID=$!

cleanup() {
  kill "${SERVER_PID}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sleep 1
python3 -m arena_agent --config arena_agent/config/tap_agent_config.yaml --iterations "${1:-1}"
