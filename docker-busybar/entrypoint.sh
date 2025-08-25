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
/opt/uart_monitor.py "$BUSYBAR_ID" --run-level "$RUN_LEVEL" --output "$log_file" --device-path /dev/tty_busybar_u5 &
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

    # Example telnet automation using expect or python
    python3 - <<EOF
import telnetlib
import time

try:
    tn = telnetlib.Telnet("${BUSYBAR_IP:-10.0.4.20}", 23, timeout=10)
    time.sleep(1)

    # Send reboot to bootloader command
    tn.write(b"bootloader\n")
    time.sleep(2)

    # Close telnet
    tn.close()
    print("BusyBar set to bootloader mode")
except Exception as e:
    print(f"Failed to set bootloader mode: {e}")
EOF

    # Flash firmware via UART
    echo "Flashing firmware via UART..."
    echo "####################################################"
    echo "#### YOU NEED TO PUT ACTUAL FLASH SEQUENCE HERE ####"
    echo "####################################################"
    # Example:

    echo "Flashing done!";
    sleep 5;

    # Verify BusyBar is back online
    python3 - <<EOF
import telnetlib
import time

max_attempts = 30
for attempt in range(max_attempts):
    try:
        tn = telnetlib.Telnet("${BUSYBAR_IP:-10.0.4.20}", 23, timeout=2)
        tn.close()
        print(f"BusyBar is back online after {attempt} attempts")
        break
    except Exception:
        time.sleep(2)
        if attempt == max_attempts - 1:
            print("BusyBar failed to come back online")
            exit(1)
EOF
}

if [[ "$RUN_LEVEL" == "NORMAL" ]]; then
    echo "Starting runner..";
    cd /actions-runner
    /entrypoint.sh ./bin/Runner.Listener run --startuptype service;
elif [[ "$RUN_LEVEL" == "REPAIR" ]]; then
    echo "App running into repair mode, restarting container..";
    flash_busybar;
    exit 0;
else
    echo "Wrong RUN_LEVEL, exiting with fail..";
    exit 2;
fi
