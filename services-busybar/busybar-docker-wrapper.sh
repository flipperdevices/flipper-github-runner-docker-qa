#!/bin/bash
BUSYBAR_SERIAL=$1
BLACKMAGIC_SERIAL=$2
GITHUB_RUNNER_TAG=$3

set -euo pipefail

source /opt/busybar-runners/$1/venv/bin/activate
exec python /opt/busybar-runners/scripts/busybar-docker-runner.py $BUSYBAR_SERIAL $BLACKMAGIC_SERIAL $GITHUB_RUNNER_TAG