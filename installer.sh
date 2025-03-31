#!/bin/bash

set -euo pipefail

# Default to normal mode (not simulating)
SIMULATE=false

# Parse named parameters
FLIPPER_ID=""
ST_LINK_ID=""

for i in "$@"; do
    case $i in
        --flipper-id=*)
        FLIPPER_ID="${i#*=}"
        shift
        ;;
        --stlink=*)
        ST_LINK_ID="${i#*=}"
        shift
        ;;
        --simulate)
        SIMULATE=true
        shift
        ;;
        *)
        # Unknown option
        ;;
    esac
done

# Validate required parameters
if [ -z "$FLIPPER_ID" ] || [ -z "$ST_LINK_ID" ]; then
    echo "Usage: $0 --flipper-id=FLIPPER_ID --stlink=ST_LINK_ID [--simulate]"
    echo "Example: $0 --flipper-id=flip_abc123 --stlink=xyz789"
    echo "  --simulate    Run in simulation mode (show commands but don't execute)"
    exit 1
fi

# Check if script is run as root when not in simulation mode
if [ "$EUID" -ne 0 ] && [ "$SIMULATE" = false ]; then
    echo "Please run as root"
    exit 1
fi

# Define a function to either execute or simulate a command
run_cmd() {
    if [ "$SIMULATE" = true ]; then
        echo "SIMULATION: "
        echo "$@"
    else
        "$@"
    fi
}

# Function to safely write to a file
write_file() {
    local file="$1"
    local content="$2"

    if [ "$SIMULATE" = true ]; then
        echo "SIMULATION: would write to file: $file"
        echo "---- File content ----"
        echo "$content"
        echo "----------------------"
    else
        echo "$content" > "$file"
    fi
}

# Function to safely append to a file
append_file() {
    local file="$1"
    local content="$2"

    if [ "$SIMULATE" = true ]; then
        echo "SIMULATION: would append to file: $file"
        echo "---- Content to append ----"
        echo "$content"
        echo "---------------------------"
    else
        echo "$content" >> "$file"
    fi
}

echo "Installing Flipper GitHub Runner for:"
echo "Flipper ID: $FLIPPER_ID"
echo "ST-Link ID: $ST_LINK_ID"
echo "Simulation mode: $SIMULATE"

# Define installation paths
INSTALL_DIR="/opt/flipper-runners"
VENV_DIR="${INSTALL_DIR}/${FLIPPER_ID}/venv"
SCRIPTS_DIR="${INSTALL_DIR}/scripts"
CONFIG_DIR="/var/lib/flipper-docker"
WRAPPER_SCRIPT="/usr/local/bin/flipper-docker-wrapper.sh"

# Install system dependencies
echo "Installing system dependencies..."
run_cmd apt-get update
run_cmd apt-get install -y docker-ce ccache python3-venv python3-dev logrotate

# Create required directories
echo "Setting up directories..."
run_cmd mkdir -p "${INSTALL_DIR}"
run_cmd mkdir -p "${SCRIPTS_DIR}"
run_cmd mkdir -p "${CONFIG_DIR}"
run_cmd mkdir -p "/opt/${FLIPPER_ID}/logs"

# Set up Python virtual environment
echo "Setting up Python virtual environment..."
run_cmd python3 -m venv ${VENV_DIR}
run_cmd ${VENV_DIR}/bin/pip install --upgrade pip
run_cmd ${VENV_DIR}/bin/pip install pyudev docker pygelf

# Copy Docker-related files
echo "Copying Docker files..."
run_cmd cp -r docker/* ${CONFIG_DIR}/

# Copy Python scripts
echo "Installing Python scripts..."
run_cmd cp scripts/flipper-docker-runner.py ${SCRIPTS_DIR}/
run_cmd chmod +x ${SCRIPTS_DIR}/flipper-docker-runner.py

# Create a wrapper script to activate the virtual environment
echo "Creating wrapper script..."
WRAPPER_CONTENT="#!/bin/bash
source ${VENV_DIR}/bin/activate
exec python ${SCRIPTS_DIR}/flipper-docker-runner \"\$@\"
"
write_file "${WRAPPER_SCRIPT}" "${WRAPPER_CONTENT}"
run_cmd chmod +x ${WRAPPER_SCRIPT}

# Create service file
echo "Creating systemd service..."
SERVICE_CONTENT="[Unit]
Description=Dockerized github runner ${FLIPPER_ID}
After=docker.service
Requires=docker.service

[Service]
TimeoutStartSec=0
Restart=always
ExecStart=${WRAPPER_SCRIPT} ${FLIPPER_ID} ${ST_LINK_ID} FlipperZeroTest
KillSignal=SIGINT

[Install]
WantedBy=multi-user.target
"
write_file "/etc/systemd/system/github-runner-${FLIPPER_ID}.service" "$SERVICE_CONTENT"

# Configure Docker logging
echo "Configuring Docker logging..."
run_cmd mkdir -p /etc/docker
DOCKER_CONFIG='{
    "log-driver": "journald"
}'
write_file "/etc/docker/daemon.json" "$DOCKER_CONFIG"

# Configure log rotation
echo "Configuring log rotation..."
LOGROTATE_FILE="/etc/logrotate.d/flipper-${FLIPPER_ID}"
LOGROTATE_CONTENT="/opt/${FLIPPER_ID}/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    dateext
    create 0644 root root
}"
write_file "$LOGROTATE_FILE" "$LOGROTATE_CONTENT"

# Reload systemd and enable service
echo "Configuring systemd service..."
run_cmd systemctl daemon-reload
run_cmd systemctl restart docker
run_cmd systemctl enable "github-runner-${FLIPPER_ID}"

echo "Installation complete!"
echo ""
echo "Please ensure you have placed the following files in ${CONFIG_DIR}:"
echo "1. flipper-docker.cfg with GitHub credentials"
echo "2. region_data"
echo ""
echo "Installation directory: ${INSTALL_DIR}"
echo "Python virtual environment: ${VENV_DIR}"
echo "Log files: /opt/${FLIPPER_ID}/logs/"
echo ""
echo "To start the service, run:"
echo "systemctl start github-runner-${FLIPPER_ID}"

