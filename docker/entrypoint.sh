#!/bin/bash

set -euo pipefail;


FLIPPER_ID=$2
ST_LINK_ID=$3

echo "Flipper ID: $FLIPPER_ID"
echo "ST-Link ID: $ST_LINK_ID"

export FLIPPER_ID="$FLIPPER_ID"
export ST_LINK_ID="$ST_LINK_ID"

echo "FLIPPER_ID=$FLIPPER_ID" >> /etc/environment
echo "ST_LINK_ID=$ST_LINK_ID" >> /etc/environment

timestamp=$(date +%Y%m%d_%H%M%S)
log_file="/opt/toolchain/logs/${FLIPPER_ID}_${timestamp}_${RUN_LEVEL}.log"

/opt/serial_monitor.py "$FLIPPER_ID" --run-level "$RUN_LEVEL" --output "$log_file" &
MONITOR_PID=$!

function cleanup() {
    echo "Cleaning up..."
    kill $MONITOR_PID 2>/dev/null || true
    wait $MONITOR_PID 2>/dev/null || true
}

trap cleanup EXIT

function flash_release_to_flipper() {
    echo "Prepare to flash flipper using fbt..";
    cd /opt/flipperzero-firmware

    # Flash firmware using fbt
    source scripts/toolchain/fbtenv.sh
    echo "Formatting ext"
    python3 scripts/storage.py format_ext -p auto
    echo "Waiting for flipper"
            if python3 scripts/testops.py -t=180 await_flipper; then
              echo "Flipper detected."
              break
            else
              echo "Flipper not detected, proceeding to flashing.."
            fi
    echo "Start flashing the flipper"
    python3 scripts/fwflash.py --interface=auto --serial=$ST_LINK_ID /opt/flipperzero-firmware/firmware.bin


    echo "Flashing done!";
    set +e;
    sleep 1;
    set -e;
    cd /
}

if [[ "$RUN_LEVEL" == "NORMAL" ]]; then
    echo "Starting runner..";
    cd /actions-runner
    /entrypoint.sh ./bin/Runner.Listener run --startuptype service;
elif [[ "$RUN_LEVEL" == "REPAIR" ]]; then
    echo "App running into repair mode, restarting container..";
    flash_release_to_flipper;
    exit 0;
else
    echo "Wrong RUN_LEVEL, exiting with fail..";
    exit 2;
fi
