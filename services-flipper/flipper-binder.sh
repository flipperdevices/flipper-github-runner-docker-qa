#!/bin/bash
DEVICE_PATH="$1"
FLIPPER_NAME="$2"
BIND_PATH="/dev/flipper/$FLIPPER_NAME/$FLIPPER_NAME"
echo "$FLIPPER_NAME is connected to $DEVICE_PATH. Binding to $BIND_PATH"

mkdir -p /dev/flipper/$FLIPPER_NAME

if [ ! -e "$BIND_PATH" ]; then
 touch "$BIND_PATH"
fi

mount --bind "$DEVICE_PATH" "$BIND_PATH"