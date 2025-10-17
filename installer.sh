#!/bin/bash
set -euo pipefail

# Usage: installer.sh --flipper=flip_SERIAL --stlink=STLINKSERIAL [--simulate --github-tag=GITHUBTAG]

# Default values for optional parameters.
SIMULATE=false
GITHUB_TAG="FlipperZeroTest"

# Parse command-line arguments.
FLIPPER_SERIAL=""
STLINK_SERIAL=""

for arg in "$@"; do
    case $arg in
        --flipper=*)
            FLIPPER_SERIAL="${arg#*=}"
            ;;
        --stlink=*)
            STLINK_SERIAL="${arg#*=}"
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

if [ -z "$FLIPPER_SERIAL" ] || [ -z "$STLINK_SERIAL" ]; then
    echo "Usage: $0 --flipper=flip_SERIAL --stlink=STLINKSERIAL [--simulate --github-tag=GITHUBTAG]"
    exit 1
fi

# Require root for real execution.
if [ "$SIMULATE" = false ] && [ "$EUID" -ne 0 ]; then
    echo "Please run as root."
    exit 1
fi

echo "Starting installation for Flipper: $FLIPPER_SERIAL, ST-Link: $STLINK_SERIAL (GitHub tag: $GITHUB_TAG)"
if [ "$SIMULATE" = true ]; then
    echo "Running in simulation mode. Commands will be printed instead of executed."
fi

# A wrapper to either execute or simulate a command.
run_cmd() {
    if [ "$SIMULATE" = true ]; then
        echo "SIMULATE: $*"
    else
        "$@"
    fi
}

# Define templates
LOG_RUNNER_TEMPLATE="templates/flipper-runners.logrotate.template"
UDEV_TEMPLATE="templates/99-udev-flipper-zero.rules.template"
BINDER_TEMPLATE="templates/github-runner-binder@.service.template"
UNBINDER_TEMPLATE="templates/github-runner-unbinder@.service.template"
SERVICE_TEMPLATE="templates/github-runner-flip.service.template"

# Define installation paths.
BASE_DIR="/opt/flipper-runner"
DOCKER_DIR="${BASE_DIR}/docker"
SCRIPTS_DIR="${BASE_DIR}/scripts"
SERVICES_DIR="${BASE_DIR}/services"
RUNNER_DIR="${BASE_DIR}/${FLIPPER_SERIAL}"
VENV_DIR="${RUNNER_DIR}/venv"
LOG_DIR="${RUNNER_DIR}/logs"
UDEV_RULE="/etc/udev/rules.d/99-udev-flipper-zero.rules"
SYSTEMD_DIR="/etc/systemd/system"
BINDER_SERVICE="${SYSTEMD_DIR}/github-runner-binder@.service"
UNBINDER_SERVICE="${SYSTEMD_DIR}/github-runner-unbinder@.service"
SERVICE_FILE="/etc/systemd/system/github-runner-flip-${FLIPPER_SERIAL}.service"

# Create necessary directories.
echo "Creating installation directories..."
run_cmd mkdir -p "$BASE_DIR" "$DOCKER_DIR" "$SCRIPTS_DIR" "$SERVICES_DIR" "$RUNNER_DIR" "$LOG_DIR"

# Copy Docker files.
echo "Copying Docker files..."
run_cmd cp -r docker/* "$DOCKER_DIR/"

# Copy runner scripts.
echo "Copying scripts..."
run_cmd cp -r scripts/* "$SCRIPTS_DIR/"

# Copy service scripts
echo "Copying service scripts..."
run_cmd cp -r services/* "$SERVICES_DIR/"

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
    echo "Installing systemd service for Flipper runner..."
    # Special handling for the sed command
    if [ "$SIMULATE" = true ]; then
        echo "SIMULATE: sed -e \"s/__FLIPPER_SERIAL__/${FLIPPER_SERIAL}/g\" -e \"s/__STLINK_SERIAL__/${STLINK_SERIAL}/g\" -e \"s/__GITHUB_RUNNER_TAG__/${GITHUB_TAG}/g\" \"$SERVICE_TEMPLATE\" > \"$SERVICE_FILE\""
    else
        sed -e "s/__FLIPPER_SERIAL__/${FLIPPER_SERIAL}/g" -e "s/__STLINK_SERIAL__/${STLINK_SERIAL}/g" -e "s/__GITHUB_RUNNER_TAG__/${GITHUB_TAG}/g" "$SERVICE_TEMPLATE" > "$SERVICE_FILE"
    fi
else
    echo "Service template ${SERVICE_TEMPLATE} not found!"
    exit 1
fi

# Reload systemd and enable the new service.
echo "Reloading systemd daemon and enabling the service..."
run_cmd systemctl daemon-reload
run_cmd systemctl enable "github-runner-flip-${FLIPPER_SERIAL}"

# Install service binaries
echo "Installing service binaries..."
run_cmd cp services/flipper-binder.sh /usr/local/bin/
run_cmd cp services/flipper-unbinder.sh /usr/local/bin/
run_cmd cp services/flipper-docker-wrapper.sh /usr/local/bin/
run_cmd chmod +x /usr/local/bin/flipper-*.sh

# Install logrotation configuration
echo "Setting up log rotation..."
if [ ! -f "/etc/logrotate.d/github-runners" ]; then
    run_cmd cp $LOG_RUNNER_TEMPLATE /etc/logrotate.d/github-runners
    run_cmd chmod 644 /etc/logrotate.d/github-runners
else
    echo "Log rotation for runners already configured, skipping."
fi

# Prepare Python environment for the runner.
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python virtual environment for ${FLIPPER_SERIAL}..."
    run_cmd python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists at ${VENV_DIR}, reusing."
fi

echo "Installing Python dependencies into runner virtual environment..."
run_cmd "$VENV_DIR/bin/pip" install --upgrade pip
run_cmd "$VENV_DIR/bin/pip" install --upgrade pyudev docker pygelf

# Notify the user about additional steps.
echo "Installation complete!"
echo "Next steps:"
echo "1. Check out the flipper-firmware repository into the Docker folder: ${DOCKER_DIR}"
echo "2. Build the Docker container for this host (e.g., docker build -t flipper-runner:latest ${DOCKER_DIR})"
echo "3. Start the service: systemctl start github-runner-flip-${FLIPPER_SERIAL}"
echo "4. Verify the service status: systemctl status github-runner-flip-${FLIPPER_SERIAL}"
