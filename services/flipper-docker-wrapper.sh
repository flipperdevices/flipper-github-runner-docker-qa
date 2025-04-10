#!/bin/bash
FLIPPER_SERIAL=$1
STLINK_SERIAL=$2
GITHUB_RUNNER_TAG=$3

set -euo pipefail

source /opt/flipper-runners/$1/venv/bin/activate
exec python /opt/flipper-runners/scripts/flipper-docker-runner.py $FLIPPER_SERIAL $STLINK_SERIAL $GITHUB_RUNNER_TAG