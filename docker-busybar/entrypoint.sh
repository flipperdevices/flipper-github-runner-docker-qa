#!/bin/bash

set -euo pipefail;

BUSYBAR_ID=$1
BLACKMAGIC_ID=$2

echo "BusyBar ID: $BUSYBAR_ID"
echo "Blackmagic ID: $BLACKMAGIC_ID"

export BUSYBAR_ID="$BUSYBAR_ID"
export BLACKMAGIC_ID="$BLACKMAGIC_ID"

echo "BUSYBAR_ID=$BUSYBAR_ID" >> /etc/environment
echo "BLACKMAGIC_ID=$BLACKMAGIC_ID" >> /etc/environment

timestamp=$(date +%Y%m%d_%H%M%S)
log_file="/opt/toolchain/logs/${BUSYBAR_ID}_${timestamp}_${RUN_LEVEL}.log"
mkdir -p /opt/toolchain/logs

# Start UART monitor for u5 CPU
#/opt/uart_monitor.py "$BUSYBAR_ID" --run-level "$RUN_LEVEL" --output "$log_file" --device-path /dev/tty_busybar_u5 &
MONITOR_PID=$!

function cleanup() {
    echo "Cleaning up..."
    kill $MONITOR_PID 2>/dev/null || true
    wait $MONITOR_PID 2>/dev/null || true
}

trap cleanup EXIT

function flash_busybar() {
    echo "Prepare to flash BusyBar u5 CPU..."
    echo "####################################################"
    echo "#### YOU NEED TO PUT ACTUAL FLASH SEQUENCE HERE ####"
    echo "####################################################"
    echo "Connecting to BusyBar CLI via telnet..."

    # Flash firmware via UART
    echo "Flashing firmware via UART..."
    echo "####################################################"
    echo "#### YOU NEED TO PUT ACTUAL FLASH SEQUENCE HERE ####"
    echo "####################################################"
    # Example:

    echo "Flashing done!";
    sleep 5;

if [[ "$RUN_LEVEL" == "NORMAL" ]]; then
    echo "Starting runner..";
    cd /actions-runner
elif [[ "$RUN_LEVEL" == "REPAIR" ]]; then
    echo "App running into repair mode, restarting container..";
    flash_busybar;
else
    echo "Wrong RUN_LEVEL, exiting with fail..";
fi
