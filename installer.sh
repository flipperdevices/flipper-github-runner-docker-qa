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
run_cmd cp scripts/flipper_docker.py ${SCRIPTS_DIR}/
run_cmd chmod +x ${SCRIPTS_DIR}/flipper_docker.py

# Create a wrapper script to activate the virtual environment
echo "Creating wrapper script..."
WRAPPER_CONTENT="#!/bin/bash
source ${VENV_DIR}/bin/activate
exec python ${SCRIPTS_DIR}/flipper_docker.py \"\$@\"
"
write_file "${WRAPPER_SCRIPT}" "${WRAPPER_CONTENT}"
run_cmd chmod +x ${WRAPPER_SCRIPT}

# Add udev rules creation
echo "Creating udev rules for devices..."

# Determine the next available numbers for Flipper (1XX) and ST-Link (2XX)
UDEV_RULES_FILE="/etc/udev/rules.d/99-flipper-devices.rules"

# Create the file if it doesn't exist
if [ ! -f "$UDEV_RULES_FILE" ] || [ "$SIMULATE" = true ]; then
    run_cmd touch "$UDEV_RULES_FILE"
fi

# Function to find the next available number
find_next_number() {
    local prefix=$1
    local existing_numbers=""

    # Check if the file exists before attempting to read from it
    if [ -f "$UDEV_RULES_FILE" ]; then
        # Look for the last used number for this prefix in the file
        # Use grep -o to extract just the matching part, then sed to get just the number
        existing_numbers=$(grep -o "${prefix}[0-9][0-9][0-9]\\?" "$UDEV_RULES_FILE" 2>/dev/null | sed "s/${prefix}//g" | sort -n)
    fi

    if [ -z "$existing_numbers" ]; then
        echo "10" # Start with 10 if no existing entries
    else
        local last_number=$(echo "$existing_numbers" | tail -1)
        echo $((last_number + 10)) # Increment by 10 for spacing
    fi
}

# Find next available numbers
FLIPPER_NUM=$(find_next_number "ttyACM1")
STLINK_NUM=$(find_next_number "ttyACM2")

# Create formatted numbers
FLIPPER_LINK="ttyACM1${FLIPPER_NUM}"
STLINK_LINK="ttyACM2${STLINK_NUM}"

echo "Creating device links: Flipper → ${FLIPPER_LINK}, ST-Link → ${STLINK_LINK}"

# Add rules to the udev rules file
if [ "$SIMULATE" = true ] || ! grep -q "ATTRS{serial}==\"${FLIPPER_ID}\"" "$UDEV_RULES_FILE" 2>/dev/null; then
    FLIPPER_RULE="ACTION==\"add\", SUBSYSTEM==\"tty\", SUBSYSTEMS==\"usb\", ATTRS{serial}==\"${FLIPPER_ID}\", SYMLINK+=\"${FLIPPER_LINK}\""
    append_file "$UDEV_RULES_FILE" "$FLIPPER_RULE"
fi

if [ "$SIMULATE" = true ] || ! grep -q "ATTRS{serial}==\"${ST_LINK_ID}\"" "$UDEV_RULES_FILE" 2>/dev/null; then
    STLINK_RULE="ACTION==\"add\", SUBSYSTEM==\"tty\", SUBSYSTEMS==\"usb\", ATTRS{serial}==\"${ST_LINK_ID}\", SYMLINK+=\"${STLINK_LINK}\""
    append_file "$UDEV_RULES_FILE" "$STLINK_RULE"
fi

# Reload udev rules
echo "Reloading udev rules..."
run_cmd udevadm control --reload-rules
run_cmd udevadm trigger

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
echo ""
echo "Device symlinks created:"
echo "- Flipper: /dev/${FLIPPER_LINK}"
echo "- ST-Link: /dev/${STLINK_LINK}"
