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

/opt/serial_monitor.py "$FLIPPER_ID" --run-level "$RUN_LEVEL" --output "$log_file" --device-path /dev/tty_stlink &
MONITOR_PID=$!

ls -l /dev/$FLIPPER_ID
ln -s /dev/$FLIPPER_ID/$FLIPPER_ID /dev/tty_$FLIPPER_ID
export FLIPPER_PATH=/dev/tty_$FLIPPER_ID
echo "FLIPPER_PATH=$FLIPPER_PATH" >> /etc/environment

function cleanup() {
    echo "Cleaning up..."
    kill $MONITOR_PID 2>/dev/null || true
    wait $MONITOR_PID 2>/dev/null || true
}

trap cleanup EXIT

function flash_release_to_flipper() {
    echo "Prepare to flash flipper using fbt..";
    cd /opt/flipperzero-firmware

    source scripts/toolchain/fbtenv.sh

    FWFLASH_CMD="python3 scripts/fwflash.py --interface=auto --serial=$ST_LINK_ID /opt/flipperzero-firmware/firmware.bin"
    AWAIT_FLIPPER="python3 scripts/testops.py -t=30 await_flipper"
    FORMAT_EXT="python3 scripts/storage.py format_ext -p auto"

    echo "Waiting for flipper"
    if timeout 35s $AWAIT_FLIPPER; then
        echo "Flipper detected."
        echo "Formatting ext"
        $FORMAT_EXT
    else
        echo "Flipper not detected, proceeding to flashing..."
        $FWFLASH_CMD
        if timeout 35s $AWAIT_FLIPPER; then
            echo "Flipper detected after flash."
            echo "Formatting ext"
            $FORMAT_EXT
        fi
    fi

    echo "Start flashing the flipper"
    $FWFLASH_CMD

    echo "Flashing done!";
    $AWAIT_FLIPPER;
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
