#!/bin/bash

FLIPPER_NAME="$1"
BIND_PATH="/dev/flipper/$FLIPPER_NAME/$FLIPPER_NAME"

echo "$FLIPPER_NAME is disconnected. Unbinding $BIND_PATH"

# Lazy + loop: clear the bind even if a running container still holds it busy,
# and unstack any repeated binds left by earlier failed attempts.
while mountpoint -q "$BIND_PATH"; do
    umount -l "$BIND_PATH" || break
done
