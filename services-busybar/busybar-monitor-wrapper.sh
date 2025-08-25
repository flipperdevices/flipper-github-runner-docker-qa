#!/bin/bash
source /opt/busybar-monitor/venv/bin/activate
exec python /opt/busybar-monitor/github-runner-monitor-busybar.py "$@"