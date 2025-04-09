#!/bin/bash

set -euo pipefail

# Check if script is run as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

# Add simulation flag support
SIMULATE=false
for arg in "$@"; do
    case $arg in
        --simulate)
            SIMULATE=true
            ;;
        *)
            echo "Unknown option: $arg"
            ;;
    esac
done

if [ "$SIMULATE" = true ]; then
    echo "Running in simulation mode. Commands will be printed instead of executed."
fi

# A wrapper to either execute or simulate a command
run_cmd() {
    if [ "$SIMULATE" = true ]; then
        echo "SIMULATE: $*"
    else
        "$@"
    fi
}

echo "===== Flipper GitHub Runner Monitor Installer ====="
echo "This script will install the monitoring service for Flipper GitHub Runners"

# Define paths
INSTALL_DIR="/opt/flipper-monitor"
VENV_DIR="${INSTALL_DIR}/venv"
MONITOR_SCRIPT="${INSTALL_DIR}/github-runner-monitor.py"
SERVICE_FILE="/etc/systemd/system/github-runner-monitor.service"
METRICS_DIR="/var/lib/node_exporter/textfile_collector"
LOG_DIR="/var/log"
WRAPPER_SCRIPT="/usr/local/bin/flipper-monitor-wrapper.sh"
LOGROTATE_FILE="/etc/logrotate.d/github-runner-metrics"
# Define templates
WRAPPER_TEMPLATE="services/flipper-monitor-wrapper.sh"
SERVICE_TEMPLATE="services/github-runner-monitor.service.template"
MONITOR_SCRIPT_FILE="scripts/github-runner-monitor.py"
LOGROTATE_TEMPLATE="services/github-runner-metrics.logrotate.template"

# Create installation directory
echo "Creating installation directory..."
run_cmd mkdir -p ${INSTALL_DIR}
run_cmd mkdir -p ${METRICS_DIR}
run_cmd chmod 755 ${METRICS_DIR}

# Set up Python virtual environment
echo "Setting up Python virtual environment..."
if [ "$SIMULATE" = false ]; then
    run_cmd python3 -m venv ${VENV_DIR}
    run_cmd ${VENV_DIR}/bin/pip install --upgrade pip
    run_cmd ${VENV_DIR}/bin/pip install pyudev docker pygelf
else
    echo "SIMULATE: Setting up Python virtual environment with pyudev, docker, and pygelf"
fi

# Copy the monitoring script
echo "Installing monitoring script..."
run_cmd cp $MONITOR_SCRIPT_FILE ${MONITOR_SCRIPT}
run_cmd chmod +x ${MONITOR_SCRIPT}

# Copy and configure the wrapper script
echo "Installing wrapper script..."
if [ -f "${WRAPPER_TEMPLATE}" ]; then
    run_cmd cp "${WRAPPER_TEMPLATE}" "${WRAPPER_SCRIPT}"
    run_cmd chmod +x "${WRAPPER_SCRIPT}"
else
    echo "Wrapper script template not found at ${WRAPPER_TEMPLATE}!"
    exit 1
fi

# Copy and configure the systemd service file
echo "Installing systemd service..."
if [ -f "${SERVICE_TEMPLATE}" ]; then
    run_cmd cp "${SERVICE_TEMPLATE}" "${SERVICE_FILE}"
else
    echo "Service template not found at ${SERVICE_TEMPLATE}!"
    exit 1
fi

# Set up log rotation
echo "Configuring log rotation..."
if [ -f "${LOGROTATE_TEMPLATE}" ]; then
    run_cmd cp "${LOGROTATE_TEMPLATE}" "${LOGROTATE_FILE}"
    run_cmd chmod 644 "${LOGROTATE_FILE}"
else
    echo "Logrotate template not found at ${LOGROTATE_TEMPLATE}!"
    exit 1
fi

# Reload systemd and enable service
echo "Configuring systemd service..."
if [ "$SIMULATE" = true ]; then
    echo "SIMULATE: systemctl daemon-reload"
    echo "SIMULATE: systemctl enable github-runner-monitor.service"
else
    run_cmd systemctl daemon-reload
    run_cmd systemctl enable github-runner-monitor.service
fi

echo "Installation complete!"
echo "The monitoring service is now installed and will start on next boot."
echo "To start it immediately, run: systemctl start github-runner-monitor.service"
echo ""
echo "The service uses the same configuration as the runners from:"
echo "/var/lib/flipper-docker/flipper-docker.cfg"
echo ""
echo "Installation directory: ${INSTALL_DIR}"
echo "Python virtual environment: ${VENV_DIR}"
echo "Metrics will be collected in: ${METRICS_DIR}"
echo "Logs will be written to: ${LOG_DIR}/github-runner-metrics.log"