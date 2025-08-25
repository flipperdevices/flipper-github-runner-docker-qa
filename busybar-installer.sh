#!/bin/bash
set -euo pipefail

# Usage: busybar-installer.sh --busybar=SERIAL --blackmagic=SERIAL [--simulate --github-tag=GITHUBTAG]

# Default values for optional parameters.
SIMULATE=false
GITHUB_TAG="BusyBarTest"

# Parse command-line arguments.
BUSYBAR_SERIAL=""
BLACKMAGIC_SERIAL=""

for arg in "$@"; do
    case $arg in
        --busybar=*)
            BUSYBAR_SERIAL="${arg#*=}"
            ;;
        --blackmagic=*)
            BLACKMAGIC_SERIAL="${arg#*=}"
            ;;
        --simulate)
            SIMULATE=true
            ;;
        --github-tag=*)
            GITHUB_TAG="${arg#*=}"
            ;;
        *)
            echo "Unknown option: $arg"
            exit 1
            ;;
    esac
done

if [ -z "$BUSYBAR_SERIAL" ] || [ -z "$BLACKMAGIC_SERIAL" ]; then
    echo "Usage: $0 --busybar=SERIAL --blackmagic=SERIAL [--simulate --github-tag=GITHUBTAG]"
    exit 1
fi

# Require root for real execution.
if [ "$SIMULATE" = false ] && [ "$EUID" -ne 0 ]; then
    echo "Please run as root."
    exit 1
fi

echo "Starting installation for BusyBar: $BUSYBAR_SERIAL, Blackmagic: $BLACKMAGIC_SERIAL (GitHub tag: $GITHUB_TAG)"
if [ "$SIMULATE" = true ]; then
    echo "Running in simulation mode. Commands will be printed instead of executed."
fi

run_cmd() {
    if [ "$SIMULATE" = true ]; then
        echo "SIMULATE: $*"
    else
        "$@"
    fi
}

# Define templates
LOG_RUNNER_TEMPLATE="templates-busybar/busybar-runners.logrotate.template"
UDEV_TEMPLATE="templates-busybar/99-udev-busybar.rules.template"
BINDER_TEMPLATE="templates-busybar/github-runner-busybar-binder@.service.template"
UNBINDER_TEMPLATE="templates-busybar/github-runner-busybar-unbinder@.service.template"
SERVICE_TEMPLATE="templates-busybar/github-runner-busybar.service.template"

# Define installation paths.
BASE_DIR="/opt/busybar-runner"
DOCKER_DIR="${BASE_DIR}/docker"
SCRIPTS_DIR="${BASE_DIR}/scripts"
SERVICES_DIR="${BASE_DIR}/services"
UDEV_RULE="/etc/udev/rules.d/99-udev-busybar.rules"
SYSTEMD_DIR="/etc/systemd/system"
BINDER_SERVICE="${SYSTEMD_DIR}/github-runner-busybar-binder@.service"
UNBINDER_SERVICE="${SYSTEMD_DIR}/github-runner-busybar-unbinder@.service"
SERVICE_FILE="/etc/systemd/system/github-runner-busybar-${BUSYBAR_SERIAL}.service"

# Create necessary directories.
echo "Creating installation directories..."
run_cmd mkdir -p "$BASE_DIR" "$DOCKER_DIR" "$SCRIPTS_DIR" "$SERVICES_DIR"

# Copy Docker files.
echo "Copying Docker files..."
run_cmd cp -r docker-busybar/* "$DOCKER_DIR/"

# Copy runner scripts.
echo "Copying scripts..."
run_cmd cp -r scripts-busybar/* "$SCRIPTS_DIR/"

# Copy service scripts
echo "Copying service scripts..."
run_cmd cp -r services-busybar/* "$SERVICES_DIR/"

# Install the udev rule if not already present.
if [ ! -f "$UDEV_RULE" ]; then
    echo "Installing udev rule..."
    run_cmd cp "$UDEV_TEMPLATE" "$UDEV_RULE"
    run_cmd udevadm control --reload-rules
    run_cmd udevadm trigger
else
    echo "Udev rule already exists, skipping installation."
fi

# Install binder and unbinder service if not already present.
if [ ! -f "$BINDER_SERVICE" ]; then
    echo "Installing binder service..."
    run_cmd cp "$BINDER_TEMPLATE" "$BINDER_SERVICE"
    run_cmd cp "$UNBINDER_TEMPLATE" "$UNBINDER_SERVICE"
    run_cmd systemctl daemon-reload
else
    echo "Binder service already exists, skipping installation."
fi

# Install the systemd service using the template.
if [ -f "$SERVICE_TEMPLATE" ]; then
    echo "Installing systemd service for BusyBar runner..."
    if [ "$SIMULATE" = true ]; then
        echo "SIMULATE: sed -e \"s/__BUSYBAR_SERIAL__/${BUSYBAR_SERIAL}/g\" -e \"s/__BLACKMAGIC_SERIAL__/${BLACKMAGIC_SERIAL}/g\" -e \"s/__GITHUB_RUNNER_TAG__/${GITHUB_TAG}/g\" \"$SERVICE_TEMPLATE\" > \"$SERVICE_FILE\""
    else
        sed -e "s/__BUSYBAR_SERIAL__/${BUSYBAR_SERIAL}/g" -e "s/__BLACKMAGIC_SERIAL__/${BLACKMAGIC_SERIAL}/g" -e "s/__GITHUB_RUNNER_TAG__/${GITHUB_TAG}/g" "$SERVICE_TEMPLATE" > "$SERVICE_FILE"
    fi
else
    echo "Service template ${SERVICE_TEMPLATE} not found!"
    exit 1
fi

# Reload systemd and enable the new service.
echo "Reloading systemd daemon and enabling the service..."
run_cmd systemctl daemon-reload
run_cmd systemctl enable "github-runner-busybar-${BUSYBAR_SERIAL}"

# Install service binaries
echo "Installing service binaries..."
run_cmd cp services-busybar/busybar-binder.sh /usr/local/bin/
run_cmd cp services-busybar/busybar-unbinder.sh /usr/local/bin/
run_cmd cp services-busybar/busybar-docker-wrapper.sh /usr/local/bin/
run_cmd chmod +x /usr/local/bin/busybar-*.sh

# Install logrotation configuration
echo "Setting up log rotation..."
if [ ! -f "/etc/logrotate.d/github-busybar-runners" ]; then
    run_cmd cp $LOG_RUNNER_TEMPLATE /etc/logrotate.d/github-busybar-runners
    run_cmd chmod 644 /etc/logrotate.d/github-busybar-runners
else
    echo "Log rotation for runners already configured, skipping."
fi

echo "Installation complete!"
echo "Next steps:"
echo "1. Build the Docker container for this host (e.g., docker build -t busybar-runner:latest ${DOCKER_DIR})"
echo "2. Start the service: systemctl start github-runner-busybar-${BUSYBAR_SERIAL}"
echo "3. Verify the service status: systemctl status github-runner-busybar-${BUSYBAR_SERIAL}"
