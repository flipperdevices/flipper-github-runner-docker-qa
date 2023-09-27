#!/bin/bash

set -euo pipefail;

function flash_release_to_flipper() {
    echo "Flashing flipper..";
    openocd \
        -f interface/stlink.cfg \
        -c "transport select hla_swd" \
        -f target/stm32wbx.cfg \
        -c "stm32wbx.cpu configure -rtos auto" \
        -c "reset_config srst_only srst_nogate connect_assert_srst" \
        -c init \
        -c "program /opt/flipperzero-firmware/firmware.bin exit 0x8000000" \
        2>&1;
    echo "Flashing done!";
    set +e;
    sleep 1;
    echo "Resetting flipper..";
    openocd \
        -f interface/stlink.cfg \
        -c "transport select hla_swd" \
        -f target/stm32wbx.cfg \
        -c "stm32wbx.cpu configure -rtos auto" \
        -c "reset_config srst_only srst_nogate connect_assert_srst" \
        -c init \
        -c "reset run" \
        -c "exit"
        2>&1;
    echo "Resetting done!";
    set -e;
}

if [[ "$RUN_LEVEL" == "NORMAL" ]]; then
    echo "Starting runner..";
    /entrypoint.sh ./bin/Runner.Listener run --startuptype service;
elif [[ "$RUN_LEVEL" == "REPAIR" ]]; then
    echo "App running into repair mode, restarting container..";
    flash_release_to_flipper;
    exit 0;
else
    echo "Wrong RUN_LEVER, exiting with fail..";
    exit 2;
fi
