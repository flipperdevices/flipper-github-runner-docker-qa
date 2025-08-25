#!/bin/bash
BUSYBAR_NAME="$1"
BIND_PATH="/dev/busybar/$BUSYBAR_NAME"

echo "$BUSYBAR_NAME is disconnected. Unbinding $BIND_PATH"

for bind in $BIND_PATH/*; do
    if mountpoint -q "$bind"; then
        umount "$bind"
        echo "Unbound $bind"
    fi
done

rmdir "$BIND_PATH" 2>/dev/null