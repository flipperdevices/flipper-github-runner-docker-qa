#!/bin/bash
BUSYBAR_NAME="$1"
BIND_PATH="/dev/busybar/$BUSYBAR_NAME"

echo "$BUSYBAR_NAME is connected. Creating bind path at $BIND_PATH"

mkdir -p /dev/busybar/$BUSYBAR_NAME

# Find and bind Blackmagic UART devices
for tty in /dev/ttyACM*; do
    if udevadm info --query=all --name=$tty | grep -q "blackmagic"; then
        tty_name=$(basename $tty)
        touch "$BIND_PATH/$tty_name"
        mount --bind "$tty" "$BIND_PATH/$tty_name"
        echo "Bound $tty to $BIND_PATH/$tty_name"
    fi
done