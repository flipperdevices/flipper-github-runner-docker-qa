#!/bin/bash

FLIPPER_NAME="$1"
BIND_PATH="/dev/flipper/$FLIPPER_NAME/$FLIPPER_NAME"

echo "$FLIPPER_NAME is disconnected. Unbinding $BIND_PATH"
umount "$BIND_PATH"