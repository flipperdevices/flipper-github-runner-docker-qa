#!/bin/bash
DEVICE_PATH="$1"
FLIPPER_NAME="$2"
BIND_PATH="/dev/flipper/$FLIPPER_NAME/$FLIPPER_NAME"
echo "$FLIPPER_NAME is connected to $DEVICE_PATH. Binding to $BIND_PATH"

mkdir -p "/dev/flipper/$FLIPPER_NAME"

# The udev DEVPATH from the add event is racy: under rapid re-enumeration the
# Flipper often moves again before this service runs, so DEVPATH points at a
# /dev/ttyACMx that no longer exists (mount --bind then fails with ENOENT).
# Resolve the LIVE node by serial from /dev/serial/by-id, retrying briefly while
# the device settles.
LIVE=""
for _ in $(seq 1 10); do
    cand=$(readlink -f /dev/serial/by-id/usb-Flipper_*_"${FLIPPER_NAME}"-if00 2>/dev/null | head -1)
    if [ -n "$cand" ] && [ -e "$cand" ]; then
        LIVE="$cand"
        break
    fi
    sleep 0.5
done
[ -n "$LIVE" ] || LIVE="$DEVICE_PATH"   # fallback to the udev-provided path

# Clear any stale bind first (lazy: a running container may still hold it busy),
# then bind the live node onto the stable name-keyed path.
while mountpoint -q "$BIND_PATH"; do
    umount -l "$BIND_PATH" || break
done
[ -e "$BIND_PATH" ] || touch "$BIND_PATH"
mount --bind "$LIVE" "$BIND_PATH"
echo "Bound $LIVE -> $BIND_PATH"
