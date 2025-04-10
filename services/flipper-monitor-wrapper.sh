#!/bin/bash
source /opt/flipper-monitor/venv/bin/activate
exec python /opt/flipper-monitor/github-runner-monitor.py "$@"