#!/bin/bash
FLIPPER_SERIAL=$1
STLINK_SERIAL=$2
GITHUB_RUNNER_TAG=$3

set -euo pipefail

BASE_DIR="/opt/flipper-runner"
VENV_PATH="${BASE_DIR}/${FLIPPER_SERIAL}/venv"
SCRIPT_PATH="${BASE_DIR}/scripts/flipper-docker-runner.py"

if [ ! -d "${VENV_PATH}" ]; then
    echo "Virtual environment not found at ${VENV_PATH}"
    exit 1
fi

source "${VENV_PATH}/bin/activate"
exec python "${SCRIPT_PATH}" "$FLIPPER_SERIAL" "$STLINK_SERIAL" "$GITHUB_RUNNER_TAG"
