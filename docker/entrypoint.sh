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

function flash_release_to_flipper() {
    echo "Flashing flipper using fbt..";
    cd /opt/flipperzero-firmware

    # Flash firmware using fbt
    source scripts/toolchain/fbtenv.sh
    python3 scripts/fwflash.py --interface=auto --serial=$ST_LINK_ID /opt/flipperzero-firmware/firmware.bin
    python3 scripts/storage.py format_ext

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