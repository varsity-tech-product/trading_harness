#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env.runtime.local}"
CONFIG_PATH="${1:-${ROOT_DIR}/arena_agent/config/agent_live.yaml}"
LOG_DIR="${ROOT_DIR}/logs"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/continuous_agent.log}"
RESTART_DELAY_SECONDS="${RESTART_DELAY_SECONDS:-15}"
PYTHON_BIN="${PYTHON_BIN:-}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Copy .env.runtime.local.example and add your runtime secrets." >&2
  exit 1
fi

if [[ "${CONFIG_PATH}" != /* ]]; then
  CONFIG_PATH="${ROOT_DIR}/${CONFIG_PATH}"
fi

if [[ ! -f "${CONFIG_PATH}" ]]; then
  echo "Missing runtime config ${CONFIG_PATH}." >&2
  exit 1
fi

mkdir -p "${LOG_DIR}"

if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

while true; do
  printf '[%s] starting arena runtime with %s\n' "$(date -Is)" "${CONFIG_PATH}" >> "${LOG_FILE}"

  set +e
  (
    cd "${ROOT_DIR}"
    set -a
    source "${ENV_FILE}"
    set +a
    "${PYTHON_BIN}" -m arena_agent --config "${CONFIG_PATH}" --log-level INFO
  ) >> "${LOG_FILE}" 2>&1
  status=$?
  set -e

  printf '[%s] runtime exited with status %s; restarting in %ss\n' \
    "$(date -Is)" "${status}" "${RESTART_DELAY_SECONDS}" >> "${LOG_FILE}"
  sleep "${RESTART_DELAY_SECONDS}"
done
